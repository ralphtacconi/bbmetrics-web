"""
Tests for the BBMetrics FastAPI web application.
Uses httpx AsyncClient with TestClient for sync testing.
Cosmos DB and Azure OpenAI are mocked.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "cosmos" in data


def test_dashboard_empty():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "BBMetrics" in resp.text


def test_scan_form():
    resp = client.get("/scan")
    assert resp.status_code == 200
    assert "New Scan" in resp.text
    assert "bitbucket_base_url" in resp.text


def test_scan_not_found():
    resp = client.get("/results/nonexistent-id-1234")
    assert resp.status_code == 404


def test_scan_status_not_found():
    resp = client.get("/api/scan/nonexistent-id-1234/status")
    assert resp.status_code == 404


def test_post_scan_missing_repos():
    resp = client.post(
        "/scan",
        data={
            "bitbucket_base_url": "https://example.com",
            "bitbucket_username": "user",
            "bitbucket_password": "pass",
            "project_key": "TEST",
            "repos": "",
            "pr_start": "01-01-2026",
            "pr_end": "03-31-2026",
        },
    )
    assert resp.status_code == 400


def test_post_scan_creates_pending(monkeypatch):
    """POST /scan should create a scan in pending status and return a scan_id."""

    # Prevent the background task from actually running
    from app import main as app_main

    def fake_background_task(*args, **kwargs):
        pass

    monkeypatch.setattr(app_main, "_run_scan_background", fake_background_task)

    resp = client.post(
        "/scan",
        data={
            "bitbucket_base_url": "https://example.com",
            "bitbucket_username": "user",
            "bitbucket_password": "pass",
            "project_key": "TEST",
            "repos": "repo1,repo2",
            "pr_start": "01-01-2026",
            "pr_end": "03-31-2026",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "scan_id" in data
    scan_id = data["scan_id"]

    # Status should be pending
    status_resp = client.get(f"/api/scan/{scan_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "pending"

    # Results page should load
    results_resp = client.get(f"/results/{scan_id}")
    assert results_resp.status_code == 200
    assert scan_id in results_resp.text
