from __future__ import annotations

from dataclasses import dataclass
from typing import List

from bbmetrics_dc.client import BitbucketDCClient


@dataclass(frozen=True)
class ProjectChoice:
    key: str
    name: str


@dataclass(frozen=True)
class RepoChoice:
    slug: str
    name: str


def list_projects(client: BitbucketDCClient) -> List[ProjectChoice]:
    out: List[ProjectChoice] = []
    for p in client.paginate("/rest/api/1.0/projects", params={"limit": 100}):
        key = (p.get("key") or "").strip()
        name = (p.get("name") or "").strip()
        if key:
            out.append(ProjectChoice(key=key, name=name or key))
    # ordena por key para ficar previsível
    out.sort(key=lambda x: x.key.lower())
    return out


def list_repos_in_project(client: BitbucketDCClient, project_key: str) -> List[RepoChoice]:
    out: List[RepoChoice] = []
    path = f"/rest/api/1.0/projects/{project_key}/repos"
    for r in client.paginate(path, params={"limit": 100}):
        slug = (r.get("slug") or "").strip()
        name = (r.get("name") or "").strip()
        if slug:
            out.append(RepoChoice(slug=slug, name=name or slug))
    out.sort(key=lambda x: x.slug.lower())
    return out