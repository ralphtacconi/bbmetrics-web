from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional

import httpx


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    s = v.strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


@dataclass
class BitbucketDCClient:
    base_url: str
    username: str
    password: str
    timeout_s: float = 30.0
    max_retries: int = 6

    def _client(self, *, accept: str) -> httpx.Client:
        verify_ssl = _env_bool("BITBUCKET_VERIFY_SSL", True)
        return httpx.Client(
            base_url=self.base_url,
            auth=(self.username, self.password),
            timeout=self.timeout_s,
            headers={"Accept": accept},
            verify=verify_ssl,
        )

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        last_exc: Optional[Exception] = None
        last_status: Optional[int] = None
        last_body: str = ""

        with self._client(accept="application/json") as c:
            for attempt in range(self.max_retries):
                try:
                    r = c.get(path, params=params)
                    last_status = r.status_code
                    try:
                        last_body = (r.text or "")[:1000]
                    except Exception:
                        last_body = ""

                    if r.status_code == 404:
                        r.raise_for_status()

                    if r.status_code == 429:
                        retry_after = r.headers.get("Retry-After")
                        sleep_s = float(retry_after) if retry_after else min(2**attempt, 60)
                        time.sleep(sleep_s)
                        continue

                    if 500 <= r.status_code <= 599:
                        time.sleep(min(2**attempt, 30))
                        continue

                    r.raise_for_status()
                    return r.json()

                except Exception as e:
                    last_exc = e
                    time.sleep(min(2**attempt, 30))

        raise RuntimeError(
            f"GET failed for {path} params={params} last_status={last_status} "
            f"verify_ssl={_env_bool('BITBUCKET_VERIFY_SSL', True)} last_body={last_body!r}"
        ) from last_exc

    def get_text(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        accept: str = "text/plain",
    ) -> str:
        params = params or {}
        last_exc: Optional[Exception] = None
        last_status: Optional[int] = None
        last_body: str = ""

        with self._client(accept=accept) as c:
            for attempt in range(self.max_retries):
                try:
                    r = c.get(path, params=params)
                    last_status = r.status_code
                    try:
                        last_body = (r.text or "")[:300]
                    except Exception:
                        last_body = ""

                    if r.status_code == 404:
                        r.raise_for_status()

                    if r.status_code == 429:
                        retry_after = r.headers.get("Retry-After")
                        sleep_s = float(retry_after) if retry_after else min(2**attempt, 60)
                        time.sleep(sleep_s)
                        continue

                    if 500 <= r.status_code <= 599:
                        time.sleep(min(2**attempt, 30))
                        continue

                    r.raise_for_status()
                    return r.text or ""

                except Exception as e:
                    last_exc = e
                    time.sleep(min(2**attempt, 30))

        raise RuntimeError(
            f"GET(text) failed for {path} params={params} last_status={last_status} "
            f"verify_ssl={_env_bool('BITBUCKET_VERIFY_SSL', True)} last_body={last_body!r}"
        ) from last_exc

    def paginate(self, path: str, params: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        params = dict(params or {})
        if "limit" not in params:
            params["limit"] = 100

        start = params.get("start", 0)
        while True:
            params["start"] = start
            data = self.get_json(path, params=params)
            for v in data.get("values", []):
                yield v
            if data.get("isLastPage", True):
                break
            start = data.get("nextPageStart")
            if start is None:
                break