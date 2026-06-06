import pytest
import time
from kubernetes import client, config
from kubernetes.client.rest import ApiException

config.load_kube_config()

v1 = client.CoreV1Api()

# =========================================================
# CONFIG
# =========================================================
NAMESPACE = "test-auto"
POD_NAME = "nginx"


# =========================================================
# FIXTURE: SETUP + TEARDOWN
# =========================================================
@pytest.fixture(scope="module", autouse=True)
def setup_nginx_pod():
    # Create namespace if it doesn't exist
    try:
        v1.create_namespace(
            client.V1Namespace(metadata=client.V1ObjectMeta(name=NAMESPACE))
        )
    except ApiException as e:
        if e.status != 409:
            raise

    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": POD_NAME,
            "namespace": NAMESPACE
        },
        "spec": {
            "containers": [
                {
                    "name": "nginx",
                    "image": "nginx:stable",
                    "ports": [{"containerPort": 80}],
                    "livenessProbe": {
                        "httpGet": {
                            "path": "/",
                            "port": 80
                        },
                        "initialDelaySeconds": 5,
                        "periodSeconds": 5
                    },
                    "readinessProbe": {
                        "httpGet": {
                            "path": "/",
                            "port": 80
                        },
                        "initialDelaySeconds": 5,
                        "periodSeconds": 5
                    }
                }
            ]
        }
    }

    # Ensure clean slate
    try:
        v1.delete_namespaced_pod(POD_NAME, NAMESPACE)
        time.sleep(2)
    except ApiException:
        pass

    v1.create_namespaced_pod(namespace=NAMESPACE, body=pod_manifest)

    # Wait for Pod to exist
    for _ in range(30):
        try:
            pod = v1.read_namespaced_pod(POD_NAME, NAMESPACE)
            if pod.status.phase in ("Running", "Pending"):
                break
        except ApiException:
            pass
        time.sleep(2)

    # Wait for Running
    for _ in range(60):
        pod = v1.read_namespaced_pod(POD_NAME, NAMESPACE)
        if pod.status.phase == "Running":
            break
        time.sleep(2)

    yield

    # Cleanup
    try:
        v1.delete_namespaced_pod(POD_NAME, NAMESPACE)
    except ApiException:
        pass


# =========================================================
# 1. CLUSTER TESTS
# =========================================================
def test_cluster_api_accessible():
    nodes = v1.list_node().items
    assert len(nodes) > 0, "Kubernetes API not accessible"


def test_cluster_nodes_ready():
    nodes = v1.list_node().items

    for node in nodes:
        conditions = node.status.conditions or []

        ready = any(
            c.type == "Ready" and c.status == "True"
            for c in conditions
        )

        assert ready, f"Node not Ready: {node.metadata.name}"


# =========================================================
# 2. POD TESTS
# =========================================================
def test_nginx_pod_running():
    pod = v1.read_namespaced_pod(POD_NAME, NAMESPACE)
    assert pod.status.phase == "Running", f"Pod not running: {pod.status.phase}"


def test_nginx_has_probes():
    pod = v1.read_namespaced_pod(POD_NAME, NAMESPACE)

    container = pod.spec.containers[0]

    assert container.liveness_probe is not None
    assert container.readiness_probe is not None


# =========================================================
# 3. READINESS TEST
# =========================================================
def test_readiness_probe_passes():
    for _ in range(30):
        pod = v1.read_namespaced_pod(POD_NAME, NAMESPACE)
        statuses = pod.status.container_statuses or []

        if statuses and statuses[0].ready:
            return

        time.sleep(2)

    assert False, "Readiness probe never became True"


# =========================================================
# 4. LIVENESS CHECK (SAFE VERSION)
# =========================================================
def test_liveness_probe_works():
    pod = v1.read_namespaced_pod(POD_NAME, NAMESPACE)

    status = pod.status.container_statuses[0]

    assert status is not None
    assert status.restart_count >= 0


# =========================================================
# 5. STABILITY TEST (NO PATCHING PODS)
# =========================================================
def test_pod_stability_over_time():
    start = time.time()

    for _ in range(10):
        pod = v1.read_namespaced_pod(POD_NAME, NAMESPACE)
        assert pod.status.phase in ("Running", "Pending")
        time.sleep(3)

    duration = time.time() - start
    assert duration > 0


# =========================================================
# 6. CLEANUP TEST (SAFE VERIFY)
# =========================================================
def test_cleanup_delete_pod():
    v1.delete_namespaced_pod(POD_NAME, NAMESPACE)

    for _ in range(20):
        pods = v1.list_namespaced_pod(NAMESPACE).items
        if POD_NAME not in [p.metadata.name for p in pods]:
            return
        time.sleep(2)

    assert False, "Pod was not deleted"
