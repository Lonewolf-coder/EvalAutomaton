"""Tests for admin compare diff logic."""
import pytest
from fastapi.testclient import TestClient
from governiq.main import app

client = TestClient(app)


def _make_scorecard(session_id, task_scores):
    return {
        "session_id": session_id,
        "candidate_id": "test",
        "assessment_name": "Test",
        "overall_score": 0.75,
        "task_scores": task_scores,
    }


def test_compare_no_params_returns_200():
    resp = client.get("/admin/compare")
    assert resp.status_code == 200


def test_compare_diff_logic():
    """Test that task delta computation works correctly."""
    from governiq.admin.routes import _compute_task_diff

    left = _make_scorecard("s1", [
        {"task_id": "t1", "task_name": "Create", "combined_score": 0.9},
        {"task_id": "t2", "task_name": "Delete", "combined_score": 0.5},
    ])
    right = _make_scorecard("s2", [
        {"task_id": "t1", "task_name": "Create", "combined_score": 0.6},
        {"task_id": "t2", "task_name": "Delete", "combined_score": 0.5},
    ])
    diff = _compute_task_diff(left, right)
    assert len(diff) == 2
    t1 = next(d for d in diff if d["task_id"] == "t1")
    assert t1["significant"] is True
    assert abs(t1["delta"] - 0.30) < 0.01
    t2 = next(d for d in diff if d["task_id"] == "t2")
    assert t2["significant"] is False


def test_compare_diff_missing_task_on_right():
    """Tasks present in left but not in right should be handled gracefully."""
    from governiq.admin.routes import _compute_task_diff
    left = _make_scorecard("s1", [{"task_id": "t1", "task_name": "Create", "combined_score": 0.9}])
    right = _make_scorecard("s2", [])
    diff = _compute_task_diff(left, right)
    assert len(diff) == 1
    assert diff[0]["right_score"] is None
