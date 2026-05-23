from __future__ import annotations

from typing import Dict, Iterator, Optional

from .client import BitbucketDCClient


def list_pr_commits(
    client: BitbucketDCClient,
    project_key: str,
    repo_slug: str,
    pr_id: int,
    *,
    page_limit: int = 100,
    max_commits: Optional[int] = None,
) -> Iterator[Dict]:
    """
    GET /rest/api/1.0/projects/{projectKey}/repos/{repoSlug}/pull-requests/{prId}/commits
    Returns commit objects (varies by BB version), often with fields:
      - id (commit hash)
      - author / authorTimestamp
      - committer / committerTimestamp
      - message
    """
    scanned = 0
    path = f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests/{pr_id}/commits"
    for c in client.paginate(path, params={"limit": int(page_limit)}):
        scanned += 1
        if max_commits is not None and scanned > max_commits:
            break
        yield c