"""能力目录结构的静态回归，不连接 CAD。"""

import json

import pytest

from scripts.capabilities import capability_index
from scripts.validate_skill import ROOT, check_capability_manifest


def test_native_round_sweeps_is_discoverable_without_promoting_qualification():
    payload = json.loads((ROOT / "capabilities.yaml").read_text(encoding="utf-8"))
    check_capability_manifest(payload)
    index = capability_index(payload)
    assert index["native_round_sweeps"]["level"] == "pilot"
    assert index["native_round_sweeps"]["allowed_modes"] == ["interactive", "reviewed"]
    assert index["native_frame_cut"]["allowed_modes"] == ["interactive", "reviewed"]


@pytest.mark.parametrize(
    "modes",
    [
        ["interactive", {"id": "nested", "allowed_modes": ["reviewed"]}],
        "interactive",
        None,
        ["interactive", 1],
        ["interactive", ""],
    ],
)
def test_rejects_non_string_or_malformed_allowed_modes(modes):
    with pytest.raises(ValueError, match="allowed_modes"):
        check_capability_manifest({"capabilities": [{"id": "part", "allowed_modes": modes}]})


def test_rejects_duplicate_ids_instead_of_silently_overwriting_index():
    item = {"id": "part", "allowed_modes": ["interactive"]}
    with pytest.raises(ValueError, match="ID 重复"):
        check_capability_manifest({"capabilities": [item, dict(item)]})


@pytest.mark.parametrize("identifier", [None, True, "", " "])
def test_rejects_missing_or_non_string_ids(identifier):
    with pytest.raises(ValueError, match="ID 必须"):
        check_capability_manifest(
            {"capabilities": [{"id": identifier, "allowed_modes": ["reviewed"]}]}
        )


@pytest.mark.parametrize("payload", [None, {}, {"capabilities": {}}, {"capabilities": [1]}])
def test_rejects_invalid_manifest_structure(payload):
    with pytest.raises(ValueError):
        check_capability_manifest(payload)
