"""
Tests for cosmos.py module (without real Azure connection).
"""
from __future__ import annotations

import os

import pytest

# Ensure no real Cosmos DB connection is attempted
os.environ.pop("COSMOS_ENDPOINT", None)
os.environ.pop("COSMOS_KEY", None)

from app.cosmos import cosmos_available, get_scan, list_scans, upsert_scan


def test_cosmos_not_available():
    assert cosmos_available() is False


def test_upsert_scan_no_cosmos():
    # Should not raise even when Cosmos DB is not configured
    upsert_scan({"scan_id": "test-123", "status": "done"})


def test_get_scan_no_cosmos():
    result = get_scan("test-123")
    assert result is None


def test_list_scans_no_cosmos():
    result = list_scans()
    assert result == []
