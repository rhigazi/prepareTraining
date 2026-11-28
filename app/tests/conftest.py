"""Gemeinsame Fixtures für die App-Tests.

Jeder Test arbeitet auf einer Kopie von ``fixtures/bundle_min`` unter ``tmp_path``;
das echte Bundle wird von pytest nie beschrieben.
"""

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture()
def bundle(tmp_path, monkeypatch):
    """Kopie des Mini-Bundles als ``BUNDLE_ROOT`` (Rückgabe: Wurzelpfad)."""
    import okf_bundle

    ziel = tmp_path / "bundle"
    shutil.copytree(FIXTURES / "bundle_min", ziel)
    monkeypatch.setattr(okf_bundle, "BUNDLE_ROOT", str(ziel))
    return ziel
