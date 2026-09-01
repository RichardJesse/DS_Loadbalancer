"""
Task 3: Load Balancer

Routes client requests to a set of N server replicas using the consistent
hash map from Task 2, exposes management endpoints (/rep, /add, /rm) and
transparently proxies everything else (/<path>) to a replica chosen by the
hash map. A background thread polls every replica's /heartbeat endpoint and
replaces any replica that stops responding, so that exactly N replicas are
always available (Task 3 failure-recovery requirement).

Two deployment modes, selected by the LB_MODE env var:
  docker   (default)  -> replicas are real Docker containers on `net1`,
                          managed through the Docker socket (see
                          container_manager.DockerContainerManager). This is
                          the mode required by the assignment and used by
                          docker-compose.yml.
  process              -> replicas are local subprocesses on 127.0.0.1
                          (container_manager.ProcessContainerManager). Used
                          for local development/testing on machines without
                          a Docker daemon (see analysis/ scripts and README).
"""
import os
import random
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from flask import Flask, jsonify, request

# A pooled, keep-alive session for talking to replicas. Using plain
# requests.get() per call opens a fresh TCP connection every time, which
# becomes the bottleneck (and source of spurious connection errors) once
# the load balancer is fanning thousands of requests/sec out to a handful
# of replicas (see analysis/ Task 4 load tests).
_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=64, pool_maxsize=64, max_retries=0)
_session.mount("http://", _adapter)

from consistent_hash import ConsistentHashMap
from container_manager import (
    DockerContainerManager,
    ProcessContainerManager,
    random_hostname,
)

# ---------------------------------------------------------------------------
# Configuration (Task 2 defaults; can be overridden via env vars for A-4).
# ---------------------------------------------------------------------------
NUM_SLOTS = int(os.environ.get("NUM_SLOTS", 512))
NUM_VIRTUAL = int(os.environ.get("NUM_VIRTUAL", 9))
INITIAL_N = int(os.environ.get("N", 3))
HEARTBEAT_INTERVAL = float(os.environ.get("HEARTBEAT_INTERVAL", 4))
HEARTBEAT_TIMEOUT = float(os.environ.get("HEARTBEAT_TIMEOUT", 2))
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", 5))
LB_MODE = os.environ.get("LB_MODE", "docker")


def _load_hash_fn(env_name, default_fn, arity):
    """Allows A-4 to inject alternative H(i)/Phi(i,j) via env vars, e.g.
    LB_REQUEST_HASH="lambda i: i*7 + 3" without touching the source code."""
    expr = os.environ.get(env_name)
    if not expr:
        return default_fn
    fn = eval(expr)  # trusted, operator-supplied config only (see README)
    return fn


from consistent_hash import default_request_hash, default_virtual_hash

request_hash = _load_hash_fn("LB_REQUEST_HASH", default_request_hash, 1)
virtual_hash = _load_hash_fn("LB_VIRTUAL_HASH", default_virtual_hash, 2)

# ---------------------------------------------------------------------------
app = Flask(__name__)
state_lock = threading.RLock()
chm = ConsistentHashMap(
    num_slots=NUM_SLOTS,
    num_virtual=NUM_VIRTUAL,
    request_hash=request_hash,
    virtual_hash=virtual_hash,
)

manager = (
    ProcessContainerManager()
    if LB_MODE == "process"
    else DockerContainerManager()
)

# hostname -> {"server_id": int, "address": "host:port"}
replicas = {}
_server_id_counter = 0


def _next_server_id():
    global _server_id_counter
    _server_id_counter += 1
    return _server_id_counter


def _spawn_one(hostname=None):
    """Starts one new replica, registers it in the hash map. Caller must
    hold state_lock. Returns the hostname used."""
    hostname = hostname or random_hostname()
    server_id = _next_server_id()
    address = manager.start(hostname, server_id)
    replicas[hostname] = {"server_id": server_id, "address": address}
    chm.add_server(hostname)
    return hostname


def _remove_one(hostname):
    """Caller must hold state_lock."""
    manager.stop(hostname)
    chm.remove_server(hostname)
    replicas.pop(hostname, None)


def _bootstrap():
    with state_lock:
        for i in range(1, INITIAL_N + 1):
            _spawn_one(f"Server {i}")


# ---------------------------------------------------------------------------
# Heartbeat / self-healing thread
# ---------------------------------------------------------------------------
def _heartbeat_loop():
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        with state_lock:
            hosts = list(replicas.items())
        for hostname, info in hosts:
            ok = False
            try:
                r = _session.get(f"http://{info['address']}/heartbeat", timeout=HEARTBEAT_TIMEOUT)
                ok = r.status_code == 200
            except requests.RequestException:
                ok = False
            if not ok:
                with state_lock:
                    if hostname in replicas:  # still missing -> replace
                        print(f"[heartbeat] {hostname} is down, spawning replacement", flush=True)
                        _remove_one(hostname)
                        new_host = _spawn_one()
                        print(f"[heartbeat] spawned replacement {new_host}", flush=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.route("/rep", methods=["GET"])
def rep():
    with state_lock:
        names = list(replicas.keys())
    return jsonify({
        "message": {"N": len(names), "replicas": names},
        "status": "successful",
    }), 200


@app.route("/add", methods=["POST"])
def add():
    payload = request.get_json(force=True, silent=True) or {}
    n = payload.get("n")
    hostnames = payload.get("hostnames", [])

    if not isinstance(n, int) or n <= 0:
        return jsonify({"message": "<Error> 'n' must be a positive integer", "status": "failure"}), 400
    if not isinstance(hostnames, list):
        return jsonify({"message": "<Error> 'hostnames' must be a list", "status": "failure"}), 400
    if len(hostnames) > n:
        return jsonify({
            "message": "<Error> Length of hostname list is more than newly added instances",
            "status": "failure",
        }), 400

    with state_lock:
        dup = [h for h in hostnames if h in replicas]
        if dup:
            return jsonify({"message": f"<Error> hostname(s) already in use: {dup}", "status": "failure"}), 400

        for h in hostnames:
            _spawn_one(h)
        for _ in range(n - len(hostnames)):
            _spawn_one()

        names = list(replicas.keys())

    return jsonify({
        "message": {"N": len(names), "replicas": names},
        "status": "successful",
    }), 200


@app.route("/rm", methods=["DELETE"])
def rm():
    payload = request.get_json(force=True, silent=True) or {}
    n = payload.get("n")
    hostnames = payload.get("hostnames", [])

    if not isinstance(n, int) or n <= 0:
        return jsonify({"message": "<Error> 'n' must be a positive integer", "status": "failure"}), 400
    if not isinstance(hostnames, list):
        return jsonify({"message": "<Error> 'hostnames' must be a list", "status": "failure"}), 400
    if len(hostnames) > n:
        return jsonify({
            "message": "<Error> Length of hostname list is more than removable instances",
            "status": "failure",
        }), 400

    with state_lock:
        missing = [h for h in hostnames if h not in replicas]
        if missing:
            return jsonify({"message": f"<Error> unknown hostname(s): {missing}", "status": "failure"}), 400
        if n > len(replicas):
            return jsonify({"message": "<Error> n exceeds current number of replicas", "status": "failure"}), 400

        to_remove = list(hostnames)
        remaining_pool = [h for h in replicas.keys() if h not in to_remove]
        random.shuffle(remaining_pool)
        to_remove += remaining_pool[: n - len(hostnames)]

        for h in to_remove:
            _remove_one(h)

        names = list(replicas.keys())

    return jsonify({
        "message": {"N": len(names), "replicas": names},
        "status": "successful",
    }), 200


@app.route("/<path:path>", methods=["GET"])
def route_request(path):
    request_id = random.randint(100000, 999999)  # 6-digit request id, per Appendix A

    # A replica can be mid-restart (heartbeat failure not yet detected, or a
    # brand-new replica still booting); retry once against a fresh pick
    # before giving up, so a single flaky replica doesn't surface as a
    # user-visible error.
    for attempt in range(2):
        with state_lock:
            hostname = chm.get_server(request_id)
            info = replicas.get(hostname) if hostname else None

        if not info:
            return jsonify({"message": "<Error> no server replicas available", "status": "failure"}), 503

        try:
            r = _session.get(f"http://{info['address']}/{path}", timeout=REQUEST_TIMEOUT)
        except requests.RequestException:
            if attempt == 0:
                request_id = random.randint(100000, 999999)
                continue
            return jsonify({
                "message": f"<Error> replica '{hostname}' is unreachable, please retry",
                "status": "failure",
            }), 503

        if r.status_code == 404:
            return jsonify({
                "message": f"<Error> '/{path}' endpoint does not exist in server replicas",
                "status": "failure",
            }), 400

        return (r.content, r.status_code, {"Content-Type": r.headers.get("Content-Type", "application/json")})


if __name__ == "__main__":
    _bootstrap()
    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("LB_PORT", 5000)), threads=64, connection_limit=1000)
