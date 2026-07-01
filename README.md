# C/C++ Code-Review Benchmark

A reproducible benchmark for **AI code-review tools on C and C++**, built from real
merged pull requests with human-verified bug findings. It measures how well a
reviewer catches genuine issues (recall) without drowning them in noise (precision),
and produces a single F1 leaderboard.

➡️ **[Current leaderboard](LEADERBOARD.md)** · **[Full benchmark report](https://www.cloudaeye.com/products/code-review/benchmark-2026/index-cpp.html)**

Everything needed to reproduce the leaderboard and to score a new reviewer is in
this folder. The raw reviews each bot posted can be read on the live forks — see
[Browse the bot reviews](#browse-the-bot-reviews).

> **Inspired by [withmartian/code-review-benchmark](https://github.com/withmartian/code-review-benchmark)** —
> we adopted its scrape → atomic-candidate → LLM-as-judge methodology and per-judge
> results layout, then built a benchmark dedicated to **C and C++** with
> human-verified goldens, commit-pinned forks, and a multi-judge leaderboard.

---

## The dataset

- **16 pull requests** — 7 C, 9 C++ — from widely-used open-source projects:
  nlohmann/json, dragonflydb/dragonfly (×2), fastfetch, carla (×2), libuv (×2),
  godotengine/godot, micropython, nginx, microsoft/terminal, opencv, tesseract,
  php-src, valkey.
- **20 golden findings** — concrete, localized bugs/issues that were confirmed real
  (most were fixed in human review on the original PR). Each golden is objective,
  points at a specific file/line, and is phrased as *what* is wrong and *where*.
- **Commit-pinned.** Every PR records the exact `base_sha` and `head_sha` the goldens
  were verified against, so the review surface is identical for every reviewer and
  doesn't drift as upstream moves.

`benchmark_final16.json` is the source of truth: the 16 PRs, their pinned SHAs, and
the full golden set with categories, severities, paths, and evidence.

## Why C/C++ — and how these repos were chosen

Most public code-review benchmarks are dominated by web and application languages
(JavaScript/TypeScript, Python), where the common defects are logic, API-misuse, and
framework issues. **C and C++ have a different, higher-stakes bug surface** that those
suites barely exercise: manual memory management (use-after-free, leaks, double-free),
undefined behavior, pointer/lifetime/aliasing mistakes, integer overflow and signedness,
buffer and bounds errors, data races and lock discipline, and RAII/ownership violations.
A reviewer that looks strong on web code can miss exactly these — so measuring C/C++
review quality needs its own benchmark.

**Repo selection.** We picked from widely-used, actively-maintained open-source C and
C++ projects with a **strong human code-review culture**, because that culture is what
makes a golden trustworthy: the bug was caught and fixed by a human reviewer on the
original PR, not asserted by us. Concretely:

1. **Candidate pool** — popular, well-reviewed C/C++ repositories, ranked by reach and
   spread so the set isn't one ecosystem. The final 16 span databases / KV stores
   (dragonfly, valkey), systems & runtimes (libuv, micropython, nginx, php-src),
   foundational libraries (nlohmann/json, opencv, tesseract), and apps / engines
   (godot, carla, fastfetch, microsoft/terminal) — balanced **7 C / 9 C++**.
2. **PR mining** — within each repo we looked for merged PRs where a **real defect was
   raised and fixed during human review** (a "resolved-in-review" signal), so each
   golden traces back to a confirmed, localized bug rather than a style nit.
3. **Golden vetting** — every candidate golden had to be *objective*, *localizable to a
   specific file/line*, *discoverable from the diff + surrounding context*,
   *confirmed real*, *correctly categorized*, and *cleanly phrased* (what is wrong and
   where, with no fix leakage). Goldens that didn't survive this bar were dropped.
4. **Commit pinning + fork verification** — each surviving PR is pinned to the exact
   `base_sha..head_sha` the golden was verified against. We re-checked every fork at its
   pinned head and removed goldens whose fix was already present there, so a reviewer is
   only ever credited for finding a bug that is actually live in the reviewed code.

The result is 16 PRs / 20 goldens that are small enough to review fairly, varied enough
to be representative, and pinned so every reviewer sees an identical surface.

## Browse the bot reviews

Every bot reviewed the **same neutral fork** of each PR (renamed so the bot isn't
biased by the upstream project). Open any fork PR below to read the exact comments
each tool posted — that's the raw material behind the scores in `evaluations.json`.

| Upstream project | Lang | Original PR | Bot reviews (fork) |
|------------------|:----:|-------------|--------------------|
| nlohmann/json | C++ | [json#5163](https://github.com/nlohmann/json/pull/5163) | [view](https://github.com/headerslow/json-pr5163-7b94/pull/1) |
| dragonflydb/dragonfly | C++ | [dragonfly#6011](https://github.com/dragonflydb/dragonfly/pull/6011) | [view](https://github.com/headerslow/dragonfly-pr6011-e03b/pull/1) |
| fastfetch-cli/fastfetch | C | [fastfetch#2137](https://github.com/fastfetch-cli/fastfetch/pull/2137) | [view](https://github.com/headerslow/fastfetch-pr2137-b206/pull/1) |
| carla-simulator/carla | C++ | [carla#9652](https://github.com/carla-simulator/carla/pull/9652) | [view](https://github.com/headerslow/carla-pr9652-b52c/pull/1) |
| carla-simulator/carla | C++ | [carla#9653](https://github.com/carla-simulator/carla/pull/9653) | [view](https://github.com/headerslow/carla-pr9653-56f5/pull/1) |
| libuv/libuv | C | [libuv#4936](https://github.com/libuv/libuv/pull/4936) | [view](https://github.com/headerslow/libuv-pr4936-28e0/pull/1) |
| godotengine/godot | C++ | [godot#119999](https://github.com/godotengine/godot/pull/119999) | [view](https://github.com/headerslow/godot-pr119999-0a2c/pull/1) |
| libuv/libuv | C | [libuv#5013](https://github.com/libuv/libuv/pull/5013) | [view](https://github.com/headerslow/libuv-pr5013-1d8c/pull/1) |
| micropython/micropython | C | [micropython#19080](https://github.com/micropython/micropython/pull/19080) | [view](https://github.com/headerslow/micropython-pr19080-91b0/pull/1) |
| nginx/nginx | C | [nginx#1361](https://github.com/nginx/nginx/pull/1361) | [view](https://github.com/headerslow/nginx-pr1361-0266/pull/1) |
| dragonflydb/dragonfly | C++ | [dragonfly#7545](https://github.com/dragonflydb/dragonfly/pull/7545) | [view](https://github.com/headerslow/dragonfly-pr7545-a5e7/pull/1) |
| microsoft/terminal | C++ | [terminal#18953](https://github.com/microsoft/terminal/pull/18953) | [view](https://github.com/headerslow/terminal-pr18953-4b93/pull/1) |
| opencv/opencv | C++ | [opencv#29240](https://github.com/opencv/opencv/pull/29240) | [view](https://github.com/headerslow/opencv-pr29240-5c5a/pull/1) |
| tesseract-ocr/tesseract | C++ | [tesseract#4138](https://github.com/tesseract-ocr/tesseract/pull/4138) | [view](https://github.com/headerslow/tesseract-pr4138-434f/pull/1) |
| php/php-src | C | [php-src#22075](https://github.com/php/php-src/pull/22075) | [view](https://github.com/headerslow/php-src-pr22075-ccc1/pull/1) |
| valkey-io/valkey | C | [valkey#3836](https://github.com/valkey-io/valkey/pull/3836) | [view](https://github.com/headerslow/valkey-pr3836-8702/pull/1) |

## How scoring works

```
 fork the 16 PRs            run your reviewer        scrape its comments
 (step0, commit-pinned) ─▶  on those forks      ─▶   (step1)
                                                       │
                                                       ▼
   leaderboard      ◀──  LLM judge vs goldens  ◀──  split into atomic
 (compute_metrics)        (step3)                    candidates + dedup
                                                     (step2, step2_5)
```

1. **Atomic candidates.** Each scraped review comment is split into individual
   concrete claims (one comment can raise several issues).
2. **Dedup.** Near-duplicate candidates within a PR are merged so a reviewer isn't
   rewarded or penalized for repeating itself.
3. **LLM-as-judge.** For each PR, the judge matches every candidate against that PR's
   goldens. A matched candidate is a **true positive**, an unmatched candidate is a
   **false positive**, and a golden no candidate matched is a **false negative**.
4. **Aggregate.** Precision = TP/(TP+FP), Recall = TP/(TP+FN), F1 = their harmonic
   mean, summed across all 16 PRs.

All reviewers are scored by the **same judge** so the comparison is fair. The
benchmark ships results from **three judge models** — `anthropic_claude-sonnet-4-5-20250929`
(default), `anthropic_claude-opus-4-5-20251101`, and `openai_gpt-5.2` — so you can
confirm the ranking holds regardless of who judges.

---

## Quickstart

### Prerequisites
- Python 3.10+
- `pip install -r requirements.txt`
- `git` and the [`gh`](https://cli.github.com/) CLI (used by the fork/scrape steps)

### A) Just read the current leaderboard (no API key)

The judged results for every reviewer are bundled under `results/`. Regenerate the
table from them:

```bash
python pipeline/compute_metrics.py
```

This reads `results/anthropic_claude-sonnet-4-5-20250929/evaluations.json` and prints
the per-PR breakdown plus the ranked leaderboard. Every tool present in that file is
scored automatically.

The benchmark is scored by **three independent judge models** so you can see the
ranking doesn't depend on any single judge. Switch with `--judge`:

```bash
python pipeline/compute_metrics.py --judge anthropic_claude-opus-4-5-20251101
python pipeline/compute_metrics.py --judge openai_gpt-5.2
```

### B) Add your own reviewer

> Run all commands from this folder (`cpp_benchmark/`). Copy `.env.example` to `.env`
> and fill in `GITHUB_TOKEN` and the `MARTIAN_*` judge settings first.

**1. Fork the 16 PRs into your own GitHub org/account.** This recreates each PR at
its pinned commit so your reviewer sees the exact same code. `--neutral-names` gives
the forks anonymous names so your tool isn't biased by the repo name.

```bash
python pipeline/step0_fork_prs.py \
  --file benchmark_final16.json \
  --org YOUR_GITHUB_ORG \
  --name yourbot \
  --neutral-names \
  --manifest manifests/forks_yourbot.json
```

This writes `manifests/forks_yourbot.json` mapping each original PR to your new fork.

**2. Run your reviewer on those forks.** Install/trigger your AI reviewer on each
fork PR (however your tool is normally invoked) and wait for it to post its review
comments.

**3. Scrape your reviewer's comments.** `--bot-map` tells the scraper which GitHub
comment-author login belongs to your tool (find it by looking at who posted the
review). The result merges into `results/benchmark_data.json` under a new column.

```bash
python pipeline/step1_download_prs.py \
  --manifest manifests/forks_yourbot.json \
  --golden goldens \
  --output results/benchmark_data.json \
  --tool yourbot --force \
  --bot-map "your-bot-login=yourbot"
```

**4. Extract → dedup → judge** (uses the `MARTIAN_*` judge from your `.env`):

```bash
python pipeline/step2_extract_comments.py   --tool yourbot
python pipeline/step2_5_dedup_candidates.py --tool yourbot
python pipeline/step3_judge_comments.py     --tool yourbot --force
```

**5. See your row on the leaderboard:**

```bash
python pipeline/compute_metrics.py
```

To submit, open a pull request adding your tool. Include `manifests/forks_yourbot.json`
and the updated `results/` so your score is reproducible.

---

## What's in here

```
cpp_benchmark/
├── README.md                      # this file
├── LEADERBOARD.md                 # current standings
├── requirements.txt
├── .env.example                   # copy to .env and fill in (never committed)
├── benchmark_final16.json         # the 16 PRs + pinned SHAs + 20 golden findings
├── goldens/
│   └── cpp_goldens.json           # slim golden set consumed by step1 (--golden goldens)
├── manifests/
│   └── forks_reference_headerslow.json   # the maintainer's reference forks (example manifest)
├── pipeline/
│   ├── step0_fork_prs.py          # fork the PRs into your org at the pinned commits
│   ├── step1_download_prs.py      # scrape a reviewer's comments off the forks
│   ├── step2_extract_comments.py  # split comments into atomic candidate issues
│   ├── step2_5_dedup_candidates.py# merge near-duplicate candidates
│   ├── step3_judge_comments.py    # LLM-judge candidates vs goldens -> TP/FP/FN
│   ├── step4_export_by_tool.py    # (optional) export results to .xlsx
│   └── compute_metrics.py         # build the leaderboard from judged evaluations
└── results/                       # one folder per judge model (all score the same forks)
    ├── benchmark_data.json        # raw scraped review comments for every tool, keyed by PR
    ├── anthropic_claude-sonnet-4-5-20250929/
    │   └── evaluations.json       # per-tool TP/FP/FN (default judge — drives the leaderboard)
    ├── anthropic_claude-opus-4-5-20251101/
    │   └── evaluations.json
    └── openai_gpt-5.2/
        └── evaluations.json
```

> `results/benchmark_data.json` (the raw scrape) is committed so the pipeline is
> reproducible and inspectable offline. The per-judge extraction/dedup intermediates
> (`candidates.json`, `dedup_groups.json`) are **not** shipped — regenerate them
> locally by running steps 1–3 below. The raw bot reviews can also be read live on
> the forks linked under [Browse the bot reviews](#browse-the-bot-reviews).

## Notes & caveats

- **Same judge required.** Scores are only comparable within one judge. The bundled
  results cover three judges (`results/<judge>/evaluations.json`); pick one with
  `--judge` and judge your own tool with the matching `MARTIAN_MODEL` so it lands in
  the same folder. The per-judge folder name is the model id with `/` replaced by `_`.
- **Judge non-determinism.** LLM judges are not perfectly deterministic; expect ±1
  finding of run-to-run jitter. Treat very small F1 gaps as ties.
- **No data in the prompt.** A fair score comes from running your reviewer on the
  forked code only. Feeding the goldens (in `benchmark_final16.json`) into your
  reviewer would inflate the number and isn't a valid submission.
- **Secrets.** Scripts read all credentials from the environment / a local `.env`.
  Never commit `.env` or paste tokens into the JSON files.

## License & provenance

This repository is licensed under the [MIT License](LICENSE) (Copyright (c) 2026
CloudAEye).

The golden findings are derived from public pull requests on the upstream projects;
each golden links back to its source. This benchmark is maintained by CloudAEye and
provided for the community to evaluate and compare C/C++ code-review tools.

Methodology and layout are inspired by
[withmartian/code-review-benchmark](https://github.com/withmartian/code-review-benchmark)
(MIT License); this project adapts that approach specifically to C and C++. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the upstream license text.
