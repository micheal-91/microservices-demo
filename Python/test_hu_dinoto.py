import time
import pytest
import yaml

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.stream import stream


NAMESPACE = "testtest-auto"
POD_NAME = "nginx-healthcheck"
MANIFEST_FILE = "nginx-healthcheck.yaml"


def log(msg):
    print(f"\n[INFO] {msg}")


def log_ok(msg):
    print(f"[OK] {msg}")


def log_warn(msg):
    print(f"[WARN] {msg}")


@pytest.fixture(scope="session")
def kube_clients():
    log("Loading kubeconfig...")
    config.load_kube_config()
    core_v1 = client.CoreV1Api()
    log_ok("Kubernetes client initialized")
    return core_v1


@pytest.fixture(scope="session", autouse=True)
def ensure_namespace(kube_clients):
    core_v1 = kube_clients
    ns_body = client.V1Namespace(metadata=client.V1ObjectMeta(name=NAMESPACE))
    log(f"Ensuring namespace exists: {NAMESPACE}")
    try:
        core_v1.read_namespace(name=NAMESPACE)
        log_ok(f"Namespace '{NAMESPACE}' already exists")
    except ApiException as e:
        if e.status == 404:
            core_v1.create_namespace(body=ns_body)
            log_ok(f"Namespace '{NAMESPACE}' created")
        else:
            raise
    yield


@pytest.fixture(scope="module", autouse=True)
def create_test_pod(kube_clients):
    core_v1 = kube_clients

    log(f"Loading pod manifest from: {MANIFEST_FILE}")
    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        pod_manifest = yaml.safe_load(f)

    log(f"Creating pod '{POD_NAME}' in namespace '{NAMESPACE}'")
    try:
        core_v1.create_namespaced_pod(namespace=NAMESPACE, body=pod_manifest)
        log_ok("Pod created")
    except ApiException as e:
        if e.status == 409:
            log_warn("Pod already exists, reusing existing pod")
        else:
            raise

    wait_for_pod_phase(core_v1, NAMESPACE, POD_NAME, "Running", timeout=180)
    wait_for_pod_ready(core_v1, NAMESPACE, POD_NAME, timeout=180)
    yield


def wait_for_pod_phase(core_v1, namespace, pod_name, expected_phase, timeout=120, interval=3):
    log(f"Waiting for pod '{pod_name}' phase='{expected_phase}' (timeout={timeout}s)")
    end = time.time() + timeout
    while time.time() < end:
        pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        current_phase = pod.status.phase
        print(f"  - Current phase: {current_phase}")
        if current_phase == expected_phase:
            log_ok(f"Pod phase reached '{expected_phase}'")
            return pod
        time.sleep(interval)
    raise TimeoutError(f"Pod {pod_name} did not reach phase {expected_phase} within {timeout}s")


def wait_for_pod_ready(core_v1, namespace, pod_name, timeout=120, interval=3):
    log(f"Waiting for pod '{pod_name}' Ready=True (timeout={timeout}s)")
    end = time.time() + timeout
    while time.time() < end:
        pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        conditions = pod.status.conditions or []
        ready = False
        for c in conditions:
            if c.type == "Ready":
                print(f"  - Ready condition: {c.status}")
                if c.status == "True":
                    ready = True
        if ready:
            log_ok("Pod is Ready")
            return pod
        time.sleep(interval)
    raise TimeoutError(f"Pod {pod_name} did not become Ready within {timeout}s")


def wait_for_pod_deleted(core_v1, namespace, pod_name, timeout=120, interval=2):
    log(f"Waiting for pod '{pod_name}' deletion (timeout={timeout}s)")
    end = time.time() + timeout
    while time.time() < end:
        try:
            core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            print("  - Pod still exists...")
            time.sleep(interval)
        except ApiException as e:
            if e.status == 404:
                log_ok("Pod deleted")
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
    log("TEST 01 - Cluster accessibility and node status")

    nodes = core_v1.list_node().items
    assert len(nodes) > 0, "No nodes found; API may be inaccessible."
    log_ok(f"Kubernetes API reachable, nodes found: {len(nodes)}")

    ready_nodes = 0
    print("Node statuses:")
    for node in nodes:
        node_name = node.metadata.name
        node_ready = "Unknown"
        for cond in (node.status.conditions or []):
            if cond.type == "Ready":
                node_ready = cond.status
                if cond.status == "True":
                    ready_nodes += 1
                break
        print(f"  - {node_name}: Ready={node_ready}")

    assert ready_nodes >= 1, "No Ready node found in cluster."
    log_ok(f"Ready nodes: {ready_nodes}/{len(nodes)}")


def test_02_pod_status_running(kube_clients):
    core_v1 = kube_clients
    log("TEST 02 - List pods and verify nginx pod is Running")

    pods = core_v1.list_namespaced_pod(namespace=NAMESPACE).items
    print(f"Pods in namespace '{NAMESPACE}':")
    for p in pods:
        print(f"  - {p.metadata.name}: phase={p.status.phase}")

    pod_names = [p.metadata.name for p in pods]
    assert POD_NAME in pod_names, f"{POD_NAME} not found in namespace {NAMESPACE}"

    pod = core_v1.read_namespaced_pod(name=POD_NAME, namespace=NAMESPACE)
    assert pod.status.phase == "Running", f"Pod phase is {pod.status.phase}, expected Running"
    log_ok(f"Pod '{POD_NAME}' is Running")


def test_03_probes_present_and_readiness_ok(kube_clients):
    core_v1 = kube_clients
    log("TEST 03 - Check liveness/readiness probes and readiness status")

    pod = core_v1.read_namespaced_pod(name=POD_NAME, namespace=NAMESPACE)

    nginx_container = None
    for c in pod.spec.containers:
        if c.name == "nginx":
            nginx_container = c
            break
    assert nginx_container is not None, "Container 'nginx' not found"

    assert nginx_container.liveness_probe is not None, "Liveness probe is missing"
    log_ok("Liveness probe is configured")

    assert nginx_container.readiness_probe is not None, "Readiness probe is missing"
    log_ok("Readiness probe is configured")

    wait_for_pod_ready(core_v1, NAMESPACE, POD_NAME, timeout=180)
    log_ok("Readiness probe passing (Pod Ready=True)")


def test_04_liveness_failure_triggers_restart(kube_clients):
    core_v1 = kube_clients
    log("TEST 04 - Simulate liveness failure and verify auto-restart")

    pod_before = core_v1.read_namespaced_pod(name=POD_NAME, namespace=NAMESPACE)
    before_restart = get_restart_count(pod_before, "nginx")
    print(f"Restart count before failure: {before_restart}")

    log("Killing PID 1 in nginx container to trigger failure...")
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
    log_ok("Failure injected")

    end = time.time() + 180
    while time.time() < end:
        pod_now = core_v1.read_namespaced_pod(name=POD_NAME, namespace=NAMESPACE)
        now_restart = get_restart_count(pod_now, "nginx")
        print(f"  - Current restart count: {now_restart}")
        if now_restart > before_restart:
            log_ok(f"Container restarted automatically ({before_restart} -> {now_restart})")
            return
        time.sleep(3)

    pytest.fail("Pod was not restarted after liveness failure simulation")


def test_05_cleanup_delete_pod(kube_clients):
    core_v1 = kube_clients
    log("TEST 05 - Cleanup: delete pod")

    try:
        core_v1.delete_namespaced_pod(name=POD_NAME, namespace=NAMESPACE)
        log_ok(f"Delete request sent for pod '{POD_NAME}'")
    except ApiException as e:
        if e.status == 404:
            log_warn("Pod already deleted")
            return
        raise

    wait_for_pod_deleted(core_v1, NAMESPACE, POD_NAME, timeout=120)
    log_ok("Cleanup completed")
