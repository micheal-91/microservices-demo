import time
import pytest
import yaml

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.stream import stream


NAMESPACE = "testtest-auto"
POD_NAME = "nginx-healthcheck"
MANIFEST_FILE = "nginx-healthcheck.yaml"


@pytest.fixture(scope="session")
def kube_clients():
    # Use kubeconfig from current user context
    # If running inside cluster, replace with: config.load_incluster_config()
    config.load_kube_config()
    core_v1 = client.CoreV1Api()
    return core_v1


@pytest.fixture(scope="session", autouse=True)
def ensure_namespace(kube_clients):
    core_v1 = kube_clients
    ns_body = client.V1Namespace(metadata=client.V1ObjectMeta(name=NAMESPACE))
    try:
        core_v1.read_namespace(name=NAMESPACE)
    except ApiException as e:
        if e.status == 404:
            core_v1.create_namespace(body=ns_body)
        else:
            raise
    yield


@pytest.fixture(scope="module", autouse=True)
def create_test_pod(kube_clients):
    core_v1 = kube_clients

    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        pod_manifest = yaml.safe_load(f)

    try:
        core_v1.create_namespaced_pod(namespace=NAMESPACE, body=pod_manifest)
    except ApiException as e:
        if e.status != 409:  # already exists
            raise

    wait_for_pod_phase(core_v1, NAMESPACE, POD_NAME, "Running", timeout=180)
    wait_for_pod_ready(core_v1, NAMESPACE, POD_NAME, timeout=180)
    yield


def wait_for_pod_phase(core_v1, namespace, pod_name, expected_phase, timeout=120, interval=3):
    end = time.time() + timeout
    while time.time() < end:
        pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        if pod.status.phase == expected_phase:
            return pod
        time.sleep(interval)
    raise TimeoutError(f"Pod {pod_name} did not reach phase {expected_phase} within {timeout}s")


def wait_for_pod_ready(core_v1, namespace, pod_name, timeout=120, interval=3):
    end = time.time() + timeout
    while time.time() < end:
        pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        conditions = pod.status.conditions or []
        for c in conditions:
            if c.type == "Ready" and c.status == "True":
                return pod
        time.sleep(interval)
    raise TimeoutError(f"Pod {pod_name} did not become Ready within {timeout}s")


def wait_for_pod_deleted(core_v1, namespace, pod_name, timeout=120, interval=2):
    end = time.time() + timeout
    while time.time() < end:
        try:
            core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            time.sleep(interval)
        except ApiException as e:
            if e.status == 404:
                return
            raise
    raise TimeoutError(f"Pod {pod_name} still exists after {timeout}s")


def get_restart_count(pod, container_name="nginx"):
    statuses = pod.status.container_statuses or []
    for s in statuses:
        if s.name == container_name:
            return s.restart_count
    return 0


def test_01_cluster_access_and_nodes_ready(kube_clients):
    core_v1 = kube_clients

    # API accessibility
    nodes = core_v1.list_node().items
    assert len(nodes) > 0, "No nodes found; API may be inaccessible."

    # Node readiness
    ready_nodes = 0
    for node in nodes:
        for cond in (node.status.conditions or []):
            if cond.type == "Ready" and cond.status == "True":
                ready_nodes += 1
                break

    assert ready_nodes >= 1, "No Ready node found in cluster."


def test_02_pod_status_running(kube_clients):
    core_v1 = kube_clients

    pods = core_v1.list_namespaced_pod(namespace=NAMESPACE).items
    pod_names = [p.metadata.name for p in pods]
    assert POD_NAME in pod_names, f"{POD_NAME} not found in namespace {NAMESPACE}"

    pod = core_v1.read_namespaced_pod(name=POD_NAME, namespace=NAMESPACE)
    assert pod.status.phase == "Running", f"Pod phase is {pod.status.phase}, expected Running"


def test_03_probes_present_and_readiness_ok(kube_clients):
    core_v1 = kube_clients
    pod = core_v1.read_namespaced_pod(name=POD_NAME, namespace=NAMESPACE)

    # Find nginx container explicitly
    nginx_container = None
    for c in pod.spec.containers:
        if c.name == "nginx":
            nginx_container = c
            break
    assert nginx_container is not None, "Container 'nginx' not found in pod spec"

    assert nginx_container.liveness_probe is not None, "Liveness probe is missing"
    assert nginx_container.readiness_probe is not None, "Readiness probe is missing"

    pod_ready = wait_for_pod_ready(core_v1, NAMESPACE, POD_NAME, timeout=180)
    conditions = {c.type: c.status for c in (pod_ready.status.conditions or [])}
    assert conditions.get("Ready") == "True", "Pod readiness probe did not pass"


def test_04_liveness_failure_triggers_restart(kube_clients):
    core_v1 = kube_clients

    # Baseline restart count
    pod_before = core_v1.read_namespaced_pod(name=POD_NAME, namespace=NAMESPACE)
    before_restart = get_restart_count(pod_before, "nginx")

    # Simulate liveness failure by killing container PID 1 (nginx master process)
    stream(
        core_v1.connect_get_namespaced_pod_exec,
        POD_NAME,
        NAMESPACE,
        container="nginx",
        command=["/bin/sh", "-c", "kill 1"],
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False,
    )

    # Wait for Kubernetes restart
    end = time.time() + 180
    while time.time() < end:
        pod_now = core_v1.read_namespaced_pod(name=POD_NAME, namespace=NAMESPACE)
        now_restart = get_restart_count(pod_now, "nginx")
        if now_restart > before_restart:
            return
        time.sleep(3)

    pytest.fail("Pod was not restarted after liveness failure simulation")


def test_05_cleanup_delete_pod(kube_clients):
    core_v1 = kube_clients

    try:
        core_v1.delete_namespaced_pod(name=POD_NAME, namespace=NAMESPACE)
    except ApiException as e:
        if e.status != 404:
            raise

    wait_for_pod_deleted(core_v1, NAMESPACE, POD_NAME, timeout=120)
