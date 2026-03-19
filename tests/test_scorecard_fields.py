"""Tests: Scorecard plagiarism fields are serialised correctly."""
import pytest
from governiq.core.scoring import Scorecard

def test_scorecard_has_plagiarism_fields():
    sc = Scorecard(session_id="s1", candidate_id="c1", manifest_id="m1", assessment_name="Test")
    assert hasattr(sc, "plagiarism_flag")
    assert hasattr(sc, "plagiarism_message")
    assert sc.plagiarism_flag is False
    assert sc.plagiarism_message == ""

def test_scorecard_to_dict_includes_plagiarism():
    sc = Scorecard(session_id="s1", candidate_id="c1", manifest_id="m1", assessment_name="Test")
    sc.plagiarism_flag = True
    sc.plagiarism_message = "HIGH — Bot identical to sub_abc"
    d = sc.to_dict()
    assert d["plagiarism_flag"] is True
    assert d["plagiarism_message"] == "HIGH — Bot identical to sub_abc"

def test_compute_weighted_score_removed():
    sc = Scorecard(session_id="s1", candidate_id="c1", manifest_id="m1", assessment_name="Test")
    assert not hasattr(sc, "compute_weighted_score"), \
        "compute_weighted_score should have been deleted (dead code with wrong weights)"
