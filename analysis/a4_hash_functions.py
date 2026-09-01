"""
A-4: Modify the hash functions H(i), Phi(i, j) and repeat the A-1 (N=3 bar
chart) and A-2 (N=2..6 scalability) experiments, to see whether a better
hash function improves load distribution.

The assignment's default functions are quadratic and reused unchanged
across the analysis:
    H(i)     = i^2 + 2*i + 17
    Phi(i,j) = i^2 + j^2 + 2*j + 25

Both concentrate outputs (mod 512) unevenly -- e.g. Phi doesn't depend much
on the low bits of i, so different servers' virtual nodes can land in
nearby clusters, which is what produced the imbalance seen in A-1/A-2.

As an alternative we use a cheap multiplicative (Knuth) hash, which mixes
bits far better while remaining trivial to compute:
    H'(i)     = (i * 2654435761)
    Phi'(i,j) = ((i * 2654435761) ^ (j * 40503))

The two hash functions are injected into the load balancer via the
LB_REQUEST_HASH / LB_VIRTUAL_HASH env vars (see load_balancer/app.py), so
this script exercises the *actual system*, not just a standalone
simulation.
"""
import os
import statistics
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lb_harness import start_lb, stop_lb, fire_requests, count_by_message

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

REQUESTS = 10000

HASH_VARIANTS = {
    "default (assignment)": None,  # use built-in defaults
    "multiplicative (Knuth)": {
        "LB_REQUEST_HASH": "lambda i: (i * 2654435761)",
        "LB_VIRTUAL_HASH": "lambda i, j: (i * 2654435761) ^ (j * 40503)",
    },
}


def run_a1(variant_name, env, port):
    proc, base_url = start_lb(port, n=3, heartbeat_interval=1000, extra_env=env)
    try:
        results = fire_requests(base_url, "home", REQUESTS)
        counts, errors = count_by_message(results)
    finally:
        stop_lb(proc)
    values = [v for k, v in counts.items() if k.startswith("Hello from Server:")]
    mean = statistics.mean(values) if values else 0
    stdev = statistics.pstdev(values) if values else 0
    cv = stdev / mean if mean else 0
    print(f"  A-1 [{variant_name}] counts={sorted(values, reverse=True)} mean={mean:.1f} cv={cv:.3f} errors={errors}")
    return values, cv


def run_a2(variant_name, env, base_port):
    ns = list(range(2, 7))
    cvs = []
    for idx, n in enumerate(ns):
        proc, base_url = start_lb(base_port + idx, n=n, heartbeat_interval=1000, extra_env=env)
        try:
            results = fire_requests(base_url, "home", REQUESTS)
            counts, errors = count_by_message(results)
        finally:
            stop_lb(proc)
        values = [v for k, v in counts.items() if k.startswith("Hello from Server:")]
        mean = statistics.mean(values) if values else 0
        stdev = statistics.pstdev(values) if values else 0
        cv = stdev / mean if mean else 0
        cvs.append(cv)
        print(f"  A-2 [{variant_name}] N={n} cv={cv:.3f} errors={errors}")
    return ns, cvs


def main():
    a1_results = {}
    a2_results = {}
    port = 7200

    for name, env in HASH_VARIANTS.items():
        print(f"=== Hash variant: {name} ===")
        values, cv = run_a1(name, env, port)
        a1_results[name] = (values, cv)
        port += 1

        ns, cvs = run_a2(name, env, port)
        a2_results[name] = (ns, cvs)
        port += len(ns)

    # --- Chart 1: A-1 bar comparison ------------------------------------
    fig, ax = plt.subplots(figsize=(7, 4.5))
    width = 0.35
    names = list(a1_results.keys())
    max_servers = max(len(v[0]) for v in a1_results.values())
    x = range(max_servers)
    for i, name in enumerate(names):
        values = sorted(a1_results[name][0], reverse=True)
        values += [0] * (max_servers - len(values))
        offset = (i - 0.5) * width
        ax.bar([xi + offset for xi in x], values, width=width, label=name)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"server rank {i+1}" for i in x])
    ax.set_ylabel("Requests handled (N=3, 10000 requests)")
    ax.set_title("A-4: Load distribution, default vs. multiplicative hash")
    ax.legend()
    plt.tight_layout()
    out1 = os.path.join(RESULTS_DIR, "a4_hash_comparison_bar.png")
    plt.savefig(out1, dpi=150)
    print(f"Saved chart to {out1}")

    # --- Chart 2: A-2 CV-vs-N comparison ---------------------------------
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for name, (ns, cvs) in a2_results.items():
        ax.plot(ns, cvs, marker="o", label=name)
    ax.set_xlabel("N (server replicas)")
    ax.set_ylabel("Coefficient of variation (stdev / mean)")
    ax.set_title("A-4: Load imbalance vs N, default vs. multiplicative hash")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    out2 = os.path.join(RESULTS_DIR, "a4_hash_comparison_scalability.png")
    plt.savefig(out2, dpi=150)
    print(f"Saved chart to {out2}")

    with open(os.path.join(RESULTS_DIR, "a4_summary.txt"), "w") as f:
        for name in names:
            values, cv = a1_results[name]
            f.write(f"[{name}] A-1 N=3 counts={sorted(values, reverse=True)} cv={cv:.3f}\n")
        for name, (ns, cvs) in a2_results.items():
            f.write(f"[{name}] A-2 cv-by-N: {list(zip(ns, [round(c,3) for c in cvs]))}\n")


if __name__ == "__main__":
    main()
