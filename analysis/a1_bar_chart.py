"""
A-1: Launch 10000 async requests on N = 3 server containers and report the
request count handled by each server instance in a bar chart.
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

N = 3
REQUESTS = 10000
PORT = 7101


def main():
    print(f"Starting load balancer with N={N} on port {PORT} ...")
    proc, base_url = start_lb(PORT, n=N, heartbeat_interval=1000)
    try:
        print(f"Firing {REQUESTS} async GET /home requests ...")
        results = fire_requests(base_url, "home", REQUESTS)
        counts, errors = count_by_message(results)
    finally:
        stop_lb(proc)

    print(f"Errors/timeouts: {errors}")
    labels = sorted(
        (m for m in counts if m.startswith("Hello from Server:")),
        key=lambda m: int(m.split(":")[-1].strip()),
    )
    values = [counts[l] for l in labels]
    short_labels = [l.replace("Hello from Server: ", "Server ") for l in labels]

    mean = statistics.mean(values)
    stdev = statistics.pstdev(values)
    print("Per-server counts:")
    for l, v in zip(short_labels, values):
        print(f"  {l}: {v}")
    print(f"mean={mean:.1f}  pstdev={stdev:.1f}  coeff_of_variation={stdev/mean:.3f}")

    plt.figure(figsize=(6, 4))
    bars = plt.bar(short_labels, values, color="#4C72B0")
    plt.axhline(mean, color="red", linestyle="--", linewidth=1, label=f"mean={mean:.0f}")
    for b, v in zip(bars, values):
        plt.text(b.get_x() + b.get_width() / 2, v + 30, str(v), ha="center", fontsize=9)
    plt.ylabel("Requests handled")
    plt.title(f"A-1: Load distribution across N={N} servers ({REQUESTS} requests)")
    plt.legend()
    plt.tight_layout()
    out = os.path.join(RESULTS_DIR, "a1_bar_chart.png")
    plt.savefig(out, dpi=150)
    print(f"Saved chart to {out}")

    with open(os.path.join(RESULTS_DIR, "a1_summary.txt"), "w") as f:
        f.write(f"N={N} requests={REQUESTS} errors={errors}\n")
        for l, v in zip(short_labels, values):
            f.write(f"{l}: {v}\n")
        f.write(f"mean={mean:.1f} pstdev={stdev:.1f} coeff_of_variation={stdev/mean:.3f}\n")


if __name__ == "__main__":
    main()
