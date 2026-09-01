"""
Shared test harness for the Task 4 analysis scripts.

Starts the load balancer (load_balancer/app.py) as a local subprocess in
LB_MODE=process, so the full request-routing / consistent-hashing /
heartbeat-recovery logic runs exactly as it would in Docker, just with
plain OS processes standing in for containers. This lets the analysis run
end-to-end on any machine, Docker or not (see README "How the analysis was
run" for why this project uses that mode here).
"""
import asyncio
import os
import subprocess
import sys
import time

import psutil
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LB_SCRIPT = os.path.join(ROOT, "load_balancer", "app.py")


def start_lb(port, n=3, heartbeat_interval=4, heartbeat_timeout=2,
             num_slots=512, num_virtual=9, extra_env=None, ready_timeout=15):
    env = dict(os.environ)
    env.update({
        "LB_MODE": "process",
        "LB_PORT": str(port),
        "N": str(n),
        "NUM_SLOTS": str(num_slots),
        "NUM_VIRTUAL": str(num_virtual),
        "HEARTBEAT_INTERVAL": str(heartbeat_interval),
        "HEARTBEAT_TIMEOUT": str(heartbeat_timeout),
        "PYTHONUNBUFFERED": "1",
    })
    if extra_env:
        env.update(extra_env)

    proc = subprocess.Popen(
        [sys.executable, LB_SCRIPT],
        cwd=os.path.join(ROOT, "load_balancer"),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + ready_timeout
    last_err = None
    while time.time() < deadline:
        try:
            r = requests.get(f"{base_url}/rep", timeout=1)
            if r.status_code == 200 and r.json()["message"]["N"] == n:
                return proc, base_url
        except requests.RequestException as e:
            last_err = e
        time.sleep(0.3)
    stop_lb(proc)
    raise RuntimeError(f"load balancer on port {port} did not become ready: {last_err}")


def stop_lb(proc):
    """Kills the LB process and every server subprocess it spawned (its
    children aren't reaped automatically by terminating the parent alone
    on Windows)."""
    try:
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        for c in children:
            try:
                c.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
    except psutil.NoSuchProcess:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def child_pids(proc):
    try:
        return [c.pid for c in psutil.Process(proc.pid).children(recursive=True)]
    except psutil.NoSuchProcess:
        return []


# ---------------------------------------------------------------------------
async def _fetch(session, url, retries=2):
    for attempt in range(retries + 1):
        try:
            async with session.get(url, timeout=10) as resp:
                return await resp.json(content_type=None)
        except Exception as e:
            last_err = str(e)
    return {"error": last_err}


async def _fire_all(base_url, path, count, concurrency=200):
    import aiohttp
    connector = aiohttp.TCPConnector(limit=concurrency)
    results = []
    async with aiohttp.ClientSession(connector=connector) as session:
        sem = asyncio.Semaphore(concurrency)

        async def bound_fetch():
            async with sem:
                return await _fetch(session, f"{base_url}/{path}")

        tasks = [asyncio.create_task(bound_fetch()) for _ in range(count)]
        for coro in asyncio.as_completed(tasks):
            results.append(await coro)
    return results


def fire_requests(base_url, path, count, concurrency=100):
    """Fires `count` asynchronous GET requests at base_url/path and returns
    the list of parsed JSON responses."""
    return asyncio.run(_fire_all(base_url, path, count, concurrency))


def count_by_message(results):
    counts = {}
    errors = 0
    for r in results:
        msg = r.get("message") if isinstance(r, dict) else None
        if not msg or "error" in r:
            errors += 1
            continue
        counts[msg] = counts.get(msg, 0) + 1
    return counts, errors
