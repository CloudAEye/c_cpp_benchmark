# C/C++ Code-Review Leaderboard

**Dataset:** 16 real merged PRs (7 C / 9 C++), 20 human-verified golden findings
**Judge (default):** `anthropic_claude-opus-4-5-20251101` — also scored by
`anthropic_claude-sonnet-4-5-20250929` and `openai_gpt-5.2`
**Last updated:** 2026-07-02

Every reviewer is scored by the same scrape-and-judge pipeline on the same forks.
Reproduce the scores from `results/` with `python pipeline/compute_metrics.py --judge anthropic_claude-opus-4-5-20251101`
(no API key needed to read the existing scores); add `--judge <name>` to view a
different judge.

**CloudAEye ranks #1 under all three judge models** (the bot order shuffles slightly
between judges; CloudAEye's lead does not).

| Rank | Reviewer | TP | FP | FN | Precision | Recall | F1 |
|-----:|----------|---:|---:|---:|----------:|-------:|---:|
| 1 | **CloudAEye** | 14 | 6 | 6 | **70.0%** | **70.0%** | **70.0** |
| 2 | Cursor Bugbot | 7 | 7 | 13 | 50.0% | 35.0% | 41.2 |
| 3 | Qodo | 10 | 25 | 10 | 28.6% | 50.0% | 36.4 |
| 4 | Greptile | 10 | 26 | 10 | 27.8% | 50.0% | 35.7 |
| 5 | Gemini Code Assist | 10 | 31 | 10 | 24.4% | 50.0% | 32.8 |
| 6 | GitHub Copilot | 10 | 38 | 10 | 20.8% | 50.0% | 29.4 |
| 7 | Claude (GitHub App) | 13 | 62 | 7 | 17.3% | 65.0% | 27.4 |
| 8 | OpenAI Codex | 5 | 12 | 15 | 29.4% | 25.0% | 27.0 |
| 9 | CodeRabbit | 5 | 13 | 15 | 27.8% | 25.0% | 26.3 |

- **TP** — golden findings the reviewer correctly raised
- **FP** — issues the reviewer raised that don't correspond to a golden
- **FN** — golden findings the reviewer missed
- **F1** — harmonic mean of precision and recall (the headline ranking metric)

## How the scores are measured

Every reviewer reviews the **same 16 forked PRs**, pinned to the exact commit the
golden findings were verified against. Their comments are scraped, each comment is
broken into atomic candidate issues, near-duplicates are merged, and an LLM judge
matches every candidate against the golden findings for that PR to label it TP / FP,
and counts unmatched goldens as FN. See [`README.md`](README.md) for the full
methodology and for how to add your own reviewer.

## Submitting a new reviewer

Run your reviewer over the 16 PRs and open a PR adding your scored column — see the
**"Add your own reviewer"** section of [`README.md`](README.md). Submissions must use
the same judge model so scores are comparable.
