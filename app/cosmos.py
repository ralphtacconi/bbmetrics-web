from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from azure.cosmos import CosmosClient, PartitionKey
except Exception:  # pragma: no cover
    CosmosClient = None
    PartitionKey = None


class CosmosStore:
    def __init__(self) -> None:
        self.endpoint = os.getenv('COSMOS_ENDPOINT', '').strip()
        self.key = os.getenv('COSMOS_KEY', '').strip()
        self.database_name = os.getenv('COSMOS_DATABASE', 'bbmetrics')
        self.container_name = os.getenv('COSMOS_CONTAINER', 'scans')
        self._memory: Dict[str, Dict[str, Any]] = {}
        self._container = None

        if self.endpoint and self.key and CosmosClient and PartitionKey:
            client = CosmosClient(self.endpoint, credential=self.key)
            db = client.create_database_if_not_exists(id=self.database_name)
            self._container = db.create_container_if_not_exists(
                id=self.container_name,
                partition_key=PartitionKey(path='/scan_id'),
            )

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def upsert_scan(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        scan_id = str(doc['scan_id'])
        if 'created_at' not in doc:
            doc['created_at'] = self.now_iso()
        if self._container is not None:
            self._container.upsert_item(doc)
            return doc
        self._memory[scan_id] = doc
        return doc

    def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        if self._container is not None:
            query = 'SELECT * FROM c WHERE c.scan_id = @scan_id'
            params = [{'name': '@scan_id', 'value': scan_id}]
            items = list(self._container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
            return items[0] if items else None
        return self._memory.get(scan_id)

    def list_recent_scans(self, limit: int = 20) -> List[Dict[str, Any]]:
        if self._container is not None:
            query = f'SELECT TOP {int(limit)} * FROM c ORDER BY c.created_at DESC'
            return list(self._container.query_items(query=query, enable_cross_partition_query=True))
        scans = list(self._memory.values())
        scans.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return scans[:limit]
