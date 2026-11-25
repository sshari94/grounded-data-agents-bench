"""Summarise results/runs.jsonl into tables and a chart."""
import argparse, json, os, collections
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
CONDS = ["schema", "tables", "lineage"]


def pct(n, d):
    return f"{100 * n / d:.1f}" if d else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=os.path.join(ROOT, "results", "runs.jsonl"))
    ap.add_argument("--outdir", default=os.path.join(ROOT, "results"))
    a = ap.parse_args()
    R = [json.loads(l) for l in open(a.runs)]
    systems = sorted({(r["provider"], r["model"]) for r in R})
    lines = ["# Results", "",
             "Accuracy = share of questions answered correctly (for the 6 unanswerable questions, correct means the agent asked to clarify).",
             "Silent wrong = the agent returned an answer and it was wrong. Clarified = the agent asked instead of answering an answerable question.",
             "Numbers are means over runs; each cell is a percent of questions.", "",
             "## Overall", "", "| System | Condition | Accuracy | Silent wrong | Clarified | Error | N |", "|---|---|---|---|---|---|---|"]
    summary = {}
    for s in systems:
        for c in CONDS:
            rs = [r for r in R if (r["provider"], r["model"]) == s and r["condition"] == c]
            if not rs:
                continue
            k = collections.Counter(r["outcome"] for r in rs); n = len(rs)
            summary[(s, c)] = 100 * k["correct"] / n
            lines.append(f"| {s[0]} {s[1]} | {c} | {pct(k['correct'], n)} | {pct(k['silent_wrong'], n)} | {pct(k['clarified'], n)} | {pct(k['error'], n)} | {n} |")
    cats = sorted({r["cat"] for r in R})
    lines += ["", "## Accuracy by question category", "", "| System | Condition | " + " | ".join(cats) + " |", "|---|---|" + "---|" * len(cats)]
    for s in systems:
        for c in CONDS:
            rs = [r for r in R if (r["provider"], r["model"]) == s and r["condition"] == c]
            if not rs:
                continue
            cells = []
            for cat in cats:
                x = [r for r in rs if r["cat"] == cat]
                cells.append(pct(sum(r["outcome"] == "correct" for r in x), len(x)))
            lines.append(f"| {s[0]} {s[1]} | {c} | " + " | ".join(cells) + " |")
    lines += ["", "## Silent-wrong answers by error type (Table I category)", "", "| System | Condition | Error type | Count |", "|---|---|---|---|"]
    for s in systems:
        for c in CONDS:
            k = collections.Counter(r["error_type"] for r in R if (r["provider"], r["model"]) == s and r["condition"] == c and r["outcome"] == "silent_wrong")
            for et, n in k.most_common():
                lines.append(f"| {s[0]} {s[1]} | {c} | {et} | {n} |")
    os.makedirs(a.outdir, exist_ok=True)
    open(os.path.join(a.outdir, "summary.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(6.5, 3.6))
        w = 0.8 / max(1, len(systems))
        for i, s in enumerate(systems):
            ys = [summary.get((s, c), 0) for c in CONDS]
            ax.bar([j + i * w for j in range(3)], ys, w, label=(s[1] if s[1] != "-" else s[0]).replace("claude-", "Claude ").replace("-5-5", " 5.5").replace("opus", "Opus").replace("haiku", "Haiku"))
        ax.set_xticks([j + w * (len(systems) - 1) / 2 for j in range(3)])
        ax.set_xticklabels(["Schema only", "+ Table metadata", "+ Lineage"])
        ax.set_ylabel("Execution accuracy (%)"); ax.set_ylim(0, 100)
        ax.spines[["top", "right"]].set_visible(False); ax.legend(frameon=False, fontsize=8, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=len(systems))
        fig.tight_layout(); fig.savefig(os.path.join(a.outdir, "accuracy_by_condition.png"), dpi=200)
    except ImportError:
        pass


if __name__ == "__main__":
    main()
