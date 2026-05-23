from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional, Set

from .client import BitbucketDCClient
from .timeutil import from_epoch_ms, utc_now


def list_pull_requests(
    client: BitbucketDCClient,
    project_key: str,
    repo_slug: str,
    state: str,
    *,
    created_after_ms: Optional[int] = None,
    created_before_ms: Optional[int] = None,
    page_limit: int = 50,
    max_prs_scanned: int = 5000,
) -> Iterator[Dict]:
    """
    Lists pull requests filtered by createdDate window.

    Important:
    - Bitbucket DC endpoint doesn't support createdDate filtering.
    - We may early-stop ONLY if we can confirm results are ordered by createdDate DESC.

    If order is ASC or unknown, we avoid early-stop (to prevent dropping all results),
    and instead rely on scanning up to max_prs_scanned for safety.
    """
    scanned = 0
    stop_early_enabled: Optional[bool] = None  # None=unknown, True=DESC, False=ASC/unknown
    last_created: Optional[int] = None

    for pr in client.paginate(
        f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests",
        params={"state": state, "limit": int(page_limit)},
    ):
        scanned += 1
        if max_prs_scanned and scanned > max_prs_scanned:
            # Safety break to avoid scanning entire history if server order is ASC/unknown.
            break

        created_ms = pr.get("createdDate")
        created_i: Optional[int]
        if created_ms is None:
            created_i = None
        else:
            try:
                created_i = int(created_ms)
            except Exception:
                created_i = None

        # Determine ordering based on first comparable pair
        if stop_early_enabled is None and created_i is not None and last_created is not None:
            # If created dates are going down as we iterate -> DESC (newest first)
            if created_i < last_created:
                stop_early_enabled = True
            # If going up -> ASC (oldest first)
            elif created_i > last_created:
                stop_early_enabled = False
            else:
                # equal; keep unknown until we see a difference
                pass

        if created_i is not None:
            last_created = created_i

        # Upper bound: too new => skip
        if created_before_ms is not None and created_i is not None and created_i > created_before_ms:
            continue

        # Lower bound:
        if created_after_ms is not None and created_i is not None:
            if created_i < created_after_ms:
                # Only early-stop when we CONFIRMED DESC ordering
                if stop_early_enabled is True:
                    break
                # If ASC/unknown, just skip (do not stop)
                continue

        yield pr


def list_pr_activities(client: BitbucketDCClient, project_key: str, repo_slug: str, pr_id: int):
    for a in client.paginate(
        f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests/{pr_id}/activities",
        params={"limit": 100},
    ):
        yield a


def list_pr_comments(client: BitbucketDCClient, project_key: str, repo_slug: str, pr_id: int):
    yield from list_pr_activities(client, project_key, repo_slug, pr_id)


def _get_actor_username(activity: Dict) -> str:
    u = activity.get("user") or {}
    if isinstance(u, dict):
        return u.get("name") or u.get("displayName") or u.get("emailAddress") or "UNKNOWN"
    return "UNKNOWN"


def _get_activity_created_dt(activity: Dict):
    ms = activity.get("createdDate")
    if ms is None:
        return None
    try:
        return from_epoch_ms(int(ms))
    except Exception:
        return None


def _is_inline_comment(comment: Dict) -> bool:
    return bool(comment.get("anchor"))


def count_comments_from_activities(activities: Iterable[Dict]) -> Dict[str, int]:
    total = inline = general = 0
    for a in activities:
        if a.get("action") != "COMMENTED":
            continue
        c = a.get("comment") or {}
        total += 1
        if _is_inline_comment(c):
            inline += 1
        else:
            general += 1
    return {"total": total, "inline": inline, "general": general}


def estimate_time_open_minutes(pr: Dict) -> tuple[str, str, Optional[str], float]:
    created_ms = pr.get("createdDate")
    updated_ms = pr.get("updatedDate")
    closed_ms = pr.get("closedDate")
    state = pr.get("state", "OPEN")

    created_dt = from_epoch_ms(int(created_ms))
    created_iso = created_dt.isoformat()

    closed_iso: Optional[str] = None
    if state == "OPEN":
        end = utc_now()
    else:
        if closed_ms is not None:
            end = from_epoch_ms(int(closed_ms))
            closed_iso = end.isoformat()
        else:
            end = from_epoch_ms(int(updated_ms)) if updated_ms is not None else utc_now()
            closed_iso = end.isoformat()

    updated_iso = from_epoch_ms(int(updated_ms)).isoformat() if updated_ms is not None else ""
    minutes = (end - created_dt).total_seconds() / 60.0
    return created_iso, updated_iso, closed_iso, round(minutes, 2)


_REVIEW_ACTIONS: Set[str] = {
    "COMMENTED",
    "APPROVED",
    "UNAPPROVED",
    "NEEDS_WORK",
    "OPENED",
    "REOPENED",
    "RESCOPED",
    "UPDATED",
    "MERGED",
    "DECLINED",
}


@dataclass
class ReviewEvent:
    project_key: str
    repo_slug: str
    pr_id: int
    event_type: str
    action: str
    actor: str
    created_on: str
    is_inline: int
    comment_id: Optional[int]
    text: str


def extract_review_events(
    activities: Iterable[Dict],
    project_key: str,
    repo_slug: str,
    pr_id: int,
    include_text: bool = False,
) -> List[ReviewEvent]:
    out: List[ReviewEvent] = []

    for a in activities:
        action = (a.get("action") or "").upper().strip()
        if not action:
            continue

        actor = _get_actor_username(a)
        created_dt = _get_activity_created_dt(a)
        created_on = created_dt.isoformat() if created_dt else ""

        if action == "COMMENTED":
            c = a.get("comment") or {}
            is_inline = 1 if _is_inline_comment(c) else 0
            comment_id = c.get("id")
            text = ""
            if include_text:
                text = (c.get("text") or "").strip()
            out.append(
                ReviewEvent(
                    project_key=project_key,
                    repo_slug=repo_slug,
                    pr_id=pr_id,
                    event_type="COMMENT",
                    action=action,
                    actor=actor,
                    created_on=created_on,
                    is_inline=is_inline,
                    comment_id=int(comment_id) if comment_id is not None else None,
                    text=text,
                )
            )
            continue

        if action in {"APPROVED", "UNAPPROVED", "NEEDS_WORK"}:
            et = "APPROVAL" if action == "APPROVED" else ("UNAPPROVAL" if action == "UNAPPROVED" else "NEEDS_WORK")
            out.append(
                ReviewEvent(
                    project_key=project_key,
                    repo_slug=repo_slug,
                    pr_id=pr_id,
                    event_type=et,
                    action=action,
                    actor=actor,
                    created_on=created_on,
                    is_inline=0,
                    comment_id=None,
                    text="",
                )
            )
            continue

        if action in _REVIEW_ACTIONS:
            out.append(
                ReviewEvent(
                    project_key=project_key,
                    repo_slug=repo_slug,
                    pr_id=pr_id,
                    event_type="OTHER",
                    action=action,
                    actor=actor,
                    created_on=created_on,
                    is_inline=0,
                    comment_id=None,
                    text="",
                )
            )

    out.sort(key=lambda e: e.created_on or "")
    return out


def compute_review_metrics_from_events(
    pr: Dict,
    events: List[ReviewEvent],
    pr_commit_times_iso: List[str],
) -> Dict:
    created_on, updated_on, closed_on, time_open_minutes = estimate_time_open_minutes(pr)
    created_dt = from_epoch_ms(int(pr.get("createdDate")))

    first_comment_at: Optional[str] = None
    first_review_event_at: Optional[str] = None
    first_approval_at: Optional[str] = None

    approvers: Set[str] = set()
    commenters: Set[str] = set()
    comments_total = 0
    comments_inline = 0
    comments_general = 0
    approvals_total = 0

    for e in events:
        if e.event_type == "COMMENT":
            comments_total += 1
            commenters.add(e.actor)
            if e.is_inline:
                comments_inline += 1
            else:
                comments_general += 1
            if not first_comment_at and e.created_on:
                first_comment_at = e.created_on
            if not first_review_event_at and e.created_on:
                first_review_event_at = e.created_on

        elif e.event_type == "APPROVAL":
            approvals_total += 1
            approvers.add(e.actor)
            if not first_approval_at and e.created_on:
                first_approval_at = e.created_on
            if not first_review_event_at and e.created_on:
                first_review_event_at = e.created_on

        elif e.event_type in {"UNAPPROVAL", "NEEDS_WORK"}:
            if not first_review_event_at and e.created_on:
                first_review_event_at = e.created_on

    def _delta_minutes(iso: Optional[str]) -> Optional[float]:
        if not iso:
            return None
        try:
            import datetime as _dt

            dt = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt.timezone.utc)
            return round((dt - created_dt).total_seconds() / 60.0, 2)
        except Exception:
            return None

    time_to_first_comment_minutes = _delta_minutes(first_comment_at)
    time_to_first_review_event_minutes = _delta_minutes(first_review_event_at)
    time_to_first_approval_minutes = _delta_minutes(first_approval_at)

    commits_total = len(pr_commit_times_iso)
    last_commit_at = pr_commit_times_iso[-1] if pr_commit_times_iso else ""

    def _count_commits_after(iso: Optional[str]) -> Optional[int]:
        if not iso:
            return None
        try:
            import datetime as _dt

            pivot = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
            if pivot.tzinfo is None:
                pivot = pivot.replace(tzinfo=_dt.timezone.utc)

            count = 0
            for x in pr_commit_times_iso:
                dt = _dt.datetime.fromisoformat(x.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=_dt.timezone.utc)
                if dt > pivot:
                    count += 1
            return count
        except Exception:
            return None

    commits_after_first_comment = _count_commits_after(first_comment_at)
    commits_after_first_approval = _count_commits_after(first_approval_at)

    merge_lag_minutes: Optional[float] = None
    if last_commit_at and closed_on:
        try:
            import datetime as _dt

            last_dt = _dt.datetime.fromisoformat(last_commit_at.replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=_dt.timezone.utc)
            closed_dt = _dt.datetime.fromisoformat(closed_on.replace("Z", "+00:00"))
            if closed_dt.tzinfo is None:
                closed_dt = closed_dt.replace(tzinfo=_dt.timezone.utc)
            merge_lag_minutes = round((closed_dt - last_dt).total_seconds() / 60.0, 2)
        except Exception:
            merge_lag_minutes = None

    return {
        "created_on": created_on,
        "updated_on": updated_on,
        "closed_on": closed_on or "",
        "time_open_minutes": time_open_minutes,
        "comments_total": comments_total,
        "comments_inline": comments_inline,
        "comments_general": comments_general,
        "approvals_total": approvals_total,
        "approvers_unique_count": len(approvers),
        "approvers_unique": ",".join(sorted(approvers)),
        "commenters_unique_count": len(commenters),
        "commenters_unique": ",".join(sorted(commenters)),
        "first_comment_at": first_comment_at or "",
        "first_review_event_at": first_review_event_at or "",
        "first_approval_at": first_approval_at or "",
        "time_to_first_comment_minutes": time_to_first_comment_minutes if time_to_first_comment_minutes is not None else "",
        "time_to_first_review_event_minutes": time_to_first_review_event_minutes if time_to_first_review_event_minutes is not None else "",
        "time_to_first_approval_minutes": time_to_first_approval_minutes if time_to_first_approval_minutes is not None else "",
        "commits_total": commits_total,
        "last_commit_at": last_commit_at,
        "commits_after_first_comment": commits_after_first_comment if commits_after_first_comment is not None else "",
        "commits_after_first_approval": commits_after_first_approval if commits_after_first_approval is not None else "",
        "merge_lag_minutes": merge_lag_minutes if merge_lag_minutes is not None else "",
    }