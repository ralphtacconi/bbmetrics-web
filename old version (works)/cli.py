from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List, Optional, Set

import typer

from .client import BitbucketDCClient
from .collect_prs import (
    count_comments_from_activities,
    estimate_time_open_seconds,
    list_pr_comments,
    list_pull_requests,
)
from .collect_repos import list_repos_in_project
from .diffstat import get_commit_diffstat_totals
from .export_csv import write_csv
from .metrics import summarize_users

app = typer.Typer(add_completion=False)


def _env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise typer.BadParameter(f"Missing env var: {name}")
    return v


def _norm_repo(s: str) -> str:
    return (s or "").strip().lower()


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


@app.command()
def scan(
    project_key: str = typer.Option(..., help="Bitbucket project key, ex: APP"),
    out: str = typer.Option("./out", help="Output directory"),
    user: Optional[str] = typer.Option(
        None,
        "--user",
        help="Filter by PR author username (Bitbucket DC). Example: ralphtacconi",
    ),
    repos: Optional[List[str]] = typer.Option(
        None,
        "--repos",
        help="Optional list of repository slugs/names to scan. Repeat --repos for multiple entries.",
    ),
    log_file: Optional[str] = typer.Option(
        None,
        "--log-file",
        help="Optional path to a .txt log file. Default: <out>/scan.log",
    ),
):
    """
    Bitbucket Data Center metrics for all repos in a project.
    Filters by PR author if --user is provided.
    """
    os.makedirs(out, exist_ok=True)

    if not log_file:
        log_file = os.path.join(out, "scan.log")
    _ensure_parent_dir(log_file)

    def log(msg: str) -> None:
        # terminal
        typer.echo(msg)
        # file
        with open(log_file, "a", encoding="utf-8", newline="\n") as f:
            f.write(msg + "\n")

    # Start log
    log(f"=== scan start: {datetime.now().isoformat(timespec='seconds')} ===")
    log(f"project_key={project_key} out={out} user={user or ''} repos={','.join(repos or [])}")
    log(f"log_file={log_file}")
    log("")

    base_url = os.getenv("BITBUCKET_BASE_URL", "https://git.rdisoftware.com:8443")
    username = _env("BITBUCKET_USERNAME")
    password = _env("BITBUCKET_PASSWORD")

    client = BitbucketDCClient(base_url=base_url, username=username, password=password)

    repos_all = list_repos_in_project(client, project_key)

    # Optional repo filter (client-side)
    if repos:
        requested = [r for r in repos if (r or "").strip()]
        requested_norm: Set[str] = {_norm_repo(r) for r in requested}

        repos_filtered = [
            r
            for r in repos_all
            if _norm_repo(getattr(r, "repo_slug", "")) in requested_norm
            or _norm_repo(getattr(r, "repo_name", "")) in requested_norm
        ]

        found_norm: Set[str] = set()
        for r in repos_filtered:
            found_norm.add(_norm_repo(getattr(r, "repo_slug", "")))
            found_norm.add(_norm_repo(getattr(r, "repo_name", "")))

        invalid = [r for r in requested if _norm_repo(r) not in found_norm]
        if invalid:
            log(f"WARNING: repos not found in project {project_key}: {', '.join(invalid)}")

        repos_to_scan = repos_filtered
    else:
        repos_to_scan = repos_all

    log(f"Repos in project {project_key}: {len(repos_all)}")
    log(f"Repos selected to scan: {len(repos_to_scan)}")
    if user:
        log(f"User filter (PR author): {user}")
    log("")

    pr_rows: List[Dict] = []
    commit_rows: List[Dict] = []

    for repo in repos_to_scan:
        log(f"Scanning repo: {project_key}/{repo.repo_slug}")

        for state in ["OPEN", "MERGED", "DECLINED"]:
            for pr in list_pull_requests(client, project_key, repo.repo_slug, state=state):
                pr_id = int(pr["id"])
                pr_author = (pr.get("author") or {}).get("user") or {}
                pr_author_name = pr_author.get("name") or ""

                if user and pr_author_name != user:
                    continue

                log(f"  PR #{pr_id} [{state}] author={pr_author_name} title={(pr.get('title') or '')}")

                log("    fetching activities/comments...")
                activities = list_pr_comments(client, project_key, repo.repo_slug, pr_id)
                comments = count_comments_from_activities(activities)

                created_on, updated_on, closed_on, time_open_seconds = estimate_time_open_seconds(pr)

                log("    fetching commits list...")
                pr_commits_total = 0
                pr_commits_kept = 0

                for c in client.paginate(
                    f"/rest/api/1.0/projects/{project_key}/repos/{repo.repo_slug}/pull-requests/{pr_id}/commits",
                    params={"limit": 100},
                ):
                    pr_commits_total += 1
                    commit_hash = c.get("id") or c.get("displayId")
                    commit_author = (c.get("author") or {}).get("name") or ""

                    pr_commits_kept += 1

                    log(f"    commit {pr_commits_total}: {commit_hash} diffstat...")
                    diff = get_commit_diffstat_totals(client, project_key, repo.repo_slug, commit_hash)

                    commit_rows.append(
                        {
                            "project_key": project_key,
                            "repo_slug": repo.repo_slug,
                            "pr_id": pr_id,
                            "commit_hash": commit_hash,
                            "author": commit_author,
                            "lines_added": diff.lines_added,
                            "lines_removed": diff.lines_removed,
                            "lines_changed": diff.lines_changed,
                            "files_changed": diff.files_changed,
                        }
                    )

                pr_rows.append(
                    {
                        "project_key": project_key,
                        "repo_slug": repo.repo_slug,
                        "pr_id": pr_id,
                        "state": pr.get("state") or state,
                        "title": pr.get("title") or "",
                        "author": pr_author_name,
                        "created_on": created_on,
                        "updated_on": updated_on,
                        "closed_on": closed_on or "",
                        "time_open_seconds": time_open_seconds,
                        "comments_total": comments["total"],
                        "comments_inline": comments["inline"],
                        "comments_general": comments["general"],
                        "commits_count_total": pr_commits_total,
                        "commits_count_kept": pr_commits_kept,
                    }
                )

        log("")  # blank line between repos

    users_rows = summarize_users(commit_rows, pr_rows)

    write_csv(os.path.join(out, "prs.csv"), pr_rows)
    write_csv(os.path.join(out, "commits.csv"), commit_rows)
    write_csv(os.path.join(out, "users_summary.csv"), users_rows)

    log(f"Wrote: {os.path.join(out, 'prs.csv')}")
    log(f"Wrote: {os.path.join(out, 'commits.csv')}")
    log(f"Wrote: {os.path.join(out, 'users_summary.csv')}")
    log(f"=== scan end: {datetime.now().isoformat(timespec='seconds')} ===")


if __name__ == "__main__":
    app()