from __future__ import annotations

from datetime import datetime, timezone
from dateutil import parser


def parse_time(s: str) -> datetime:
    """
    Bitbucket DC pode devolver ISO ou timestamp dependendo do endpoint.
    Para PRs costuma ser ISO em "createdDate"/"updatedDate" (ms) ou ISO em alguns endpoints.
    Aqui suportamos ISO; para ms a gente trata no collector.
    """
    dt = parser.isoparse(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def from_epoch_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)