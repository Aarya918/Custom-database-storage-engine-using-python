"""matplotlib charts, always saved to PNG with a non-interactive backend."""
import matplotlib

try:
    matplotlib.use("Agg", force=True)
except Exception:  # pragma: no cover
    pass
import matplotlib.pyplot as plt  # noqa: E402

COLORS = {"GET": "#2f7fc1", "PUT": "#e08e1b", "DELETE": "#c0392b"}


def plot_distribution(summary, path, title="Operation distribution"):
    fig, ax = plt.subplots(figsize=(6, 4))
    ops = list(summary["counts"])
    counts = [summary["counts"][o] for o in ops]
    bars = ax.bar(ops, counts, color=[COLORS[o] for o in ops])
    ax.set_ylabel("operations")
    ax.set_title(title)
    if summary["total_ops"]:
        for bar, op in zip(bars, ops):
            ax.annotate(f"{summary['op_pct'][op]}%", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        ha="center", va="bottom", fontsize=9)
    else:
        ax.text(0.5, 0.5, "No operations (N/A)", transform=ax.transAxes, ha="center")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_windows(table, path, title="Operations per window"):
    fig, ax = plt.subplots(figsize=(8, 4))
    if table.empty:
        ax.text(0.5, 0.5, "No operations (N/A)", transform=ax.transAxes, ha="center")
    else:
        bottom = None
        x = range(len(table))
        for op in ("GET", "PUT", "DELETE"):
            ax.bar(x, table[op], bottom=bottom, label=op, color=COLORS[op])
            bottom = table[op] if bottom is None else bottom + table[op]
        step = max(1, len(table) // 10)
        ax.set_xticks(list(x)[::step])
        ax.set_xticklabels(table["window"].iloc[::step], rotation=45, ha="right", fontsize=7)
        ax.legend()
    ax.set_ylabel("operations")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_latency(table, path, bucket_width, title="Read latency vs dataset size"):
    fig, ax = plt.subplots(figsize=(7, 4.2))
    note = None
    if table.empty:
        note = "No read operations in this workload (N/A)"
    else:
        ax.plot(table["bucket_start"], table["p50_us"], marker="o", label="p50", color=COLORS["GET"])
        ax.plot(table["bucket_start"], table["p95_us"], marker="s", label="p95", color=COLORS["DELETE"])
        ax.set_xlabel(f"dataset size (distinct live keys, bucket width {bucket_width})")
        ax.set_ylabel("get() latency (microseconds)")
        ax.legend()
        if len(table) < 2:
            note = "Only one dataset-size bucket: the trend is not meaningful"
    if note:
        ax.text(0.5, 0.5, note, transform=ax.transAxes, ha="center", va="center", fontsize=10,
                bbox=dict(boxstyle="round", fc="white", ec="gray"))
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
