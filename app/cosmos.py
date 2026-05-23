from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

_cosmos_client = None
_container = None

COSMOS_DATABASE = "bbmetrics"
COSMOS_CONTAINER = "scans"


def _get_container():
    global _cosmos_client, _container
    if _container is not None:
        return _container

    endpoint = os.getenv("COSMOS_ENDPOINT", "")
    key = os.getenv("COSMOS_KEY", "")

    if not endpoint or not key:
        return None

    try:
        from azure.cosmos import CosmosClient, PartitionKey  # type: ignore

        _cosmos_client = CosmosClient(endpoint, credential=key)
        db = _cosmos_client.create_database_if_not_exists(id=COSMOS_DATABASE)
        _container = db.create_container_if_not_exists(
            id=COSMOS_CONTAINER,
            partition_key=PartitionKey(path="/scan_id"),
            offer_throughput=400,
        )
    except Exception:
        _container = None

    return _container


def upsert_scan(doc: Dict[str, Any]) -> None:
    container = _get_container()
    if container is None:
        return
    try:
        container.upsert_item(body=doc)
    except Exception:
        pass


def get_scan(scan_id: str) -> Optional[Dict[str, Any]]:
    container = _get_container()
    if container is None:
        return None
    try:
        return container.read_item(item=scan_id, partition_key=scan_id)
    except Exception:
        return None


def list_scans(limit: int = 20) -> List[Dict[str, Any]]:
    container = _get_container()
    if container is None:
        return []
    try:
        query = (
            "SELECT c.scan_id, c.status, c.created_at, c.params "
            "FROM c ORDER BY c._ts DESC OFFSET 0 LIMIT @limit"
        )
        items = list(
            container.query_items(
                query=query,
                parameters=[{"name": "@limit", "value": limit}],
                enable_cross_partition_query=True,
            )
        )
        return items
    except Exception:
        return []


def cosmos_available() -> bool:
    return _get_container() is not None
