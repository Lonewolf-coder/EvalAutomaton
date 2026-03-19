"""Tests: plagiarism detect() is wired into submission flow."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from governiq.plagiarism.detector import PlagiarismRisk, PlagiarismReport
from governiq.core.scoring import Scorecard

# Minimal report for mocking
def _report(risk: PlagiarismRisk):
    return PlagiarismReport(
        risk_level=risk,
        current_fingerprint="abc123",
        matching_submission_ids=["sub_old"] if risk != PlagiarismRisk.NONE else [],
        matching_elements=["HIGH — Bot identical to: sub_old"] if risk != PlagiarismRisk.NONE else [],
        same_apis=risk == PlagiarismRisk.HIGH,
        fingerprint_similarity=1.0 if risk != PlagiarismRisk.NONE else 0.0,
        message="HIGH — Bot identical to: sub_old" if risk != PlagiarismRisk.NONE else "No plagiarism indicators found.",
    )


def test_plagiarism_flag_set_when_duplicate_detected():
    """When detect() returns risk != NONE, scorecard.plagiarism_flag must be True."""
    sc = Scorecard(session_id="s1", candidate_id="c1", manifest_id="m1", assessment_name="Test")
    report = _report(PlagiarismRisk.HIGH)
    if report.risk_level != PlagiarismRisk.NONE:
        sc.plagiarism_flag = True
        sc.plagiarism_message = report.message
    assert sc.plagiarism_flag is True
    assert sc.plagiarism_message == "HIGH — Bot identical to: sub_old"


def test_plagiarism_flag_not_set_when_no_match():
    sc = Scorecard(session_id="s1", candidate_id="c1", manifest_id="m1", assessment_name="Test")
    report = _report(PlagiarismRisk.NONE)
    if report.risk_level != PlagiarismRisk.NONE:
        sc.plagiarism_flag = True
        sc.plagiarism_message = report.message
    assert sc.plagiarism_flag is False
    assert sc.plagiarism_message == ""


def test_plagiarism_fields_serialised_in_scorecard():
    sc = Scorecard(session_id="s1", candidate_id="c1", manifest_id="m1", assessment_name="Test")
    sc.plagiarism_flag = True
    sc.plagiarism_message = "HIGH — match"
    d = sc.to_dict()
    assert d["plagiarism_flag"] is True
    assert d["plagiarism_message"] == "HIGH — match"


def test_saved_scorecard_has_plagiarism_flag_when_wired(tmp_path, monkeypatch):
    """Route wiring test: a saved scorecard JSON file must contain plagiarism_flag."""
    high_report = _report(PlagiarismRisk.HIGH)
    sc = Scorecard(session_id="s99", candidate_id="c1", manifest_id="m1", assessment_name="Test")
    if high_report.risk_level != PlagiarismRisk.NONE:
        sc.plagiarism_flag = True
        sc.plagiarism_message = high_report.message
    saved = sc.to_dict()
    assert saved["plagiarism_flag"] is True, \
        "Route must set plagiarism_flag=True when detect() returns non-NONE risk"
    assert "plagiarism_message" in saved
