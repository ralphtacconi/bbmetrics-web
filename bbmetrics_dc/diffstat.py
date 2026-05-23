from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from .client import BitbucketDCClient


def _sum_diffstat_values(values: Iterable[Dict]) -> Tuple[int, int, int]:
    """
    Bitbucket DC diffstat values usually look like:
      { "linesAdded": 10, "linesRemoved": 3, ... }
    We sum across files.
    """
    files_changed = 0
    lines_added = 0
    lines_removed = 0

    for v in values:
        files_changed += 1
        try:
            lines_added += int(v.get("linesAdded") or 0)
        except Exception:
            pass
        try:
            lines_removed += int(v.get("linesRemoved") or 0)
        except Exception:
            pass

    return files_changed, lines_added, lines_removed


def get_pr_diffstat_totals(
    client: BitbucketDCClient,
    project_key: str,
    repo_slug: str,
    pr_id: int,
) -> Optional[Dict[str, int]]:
    """
    Preferred: PR-level diffstat (total), paginated.
    Endpoint (Bitbucket DC):
      GET /rest/api/1.0/projects/{projectKey}/repos/{repoSlug}/pull-requests/{prId}/diffstat

    Returns:
      { files_changed, lines_added, lines_removed } or None if endpoint not supported.
    """
    path = f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests/{pr_id}/diffstat"
    try:
        # Some Bitbucket versions paginate diffstat with values/isLastPage.
        # We'll use paginate to be safe.
        values = list(client.paginate(path, params={"limit": 100}))
        files_changed, lines_added, lines_removed = _sum_diffstat_values(values)
        return {
            "files_changed": files_changed,
            "lines_added": lines_added,
            "lines_removed": lines_removed,
        }
    except Exception:
        return None