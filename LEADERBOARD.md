# C/C++ Code-Review Leaderboard

**Dataset:** 16 real merged PRs (7 C / 9 C++), 20 human-verified golden findings
**Judge:** `claude-sonnet-4-5-20250929` (LLM-as-judge, identical for every reviewer)
**Last updated:** 2026-06-24

Every reviewer is scored by the same scrape-and-judge pipeline on the same forks.
Reproduce the scores from `results/` with `python pipeline/compute_metrics.py`
(no API key needed to read the existing scores).

| Rank | Reviewer | TP | FP | FN | Precision | Recall | F1 |
|-----:|----------|---:|---:|---:|----------:|-------:|---:|
| 1 | **CloudAEye** | 14 | 5 | 6 | **73.7%** | **70.0%** | **71.8** |
| 2 | Qodo | 11 | 21 | 9 | 34.4% | 55.0% | 42.3 |
| 3 | Cursor Bugbot | 7 | 7 | 13 | 50.0% | 35.0% | 41.2 |
| 4 | Greptile | 11 | 30 | 9 | 26.8% | 55.0% | 36.1 |
| 5 | Gemini Code Assist | 10 | 32 | 10 | 23.8% | 50.0% | 32.3 |
| 6 | GitHub Copilot | 10 | 40 | 10 | 20.0% | 50.0% | 28.6 |
| 7 | Claude (GitHub App) | 12 | 70 | 8 | 14.6% | 60.0% | 23.5 |
| 8 | CodeRabbit | 5 | 19 | 15 | 20.8% | 25.0% | 22.7 |

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
