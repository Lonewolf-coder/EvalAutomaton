"""Tests: data directories are created on startup."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

def test_data_dirs_created_on_startup(tmp_path, monkeypatch):
    """App startup must create required data directories."""
    monkeypatch.chdir(tmp_path)
    import importlib
    import governiq.main as main_mod
    importlib.invalidate_caches()
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as client:
        for d in ["data", "data/results", "data/runtime_contexts",
                  "data/manifests", "data/fingerprints"]:
            assert (tmp_path / d).exists(), f"Missing directory: {d}"
