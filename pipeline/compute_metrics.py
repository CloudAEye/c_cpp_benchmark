#!/usr/bin/env python3
"""
Compute the C/C++ code-review leaderboard from judged evaluations.

Reads:
  - benchmark_final16.json                  (the 16 PRs / 20 goldens — source of truth)
  - results/<judge>/evaluations.json        (per-tool TP/FP/FN, written by step3)

Every tool found in evaluations.json is scored automatically, so adding your
own reviewer is just: scrape (step1) -> extract/dedup (step2/2_5) -> judge
(step3) -> run this script. No edits here required.

The judge folder is picked from MARTIAN_MODEL (same value step3 used), defaulting
to the published judge `claude-sonnet-4-5-20250929`. Override with --judge.

TP/FN are matched by golden text against benchmark_final16.json, so goldens that
were dropped during dataset cleaning are ignored even if an old evaluation still
references them — the rich file is always authoritative.

Usage:
  python pipeline/compute_metrics.py
  python pipeline/compute_metrics.py --judge claude-sonnet-4-5-20250929
"""
import argparse
import json
import os
from pathlib import Path

# Run from the repo root regardless of where the script is invoked from.
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)

# Non-tool keys that may appear alongside tools inside a per-PR evaluation dict.
NON_TOOL_KEYS = {"golden_comments", "goldens", "pr_url", "url", "meta"}


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def main():
    ap = argparse.ArgumentParser(description="Compute the C/C++ review leaderboard.")
    default_judge = os.environ.get("MARTIAN_MODEL", "anthropic/claude-sonnet-4-5-20250929").replace("/", "_")
    ap.add_argument("--judge", default=default_judge,
                    help="Judge model dir under results/ (default: %(default)s)")
    ap.add_argument("--benchmark", default="benchmark_final16.json",
                    help="Rich benchmark/goldens file (default: %(default)s)")
    args = ap.parse_args()

    bench = json.load(open(args.benchmark, encoding="utf-8"))
    eval_path = Path("results") / args.judge / "evaluations.json"
    if not eval_path.exists():
        raise SystemExit(f"No evaluations at {eval_path}. Run step3 with this judge first.")
    ev = json.load(open(eval_path, encoding="utf-8"))

    # Authoritative golden set + per-PR golden counts, straight from the rich file.
    valid_goldens = set()
    pr_meta = {}  # pr_url -> (label, lang, num_goldens)
    for pr in bench:
        url = pr["pr_url"]
        texts = [g["comment"] for g in pr["goldens"]]
        valid_goldens.update(texts)
        label = f"{pr['repo'].split('/')[-1]}#{url.split('/')[-1]}"
        pr_meta[url] = (label, pr.get("lang", "?"), len(texts))

    # Discover every tool present across all PRs in the evaluations.
    tools = set()
    for e in ev.values():
        tools.update(k for k in e.keys() if k not in NON_TOOL_KEYS)
    tools = sorted(tools)
    if not tools:
        raise SystemExit("No tools found in evaluations.json.")

    totals = {t: {"tp": 0, "fp": 0, "fn": 0} for t in tools}
    rows = []
    for url, (label, lang, ngold) in pr_meta.items():
        e = ev.get(url, {})
        row = {"pr": label, "lang": lang, "g": ngold}
        for t in tools:
            v = e.get(t, {}) or {}
            tp = sum(1 for x in v.get("true_positives", [])
                     if x.get("golden_comment", "") in valid_goldens)
            fn = sum(1 for x in v.get("false_negatives", [])
                     if x.get("golden_comment", "") in valid_goldens)
            fp = v.get("fp", len(v.get("false_positives", [])))
            row[t] = (tp, fp, fn)
            totals[t]["tp"] += tp
            totals[t]["fp"] += fp
            totals[t]["fn"] += fn
        rows.append(row)

    # ---- per-PR table ----
    hdr = f"{'PR':22} {'L':3} {'g':>2} | " + " | ".join(f"{t:^14}" for t in tools)
    print(hdr)
    print("-" * len(hdr))
    print(f"{'':22} {'':3} {'':>2} | " + " | ".join(f"{'TP/FP/FN':^14}" for _ in tools))
    print("-" * len(hdr))
    for r in rows:
        cells = " | ".join(f"{r[t][0]:>3}/{r[t][1]:>3}/{r[t][2]:>3}   " for t in tools)
        print(f"{r['pr']:22} {r['lang']:3} {r['g']:>2} | {cells}")

    # ---- aggregate leaderboard, ranked by F1 ----
    total_gold = sum(m[2] for m in pr_meta.values())
    print(f"\n=== LEADERBOARD (judge={args.judge}, {len(pr_meta)} PRs, {total_gold} goldens) ===\n")
    print(f"{'rank':>4}  {'tool':16} {'TP':>3} {'FP':>3} {'FN':>3}   {'Prec':>6} {'Recall':>7} {'F1':>6}")
    ranked = sorted(tools, key=lambda t: prf(totals[t]["tp"], totals[t]["fp"], totals[t]["fn"])[2],
                    reverse=True)
    for i, t in enumerate(ranked, 1):
        tp, fp, fn = totals[t]["tp"], totals[t]["fp"], totals[t]["fn"]
        p, r, f = prf(tp, fp, fn)
        print(f"{i:>4}  {t:16} {tp:>3} {fp:>3} {fn:>3}   {p*100:>5.1f}% {r*100:>6.1f}% {f*100:>5.1f}%")


if __name__ == "__main__":
    main()
