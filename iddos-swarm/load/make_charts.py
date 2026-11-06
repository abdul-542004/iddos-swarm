"""load/make_charts.py — before/after figures from results/metrics.csv.

Produces two clean bar charts for the report:
    results/fig_availability.png   /work availability by scenario
    results/fig_restarts.png       web restart count by scenario

Colours are semantic and colour-blind safe (Okabe-Ito): grey = control,
vermillion = vulnerable (bad), bluish-green = mitigated (good).

Run after measure.py:
    python load/make_charts.py
"""

import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(os.path.dirname(HERE), "results")

GREY = "#999999"        # baseline / control
VERMILLION = "#D55E00"  # vulnerable (bad)
GREEN = "#009E73"       # mitigated (good)

LABELS = {
    "baseline": "Baseline\n(no attack)",
    "vulnerable_attack": "Vulnerable\n(attack)",
    "mitigated_attack": "Mitigated\n(attack)",
}
COLORS = {
    "baseline": GREY,
    "vulnerable_attack": VERMILLION,
    "mitigated_attack": GREEN,
}
ORDER = ["baseline", "vulnerable_attack", "mitigated_attack"]


def load_metrics():
    path = os.path.join(RESULTS, "metrics.csv")
    rows = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows[r["scenario"]] = r
    return [rows[s] for s in ORDER if s in rows]


def _style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, color="#dddddd", linewidth=0.8)
    ax.set_axisbelow(True)


def bar_chart(rows, value_key, title, ylabel, fmt, out_name, ymax=None, integer=False):
    scen = [r["scenario"] for r in rows]
    vals = [float(r[value_key]) for r in rows]
    colors = [COLORS[s] for s in scen]
    labels = [LABELS[s] for s in scen]

    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=150)
    bars = ax.bar(labels, vals, color=colors, width=0.6)
    _style(ax)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=12)
    ax.set_ylabel(ylabel, fontsize=11)
    if ymax is not None:
        ax.set_ylim(0, ymax)
    if integer:
        from matplotlib.ticker import MaxNLocator
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_ylim(0, max(1, max(vals)) * 1.25)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, fmt.format(v),
                ha="center", va="bottom", fontsize=11, fontweight="bold")
    fig.tight_layout()
    out = os.path.join(RESULTS, out_name)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


def main():
    rows = load_metrics()
    bar_chart(rows, "availability_pct",
              "/work availability during the attack",
              "Availability (%)", "{:.1f}%", "fig_availability.png", ymax=105)
    bar_chart(rows, "restart_count",
              "Web restart count during the attack window",
              "Restarts", "{:.0f}", "fig_restarts.png", integer=True)


if __name__ == "__main__":
    main()
