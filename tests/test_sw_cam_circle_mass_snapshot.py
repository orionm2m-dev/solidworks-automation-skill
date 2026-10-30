"""Immutable creator anchors tolerated mass noise, never actual geometry changes."""
from pathlib import Path
from copy import deepcopy
import json
import pytest
from scripts import sw_cam_circle_lifecycle_evidence as evidence
from scripts.sw_cam_turn_tool import _digest
from test_sw_cam_circular_mill_lifecycle import saved,case

@pytest.fixture
def recorded():
    return json.loads((Path(__file__).parent/'fixtures/circle_mass_roundoff.json').read_text())

def test_synthetic_roundoff_readbacks_have_identical_prepared_reference(recorded):
    diag1={};diag2={};anchor=recorded["reference_solids"]
    first=evidence.canonical_circle_solids(recorded["prepare_solids"],anchor,diag1)
    second=evidence.canonical_circle_solids(recorded["apply_solids"],anchor,diag2)
    assert first==second==anchor and _digest(first)==_digest(second)
    assert diag1["circle_solid_observation"]["observed"]!=diag2["circle_solid_observation"]["observed"]
    assert diag1["circle_solid_observation"]["comparison_verified"]
    first[0]["mass_raw"][0]=99
    assert anchor[0]["mass_raw"][0]!=99

@pytest.mark.parametrize("index",[0,1,2,3,4,5,6,7,8,9,10,11])
def test_changed_center_volume_and_inertia_remain_rejected(recorded,index):
    current=deepcopy(recorded["reference_solids"]);current[0]["mass_raw"][index]*=1.000000001
    diag={}
    with pytest.raises(ValueError):evidence.canonical_circle_solids(current,recorded["reference_solids"],diag)
    assert not diag["circle_solid_observation"]["comparison_verified"]
    assert diag["circle_solid_observation"]["observed"]==current

@pytest.mark.parametrize("mode",["box","count","length","nan","inf","bool","missing","extra"])
def test_shape_and_raw_type_guards(recorded,mode):
    current=deepcopy(recorded["reference_solids"])
    if mode=="box":current[0]["box_m"][0]+=1e-15
    if mode=="count":current.append(deepcopy(current[0]))
    if mode=="length":current[0]["mass_raw"].append(0.)
    if mode=="nan":current[0]["mass_raw"][0]=float("nan")
    if mode=="inf":current[0]["mass_raw"][0]=float("inf")
    if mode=="bool":current[0]["mass_raw"][0]=True
    if mode=="missing":del current[0]["mass_raw"]
    if mode=="extra":current[0]["other"]=1
    with pytest.raises(ValueError):evidence.canonical_circle_solids(current,recorded["reference_solids"])

@pytest.mark.parametrize("anchor",[None,[],{},[{}]])
def test_missing_anchor_never_falls_back_to_current(recorded,anchor):
    with pytest.raises(ValueError):evidence.canonical_circle_solids(recorded["apply_solids"],anchor)

def test_absolute_zero_tolerance_remains_exact():
    anchor=[{"box_m":[0.]*6,"mass_raw":[0.,1.,1.,1.]}]
    current=deepcopy(anchor);current[0]["mass_raw"][0]=1e-30
    with pytest.raises(ValueError):evidence.canonical_circle_solids(current,anchor)

def test_no_rolling_anchor_that_accumulates_tolerance(recorded):
    anchor=recorded["reference_solids"]
    first=deepcopy(anchor);first[0]["mass_raw"][0]*=1+9e-11
    assert evidence.canonical_circle_solids(first,anchor)==anchor
    second=deepcopy(first);second[0]["mass_raw"][0]*=1+9e-11
    with pytest.raises(ValueError):evidence.canonical_circle_solids(second,anchor)

def test_actual_raw_preserved_outside_digest_with_one_explicit_save(saved):
    p=saved.run();original=deepcopy(saved.case.state["solids"])
    saved.case.state["solids"][0]["mass_raw"][3]*=1+5e-14
    current=saved.run()
    assert p["state_sha256"]==current["state_sha256"]
    assert current["before"]["circle_reference"]["solids"]==original
    assert current["snapshot_diagnostics"][0]["circle_solid_observation"]["observed"]!=original
    result=saved.run("save",expected_state_sha256=p["state_sha256"],receipt_path=str(saved.output))
    assert result["save_readback_verified"],result
    saved.app.SaveActiveDocument.assert_called_once_with()

@pytest.fixture
def saved_full_mass(case, recorded, request):
    # Populate the mock model before its immutable creation evidence is written.
    case.state["solids"] = deepcopy(recorded["reference_solids"])
    return request.getfixturevalue("saved")


@pytest.mark.parametrize("index",range(12))
def test_out_of_tolerance_never_dispatches_save(saved_full_mass,index):
    saved = saved_full_mass
    p=saved.run()
    saved.case.state["solids"][0]["mass_raw"][index]=saved.case.state["solids"][0]["mass_raw"][index]*1.001+1e-6
    result=saved.run("save",expected_state_sha256=p["state_sha256"],receipt_path=str(saved.output))
    assert result["status"]=="error" and not result["mutation_attempted"],result
    saved.app.SaveActiveDocument.assert_not_called()

def test_missing_creator_never_dispatches_save(saved):
    p=saved.run();saved.creator_path.unlink()
    result=saved.run("save",expected_state_sha256=p["state_sha256"],receipt_path=str(saved.output))
    assert result["status"]=="error" and not result["mutation_attempted"]
    saved.app.SaveActiveDocument.assert_not_called()
