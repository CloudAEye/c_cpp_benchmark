#!/usr/bin/env python3
"""Aggregate PR review comments from benchmark repos with golden comments."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from tqdm import tqdm

# GitHub API allows ~30 concurrent requests, stay conservative
MAX_WORKERS = 15


def load_dotenv(filepath: str = ".env") -> None:
    """Load environment variables from .env file."""
    env_path = Path(filepath)
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                os.environ.setdefault(key, value)


def gh(args: list[str]) -> dict | list:
    """Run gh CLI command and return parsed JSON."""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        # gh emits UTF-8; without this Windows decodes as cp1252 and the reader
        # thread dies on multi-byte sequences in review bodies.
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        if "gh auth login" in result.stderr or "GH_TOKEN" in result.stderr:
            print("Error: GitHub CLI not authenticated.", file=sys.stderr)
            print("Run 'gh auth login' or set GH_TOKEN environment variable.", file=sys.stderr)
            sys.exit(1)
        raise subprocess.CalledProcessError(result.returncode, ["gh", *args], result.stdout, result.stderr)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def load_golden_comments(folder: str) -> dict[str, dict]:
    """Load all golden comment files into lookup dict keyed by URL."""
    golden = {}
    folder_path = Path(folder)
    for json_file in folder_path.glob("*.json"):
        with open(json_file) as f:
            entries = json.load(f)
        for entry in entries:
            url = entry["url"]
            golden[url] = {
                "pr_title": entry.get("pr_title"),
                "original_url": entry.get("original_url"),
                "az_comment": entry.get("az_comment"),
                "comments": entry.get("comments", []),
                "source_file": json_file.name,
            }
    return golden


def parse_repo_name(name: str) -> dict | None:
    """Parse benchmark repo name to extract components.

    Pattern: {config_prefix}__{original_repo}__{tool}__PR{number}__{date}
    Example: sentry__sentry-greptile__claude__PR1__20260127
    """
    pattern = r"^(.+?)__(.+?)__(.+?)__PR(\d+)__(\d+)$"
    match = re.match(pattern, name)
    if not match:
        return None
    return {
        "config_prefix": match.group(1),
        "original_repo": match.group(2),
        "tool": match.group(3),
        "pr_number": int(match.group(4)),
        "date": match.group(5),
    }


def find_golden_url(golden: dict[str, dict], original_repo: str, pr_number: int) -> str | None:
    """Find golden comment URL matching repo and PR number."""
    for url in golden:
        if f"/{original_repo}/pull/{pr_number}" in url:
            return url
    return None


def fetch_review_comments(org: str, repo: str, pr: int) -> list[dict]:
    """Fetch all review comments from a PR."""
    comments = []

    # Fetch PR review comments (inline code comments)
    try:
        review_comments = gh(["api", f"/repos/{org}/{repo}/pulls/{pr}/comments"])
        for c in review_comments:
            comments.append({
                "path": c.get("path"),
                "line": c.get("line") or c.get("original_line"),
                "body": c.get("body"),
                "created_at": c.get("created_at"),
                "author": (c.get("user") or {}).get("login"),
            })
    except subprocess.CalledProcessError:
        pass

    # Fetch PR review bodies (top-level review comments)
    try:
        reviews = gh(["api", f"/repos/{org}/{repo}/pulls/{pr}/reviews"])
        for r in reviews:
            if r.get("body"):
                comments.append({
                    "path": None,
                    "line": None,
                    "body": r.get("body"),
                    "created_at": r.get("submitted_at"),
                    "author": (r.get("user") or {}).get("login"),
                })
    except subprocess.CalledProcessError:
        pass

    # Fetch issue comments (general PR comments)
    try:
        issue_comments = gh(["api", f"/repos/{org}/{repo}/issues/{pr}/comments"])
        for c in issue_comments:
            comments.append({
                "path": None,
                "line": None,
                "body": c.get("body"),
                "created_at": c.get("created_at"),
                "author": (c.get("user") or {}).get("login"),
            })
    except subprocess.CalledProcessError:
        pass

    return comments


def fetch_pr_metadata(org: str, repo: str, pr: int) -> dict:
    """Fetch PR title and URL."""
    try:
        pr_data = gh(["api", f"/repos/{org}/{repo}/pulls/{pr}"])
        return {
            "title": pr_data.get("title"),
            "url": pr_data.get("html_url"),
        }
    except subprocess.CalledProcessError:
        return {"title": None, "url": None}


def fetch_repo_data(org: str, repo_name: str, pr: int = 1) -> dict:
    """Fetch both PR metadata and comments for a repo. Returns combined result."""
    pr_meta = fetch_pr_metadata(org, repo_name, pr)
    comments = fetch_review_comments(org, repo_name, pr)
    return {
        "repo_name": repo_name,
        "pr_meta": pr_meta,
        "comments": comments,
    }


# Native-app bots that review the SAME neutral fork are told apart by the
# login that posted each comment, not by the repo name.
DEFAULT_BOT_MAP = "coderabbitai[bot]=coderabbit,gemini-code-assist[bot]=gemini"


def parse_bot_map(spec: str) -> dict[str, str]:
    """Parse "login=tool,login=tool" into a {login: tool} dict."""
    bot_map = {}
    for pair in spec.split(","):
        pair = pair.strip()
        if not pair:
            continue
        login, _, tool = pair.partition("=")
        if not tool:
            raise ValueError(f"Bad --bot-map entry (need login=tool): {pair!r}")
        bot_map[login.strip()] = tool.strip()
    return bot_map


def run_manifest_mode(args) -> None:
    """Scrape reviews from neutral-named forks listed in a step0 manifest.

    The manifest (forks.json) maps each fork back to its original PR, so we
    don't need the parseable repo-name convention. Several bots review the
    same fork; their comments are split into per-tool review entries by the
    posting login (--bot-map). Comments from logins outside the map are
    dropped (with a warning for unexpected [bot] accounts), so the fork
    owner's own trigger comments never pollute the candidates.
    """
    bot_map = parse_bot_map(args.bot_map)
    print(f"Bot map: {bot_map}")

    with open(args.manifest, encoding="utf-8") as f:
        forks = json.load(f)
    print(f"Loaded {len(forks)} fork records from {args.manifest}")

    output_path = Path(args.output)
    if output_path.exists():
        with open(output_path) as f:
            output = json.load(f)
        print(f"Loaded {len(output)} existing entries from {args.output}")
    else:
        output = {}

    golden = load_golden_comments(args.golden)
    print(f"Loaded {len(golden)} golden comment entries")

    wanted_tools = set(bot_map.values())
    if args.tool:
        wanted_tools &= {args.tool}

    # Build worklist: forks whose golden entry is missing >=1 wanted tool.
    to_process = []  # (fork, golden_url, missing_tools)
    errors = []
    skipped = 0
    for fork in forks:
        golden_url = fork.get("original_pr_url")
        if golden_url not in golden:
            errors.append(f"No golden match for {fork.get('new_repo')} ({golden_url})")
            continue

        existing_tools = {
            r["tool"] for r in output.get(golden_url, {}).get("reviews", [])
        }
        missing = wanted_tools if args.force else wanted_tools - existing_tools
        if not missing:
            skipped += 1
            continue
        to_process.append((fork, golden_url, missing))

    print(f"To process: {len(to_process)}, skipped: {skipped}")
    if not to_process:
        print("Nothing to do.")
        for err in errors:
            print(f"  - {err}")
        return

    unmapped_bots: dict[str, int] = {}

    def fetch_fork(fork: dict) -> dict:
        org, repo_name = fork["new_repo"].split("/", 1)
        m = re.search(r"/pull/(\d+)", fork.get("new_pr_url") or "")
        pr_number = int(m.group(1)) if m else 1
        return fetch_repo_data(org, repo_name, pr_number)

    processed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_info = {
            executor.submit(fetch_fork, fork): (fork, golden_url, missing)
            for fork, golden_url, missing in to_process
        }
        with tqdm(total=len(to_process), desc="Fetching reviews") as pbar:
            for future in as_completed(future_to_info):
                fork, golden_url, missing = future_to_info[future]
                try:
                    result = future.result()
                except Exception as e:
                    errors.append(f"Error fetching {fork['new_repo']}: {e}")
                    pbar.update(1)
                    continue

                # Split comments by posting login.
                buckets: dict[str, list] = {tool: [] for tool in missing}
                for c in result["comments"]:
                    author = c.get("author") or ""
                    tool = bot_map.get(author)
                    if tool is None:
                        if author.endswith("[bot]"):
                            unmapped_bots[author] = unmapped_bots.get(author, 0) + 1
                        continue
                    if tool in buckets:
                        buckets[tool].append(c)

                if golden_url not in output:
                    golden_data = golden[golden_url]
                    m = re.search(r"github\.com/[^/]+/([^/]+)/pull/", golden_url)
                    output[golden_url] = {
                        "pr_title": golden_data["pr_title"],
                        "original_url": golden_data["original_url"] or golden_url,
                        "source_repo": m.group(1) if m else None,
                        "golden_comments": golden_data["comments"],
                        "golden_source_file": golden_data["source_file"],
                        "az_comment": golden_data["az_comment"],
                        "reviews": [],
                    }

                output[golden_url]["reviews"] = [
                    r for r in output[golden_url]["reviews"] if r["tool"] not in buckets
                ]
                for tool, tool_comments in buckets.items():
                    # An empty bucket still gets an entry: the bot reviewed and
                    # found nothing (or hasn't run yet — re-scrape with --force).
                    output[golden_url]["reviews"].append({
                        "tool": tool,
                        "repo_name": result["repo_name"],
                        "pr_url": result["pr_meta"]["url"],
                        "review_comments": tool_comments,
                    })

                processed += 1
                pbar.update(1)
                if processed % 50 == 0:
                    with open(output_path, "w") as f:
                        json.dump(output, f, indent=2)

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print("\nSummary:")
    print(f"  Processed: {processed}")
    print(f"  Skipped (already loaded): {skipped}")
    print(f"  Errors: {len(errors)}")
    for err in errors[:10]:
        print(f"    - {err}")
    if unmapped_bots:
        print("  Unmapped [bot] authors seen (add to --bot-map if expected):")
        for login, n in sorted(unmapped_bots.items()):
            print(f"    - {login}: {n} comment(s)")
    # Empty-review visibility: a bot that posted nothing on many forks usually
    # means it wasn't installed / hit a quota, not that the code was clean.
    empty_by_tool: dict[str, int] = {}
    for entry in output.values():
        for r in entry.get("reviews", []):
            if r["tool"] in wanted_tools and not r["review_comments"]:
                empty_by_tool[r["tool"]] = empty_by_tool.get(r["tool"], 0) + 1
    for tool, n in sorted(empty_by_tool.items()):
        print(f"  NOTE: {tool} has {n} PR(s) with zero comments")


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Aggregate benchmark PR comments with golden comments")
    parser.add_argument("--org", default="code-review-benchmark", help="GitHub organization")
    parser.add_argument("--output", default="benchmark_data.json", help="Output JSON file")
    parser.add_argument("--golden", default="golden_comments", help="Golden comments folder")
    parser.add_argument("--test", action="store_true", help="Test mode: process 1 repo per tool")
    parser.add_argument("--tool", help="Only process specific tool")
    parser.add_argument("--force", action="store_true", help="Force refetch (all tools, or specific with --tool)")
    parser.add_argument("--manifest", help="step0 forks.json manifest — scrape these forks "
                        "instead of listing org repos (use for neutral-named forks)")
    parser.add_argument("--bot-map", default=DEFAULT_BOT_MAP,
                        help="login=tool pairs for splitting one fork's comments into "
                        f"per-tool reviews (manifest mode only). Default: {DEFAULT_BOT_MAP}")
    args = parser.parse_args()

    if args.manifest:
        run_manifest_mode(args)
        return

    # Load existing output for incremental processing
    output_path = Path(args.output)
    if output_path.exists():
        with open(output_path) as f:
            output = json.load(f)
        print(f"Loaded {len(output)} existing entries from {args.output}")
    else:
        output = {}

    # Load golden comments
    golden = load_golden_comments(args.golden)
    print(f"Loaded {len(golden)} golden comment entries")

    # List all repos in org
    print(f"Fetching repos from {args.org}...")
    repos = gh(["repo", "list", args.org, "--limit", "5000", "--json", "name"])
    print(f"Found {len(repos)} repos")

    # Build list of repos to process
    tools_seen = set()
    to_process = []  # (repo_name, parsed, golden_url)
    skipped = 0
    errors = []

    for repo_entry in repos:
        repo_name = repo_entry["name"]
        parsed = parse_repo_name(repo_name)

        if not parsed:
            continue

        tool = parsed["tool"]

        if args.tool and tool != args.tool:
            continue

        if args.test and tool in tools_seen:
            continue

        golden_url = find_golden_url(golden, parsed["original_repo"], parsed["pr_number"])
        if not golden_url:
            errors.append(f"No golden match for {repo_name}")
            continue

        # Check if already processed (incremental)
        if golden_url in output:
            existing_reviews = {r["tool"]: r for r in output[golden_url].get("reviews", [])}
            if tool in existing_reviews:
                if args.force:
                    output[golden_url]["reviews"] = [
                        r for r in output[golden_url]["reviews"] if r["tool"] != tool
                    ]
                else:
                    skipped += 1
                    continue

        to_process.append((repo_name, parsed, golden_url))
        tools_seen.add(tool)

        if args.test and len(tools_seen) >= 3:
            break

    print(f"To process: {len(to_process)}, skipped: {skipped}")

    if not to_process:
        print("Nothing to do.")
        return

    # Fetch all repos concurrently
    processed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_info = {
            executor.submit(fetch_repo_data, args.org, repo_name): (repo_name, parsed, golden_url)
            for repo_name, parsed, golden_url in to_process
        }

        with tqdm(total=len(to_process), desc="Fetching reviews") as pbar:
            for future in as_completed(future_to_info):
                repo_name, parsed, golden_url = future_to_info[future]
                tool = parsed["tool"]

                try:
                    result = future.result()
                except Exception as e:
                    errors.append(f"Error fetching {repo_name}: {e}")
                    pbar.update(1)
                    continue

                # Create or update entry
                if golden_url not in output:
                    golden_data = golden[golden_url]
                    output[golden_url] = {
                        "pr_title": golden_data["pr_title"],
                        "original_url": golden_data["original_url"],
                        "source_repo": parsed["original_repo"],
                        "golden_comments": golden_data["comments"],
                        "golden_source_file": golden_data["source_file"],
                        "az_comment": golden_data["az_comment"],
                        "reviews": [],
                    }

                output[golden_url]["reviews"].append({
                    "tool": tool,
                    "repo_name": repo_name,
                    "pr_url": result["pr_meta"]["url"],
                    "review_comments": result["comments"],
                })

                processed += 1
                pbar.update(1)

                # Save periodically (every 50)
                if processed % 50 == 0:
                    with open(output_path, "w") as f:
                        json.dump(output, f, indent=2)

    # Strip any model-specific data (candidates) before saving raw PR data
    for entry in output.values():
        for review in entry.get("reviews", []):
            review.pop("candidates", None)

    # Final save
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    # Summary
    print("\nSummary:")
    print(f"  Processed: {processed}")
    print(f"  Skipped (already loaded): {skipped}")
    print(f"  Errors: {len(errors)}")
    for err in errors[:10]:
        print(f"    - {err}")
    if len(errors) > 10:
        print(f"    ... and {len(errors) - 10} more")


if __name__ == "__main__":
    main()
