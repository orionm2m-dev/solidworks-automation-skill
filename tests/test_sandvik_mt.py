"""Focused contract and failure tests for the experimental line-only MT writer."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "sw_cam_sandvik_mt.py"
spec = importlib.util.spec_from_file_location("sandvik_mt_under_test", MODULE)
mt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mt)


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def case(tmp_path, monkeypatch):
    cad = tmp_path / "factory.stp"
    cad.write_bytes(b"fixture CAD identity")
    ref = tmp_path / "observed.mt"
    ref.write_text("Version Clouds\n# observed grammar\n" +
                   "\n".join(f"line {i:.6f} 0.000000 {i+1:.6f} 1.000000"
                             for i in range(8)) + "\n", encoding="ascii")
    monkeypatch.setattr(mt, "CAD_SHA256", digest(cad))
    monkeypatch.setattr(mt, "REFERENCE_MT_SHA256", digest(ref))
    analysis = tmp_path / "analysis.json"
    analysis.write_text(json.dumps({
        "source_MT": {"sha256": digest(ref)},
        "numeric_mapping": {"native_per_MT_unit": 1.0},
        "partition": {"GetToolProfile_contains_entire_MT": True},
        "units": {"native_profile_physical_mm_proven": False},
        "physical_configuration": {"candidate_protrusion_mm": 25},
    }), encoding="utf-8")
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({
        "tool": mt.PART,
        "factory_STEP": {"sha256": digest(cad)},
        "installed_MT_example": {"sha256": digest(ref)},
        "units": "mm",
        "closed_half_section_for_revolved_sketch_rz": [
            [0, 0], [3.8, 0], [4, .2], [4, 19], [4, 62.4], [3.4, 63],
            [0, 63], [0, 0]],
        "cutting_part": {"outside_profile_rz": [[0, 0], [3.8, 0], [4, .2], [4, 19]]},
        "noncutting_part": {"outside_profile_rz": [[4, 19], [4, 62.4], [3.4, 63]]},
        "expected_parameters": {
            "ICWTool.CutDiameter": 8, "ICWMillUDTool.CutLength": 19,
            "ICWMillUDTool.OverallLength": 63, "ICWMillUDTool.ShankDia": 8,
            "ICWMillUDTool.Flutes": 4, "ICWMillUDTool.TipOffset": 0,
            "ICWMillUDTool.TipLength": 0,
        },
    }), encoding="utf-8")
    def load():
        args = []
        for p in (contract, cad, ref, analysis):
            args.extend((str(p), digest(p)))
        return mt.load_candidate_contract(*args)
    return dict(load=load, contract=contract, cad=cad, ref=ref,
                analysis=analysis, root=tmp_path)


def rewrite_json(path, change):
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def native_profile(edges):
    curves = []
    for i, (a, b) in enumerate(edges):
        curves.append(dict(index=i, read_complete=True, curve_type=0,
                           start_native=[a[0], 0., a[1]],
                           end_native=[b[0], 0., b[1]]))
    return dict(status="observed", declared_chain_count=1, chains=[
        dict(index=0, read_complete=True, declared_curve_count=len(curves), curves=curves)])


def profiles():
    points = [[0, 0], [3.8, 0], [4, .2], [4, 19], [4, 62.4], [3.4, 63]]
    return dict(tool=native_profile(list(zip(points, points[1:]))),
                shank=native_profile([([4, 19], [4, 62.4]), ([4, 62.4], [3.4, 63])]))


def test_exact_golden_payload_is_open_five_line_envelope(case):
    candidate = case["load"]()
    result = mt.render_candidate_mt(candidate).decode("ascii").splitlines()
    assert result[0] == "Version Clouds"
    records = [line for line in result[1:] if line and not line.startswith("#")]
    assert records == [
        "line 0.000000 0.000000 3.800000 0.000000",
        "line 3.800000 0.000000 4.000000 0.200000",
        "line 4.000000 0.200000 4.000000 19.000000",
        "line 4.000000 19.000000 4.000000 62.400000",
        "line 4.000000 62.400000 3.400000 63.000000",
    ]
    assert not any("arc" in line or "unit" in line for line in records)
    assert candidate["units_verified"] is False
    assert candidate["production_qualified"] is False
    assert candidate["protrusion"]["verified"] is False


def test_exclusive_file_matches_content_and_cannot_be_replayed(case):
    candidate = case["load"]()
    output = case["root"] / "candidate.mt"
    report = mt.write_candidate_mt(candidate, str(output), acknowledge_experimental=True)
    original = output.read_bytes()
    assert report["sha256"] == hashlib.sha256(original).hexdigest()
    assert report["exclusive_create"] is True
    assert report["content_verified"] is True
    assert all(report[k] is False for k in (
        "native_loaded", "units_verified", "cutting_partition_verified",
        "production_qualified", "operation_assignment_attempted"))
    with pytest.raises(ValueError):
        mt.write_candidate_mt(candidate, str(output), acknowledge_experimental=True)
    assert output.read_bytes() == original


@pytest.mark.parametrize("ack", [False, 1, "true", None])
def test_acknowledgement_must_be_literal_true(case, ack):
    p = case["root"] / "candidate.mt"
    with pytest.raises(ValueError):
        mt.write_candidate_mt(case["load"](), str(p), acknowledge_experimental=ack)
    assert not p.exists()


@pytest.mark.parametrize("name", ["candidate.txt", "missing/candidate.mt"])
def test_invalid_output_is_rejected_before_write(case, name):
    p = case["root"] / name
    with pytest.raises(ValueError):
        mt.write_candidate_mt(case["load"](), str(p), acknowledge_experimental=True)
    assert not p.exists()


def test_input_changed_after_contract_is_rejected_before_write(case):
    candidate = case["load"]()
    case["cad"].write_bytes(b"changed source")
    p = case["root"] / "candidate.mt"
    with pytest.raises(ValueError, match="Pinned input changed"):
        mt.write_candidate_mt(candidate, str(p), acknowledge_experimental=True)
    assert not p.exists()


def test_altered_candidate_cannot_bypass_revalidation(case):
    candidate = case["load"]()
    candidate["units_verified"] = True
    with pytest.raises(ValueError, match="altered"):
        mt.render_candidate_mt(candidate)


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), 1.1, "1"])
def test_numeric_mapping_requires_finite_exact_number(case, value):
    rewrite_json(case["analysis"], lambda d: d["numeric_mapping"].update(native_per_MT_unit=value))
    with pytest.raises(ValueError):
        case["load"]()


@pytest.mark.parametrize("path,value", [
    ("tool", "different part"),
    ("units", "inch"),
])
def test_other_part_or_nominal_units_rejected(case, path, value):
    rewrite_json(case["contract"], lambda d: d.update({path: value}))
    with pytest.raises(ValueError):
        case["load"]()


@pytest.mark.parametrize("value", [True, 7.9, float("nan"), "8"])
def test_scalar_spec_cannot_be_changed_or_coerced(case, value):
    rewrite_json(case["contract"], lambda d: d["expected_parameters"].update({"ICWTool.CutDiameter": value}))
    with pytest.raises(ValueError):
        case["load"]()


def test_missing_chamfer_point_rejected(case):
    rewrite_json(case["contract"], lambda d: d["cutting_part"]["outside_profile_rz"].pop(1))
    with pytest.raises(ValueError):
        case["load"]()


def test_factory_identity_pin_mismatch_rejected(case):
    candidate_args = []
    for p in (case["contract"], case["cad"], case["ref"], case["analysis"]):
        candidate_args.extend((str(p), digest(p)))
    candidate_args[3] = "0" * 64
    with pytest.raises(ValueError):
        mt.load_candidate_contract(*candidate_args)


def test_full_numeric_profile_matches_but_is_not_partition_or_unit_proof(case):
    report = mt.validate_native_profiles(case["load"](), profiles())
    assert report["source_segments_covered"] == 5
    assert report["shank_nonzero_outer_segments"] == 2
    assert report["raw_numeric_profile_match"] is True
    assert all(report[k] is False for k in (
        "units_verified", "cutting_partition_verified",
        "physical_tool_qualified", "production_qualified"))


def test_reversed_native_segments_and_documented_rear_cap_are_accepted(case):
    p = profiles()
    curves = p["tool"]["chains"][0]["curves"]
    for curve in curves:
        curve["start_native"], curve["end_native"] = curve["end_native"], curve["start_native"]
    curves.append(dict(index=5, read_complete=True, curve_type=0,
                       start_native=[3.4, 0., 63], end_native=[0., 0., 63]))
    p["tool"]["chains"][0]["declared_curve_count"] = 6
    report = mt.validate_native_profiles(case["load"](), p)
    assert report["extra_native_segments"][0]["kind"] == "radial_rear_cap"


@pytest.mark.parametrize("change", [
    lambda p: p["tool"]["chains"][0]["curves"][0].update(curve_type=1),
    lambda p: p["tool"]["chains"][0]["curves"][0].update(read_complete=False),
    lambda p: p["tool"]["chains"][0]["curves"][0]["start_native"].__setitem__(1, .1),
    lambda p: p["tool"]["chains"][0]["curves"][2]["end_native"].__setitem__(0, 4.1),
    lambda p: p["tool"]["chains"][0]["curves"][2]["end_native"].__setitem__(2, float("nan")),
    lambda p: p["tool"]["chains"][0].update(declared_curve_count=6),
    lambda p: p["tool"].update(declared_chain_count=True),
])
def test_incomplete_curved_or_outside_profile_is_rejected(case, change):
    p = profiles()
    change(p)
    with pytest.raises(ValueError):
        mt.validate_native_profiles(case["load"](), p)


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "axis_closure"])
def test_outer_profile_must_cover_exactly_once_without_extra_axis_edge(case, mutation):
    p = profiles()
    curves = p["tool"]["chains"][0]["curves"]
    if mutation == "duplicate":
        c = deepcopy(curves[0]); c["index"] = 5; curves.append(c)
    elif mutation == "missing":
        curves.pop()
    else:
        curves.append(dict(index=5, read_complete=True, curve_type=0,
                           start_native=[0., 0., 63], end_native=[0., 0., 0.]))
    p["tool"]["chains"][0]["declared_curve_count"] = len(curves)
    with pytest.raises(ValueError):
        mt.validate_native_profiles(case["load"](), p)
