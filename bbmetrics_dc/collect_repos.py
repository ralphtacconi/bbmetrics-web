from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .client import BitbucketDCClient


@dataclass
class RepoRef:
    project_key: str
    repo_slug: str
    name: str


def list_repos_in_project(client: BitbucketDCClient, project_key: str) -> List[RepoRef]:
    """
    GET /rest/api/1.0/projects/{projectKey}/repos
    """
    out: List[RepoRef] = []
    for r in client.paginate(f"/rest/api/1.0/projects/{project_key}/repos", params={"limit": 100}):
        out.append(
            RepoRef(
                project_key=project_key,
                repo_slug=r["slug"],
                name=r.get("name") or r["slug"],
            )
        )
    return out