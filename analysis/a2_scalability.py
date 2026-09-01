"""
A-2: Increment N from 2 to 6, launch 10000 requests on each such increment,
and report the average load of the servers at each run in a line chart.

"Average load" (10000/N) is trivially determined by N, so alongside it we
also report the standard deviation / coefficient of variation of the
per-server counts at each N -- this is the number that actually speaks to
how well the load balancer scales, since a perfectly balanced system keeps
CV roughly flat as N grows while a poorly balancing one gets worse.
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
BASE_PORT = 7110


def run_for_n(n, port):
    proc, base_url = start_lb(port, n=n, heartbeat_interval=1000)
    try:
        results = fire_requests(base_url, "home", REQUESTS)
        counts, errors = count_by_message(results)
    finally:
        stop_lb(proc)
    values = [v for k, v in counts.items() if k.startswith("Hello from Server:")]
    return values, errors


def main():
    ns = list(range(2, 7))
    means, stdevs, cvs, error_counts = [], [], [], []

    for idx, n in enumerate(ns):
        port = BASE_PORT + idx
        print(f"N={n}: starting load balancer on port {port} ...")
        values, errors = run_for_n(n, port)
        mean = statistics.mean(values)
        stdev = statistics.pstdev(values)
        cv = stdev / mean if mean else 0
        means.append(mean)
        stdevs.append(stdev)
        cvs.append(cv)
        error_counts.append(errors)
        print(f"  servers responded={len(values)}/{n} mean={mean:.1f} pstdev={stdev:.1f} cv={cv:.3f} errors={errors}")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

    ax1.plot(ns, means, marker="o", color="#4C72B0", label="mean requests/server")
    ax1.plot(ns, [REQUESTS / n for n in ns], linestyle="--", color="gray", label="ideal (10000/N)")
    ax1.set_xlabel("N (server replicas)")
    ax1.set_ylabel("Average requests handled per server")
    ax1.set_title("A-2: Average load vs N")
    ax1.legend()
    ax1.grid(alpha=0.3)

    ax2.plot(ns, cvs, marker="o", color="#DD8452")
    ax2.set_xlabel("N (server replicas)")
    ax2.set_ylabel("Coefficient of variation (stdev / mean)")
    ax2.set_title("A-2: Load imbalance vs N")
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    out = os.path.join(RESULTS_DIR, "a2_scalability.png")
    plt.savefig(out, dpi=150)
    print(f"Saved chart to {out}")

    with open(os.path.join(RESULTS_DIR, "a2_summary.txt"), "w") as f:
        f.write("N, mean, pstdev, coeff_of_variation, errors\n")
        for n, m, s, cv, e in zip(ns, means, stdevs, cvs, error_counts):
            f.write(f"{n}, {m:.1f}, {s:.1f}, {cv:.3f}, {e}\n")


if __name__ == "__main__":
    main()
