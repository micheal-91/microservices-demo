"""
E2E Tests for a Kubernetes Cluster
Requirements: pip install pytest kubernetes pyyaml
Run with: pytest test_k8s_e2e.py -v
"""

import time
import pytest
import yaml
from kubernetes import client, config
from kubernetes.client.rest import ApiException

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
NAMESPACE = "test-auto"
POD_NAME  = "nginx-healthcheck"          # from the example manifest

# Exact Pod manifest from the exercise
POD_MANIFEST = {
    "apiVersion": "v1",
    "kind": "Pod",
    "metadata": {
        "name": POD_NAME,
        "namespace": NAMESPACE,
    },
    "spec": {
        "containers": [
            {
                "name": "nginx",
                "image": "nginx",
                "ports": [{"containerPort": 80}],
                # Liveness Probe
                "livenessProbe": {
                    "httpGet": {"path": "/", "port": 80},
                    "initialDelaySeconds": 5,
                    "periodSeconds": 10,
                },
                # Readiness Probe
                "readinessProbe": {
                    "httpGet": {"path": "/", "port": 80},
                    "initialDelaySeconds": 5,
                    "periodSeconds": 10,
                },
            }
        ]
    },
}


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture(scope="session")
def k8s_client():
    """Load kubeconfig and return a CoreV1Api client."""
    config.load_kube_config()          # uses ~/.kube/config by default
    return client.CoreV1Api()


@pytest.fixture(scope="session", autouse=True)
def setup_namespace(k8s_client):
    """Create the test namespace once, delete it after all tests."""
    try:
        k8s_client.create_namespace(
            client.V1Namespace(metadata=client.V1ObjectMeta(name=NAMESPACE))
        )
        print(f"\n[setup] Namespace '{NAMESPACE}' created.")
    except ApiException as e:
        if e.status == 409:
            print(f"\n[setup] Namespace '{NAMESPACE}' already exists.")
        else:
            raise

    yield  # all tests run here

    k8s_client.delete_namespace(NAMESPACE)
    print(f"\n[teardown] Namespace '{NAMESPACE}' deleted.")


@pytest.fixture()
def nginx_pod(k8s_client):
    """Create the nginx-healthcheck Pod before each test, delete it after."""
    k8s_client.create_namespaced_pod(namespace=NAMESPACE, body=POD_MANIFEST)
    print(f"\n[fixture] Pod '{POD_NAME}' created.")
    _wait_for_pod(k8s_client, POD_NAME, phase="Running")
    yield
    _delete_pod(k8s_client, POD_NAME)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _wait_for_pod(k8s_client, pod_name, phase="Running", timeout=60):
    """Poll every second until the Pod reaches the expected phase."""
    for _ in range(timeout):
        try:
            pod = k8s_client.read_namespaced_pod(pod_name, NAMESPACE)
            if pod.status.phase == phase:
                return
        except ApiException:
            pass
        time.sleep(1)
    raise TimeoutError(f"Pod '{pod_name}' did not reach phase '{phase}' within {timeout}s.")


def _delete_pod(k8s_client, pod_name):
    """Delete a Pod, ignoring 404 (already gone)."""
    try:
        k8s_client.delete_namespaced_pod(pod_name, NAMESPACE)
        print(f"[cleanup] Pod '{pod_name}' deleted.")
    except ApiException as e:
        if e.status != 404:
            raise


# ─────────────────────────────────────────────
# TASK 1 – Cluster status
# ─────────────────────────────────────────────

def test_api_is_accessible(k8s_client):
    """The Kubernetes API must respond without error."""
    version = client.VersionApi().get_code()
    assert version.git_version, "API did not return a version string."
    print(f"\n  K8s version: {version.git_version}")


def test_nodes_are_ready(k8s_client):
    """Every node must have a 'Ready' condition set to True."""
    nodes = k8s_client.list_node().items
    assert nodes, "No nodes found in the cluster."

    for node in nodes:
        for condition in node.status.conditions:
            if condition.type == "Ready":
                assert condition.status == "True", (
                    f"Node '{node.metadata.name}' is NOT Ready."
                )
                print(f"\n  Node '{node.metadata.name}' → Ready ✓")


# ─────────────────────────────────────────────
# TASK 2 – Pod status
# ─────────────────────────────────────────────

def test_nginx_pod_is_running(k8s_client, nginx_pod):
    """The nginx-healthcheck Pod must be in Running phase."""
    pod = k8s_client.read_namespaced_pod(POD_NAME, NAMESPACE)
    assert pod.status.phase == "Running", (
        f"Expected 'Running', got '{pod.status.phase}'."
    )
    print(f"\n  Pod '{POD_NAME}' is Running ✓")


# ─────────────────────────────────────────────
# TASK 3 – HealthChecks (probes)
# ─────────────────────────────────────────────

def test_probes_are_defined(k8s_client, nginx_pod):
    """The nginx container must have both Liveness and Readiness probes."""
    pod = k8s_client.read_namespaced_pod(POD_NAME, NAMESPACE)
    container = pod.spec.containers[0]

    assert container.liveness_probe  is not None, "Liveness probe is missing!"
    assert container.readiness_probe is not None, "Readiness probe is missing!"

    # Verify the exact values from the manifest
    lp = container.liveness_probe.http_get
    rp = container.readiness_probe.http_get
    assert lp.path == "/",  f"Liveness path expected '/', got '{lp.path}'"
    assert lp.port == 80,   f"Liveness port expected 80, got '{lp.port}'"
    assert rp.path == "/",  f"Readiness path expected '/', got '{rp.path}'"
    assert rp.port == 80,   f"Readiness port expected 80, got '{rp.port}'"
    print("\n  Liveness  probe → path='/' port=80 ✓")
    print("  Readiness probe → path='/' port=80 ✓")


def test_readiness_probe_passes(k8s_client, nginx_pod):
    """All containers must report as Ready (readiness probe passed)."""
    pod = k8s_client.read_namespaced_pod(POD_NAME, NAMESPACE)
    for cs in pod.status.container_statuses:
        assert cs.ready, f"Container '{cs.name}' is NOT Ready."
        print(f"\n  Container '{cs.name}' → Ready ✓")


# ─────────────────────────────────────────────
# TASK 4 – Simulate Liveness Probe failure → auto-restart
# ─────────────────────────────────────────────

def test_pod_restarts_on_liveness_failure(k8s_client):
    """
    Create a Pod whose liveness probe points to a non-existent path.
    Kubernetes should fail the probe and automatically restart the container.
    """
    broken_pod_name = "nginx-healthcheck-broken"

    # Copy the manifest and break the liveness probe path
    broken_manifest = yaml.safe_load(yaml.dump(POD_MANIFEST))
    broken_manifest["metadata"]["name"] = broken_pod_name
    lp = broken_manifest["spec"]["containers"][0]["livenessProbe"]
    lp["httpGet"]["path"]      = "/does-not-exist"   # will return 404 → failure
    lp["initialDelaySeconds"]  = 5
    lp["periodSeconds"]        = 5
    lp["failureThreshold"]     = 1                   # restart after 1st failure

    try:
        k8s_client.create_namespaced_pod(namespace=NAMESPACE, body=broken_manifest)
        print(f"\n  Pod '{broken_pod_name}' created with broken liveness probe.")
        print("  Waiting for Kubernetes to detect failure and restart…")

        for _ in range(120):
            try:
                pod = k8s_client.read_namespaced_pod(broken_pod_name, NAMESPACE)
                statuses = pod.status.container_statuses
                if statuses and statuses[0].restart_count >= 1:
                    print(f"  Restart count: {statuses[0].restart_count} ✓")
                    return   # test passes
            except ApiException:
                pass
            time.sleep(1)

        pytest.fail("Pod did not restart within 120 s after liveness probe failure.")

    finally:
        _delete_pod(k8s_client, broken_pod_name)


# ─────────────────────────────────────────────
# TASK 5 – Cleanup
# ─────────────────────────────────────────────

def test_pod_deleted_after_tests(k8s_client):
    """Create a Pod, delete it, then confirm it no longer exists (404)."""
    temp_name = "nginx-healthcheck-cleanup"
    temp_manifest = yaml.safe_load(yaml.dump(POD_MANIFEST))
    temp_manifest["metadata"]["name"] = temp_name

    k8s_client.create_namespaced_pod(namespace=NAMESPACE, body=temp_manifest)
    print(f"\n  Pod '{temp_name}' created.")

    _delete_pod(k8s_client, temp_name)

    # Poll until the API returns 404 (fully deleted)
    for _ in range(30):
        try:
            k8s_client.read_namespaced_pod(temp_name, NAMESPACE)
            time.sleep(1)          # still terminating, wait
        except ApiException as e:
            if e.status == 404:
                print(f"  Pod '{temp_name}' confirmed deleted ✓")
                return

    pytest.fail("Pod was not deleted within 30 s.")
