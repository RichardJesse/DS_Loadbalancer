"""
Task 2: Consistent Hashing

Implements the circular consistent-hash map described in Appendix A of the
assignment using a fixed-size Python list as the underlying array.

Default parameters (as mandated by the assignment):
    #slots (M)              = 512
    virtual servers (K)     = log2(512) = 9
    request hash   H(i)     = i^2 + 2*i + 17
    virtual hash Phi(i, j)  = i^2 + j^2 + 2*j + 25

`i` in H(i) is the (random) request id.
`i` in Phi(i, j) is a numeric server id derived deterministically from the
server's hostname (so hostnames such as "S5" or a randomly generated
container name can still be placed on the ring); `j` is the virtual replica
index in [0, K).

Two hash functions collide often at M = 512, so slot placement uses
quadratic probing to resolve conflicts when *inserting* virtual servers.
Looking a request up walks the ring clockwise (linear scan) to the nearest
occupied slot, exactly as described in the appendix -- this is NOT probing,
it is how consistent hashing assigns a request to "the server in the
nearest slot".
"""
import hashlib
import math


def default_request_hash(i: int) -> int:
    return i ** 2 + 2 * i + 17


def default_virtual_hash(i: int, j: int) -> int:
    return i ** 2 + j ** 2 + 2 * j + 25


class ConsistentHashMap:
    def __init__(self, num_slots: int = 512, num_virtual: int = None,
                 request_hash=None, virtual_hash=None):
        self.num_slots = num_slots
        self.num_virtual = num_virtual or max(1, round(math.log2(num_slots)))
        self.request_hash = request_hash or default_request_hash
        self.virtual_hash = virtual_hash or default_virtual_hash

        # slot -> hostname (str) or None if empty
        self.slots = [None] * self.num_slots
        # hostname -> sorted list of slot indices it occupies (for O(1) removal)
        self.server_slots = {}

    # ------------------------------------------------------------------
    def _server_numeric_id(self, hostname: str) -> int:
        """Deterministically map an arbitrary hostname string to an integer
        server id used as `i` in Phi(i, j)."""
        digest = hashlib.md5(hostname.encode()).hexdigest()
        return int(digest, 16) % self.num_slots

    # ------------------------------------------------------------------
    def add_server(self, hostname: str):
        if hostname in self.server_slots:
            raise ValueError(f"server '{hostname}' already present in hash map")

        sid = self._server_numeric_id(hostname)
        placed = []
        for j in range(self.num_virtual):
            base = self.virtual_hash(sid, j) % self.num_slots
            pos = base
            tries = 0
            while self.slots[pos] is not None:
                tries += 1
                if tries > self.num_slots:
                    raise RuntimeError("consistent hash map is full")
                # quadratic probing: base, base+1^2, base+2^2, ...
                pos = (base + tries * tries) % self.num_slots
            self.slots[pos] = hostname
            placed.append(pos)

        self.server_slots[hostname] = placed
        return placed

    # ------------------------------------------------------------------
    def remove_server(self, hostname: str):
        if hostname not in self.server_slots:
            return
        for pos in self.server_slots[hostname]:
            self.slots[pos] = None
        del self.server_slots[hostname]

    # ------------------------------------------------------------------
    def get_server(self, request_id: int):
        """Return the hostname responsible for `request_id`, walking the
        ring clockwise from H(request_id) % M to the nearest occupied slot."""
        if not self.server_slots:
            return None

        pos = self.request_hash(request_id) % self.num_slots
        start = pos
        while self.slots[pos] is None:
            pos = (pos + 1) % self.num_slots
            if pos == start:
                return None  # ring is empty (shouldn't happen, guarded above)
        return self.slots[pos]

    # ------------------------------------------------------------------
    def load_counts(self):
        """Number of occupied virtual-server slots per hostname (diagnostic,
        not the same as actual request load)."""
        return {host: len(slots) for host, slots in self.server_slots.items()}

    def __len__(self):
        return len(self.server_slots)

    def __contains__(self, hostname):
        return hostname in self.server_slots
