from __future__ import annotations

from typing import Dict, Optional

from .client import BitbucketDCClient
from .timeutil import from_epoch_ms, utc_now


def list_pull_requests(client: BitbucketDCClient, project_key: str, repo_slug: str, state: str):
    """
    GET /rest/api/1.0/projects/{projectKey}/repos/{repoSlug}/pull-requests?state=OPEN|MERGED|DECLINED
    """
    for pr in client.paginate(
        f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests",
        params={"state": state, "limit": 50},
    ):
        yield pr


def list_pr_comments(client: BitbucketDCClient, project_key: str, repo_slug: str, pr_id: int):
    """
    Bitbucket DC: comentários costumam vir em "activities":
    GET /rest/api/1.0/projects/{projectKey}/repos/{repoSlug}/pull-requests/{id}/activities
    Filtramos activities do tipo COMMENT.
    """
    for a in client.paginate(
        f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests/{pr_id}/activities",
        params={"limit": 100},
    ):
        yield a


def count_comments_from_activities(activities) -> Dict[str, int]:
    """
    Conta:
    - total
    - inline (commentAnchor presente)
    - general
    """
    total = inline = general = 0
    for a in activities:
        if a.get("action") != "COMMENTED":
            continue
        c = a.get("comment") or {}
        total += 1
        if c.get("anchor"):
            inline += 1
        else:
            general += 1
    return {"total": total, "inline": inline, "general": general}


def estimate_time_open_seconds(pr: Dict) -> tuple[str, str, Optional[str], int]:
    """
    Bitbucket DC PR payload geralmente tem:
    - createdDate (epoch ms)
    - updatedDate (epoch ms)
    - closedDate (epoch ms) às vezes
    - state
    """
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
            # fallback: updatedDate
            end = from_epoch_ms(int(updated_ms)) if updated_ms is not None else utc_now()
            closed_iso = end.isoformat()

    updated_iso = from_epoch_ms(int(updated_ms)).isoformat() if updated_ms is not None else ""
    seconds = int((end - created_dt).total_seconds())
    return created_iso, updated_iso, closed_iso, seconds