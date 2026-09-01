"""
Container lifecycle management for the load balancer.

Two implementations are provided behind the same interface:

  DockerContainerManager  - spawns/stops real Docker containers on the
                             `net1` user-defined network via the Docker
                             Engine API (docker-py), talking to the socket
                             mounted into the load-balancer container
                             (/var/run/docker.sock). This is what the
                             assignment asks for and is used by default
                             when the load balancer runs inside Docker.

  ProcessContainerManager - spawns plain local `python server/app.py`
                             subprocesses on free TCP ports instead of
                             containers. This has no external dependency
                             on the Docker daemon and is used automatically
                             when LB_MODE=process (see app.py), which lets
                             the whole system be developed and the Task 4
                             analysis be exercised end-to-end on a machine
                             without Docker installed (as is the case in
                             this development sandbox). The externally
                             observable behaviour (routing, /rep, /add,
                             /rm, failure recovery) is identical either way.

Every manager exposes:
    start(hostname, server_id) -> address   # "host:port" to reach the replica
    stop(hostname)
    address_of(hostname) -> "host:port"
"""
import os
import random
import socket
import string
import subprocess
import sys
import threading


def random_hostname(prefix="srv"):
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{prefix}_{suffix}"


class DockerContainerManager:
    def __init__(self, image="ds_lb_server:latest", network="net1", internal_port=5000):
        import docker  # imported lazily so process mode has no hard dependency
        self.client = docker.from_env()
        self.image = image
        self.network = network
        self.internal_port = internal_port

    def start(self, hostname, server_id):
        self.client.containers.run(
            self.image,
            name=hostname,
            hostname=hostname,
            network=self.network,
            environment={"SERVER_ID": str(server_id)},
            detach=True,
        )
        return f"{hostname}:{self.internal_port}"

    def stop(self, hostname):
        try:
            c = self.client.containers.get(hostname)
            c.stop(timeout=2)
            c.remove(force=True)
        except Exception:
            pass  # already gone

    def address_of(self, hostname):
        return f"{hostname}:{self.internal_port}"

    def kill_ungracefully(self, hostname):
        """Used only by the failure-injection analysis script (A-3):
        hard-kills a container without deregistering it, to simulate a crash."""
        try:
            self.client.containers.get(hostname).kill()
        except Exception:
            pass


class ProcessContainerManager:
    def __init__(self, server_script=None):
        self.server_script = server_script or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server", "app.py"
        )
        self._procs = {}       # hostname -> subprocess.Popen
        self._ports = {}       # hostname -> port
        self._lock = threading.Lock()

    @staticmethod
    def _free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def start(self, hostname, server_id):
        port = self._free_port()
        env = dict(os.environ)
        env["SERVER_ID"] = str(server_id)
        env["PORT"] = str(port)
        proc = subprocess.Popen(
            [sys.executable, self.server_script],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with self._lock:
            self._procs[hostname] = proc
            self._ports[hostname] = port
        return f"127.0.0.1:{port}"

    def stop(self, hostname):
        with self._lock:
            proc = self._procs.pop(hostname, None)
            self._ports.pop(hostname, None)
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    def address_of(self, hostname):
        port = self._ports.get(hostname)
        return f"127.0.0.1:{port}" if port else None

    def kill_ungracefully(self, hostname):
        proc = self._procs.get(hostname)
        if proc is not None:
            proc.kill()
