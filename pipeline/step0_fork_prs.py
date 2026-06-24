#!/usr/bin/env python3
"""
GitHub PR Forker.

This tool clones a repository and recreates a pull request (PR) in your
organization for AI code review. You can either process a single PR URL
or provide a JSON file containing multiple PR entries (as produced by
`golden_comments/*.json`) and the script will process each PR in a simple
loop with a text progress indicator.

Usage:
    # Single PR
    python pr_forker.py <PR_URL> --org <ORG_NAME> --name <AI_TOOL_NAME>

    # Batch from file (array of objects with `url` keys)
    python pr_forker.py --file golden_comments/cal_dot_com.json --org <ORG> --name <AI_TOOL>

Example:
    python pr_forker.py https://github.com/owner/repo/pull/123 --org my-org --name coderabbit
"""

import argparse
from datetime import datetime
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time

import requests


# Workflow injected into Claude forks so the Claude GitHub App reviews the PR.
# Claude reviews run via GitHub Actions (unlike Copilot/Codex which are native /
# cloud bots), so for `--name claude` we keep Actions enabled and drop this file
# into both the base and PR trees. Requires an org/repo Actions secret named
# ANTHROPIC_API_KEY and the Claude GitHub App installed on the org.
# Source: anthropics/claude-code-action docs/solutions.md (Automatic PR Review).
CLAUDE_REVIEW_WORKFLOW = """name: Claude Auto Review
on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      id-token: write
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 1

      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          prompt: |
            REPO: ${{ github.repository }}
            PR NUMBER: ${{ github.event.pull_request.number }}

            Please review this pull request with a focus on:
            - Code quality and best practices
            - Potential bugs or issues
            - Security implications
            - Performance considerations

            Note: The PR branch is already checked out in the current working directory.

            Use `gh pr comment` for top-level feedback.
            Use `mcp__github_inline_comment__create_inline_comment` (with `confirmed: true`) to highlight specific code issues.
            Only post GitHub comments - don't submit review text as messages.

          claude_args: |
            --allowedTools "mcp__github_inline_comment__create_inline_comment,Bash(gh pr comment:*),Bash(gh pr diff:*),Bash(gh pr view:*)"
"""


class GitHubPRForker:
    def __init__(self, token: str, org: str):
        self.token = token
        self.org = org
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        self._verify_auth()

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{endpoint}"
        return requests.request(method, url, headers=self.headers, **kwargs)

    def _verify_auth(self):
        response = self._request("GET", "/user")
        if response.status_code != 200:
            raise Exception(f"Auth failed: {response.json().get('message')}")
        # Remember the authenticated login so we can tell whether `org` is really
        # a user account (create via /user/repos) or an org (/orgs/{org}/repos).
        self.authenticated_login = response.json().get("login", "")

    @property
    def owner_is_user(self) -> bool:
        return self.org.lower() == self.authenticated_login.lower()

    def parse_pr_url(self, pr_url: str) -> tuple[str, str, int]:
        match = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url)
        if match:
            owner, repo, pr_number = match.groups()
            return owner, repo.replace(".git", ""), int(pr_number)
        raise ValueError(f"Invalid PR URL: {pr_url}")

    def get_pr_details(self, owner: str, repo: str, pr_number: int) -> dict:
        response = self._request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}")
        if response.status_code != 200:
            raise Exception(f"Failed to fetch PR: {response.json().get('message')}")
        return response.json()

    def repo_exists(self, repo_name: str) -> bool:
        # Do NOT follow redirects: a renamed-away repo leaves a 301 redirect on
        # its old name, which would otherwise read as "exists" (200) and wrongly
        # cause callers to skip re-creating it.  Only a direct 200 means it lives
        # at this exact name.
        return self._request(
            "GET", f"/repos/{self.org}/{repo_name}", allow_redirects=False
        ).status_code == 200

    def create_repo(self, repo_name: str):
        # Create as private initially — public repos have mandatory push protection
        # enforced at the platform level that can't be disabled via API. We make
        # it public after pushing.
        #
        # If the target owner is the authenticated user (a personal account, not an
        # org), repos must be created via /user/repos — /orgs/{user}/repos 404s.
        endpoint = "/user/repos" if self.owner_is_user else f"/orgs/{self.org}/repos"
        response = self._request(
            "POST",
            endpoint,
            json={"name": repo_name, "private": True, "auto_init": False},
        )
        if response.status_code != 201:
            raise Exception(f"Failed to create repo: {response.json().get('message')}")

    def set_repo_secret(self, repo_name: str, secret_name: str, secret_value: str):
        """Set an Actions secret on the repo via gh CLI (handles libsodium sealed-box
        encryption for us). The value is passed over stdin, not argv."""
        env = os.environ.copy()
        env["GH_TOKEN"] = self.token
        result = subprocess.run(
            ["gh", "secret", "set", secret_name, "-R", f"{self.org}/{repo_name}"],
            input=secret_value, capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            print(f"Warning: could not set secret {secret_name}: {result.stderr.strip()}")

    def make_repo_public(self, repo_name: str):
        """Make repo public after pushing — avoids push protection on public repos."""
        response = self._request(
            "PATCH",
            f"/repos/{self.org}/{repo_name}",
            json={"private": False},
        )
        if response.status_code not in (200, 204):
            print(f"Warning: Could not make repo public: {response.json().get('message')}")

    def disable_actions(self, repo_name: str):
        """Disable GitHub Actions for the repository."""
        response = self._request(
            "PUT",
            f"/repos/{self.org}/{repo_name}/actions/permissions",
            json={"enabled": False},
        )
        if response.status_code not in (200, 204):
            print(f"Warning: Could not disable actions: {response.json().get('message')}")

    def disable_push_protection(self, repo_name: str):
        """Disable secret scanning push protection to allow pushing test fixtures with token-like strings."""
        response = self._request(
            "PATCH",
            f"/repos/{self.org}/{repo_name}",
            json={
                "security_and_analysis": {
                    "secret_scanning_push_protection": {"status": "disabled"}
                }
            },
        )
        if response.status_code not in (200, 204):
            print(f"Warning: Could not disable push protection: {response.json().get('message')}")

    def disable_dependabot(self, repo_name: str):
        """Disable Dependabot security alerts and automated fixes."""
        self._request("DELETE", f"/repos/{self.org}/{repo_name}/vulnerability-alerts")
        self._request("DELETE", f"/repos/{self.org}/{repo_name}/automated-security-fixes")

    def create_pull_request(
        self, repo: str, title: str, body: str, head: str, base: str
    ) -> dict:
        response = self._request(
            "POST",
            f"/repos/{self.org}/{repo}/pulls",
            json={"title": title, "body": body, "head": head, "base": base},
        )
        if response.status_code != 201:
            err = response.json()
            raise Exception(
                f"Failed to create PR: {err.get('message')} - {err.get('errors')}"
            )
        return response.json()

    def generate_repo_name(
        self, original_repo: str, pr_number: int, ai_tool_name: str,
        config_prefix: str | None = None, neutral: bool = False
    ) -> str:
        date_str = datetime.now().strftime("%Y%m%d")
        if neutral:
            # Anonymous benchmarking: drop the tool slug, config prefix and date so
            # the account never advertises which vendors are being compared (the
            # native bots all review the SAME fork, so the tool name doesn't belong
            # in the name anyway). A short random suffix avoids collisions while
            # keeping the repo looking like an ordinary fork.
            return f"{original_repo}-pr{pr_number}-{secrets.token_hex(2)}"
        tool_slug = re.sub(r"[^a-zA-Z0-9]+", "-", ai_tool_name.lower()).strip("-")[:30]
        if config_prefix:
            return f"{config_prefix}__{original_repo}__{tool_slug}__PR{pr_number}__{date_str}"
        return f"{original_repo}__{tool_slug}__PR{pr_number}__{date_str}"

    def run_git(self, tmpdir: str, *args) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", tmpdir, *args], capture_output=True, text=True)

    def _tree_with_workflow(self, tmpdir: str, tree: str) -> str:
        """Return a new tree equal to `tree` plus .github/workflows/claude.yml.

        Pure plumbing (read-tree/update-index/write-tree) so it works on the
        --no-checkout clone without ever touching a working tree.
        """
        wf_file = os.path.join(tmpdir, "_claude_review_workflow.yml")
        with open(wf_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(CLAUDE_REVIEW_WORKFLOW)

        def _out(*args) -> str:
            r = self.run_git(tmpdir, *args)
            if r.returncode != 0:
                raise Exception(f"git {' '.join(args)} failed:\nstdout: {r.stdout}\nstderr: {r.stderr}")
            return r.stdout.strip()

        _out("read-tree", tree)
        # Drop the forked project's own workflows so only our review workflow runs.
        # Otherwise giant repos (llvm/ClickHouse/envoy) flood Actions with their full
        # CI matrix, competing with and delaying the Claude run. --cached only touches
        # the index (safe on a --no-checkout clone); --ignore-unmatch if none exist.
        self.run_git(tmpdir, "rm", "-r", "--cached", "--ignore-unmatch", ".github/workflows")
        blob = _out("hash-object", "-w", wf_file)
        _out("update-index", "--add", "--cacheinfo", f"100644,{blob},.github/workflows/claude.yml")
        return _out("write-tree")

    def process_pr(self, pr_url: str, ai_tool_name: str, config_prefix: str | None = None,
                   neutral_names: bool = False, base_sha: str | None = None,
                   head_sha: str | None = None) -> dict:
        owner, repo, pr_number = self.parse_pr_url(pr_url)
        # Claude reviews via a GitHub Actions workflow, so its forks must keep
        # Actions enabled and carry the workflow file (see CLAUDE_REVIEW_WORKFLOW).
        is_claude = "claude" in ai_tool_name.lower()
        print(f"\nProcessing PR #{pr_number} from {owner}/{repo}")

        pr = self.get_pr_details(owner, repo, pr_number)
        pr_title = pr["title"]
        pr_body = pr["body"] or ""
        base_branch = pr["base"]["ref"]
        live_base_sha = pr["base"]["sha"]
        # base_sha/head_sha pin the fork to the exact revision the goldens were
        # mined from. This matters for resolved_in_review units: the flaw was
        # fixed by a later push WITHIN the same PR, so the live pull/N/head no
        # longer contains it — forking live would erase the golden defects.
        if base_sha and base_sha != live_base_sha:
            print(f"  Pinning base to recorded {base_sha[:10]} (live is {live_base_sha[:10]})")
        base_sha = base_sha or live_base_sha
        if head_sha:
            print(f"  Pinning head to recorded {head_sha[:10]} (flaw commit)")

        print(f"  Title: {pr_title}")
        print(f"  Base: {base_branch} ({base_sha[:7]})")

        new_repo_name = self.generate_repo_name(repo, pr_number, ai_tool_name, config_prefix, neutral_names)
        if self.repo_exists(new_repo_name):
            raise Exception(
                f"Repository {self.org}/{new_repo_name} already exists. Delete it first."
            )

        pr_branch_name = f"pr-{pr_number}"

        with tempfile.TemporaryDirectory() as tmpdir:
            clone_url = f"https://github.com/{owner}/{repo}.git"

            # Clone WITHOUT a working-tree checkout.  The fork only needs the
            # objects + refs in order to push; skipping checkout avoids failures
            # on repos containing paths Windows/NTFS cannot create (e.g. systemd
            # has filenames with backslashes and colons) or that exceed MAX_PATH,
            # and is much faster for huge trees.
            print(f"\nCloning {owner}/{repo} (no checkout)...")
            result = subprocess.run(
                ["git", "clone", "--no-checkout", "--config", "core.longpaths=true",
                 clone_url, tmpdir],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                raise Exception(f"Clone failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")

            # Fetch PR head. When head_sha is pinned, fetch that exact commit —
            # GitHub serves arbitrary in-network SHAs, including pre-force-push
            # revisions that pull/N/head no longer points at.
            if head_sha:
                print(f"Fetching pinned head {head_sha[:10]}...")
                result = self.run_git(tmpdir, "fetch", "origin", head_sha)
                if result.returncode != 0:
                    # Fall back to the PR ref and hope the sha is in its history.
                    self.run_git(tmpdir, "fetch", "origin", f"pull/{pr_number}/head:pr-head")
                    check = self.run_git(tmpdir, "cat-file", "-e", f"{head_sha}^{{commit}}")
                    if check.returncode != 0:
                        raise Exception(
                            f"Pinned head {head_sha} is not fetchable from {owner}/{repo} "
                            f"(garbage-collected?). Cannot fork the flaw commit.\n"
                            f"stderr: {result.stderr}"
                        )
                check = self.run_git(tmpdir, "cat-file", "-e", f"{base_sha}^{{commit}}")
                if check.returncode != 0:
                    result = self.run_git(tmpdir, "fetch", "origin", base_sha)
                    if result.returncode != 0:
                        raise Exception(
                            f"Pinned base {base_sha} is not fetchable from {owner}/{repo}.\n"
                            f"stderr: {result.stderr}"
                        )
            else:
                print(f"Fetching PR #{pr_number}...")
                result = self.run_git(
                    tmpdir, "fetch", "origin", f"pull/{pr_number}/head:pr-head"
                )
                if result.returncode != 0:
                    raise Exception(f"Fetch failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")

            # Build SQUASHED snapshot commits (no history) via plumbing — never
            # touches the working tree, and the push then transfers only the base
            # tree + PR tree blobs instead of the repo's full history.  This is
            # what makes huge repos (ClickHouse, llvm-project) pushable over
            # HTTPS without the "RPC failed; HTTP 500" oversized-pack error.
            #
            # The review only needs PR #1's diff (pr_tree vs base_tree) plus the
            # base tree for code context, so dropping history is lossless here.
            print("Building squashed base + PR snapshot commits...")
            # Commit identity rides along in the squashed commits and is visible in
            # `git log` on the public fork, so it must not leak who is benchmarking.
            # Defaults are neutral; override via FORK_COMMIT_NAME / FORK_COMMIT_EMAIL.
            self.run_git(tmpdir, "config", "user.email",
                         os.environ.get("FORK_COMMIT_EMAIL", "contributor@users.noreply.github.com"))
            self.run_git(tmpdir, "config", "user.name",
                         os.environ.get("FORK_COMMIT_NAME", "contributor"))

            def _git_out(*args) -> str:
                r = self.run_git(tmpdir, *args)
                if r.returncode != 0:
                    raise Exception(
                        f"git {' '.join(args)} failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"
                    )
                return r.stdout.strip()

            # The fork PR's diff is base_tree vs pr_tree (a two-dot tree diff).
            # When the PR branch contains merges from upstream that base_sha
            # predates, base_sha's tree drags all that upstream drift into the
            # review surface (v2.0: CodeRabbit "reviewed" idna.c on a 3-file
            # libuv PR). Diff from the MERGE-BASE instead — that reproduces the
            # three-dot compare the goldens' surface was verified against.
            diff_base_sha = base_sha
            if head_sha:
                mb = self.run_git(tmpdir, "merge-base", base_sha, head_sha)
                if mb.returncode == 0 and mb.stdout.strip():
                    diff_base_sha = mb.stdout.strip()
                    if diff_base_sha != base_sha:
                        print(f"  Using merge-base {diff_base_sha[:10]} as fork base "
                              f"(recorded base {base_sha[:10]} would inflate the diff)")
                else:
                    print("  Warning: merge-base failed; falling back to recorded base "
                          "(diff may include upstream drift)", file=sys.stderr)
            base_tree = _git_out("rev-parse", f"{diff_base_sha}^{{tree}}")
            pr_tree = _git_out(
                "rev-parse", f"{head_sha}^{{tree}}" if head_sha else "pr-head^{tree}"
            )
            # Inject the Claude review workflow into both trees so it exists on the
            # default branch (registered/visible) and in the PR's merge commit
            # (so `pull_request` fires). Same-repo PR ⇒ Actions secrets are available.
            if is_claude:
                print("Injecting Claude review workflow (.github/workflows/claude.yml)...")
                base_tree = self._tree_with_workflow(tmpdir, base_tree)
                pr_tree = self._tree_with_workflow(tmpdir, pr_tree)
            base_commit = _git_out("commit-tree", base_tree, "-m", f"base {base_sha[:10]}")
            pr_commit = _git_out("commit-tree", pr_tree, "-p", base_commit, "-m", f"PR #{pr_number}")

            _git_out("branch", base_branch + "-forked", base_commit)
            _git_out("branch", pr_branch_name, pr_commit)

            # Create remote repo and disable actions
            print(f"\nCreating repository {self.org}/{new_repo_name}...")
            self.create_repo(new_repo_name)
            # Dependabot PRs on the fork would each trigger a (paid) bot review.
            self.disable_dependabot(new_repo_name)
            if is_claude:
                print("Keeping GitHub Actions enabled (Claude reviews run via Actions)...")
                anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
                if anthropic_key:
                    print("Setting ANTHROPIC_API_KEY repo secret...")
                    self.set_repo_secret(new_repo_name, "ANTHROPIC_API_KEY", anthropic_key)
                else:
                    print("Warning: ANTHROPIC_API_KEY not set in env — Claude workflow will "
                          "fail until you add the secret to the repo.")
            else:
                print("Disabling GitHub Actions...")
                self.disable_actions(new_repo_name)
            time.sleep(2)

            # Add remote and push
            push_url = f"https://x-access-token:{self.token}@github.com/{self.org}/{new_repo_name}.git"
            self.run_git(tmpdir, "remote", "add", "target", push_url)

            print(f"Pushing {base_branch}...")
            result = self.run_git(
                tmpdir, "push", "target", f"{base_branch}-forked:{base_branch}"
            )
            if result.returncode != 0:
                raise Exception(f"Push base failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")

            print(f"Pushing {pr_branch_name}...")
            result = self.run_git(tmpdir, "push", "target", pr_branch_name)
            if result.returncode != 0:
                raise Exception(f"Push PR branch failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")

        # Make repo public now that all pushes are done
        print("Making repository public...")
        self.make_repo_public(new_repo_name)

        # Create PR
        print("Creating PR...")
        new_pr = self.create_pull_request(
            repo=new_repo_name,
            title=pr_title,
            body=pr_body,
            head=pr_branch_name,
            base=base_branch,
        )

        print("\n" + "=" * 60)
        print("SUCCESS!")
        print(f"New PR: {new_pr['html_url']}")
        print("=" * 60)

        return {
            "tool": ai_tool_name,
            "original_pr_url": pr_url,
            "new_repo": f"{self.org}/{new_repo_name}",
            "new_pr_url": new_pr["html_url"],
            "base_sha": base_sha,
            "head_sha": head_sha,  # None ⇒ live pull/N/head was used
        }


def _append_manifest(path: str, record: dict) -> None:
    """Append a fork record to a JSON-list manifest, creating it if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing: list = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, ValueError):
            existing = []
    existing.append(record)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)


def _load_pr_entries_from_file(path: str) -> list[dict]:
    """Load PR entries from a golden comments JSON file.

    The expected format is a JSON array where each element is an object
    containing at least a `url` (or `pr_url`) field pointing to a GitHub PR.
    Optional `base_sha`/`head_sha` fields pin the fork to the exact revision
    the goldens were mined from (needed for resolved_in_review units whose
    live head no longer contains the flaw):

    [
      {"pr_title": "...", "url": "https://github.com/org/repo/pull/123",
       "base_sha": "...", "head_sha": "...", "comments": [...]},
      ...
    ]

    Args:
        path: Filesystem path to the JSON file.

    Returns:
        A list of dicts with `url`, `base_sha`, `head_sha` keys (shas may be None).
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    entries: list[dict] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                url = item.get("url") or item.get("pr_url")
                if isinstance(url, str) and url:
                    entries.append({
                        "url": url,
                        "base_sha": item.get("base_sha"),
                        "head_sha": item.get("head_sha"),
                    })
    return entries


def main():
    """CLI entrypoint: process a single PR or a batch file."""
    parser = argparse.ArgumentParser(description="Clone PR(s) to your org for AI review")
    parser.add_argument("pr_url", nargs="?", help="GitHub PR URL (for single run)")
    parser.add_argument("--file", help="Path to golden comments JSON to batch process")
    parser.add_argument("--org", required=True, help="Target organization")
    parser.add_argument("--name", required=True, help="AI tool name for repo naming")
    parser.add_argument(
        "--token", default=os.environ.get("GITHUB_TOKEN"), help="GitHub token"
    )
    parser.add_argument(
        "--manifest", help="Path to a JSON file to append each created fork's record to "
        "(e.g. other_bots/claude/forks.json)"
    )
    parser.add_argument(
        "--neutral-names", action="store_true",
        help="Name forks anonymously (no tool slug / date) for benchmarking competitor "
        "bots from a clean-room account. Use with the native-app bots that all review "
        "the same fork (CodeRabbit / Gemini / Qodo)."
    )
    args = parser.parse_args()

    if not args.token:
        print("Error: Set GITHUB_TOKEN or use --token")
        sys.exit(1)

    if not args.pr_url and not args.file:
        print("Error: provide a PR URL or --file path", file=sys.stderr)
        sys.exit(1)

    try:
        forker = GitHubPRForker(args.token, args.org)

        if args.file:
            entries = _load_pr_entries_from_file(args.file)
            if not entries:
                print("No PR URLs found in file.", file=sys.stderr)
                sys.exit(1)

            # Extract config prefix from filename (e.g., "cal_dot_com.json" -> "cal_dot_com")
            config_prefix = os.path.splitext(os.path.basename(args.file))[0]

            total = len(entries)
            failures = 0
            for idx, entry in enumerate(entries, start=1):
                url = entry["url"]
                bar_width = 30
                filled = int((idx - 1) / total * bar_width)
                bar = "#" * filled + "-" * (bar_width - filled)
                print(f"[{bar}] {idx-1}/{total} completed", end="\r", flush=True)

                print(f"\n--- [{idx}/{total}] Processing: {url}")
                try:
                    result = forker.process_pr(
                        url, args.name, config_prefix, args.neutral_names,
                        base_sha=entry.get("base_sha"), head_sha=entry.get("head_sha"),
                    )
                    if args.manifest:
                        _append_manifest(args.manifest, result)
                except Exception as exc:
                    failures += 1
                    print(f"Error processing {url}: {exc}", file=sys.stderr)

            # Final bar update
            bar = "#" * 30
            print(f"[{bar}] {total}/{total} completed")
            if failures:
                print(f"Completed with {failures} failure(s).", file=sys.stderr)
        else:
            result = forker.process_pr(args.pr_url, args.name, None, args.neutral_names)
            if args.manifest:
                _append_manifest(args.manifest, result)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
