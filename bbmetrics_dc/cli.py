from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

import typer

from .client import BitbucketDCClient
from .collect_prs import compute_review_metrics_from_events, extract_review_events, list_pull_requests
from .collect_repos import list_repos_in_project
from .export_csv import write_csv
from .metrics import summarize_groups_by_repo, summarize_users_by_repo

app = typer.Typer(add_completion=False)

_PROGRESS_MARKER = "__BBMETRICS_PROGRESS__"
_STAGE_MARKER = "__BBMETRICS_STAGE__"


def _env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise typer.BadParameter(f"Missing env var: {name}")
    return v


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _norm_repo(s: str) -> str:
    return (s or "").strip().lower()


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _parse_mmddyyyy(s: str) -> datetime:
    dt = datetime.strptime(s, "%m-%d-%Y")
    return dt.replace(tzinfo=timezone.utc)


def _epoch_ms_to_iso(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.isoformat()


def _load_user_to_group_map() -> Dict[str, str]:
    p_env = (os.getenv("BBMETRICS_USERS_CSV") or "").strip()
    p = Path(p_env) if p_env else (Path("in") / "users.csv")
    if not p.exists():
        return {}
    out: Dict[str, str] = {}
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            u = (row.get("user") or "").strip()
            g = (row.get("group") or "").strip()
            if u and g:
                out[u] = g
    return out


def _validate_required_inputs(
    *,
    project_key: str,
    repos: Optional[List[str]],
    pr_start: Optional[str],
    pr_end: Optional[str],
) -> Tuple[datetime, datetime]:
    if not project_key or not str(project_key).strip():
        raise ValueError("project_key is required.")
    if not repos or not any((r or "").strip() for r in repos):
        raise ValueError("Select at least one repository (--repos).")
    if not pr_start or not pr_start.strip():
        raise ValueError("PR Start (--pr-start) is required (MM-DD-YYYY).")
    if not pr_end or not pr_end.strip():
        raise ValueError("PR End (--pr-end) is required (MM-DD-YYYY).")

    start_dt = _parse_mmddyyyy(pr_start)
    end_dt = _parse_mmddyyyy(pr_end).replace(hour=23, minute=59, second=59)
    if end_dt < start_dt:
        raise ValueError("PR End must be greater than or equal to PR Start.")
    return start_dt, end_dt


def _get_repo_slug(repo_obj) -> str:
    slug = getattr(repo_obj, "repo_slug", None) or getattr(repo_obj, "slug", None) or ""
    return str(slug)


def _parse_states(s: Optional[str]) -> List[str]:
    raw_in = (s or "").strip()
    if not raw_in:
        return ["OPEN", "MERGED", "DECLINED"]
    raw = [x.strip().upper() for x in raw_in.split(",") if x.strip()]
    allowed = {"OPEN", "MERGED", "DECLINED"}
    out = [x for x in raw if x in allowed]
    return out or ["OPEN", "MERGED", "DECLINED"]


def _emit_stage(text: str) -> None:
    print(f"{_STAGE_MARKER} {text}")


def _emit_progress(current: int, total: int) -> None:
    print(f"{_PROGRESS_MARKER} {int(current)} {int(total)}")


def _fetch_pr_activities_until_ready(
    client: BitbucketDCClient,
    project_key: str,
    repo_slug: str,
    pr_id: int,
    *,
    limit: int,
    stop_when_ready: bool,
) -> List[Dict]:
    endpoint = f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests/{pr_id}/activities"
    activities: List[Dict] = []
    if limit == 0:
        return activities
    page_limit = 100 if limit < 0 else min(100, limit)

    seen_review_event = False
    seen_approval = False

    for item in client.paginate(endpoint, params={"limit": page_limit}):
        activities.append(item)

        if stop_when_ready:
            act = (item.get("action") or "").upper().strip()
            if act in {"COMMENTED", "UNAPPROVED", "NEEDS_WORK", "APPROVED"}:
                seen_review_event = True
            if act == "APPROVED":
                seen_approval = True
            if seen_review_event and seen_approval:
                break

        if limit > 0 and len(activities) >= limit:
            break

    return activities


def _pr_time_for_filter(pr: Dict, state: str, *, date_field: str) -> Optional[int]:
    s = (state or pr.get("state") or "").upper().strip()

    if date_field == "closed":
        if s in {"MERGED", "DECLINED"}:
            ms = pr.get("closedDate") or pr.get("updatedDate")
            try:
                return int(ms) if ms is not None else None
            except Exception:
                return None
        ms = pr.get("createdDate")
        try:
            return int(ms) if ms is not None else None
        except Exception:
            return None

    ms = pr.get("createdDate")
    try:
        return int(ms) if ms is not None else None
    except Exception:
        return None


def _list_pr_commits(
    client: BitbucketDCClient,
    project_key: str,
    repo_slug: str,
    pr_id: int,
    *,
    page_limit: int = 200,
) -> Iterator[Dict[str, Any]]:
    path = f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests/{pr_id}/commits"
    yield from client.paginate(path, params={"limit": int(page_limit)})


def _count_diff_patch(text: str) -> Tuple[int, int, int, bool]:
    files = 0
    added = 0
    removed = 0
    looks_like_patch = False

    for line in (text or "").splitlines():
        if line.startswith("diff --git "):
            looks_like_patch = True
            files += 1
            continue

        if line.startswith("+++ ") or line.startswith("--- "):
            looks_like_patch = True
            continue

        if not line:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            added += 1
            looks_like_patch = True
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
            looks_like_patch = True

    return files, added, removed, looks_like_patch


def _changes_files_count(client: BitbucketDCClient, project_key: str, repo_slug: str, pr_id: int) -> int:
    changes_path = f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests/{pr_id}/changes"
    fc = 0
    for _ in client.paginate(changes_path, params={"limit": 200}):
        fc += 1
    return fc


def _get_pr_diff_lines(
    client: BitbucketDCClient,
    project_key: str,
    repo_slug: str,
    pr_id: int,
    log_fn,
) -> Tuple[object, object, object, str]:
    diff_path = f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests/{pr_id}/diff"

    candidates = [
        ({"withComments": "false"}, "pr_diff"),
        ({"withComments": "false", "markup": "false"}, "pr_diff_markup_false"),
        ({"withComments": "false", "format": "patch"}, "pr_diff_format_patch"),
    ]

    for params, label in candidates:
        try:
            txt = client.get_text(diff_path, params=params, accept="text/plain")
            files, added, removed, ok = _count_diff_patch(txt)
            if ok and (files or added or removed):
                return files, added, removed, label
        except Exception as e:
            log_fn(f"DIFFSTAT: diff attempt failed ({label}) for {project_key}/{repo_slug}#{pr_id}: {e!r}")

    # Could not parse patch. Log preview once.
    try:
        txt = client.get_text(diff_path, params={"withComments": "false"}, accept="text/plain")
        preview = "\n".join((txt or "").splitlines()[:25])
        log_fn(
            f"DIFFSTAT: diff endpoint did not return patch for {project_key}/{repo_slug}#{pr_id}. "
            f"Preview (first 25 lines):\n{preview}"
        )
    except Exception as e:
        log_fn(f"DIFFSTAT: diff preview fetch failed for {project_key}/{repo_slug}#{pr_id}: {e!r}")

    # Fallback: at least files_changed from /changes; keep lines blank
    try:
        fc = _changes_files_count(client, project_key, repo_slug, pr_id)
        return fc, "", "", "changes_only"
    except Exception as e:
        log_fn(f"DIFFSTAT: changes fallback failed for {project_key}/{repo_slug}#{pr_id}: {e!r}")
        return "", "", "", ""


def _extract_branch(ref: Any) -> str:
    """
    ref is usually pr['fromRef'] or pr['toRef'].
    Prefer displayId, else strip refs/heads/ from id.
    """
    if not isinstance(ref, dict):
        return ""
    disp = (ref.get("displayId") or "").strip()
    if disp:
        return disp
    rid = (ref.get("id") or "").strip()
    if rid.startswith("refs/heads/"):
        return rid[len("refs/heads/") :]
    return rid


def scan(
    *,
    project_key: str,
    out: str = "./out",
    user: Optional[str] = None,
    repos: Optional[List[str]] = None,
    pr_start: Optional[str] = None,
    pr_end: Optional[str] = None,
    log_file: Optional[str] = None,
    include_comment_text: bool = False,
    enable_diffstat: bool = False,
    output_mode: str = "completo",
    pr_states: str = "OPEN,MERGED,DECLINED",
    activities_limit: int = 0,
    stop_when_ready: bool = True,
    date_field: str = "created",
) -> None:
    output_mode = (output_mode or "completo").strip().lower()
    if output_mode not in ("summaries", "completo"):
        raise ValueError("Invalid output_mode. Use: summaries or completo.")

    date_field = (date_field or "created").strip().lower()
    if date_field not in ("created", "closed"):
        raise ValueError("Invalid date_field. Use: created or closed.")

    states = _parse_states(pr_states)

    if activities_limit == 0:
        activities_limit = 50 if output_mode == "summaries" else 200

    os.makedirs(out, exist_ok=True)
    if not log_file:
        log_file = os.path.join(out, "scan.log")
    _ensure_parent_dir(log_file)

    ignore_epic = _env_bool("BBMETRICS_IGNORE_EPIC_PRS", default=False)

    def log(msg: str) -> None:
        print(msg)
        with open(log_file, "a", encoding="utf-8", newline="\n") as f:
            f.write(msg + "\n")

    start_dt, end_dt = _validate_required_inputs(project_key=project_key, repos=repos, pr_start=pr_start, pr_end=pr_end)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    users_filter: Optional[Set[str]] = None
    if user:
        users_filter = {u.strip() for u in user.split(",") if u.strip()}

    log(f"=== scan start: {datetime.now().isoformat(timespec='seconds')} ===")
    log(
        f"project_key={project_key} out={out} user={user or ''} repos={','.join(repos or [])} "
        f"pr_start={pr_start or ''} pr_end={pr_end or ''} output_mode={output_mode} "
        f"states={','.join(states)} activities_limit={activities_limit} date_field={date_field} "
        f"enable_diffstat={enable_diffstat} ignore_epic_prs={ignore_epic}"
    )
    log(f"start={start_dt.isoformat()} ({start_ms})")
    log(f"end={end_dt.isoformat()} ({end_ms})")
    log(f"log_file={log_file}")
    log(f"include_comment_text={include_comment_text}")
    users_csv_env = (os.getenv("BBMETRICS_USERS_CSV") or "").strip()
    if users_csv_env:
        log(f"users_csv={users_csv_env}")
    log("")

    base_url = os.getenv("BITBUCKET_BASE_URL", "https://git.rdisoftware.com:8443")
    client = BitbucketDCClient(base_url=base_url, username=_env("BITBUCKET_USERNAME"), password=_env("BITBUCKET_PASSWORD"))

    _emit_stage("Loading repos...")
    repos_all = list_repos_in_project(client, project_key)

    requested = [r for r in (repos or []) if (r or "").strip()]
    requested_norm: Set[str] = {_norm_repo(r) for r in requested}

    repos_to_scan = [
        r
        for r in repos_all
        if _norm_repo(_get_repo_slug(r)) in requested_norm or _norm_repo(getattr(r, "name", "")) in requested_norm
    ]
    selected_repo_slugs: Set[str] = {_get_repo_slug(r) for r in repos_to_scan if _get_repo_slug(r)}

    _emit_stage("Listing PRs in date range...")
    pr_index: List[Tuple[str, str, int, Dict]] = []
    for repo in repos_to_scan:
        repo_slug = _get_repo_slug(repo)
        if not repo_slug:
            continue
        for state in states:
            for pr in list_pull_requests(
                client,
                project_key,
                repo_slug,
                state=state,
                created_after_ms=None,
                created_before_ms=None,
                page_limit=50,
            ):
                pr_author = (pr.get("author") or {}).get("user") or {}
                pr_author_name = pr_author.get("name") or ""
                if users_filter and pr_author_name not in users_filter:
                    continue

                t_ms = _pr_time_for_filter(pr, state, date_field=date_field)
                if t_ms is None:
                    continue
                if t_ms < start_ms or t_ms > end_ms:
                    continue

                pr_title = (pr.get("title") or "")
                if ignore_epic and "epic" in pr_title.lower():
                    continue

                pr_id = int(pr["id"])
                pr_index.append((repo_slug, state, pr_id, pr))

    total_prs = len(pr_index)
    _emit_progress(0, max(1, total_prs))
    log(f"PRs in range (after user filter): {total_prs}")

    _emit_stage("Processing PRs...")
    pr_rows: List[Dict] = []
    commit_rows: List[Dict] = []
    review_event_rows: List[Dict] = []
    pr_review_metrics_rows: List[Dict] = []

    processed = 0
    for repo_slug, state, pr_id, pr in pr_index:
        processed += 1
        _emit_progress(processed, max(1, total_prs))

        pr_author = (pr.get("author") or {}).get("user") or {}
        pr_author_name = pr_author.get("name") or ""
        pr_title = pr.get("title") or ""
        pr_state = (pr.get("state") or state or "").upper().strip()

        # Branches
        source_branch = _extract_branch(pr.get("fromRef"))
        target_branch = _extract_branch(pr.get("toRef"))

        commits = list(_list_pr_commits(client, project_key, repo_slug, pr_id))
        pr_commit_times_iso: List[str] = []
        for c in commits:
            try:
                ts = c.get("authorTimestamp") or c.get("committerTimestamp")
                if ts is not None:
                    pr_commit_times_iso.append(_epoch_ms_to_iso(int(ts)))
            except Exception:
                pass
        pr_commit_times_iso.sort()

        files_changed: object = ""
        lines_added: object = ""
        lines_removed: object = ""
        diff_source: str = ""

        if enable_diffstat:
            files_changed, lines_added, lines_removed, diff_source = _get_pr_diff_lines(
                client, project_key, repo_slug, pr_id, log
            )

        if enable_diffstat and output_mode == "completo":
            for c in commits:
                commit_id = str(c.get("id") or c.get("displayId") or "")
                author = ""
                author_ts_ms: Optional[int] = None
                try:
                    a = c.get("author") or {}
                    if isinstance(a, dict):
                        author = a.get("name") or a.get("displayName") or ""
                except Exception:
                    pass
                try:
                    ts = c.get("authorTimestamp") or c.get("committerTimestamp")
                    if ts is not None:
                        author_ts_ms = int(ts)
                except Exception:
                    author_ts_ms = None

                commit_iso = _epoch_ms_to_iso(author_ts_ms) if author_ts_ms is not None else ""

                commit_rows.append(
                    {
                        "project_key": project_key,
                        "repo_slug": repo_slug,
                        "pr_id": pr_id,
                        "pr_state": pr_state,
                        "pr_author": pr_author_name,
                        "commit_id": commit_id,
                        "author": author,
                        "author_timestamp": str(author_ts_ms or ""),
                        "commit_timestamp_iso": commit_iso,
                        "pr_files_changed": files_changed,
                        "pr_lines_added": lines_added,
                        "pr_lines_removed": lines_removed,
                        "diff_source": diff_source,
                    }
                )

        activities = _fetch_pr_activities_until_ready(
            client,
            project_key,
            repo_slug,
            pr_id,
            limit=activities_limit,
            stop_when_ready=(stop_when_ready and output_mode == "summaries"),
        )

        events = extract_review_events(
            activities,
            project_key=project_key,
            repo_slug=repo_slug,
            pr_id=pr_id,
            include_text=include_comment_text if output_mode == "completo" else False,
        )

        if output_mode == "completo":
            for e in events:
                review_event_rows.append(
                    {
                        "project_key": e.project_key,
                        "repo_slug": e.repo_slug,
                        "pr_id": e.pr_id,
                        "pr_author": pr_author_name,
                        "event_type": e.event_type,
                        "action": e.action,
                        "actor": e.actor,
                        "created_on": e.created_on,
                        "is_inline": e.is_inline,
                        "comment_id": e.comment_id or "",
                        "text": e.text,
                    }
                )

        comments_total = sum(1 for e in events if e.event_type == "COMMENT")
        comments_inline = sum(1 for e in events if e.event_type == "COMMENT" and e.is_inline == 1)
        comments_general = comments_total - comments_inline

        review_metrics = compute_review_metrics_from_events(pr, events, pr_commit_times_iso=pr_commit_times_iso)

        # Add branches to metrics CSV too (B option)
        pr_review_metrics_rows.append(
            {
                "project_key": project_key,
                "repo_slug": repo_slug,
                "pr_id": pr_id,
                "state": pr_state,
                "title": pr_title,
                "author": pr_author_name,
                "source_branch": source_branch,
                "target_branch": target_branch,
                **review_metrics,
            }
        )

        pr_rows.append(
            {
                "project_key": project_key,
                "repo_slug": repo_slug,
                "pr_id": pr_id,
                "state": pr_state,
                "title": pr_title,
                "author": pr_author_name,
                "source_branch": source_branch,
                "target_branch": target_branch,
                "created_on": review_metrics.get("created_on", ""),
                "updated_on": review_metrics.get("updated_on", ""),
                "closed_on": review_metrics.get("closed_on", ""),
                "time_open_minutes": review_metrics.get("time_open_minutes", 0),
                "comments_total": comments_total,
                "comments_inline": comments_inline,
                "comments_general": comments_general,
                "files_changed": files_changed,
                "lines_added": lines_added,
                "lines_removed": lines_removed,
                "diff_source": diff_source,
            }
        )

    _emit_stage("Writing summaries...")
    user_to_group = _load_user_to_group_map()

    users_rows = summarize_users_by_repo(
        commit_rows,
        pr_rows,
        pr_review_metrics_rows,
        user_to_group=user_to_group,
        selected_repos=selected_repo_slugs,
        diffstat_enabled=enable_diffstat,
    )

    filter_mode = (os.getenv("BBMETRICS_FILTER_MODE") or "").strip().lower()
    groups_rows: List[Dict] = []
    if filter_mode == "group":
        groups_rows = summarize_groups_by_repo(
            users_rows,
            selected_repos=selected_repo_slugs,
            diffstat_enabled=enable_diffstat,
        )

    write_csv(os.path.join(out, "users_summary.csv"), users_rows)
    if filter_mode == "group":
        write_csv(os.path.join(out, "groups_summary.csv"), groups_rows)

    if output_mode == "completo":
        _emit_stage("Writing full CSVs...")
        write_csv(os.path.join(out, "prs.csv"), pr_rows)
        write_csv(os.path.join(out, "pr_review_events.csv"), review_event_rows)
        write_csv(os.path.join(out, "pr_review_metrics.csv"), pr_review_metrics_rows)
        if enable_diffstat:
            write_csv(os.path.join(out, "commits.csv"), commit_rows)

    _emit_stage("Done.")
    _emit_progress(max(1, total_prs), max(1, total_prs))
    log(f"=== scan end: {datetime.now().isoformat(timespec='seconds')} ===")


@app.command("scan")
def scan_cmd(
    project_key: str = typer.Option(...),
    out: str = typer.Option("./out"),
    user: Optional[str] = typer.Option(None, "--user"),
    repos: Optional[List[str]] = typer.Option(None, "--repos"),
    pr_start: Optional[str] = typer.Option(None, "--pr-start"),
    pr_end: Optional[str] = typer.Option(None, "--pr-end"),
    log_file: Optional[str] = typer.Option(None, "--log-file"),
    include_comment_text: bool = typer.Option(False, "--include-comment-text"),
    enable_diffstat: bool = typer.Option(False, "--enable-diffstat/--disable-diffstat"),
    output_mode: str = typer.Option("completo", "--output-mode"),
    pr_states: str = typer.Option("OPEN,MERGED,DECLINED", "--pr-states"),
    activities_limit: int = typer.Option(0, "--activities-limit"),
    date_field: str = typer.Option("created", "--date-field"),
) -> None:
    scan(
        project_key=project_key,
        out=out,
        user=user,
        repos=repos,
        pr_start=pr_start,
        pr_end=pr_end,
        log_file=log_file,
        include_comment_text=include_comment_text,
        enable_diffstat=enable_diffstat,
        output_mode=output_mode,
        pr_states=pr_states,
        activities_limit=activities_limit,
        date_field=date_field,
    )


if __name__ == "__main__":
    app()