"""
A-3: Exercise every load balancer endpoint (/rep, /add, /rm, /<path>) and
demonstrate that on a server-replica failure, the load balancer detects it
and spawns a replacement quickly.
"""
import json
import os
import random
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lb_harness import start_lb, stop_lb, child_pids

import psutil

PORT = 7130
HEARTBEAT_INTERVAL = 2
HEARTBEAT_TIMEOUT = 1


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label} {detail}")
    return cond


def main():
    all_ok = True
    base = f"http://127.0.0.1:{PORT}"
    print(f"Starting load balancer (N=3) on port {PORT} ...")
    proc, base_url = start_lb(PORT, n=3, heartbeat_interval=HEARTBEAT_INTERVAL,
                               heartbeat_timeout=HEARTBEAT_TIMEOUT)
    try:
        # --- /rep -------------------------------------------------------
        r = requests.get(f"{base}/rep")
        body = r.json()
        all_ok &= check("GET /rep returns N=3", r.status_code == 200 and body["message"]["N"] == 3, body)

        # --- /<path> valid endpoint --------------------------------------
        r = requests.get(f"{base}/home")
        body = r.json()
        all_ok &= check("GET /home routes to a replica", r.status_code == 200 and "Hello from Server" in body["message"], body)

        # --- /<path> invalid endpoint --------------------------------------
        r = requests.get(f"{base}/other")
        body = r.json()
        all_ok &= check("GET /other returns 400 'does not exist'",
                         r.status_code == 400 and "does not exist" in body["message"], body)

        # --- /add -----------------------------------------------------------
        r = requests.post(f"{base}/add", json={"n": 2, "hostnames": ["S_A"]})
        body = r.json()
        all_ok &= check("POST /add n=2 hostnames=[S_A] -> N=5",
                         r.status_code == 200 and body["message"]["N"] == 5, body)

        r = requests.post(f"{base}/add", json={"n": 1, "hostnames": ["S_A", "S_B"]})
        body = r.json()
        all_ok &= check("POST /add with too many hostnames -> 400",
                         r.status_code == 400 and "more than newly added" in body["message"], body)

        # --- /rm -----------------------------------------------------------
        r = requests.delete(f"{base}/rm", json={"n": 2, "hostnames": ["S_A"]})
        body = r.json()
        all_ok &= check("DELETE /rm n=2 hostnames=[S_A] -> N=3",
                         r.status_code == 200 and body["message"]["N"] == 3, body)

        r = requests.delete(f"{base}/rm", json={"n": 1, "hostnames": ["S_A", "S_B"]})
        body = r.json()
        all_ok &= check("DELETE /rm with too many hostnames -> 400",
                         r.status_code == 400 and "more than removable" in body["message"], body)

        # --- failure recovery -------------------------------------------
        before = requests.get(f"{base}/rep").json()["message"]["replicas"]
        print(f"Replicas before failure: {before}")

        pids = child_pids(proc)
        assert pids, "no child server processes found"
        victim_pid = random.choice(pids)
        victim_proc = psutil.Process(victim_pid)
        print(f"Killing replica process pid={victim_pid} to simulate a crash ...")
        t_kill = time.time()
        victim_proc.kill()

        recovered_at = None
        deadline = t_kill + 20
        while time.time() < deadline:
            r = requests.get(f"{base}/rep")
            body = r.json()
            replicas_now = body["message"]["replicas"]
            if body["message"]["N"] == 3 and set(replicas_now) != set(before):
                recovered_at = time.time()
                after = replicas_now
                break
            time.sleep(0.2)

        if recovered_at:
            print(f"Replicas after recovery: {after}")
            all_ok &= check(
                "Load balancer restored N=3 replicas after a crash",
                True,
                f"(recovered in {recovered_at - t_kill:.2f}s, "
                f"within {HEARTBEAT_INTERVAL + HEARTBEAT_TIMEOUT}s heartbeat budget)",
            )
        else:
            all_ok &= check("Load balancer restored N=3 replicas after a crash", False, "timed out")

        # confirm routing still works post-recovery
        r = requests.get(f"{base}/home")
        all_ok &= check("GET /home still works after recovery", r.status_code == 200, r.json())

    finally:
        stop_lb(proc)

    print()
    print("ALL CHECKS PASSED" if all_ok else "SOME CHECKS FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
