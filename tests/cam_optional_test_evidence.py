"""Strict opt-in external regression evidence; public synthetic tests stay separate."""
import os
from pathlib import Path
import pytest


def evidence_root(name):
    value = os.environ.get(name)
    if value is None:
        pytest.skip(name + " is not configured; actual evidence is optional")
    root = Path(value)
    if not value.strip() or not root.is_absolute() or not root.is_dir():
        raise ValueError(name + " must be an existing absolute evidence directory")
    return root


def required_evidence(root, relative):
    path = root / relative
    if not path.is_file():
        raise ValueError("Explicit evidence directory lacks required file: " + relative)
    return path
