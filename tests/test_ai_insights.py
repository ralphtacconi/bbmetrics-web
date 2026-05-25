"""
Tests for ai_insights module (no external calls).
"""
from __future__ import annotations

import os

import pytest

from app.ai_insights import _safe_avg, _safe_float, _safe_int, generate_insights


def test_safe_float_normal():
    assert _safe_float("3.14") == pytest.approx(3.14)


def test_safe_float_na():
    assert _safe_float("NA") == 0.0


def test_safe_float_none():
    assert _safe_float(None) == 0.0


def test_safe_int_empty():
    assert _safe_int("") == 0


def test_safe_avg_empty():
    assert _safe_avg([]) is None


def test_safe_avg_zeros():
    assert _safe_avg([0.0, 0.0]) is None


def test_safe_avg_values():
    result = _safe_avg([60.0, 120.0])
    assert result == pytest.approx(90.0)


def test_generate_insights_no_config():
    """Without OpenAI config, should return None (graceful degradation)."""
    os.environ.pop("AZURE_OPENAI_ENDPOINT", None)
    os.environ.pop("AZURE_OPENAI_KEY", None)
    result = generate_insights({"prs": [], "users_summary": []})
    assert result is None
