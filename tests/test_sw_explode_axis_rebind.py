"""Focused offline checks for bounded axis repair and failure recovery."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("staged_axis_rebind", ROOT / "scripts/sw_explode_axis_rebind.py")
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)
CYLINDER = [0.0, 0.0, -0.01, 0.0, 0.0, -1.0, 0.02565]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def member(obj, name, *args):
    value = getattr(obj, name)
    return value(*args) if callable(value) else value


@pytest.fixture
def scene(tmp_path, monkeypatch):
    top, part = tmp_path / "Assembly.SLDASM", tmp_path / "Base.SLDPRT"
    top.write_bytes(b"saved assembly"); part.write_bytes(b"saved part")
    owner = dict(name="Mount-1/Base-1", reference="BASE", path=str(part))
    component = dict(**owner, matrix=list(repair.IDENTITY), loaded=True, suppressed=False,
                     fixed=True, native_id=28, configuration="Default")
    axis = lambda index: dict(index=index, entity_present=True, owner=deepcopy(owner),
                             surface_available=True, is_cylinder=True,
                             cylinder_parameters=list(CYLINDER), entity_type=2)
    expected = dict(document_path=str(top), active_configuration="Default",
                    configuration_names=["Default"], explode_views=["Existing"],
                    explode_step_scope="active_configuration_only", components=[component],
                    native_step_sequence=[], studies=[{"name": "Existing motion", "duration_seconds": 30.0}])
    for index in range(3):
        expected["native_step_sequence"].append(dict(
            index=index, name="Step"+str(index), distance_m=0.001, angle_rad=-0.5,
            components=["Mount-1/Base-1"],
            axes={"GetExplodeDirection": axis(2), "GetRotationAxis": axis(0)}))
    current = deepcopy(expected)
    targets = [{"index": i, "name": "Step"+str(i)} for i in (1, 2)]
    for i in (1, 2):
        current["native_step_sequence"][i]["axes"] = {
            "GetExplodeDirection": repair._missing_axis(2),
            "GetRotationAxis": repair._missing_axis(0)}
    flags = [dict(index=i, name="Step"+str(i), reverse_translation=False, reverse_rotation=True) for i in range(3)]
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"snapshot": expected}), encoding="utf-8")
    cfg = SimpleNamespace(Name="Default")
    model = SimpleNamespace(ConfigurationManager=SimpleNamespace(ActiveConfiguration=cfg))
    state = dict(snapshot=current, expected=expected, flags=flags, dirty=False, kind=2, pid=42,
                 path=str(top), calls=[], guards=0, mode=None, model=model, candidate_calls=0)
    model.GetType = lambda: state["kind"]
    steps = {i: SimpleNamespace(index=i) for i in range(3)}
    entity = object()
    def guard(sw, pid, path, *, clean=False):
        state["guards"] += 1
        if state["pid"] != pid or state["path"] != str(path):
            raise ValueError("Identity differs")
        if clean and state["dirty"]:
            raise ValueError("Dirty input")
        return model, {"path": str(path), "needs_save": state["dirty"]}
    def structure(m):
        return deepcopy(state["snapshot"]), deepcopy(state["flags"]), steps
    def step_record(step, index, known):
        return deepcopy(state["snapshot"]["native_step_sequence"][index])
    def reverse(step):
        row = state["flags"][step.index]
        return {key: row[key] for key in ("reverse_translation", "reverse_rotation")}
    def select(m, snapshot, who, cylinder):
        state["candidate_calls"] += 1
        return entity, {"match_count": 1, "selected": {"face_index": 2}, "owner": who, "cylinder": cylinder}
    def call(obj, name, *args):
        if name not in ("SetExplodeDirection", "SetRotationAxis"):
            return member(obj, name, *args)
        assert args == (entity, -1)
        receipt = json.loads(Path(state["apply_receipt"]).read_text(encoding="utf-8"))
        assert receipt["native_dispatch_pending"] is True
        assert receipt["mutation_attempted"] is True and receipt["setters"][-1]["attempted"] is True
        assert receipt["setters"][-1]["returned"] is False
        state["calls"].append((obj.index, name))
        if state["mode"] == "noop":
            return None
        if state["mode"] == "raise_before" or (state["mode"] == "second_raise" and len(state["calls"]) == 2):
            raise RuntimeError("unknown native outcome")
        getter = "GetExplodeDirection" if name == "SetExplodeDirection" else "GetRotationAxis"
        state["snapshot"]["native_step_sequence"][obj.index]["axes"][getter] = deepcopy(
            expected["native_step_sequence"][obj.index]["axes"][getter])
        state["dirty"] = True
        if state["mode"] == "raise_after":
            raise RuntimeError("unknown native outcome")
        if state["mode"] == "scalar":
            state["snapshot"]["native_step_sequence"][obj.index]["angle_rad"] = 10.0
        if state["mode"] == "reverse":
            state["flags"][obj.index]["reverse_rotation"] = False
        if state["mode"] == "configuration":
            cfg.Name = "Other"
        if state["mode"] == "unrelated":
            state["snapshot"]["native_step_sequence"][0]["distance_m"] = 0.1
        if state["mode"] == "other_axis":
            state["snapshot"]["native_step_sequence"][obj.index]["axes"]["GetRotationAxis"] = deepcopy(
                expected["native_step_sequence"][obj.index]["axes"]["GetRotationAxis"])
        return False if state["mode"] == "return_bool" else None
    monkeypatch.setattr(repair.audit, "_guard", guard)
    monkeypatch.setattr(repair.audit, "call", call)
    monkeypatch.setattr(repair.audit, "_member", member)
    monkeypatch.setattr(repair, "_structure", structure)
    monkeypatch.setattr(repair, "_step_record", step_record)
    monkeypatch.setattr(repair, "_reverse_flags", reverse)
    monkeypatch.setattr(repair, "_select_cylinder", select)
    params = dict(process_id=42, expected_document_path=str(top), expected_file_sha256=sha(top),
                  expected_snapshot_path=str(baseline), expected_snapshot_sha256=sha(baseline),
                  path_replacements={}, owner_name=owner["name"], owner_reference="BASE",
                  owner_path=str(part), owner_sha256=sha(part),
                  cylinder_parameters_native=list(CYLINDER), target_steps=targets)
    state.update(params=params, tmp=tmp_path, top=top, part=part, baseline=baseline)
    return state


def prepare(state):
    path = state["tmp"] / "prepare.json"
    result = repair.rebind_explode_axes(object(), action="prepare", receipt_path=str(path), **state["params"])
    state["prepare_path"] = path
    state["prepare_result"] = result
    return result


def apply(state, filename="apply.json", **changes):
    path = state["tmp"] / filename
    state["apply_receipt"] = path
    params = dict(state["params"], action="apply", receipt_path=str(path),
                  expected_state_sha256=state["prepare_result"]["state_sha256"],
                  prepare_receipt_path=str(state["prepare_path"]),
                  prepare_receipt_sha256=sha(state["prepare_path"]))
    params.update(changes)
    return repair.rebind_explode_axes(object(), **params)


def test_prepare_is_read_only_and_apply_repairs_exact_targets(scene):
    before = deepcopy(scene["snapshot"])
    prepared = prepare(scene)
    assert prepared["status"] == "ok" and prepared["phase"] == "prepared", prepared.get("error")
    assert scene["calls"] == [] and scene["snapshot"] == before and not scene["dirty"]
    result = apply(scene)
    assert result["repair_verified"] and result["snapshot_matches_expected"]
    assert result["status"] == "review_required" and result["exact_changed_axis_count"] == 4
    assert result["completed_setters"] == 4 and len(scene["calls"]) == 4
    assert not result["model_saved"] and result["source_files_unchanged"]
    assert scene["snapshot"] == scene["expected"]
    assert result["after_reverse_flags"] == prepared["prepared_state"]["reverse_flags"]


@pytest.mark.parametrize("params", [
    {"process_id": True}, {"process_id": 0}, {"action": "repair"},
    {"target_steps": []}, {"target_steps": [{"index": True, "name": "Step1"}]},
    {"target_steps": [{"index": 1, "name": "Step1"}, {"index": 1, "name": "Step2"}]},
    {"target_steps": [{"index": 9, "name": "Absent"}]},
    {"expected_file_sha256": "0"*64}, {"owner_sha256": "0"*64},
    {"expected_snapshot_sha256": "0"*64}, {"cylinder_parameters_native": [float("nan")]*7},
])
def test_bad_request_rejected_before_native(scene, params):
    kwargs = dict(scene["params"], action="prepare", receipt_path=str(scene["tmp"]/"bad.json"))
    kwargs.update(params)
    result = repair.rebind_explode_axes(object(), **kwargs)
    assert result["status"] == "error" and scene["guards"] == 0 and scene["calls"] == []


@pytest.mark.parametrize("change", ["component", "study", "wrong_axis", "one_already_present", "distance", "extra_step"])
def test_only_explicit_both_missing_difference_is_eligible(scene, change):
    s = scene["snapshot"]
    if change == "component": s["components"][0]["native_id"] = 99
    if change == "study": s["studies"][0]["duration_seconds"] = 99
    if change == "wrong_axis": s["native_step_sequence"][1]["axes"]["GetExplodeDirection"]["index"] = 0
    if change == "one_already_present":
        s["native_step_sequence"][1]["axes"]["GetExplodeDirection"] = deepcopy(scene["expected"]["native_step_sequence"][1]["axes"]["GetExplodeDirection"])
    if change == "distance": s["native_step_sequence"][2]["distance_m"] = 1
    if change == "extra_step": s["native_step_sequence"].append(deepcopy(s["native_step_sequence"][0]))
    assert prepare(scene)["status"] == "error"
    assert scene["calls"] == [] and scene["candidate_calls"] == 0


@pytest.mark.parametrize("mode", ["raise_before", "raise_after", "return_bool", "scalar", "reverse", "configuration", "other_axis"])
def test_first_uncertain_setter_outcome_stops_without_replay(scene, mode):
    assert prepare(scene)["status"] == "ok"
    scene["mode"] = mode
    result = apply(scene)
    assert result["status"] == "uncertain" and not result["repair_verified"]
    assert len(scene["calls"]) == 1
    assert Path(str(scene["prepare_path"])+".apply_attempt.json").is_file()
    count = len(scene["calls"])
    replay = apply(scene, "another_receipt.json")
    assert replay["status"] == "error" and len(scene["calls"]) == count


def test_unrelated_step_change_fails_final_whole_snapshot(scene):
    prepare(scene); scene["mode"] = "unrelated"
    result = apply(scene)
    assert result["status"] == "uncertain" and not result["repair_verified"]
    assert "Final structure" in result["error"]["message"]


def test_stale_state_blocks_all_setters(scene):
    prepare(scene)
    scene["flags"][0]["reverse_translation"] = True
    result = apply(scene)
    assert result["status"] == "error" and scene["calls"] == []
    assert not Path(str(scene["prepare_path"])+".apply_attempt.json").exists()


def test_prepare_receipt_tampering_blocks_all_native(scene):
    prepare(scene)
    scene["prepare_path"].write_text("{}", encoding="utf-8")
    guards = scene["guards"]
    result = apply(scene)
    assert result["status"] == "error" and scene["calls"] == [] and scene["guards"] == guards


def test_intent_publication_failure_prevents_setter(scene, monkeypatch):
    prepare(scene)
    writer = repair._write_receipt
    def fail(path, report, **kwargs):
        if report.get("phase") == "setter_intent":
            raise OSError("receipt locked")
        return writer(path, report, **kwargs)
    monkeypatch.setattr(repair, "_write_receipt", fail)
    result = apply(scene)
    assert result["status"] == "uncertain" and scene["calls"] == []
    assert result["native_dispatch_pending"] is True and not result["repair_verified"]


@pytest.mark.parametrize("kind", [True, 2.0, "2"])
def test_mutation_guard_does_not_coerce_document_type(scene, kind):
    scene["kind"] = kind
    assert prepare(scene)["status"] == "error"
    assert scene["calls"] == []


@pytest.mark.parametrize("actual, expected_match", [
    (CYLINDER, True),
    ([0, 0, 4.0, 0, 0, -1, 0.02565], True),
    ([0.01, 0, -0.01, 0, 0, -1, 0.02565], False),
    ([0, 0, -0.01, 0, 0, 1, 0.02565], False),
    ([0, 0, -0.01, 0, 0, -1, 0.026], False),
    ([0, 0, -0.01, 0, 0, -2, 0.02565], False),
])
def test_semantic_match_uses_signed_line_and_radius(actual, expected_match):
    assert repair._signed_cylinder_match(actual, CYLINDER) is expected_match


@pytest.mark.parametrize("params, expected_count, success", [
    ([CYLINDER], 1, True),
    ([CYLINDER, CYLINDER], 2, False),
    ([[0.1, 0, -0.01, 0, 0, -1, 0.02565]], 0, False),
    ([[0, 0, 0.5, 0, 0, -1, 0.02565]], 1, False),
])
def test_unique_face_selection_never_uses_largest_area(monkeypatch, params, expected_count, success):
    owner = dict(name="Base-1", reference="BASE", path=repair._path_identity(r"C:\fixture\Base.SLDPRT"))
    row = dict(**owner, configuration="Default")
    corresponding_calls = []
    faces = [SimpleNamespace(GetSurface=lambda cp=cp: SimpleNamespace(IsCylinder=lambda: True, CylinderParams=cp),
                             GetArea=lambda i=i: float(i+1)) for i, cp in enumerate(params)]
    part = SimpleNamespace(GetType=lambda: 1,
        ConfigurationManager=SimpleNamespace(ActiveConfiguration=SimpleNamespace(Name="Default")),
        GetBodies2=lambda *_args: [SimpleNamespace(GetFaces=lambda: faces)])
    def corresponding(face):
        corresponding_calls.append(face)
        return object()
    component = SimpleNamespace(GetModelDoc2=lambda: part, GetCorresponding=corresponding)
    monkeypatch.setattr(repair.audit, "_components", lambda m: ([row], {"Base-1": component}))
    monkeypatch.setattr(repair.audit, "call", member)
    monkeypatch.setattr(repair.audit, "_member", member)
    monkeypatch.setattr(repair, "_entity_evidence", lambda e: (e, dict(owner=owner, entity_type=2, cylinder_parameters=CYLINDER)))
    if success:
        _, evidence = repair._select_cylinder(object(), {"components":[row]}, owner, CYLINDER)
        assert evidence["match_count"] == expected_count and len(corresponding_calls) == 1
    else:
        with pytest.raises(ValueError) as caught:
            repair._select_cylinder(object(), {"components":[row]}, owner, CYLINDER)
        assert caught.value.candidate_evidence["match_count"] == expected_count
        assert corresponding_calls == []


def test_second_setter_failure_keeps_first_verified_and_stops(scene):
    prepare(scene); scene["mode"] = "second_raise"
    result = apply(scene)
    assert result["status"] == "uncertain" and result["completed_setters"] == 1
    assert len(scene["calls"]) == 2 and len(result["setters"]) == 2
    assert result["setters"][0]["returned"] and result["setters"][0]["readback_verified"]
    assert result["setters"][1]["attempted"] and not result["setters"][1]["returned"]
    count = len(scene["calls"])
    assert apply(scene, "retry.json")["status"] == "error"
    assert len(scene["calls"]) == count


def test_void_return_without_repaired_axis_is_failure(scene):
    prepare(scene); scene["mode"] = "noop"
    result = apply(scene)
    assert result["status"] == "uncertain" and result["completed_setters"] == 0
    assert len(scene["calls"]) == 1 and not result["repair_verified"]


@pytest.mark.parametrize("change", ["configuration", "owner_file"])
def test_state_change_between_capture_and_first_setter_blocks_dispatch(scene, monkeypatch, change):
    prepare(scene)
    writer = repair._write_receipt
    def change_after_marker(path, report, **kwargs):
        value = writer(path, report, **kwargs)
        if report.get("no_replay"):
            if change == "configuration":
                scene["model"].ConfigurationManager.ActiveConfiguration.Name = "Other"
            else:
                scene["part"].write_bytes(b"changed after capture")
        return value
    monkeypatch.setattr(repair, "_write_receipt", change_after_marker)
    result = apply(scene)
    assert result["status"] == "error" and not result["mutation_attempted"]
    assert scene["calls"] == []
    assert Path(str(scene["prepare_path"])+".apply_attempt.json").is_file()

GROUP = [{"body_index":0,"face_index":0},{"body_index":0,"face_index":1}]


@pytest.fixture
def equivalent_scene(monkeypatch):
    owner = dict(name="Base-1", reference="BASE", path=repair._path_identity(r"C:\fixture\Base.SLDPRT"))
    row = dict(**owner, configuration="Default")
    faces = []
    for index, area in enumerate((1.0, 100.0)):
        face = SimpleNamespace(index=index, params=list(CYLINDER), area=area)
        face.GetSurface = lambda f=face: SimpleNamespace(IsCylinder=lambda:True,CylinderParams=f.params)
        face.GetArea = lambda f=face:f.area
        faces.append(face)
    calls = []
    state = dict(context_change=None, faces=faces, calls=calls)
    part = SimpleNamespace(GetType=lambda:1,
        ConfigurationManager=SimpleNamespace(ActiveConfiguration=SimpleNamespace(Name="Default")),
        GetBodies2=lambda *_args:[SimpleNamespace(GetFaces=lambda:faces)])
    def corresponding(face):
        calls.append(face.index)
        if state["context_change"] == "missing" and face.index == 1:
            return None
        return face
    component = SimpleNamespace(GetModelDoc2=lambda:part,GetCorresponding=corresponding)
    monkeypatch.setattr(repair.audit,"_components",lambda model:([row],{"Base-1":component}))
    monkeypatch.setattr(repair.audit,"call",member)
    monkeypatch.setattr(repair.audit,"_member",member)
    def context(face):
        ctx = dict(owner=deepcopy(owner),entity_type=2,cylinder_parameters=list(face.params))
        if face.index == 1:
            if state["context_change"] == "owner":ctx["owner"]["name"] = "Other-1"
            if state["context_change"] == "reference":ctx["owner"]["reference"] = "OTHER"
            if state["context_change"] == "path":ctx["owner"]["path"] = "Other.SLDPRT"
            if state["context_change"] == "type":ctx["entity_type"] = 1
            if state["context_change"] == "cylinder":ctx["cylinder_parameters"][6] += 0.1
        return face,ctx
    monkeypatch.setattr(repair,"_entity_evidence",context)
    state["select"] = lambda group:repair._select_cylinder(object(),{"components":[row]},owner,CYLINDER,equivalent_face_group=group)
    return state


def test_explicit_group_selects_lowest_index_not_largest_area(equivalent_scene):
    entity,evidence = equivalent_scene["select"](list(reversed(GROUP)))
    assert entity is equivalent_scene["faces"][0]
    assert equivalent_scene["calls"] == [0,1]
    assert evidence["selected"]["face_index"] == 0
    assert evidence["selected"]["area_m2"] == 1.0
    assert len(evidence["axis_equivalent_group"]) == 2
    assert evidence["requested_equivalent_face_group"] == GROUP
    assert evidence["geometric_axis_equivalence_verified"] is True
    assert evidence["face_surface_sense_verified"] is False
    assert evidence["native_direction_equivalence_verified"] is False
    assert evidence["motion_review_required"] is True


def test_default_unique_still_rejects_two_faces(equivalent_scene):
    with pytest.raises(ValueError,match="exactly one"):
        equivalent_scene["select"](None)
    assert equivalent_scene["calls"] == []


@pytest.mark.parametrize("delta",["shift_along","near_radius","near_direction","near_offset","flipped_axis"])
def test_equivalent_group_does_not_relax_exact_seven_parameters(equivalent_scene,delta):
    cp=equivalent_scene["faces"][1].params
    if delta=="shift_along":cp[2]+=0.2
    if delta=="near_radius":cp[6]+=1e-10
    if delta=="near_direction":cp[3]+=1e-10
    if delta=="near_offset":cp[0]+=1e-10
    if delta=="flipped_axis":cp[5]=1.0
    with pytest.raises(ValueError):
        equivalent_scene["select"](GROUP)
    assert equivalent_scene["calls"] == []


@pytest.mark.parametrize("change",["missing","owner","reference","path","type","cylinder"])
def test_every_group_corresponding_context_must_match(equivalent_scene,change):
    equivalent_scene["context_change"]=change
    with pytest.raises(ValueError):
        equivalent_scene["select"](GROUP)
    assert equivalent_scene["calls"] == [0,1]


def test_group_must_cover_all_matches(equivalent_scene):
    face=equivalent_scene["faces"][1]
    equivalent_scene["faces"].append(face)
    with pytest.raises(ValueError,match="all semantic"):
        equivalent_scene["select"](GROUP)
    assert equivalent_scene["calls"] == []


def test_pinned_group_may_not_silently_select_other_indices(equivalent_scene):
    with pytest.raises(ValueError,match="all semantic"):
        equivalent_scene["select"]([GROUP[0],{"body_index":0,"face_index":2}])
    assert equivalent_scene["calls"] == []


def test_complete_group_areas_are_digest_bound(equivalent_scene):
    _,one=equivalent_scene["select"](GROUP)
    equivalent_scene["faces"][1].area += 1.0
    _,two=equivalent_scene["select"](GROUP)
    assert repair._digest(one) != repair._digest(two)
    assert one["selected"] == two["selected"]


@pytest.mark.parametrize("group",[
    [], [GROUP[0]], tuple(GROUP), GROUP+[GROUP[0]],
    [{"body_index":False,"face_index":0},GROUP[1]],
    [{"body_index":0,"face_index":1.0},GROUP[1]],
    [{"body_index":0,"face_index":"0"},GROUP[1]],
    [{"body_index":64,"face_index":0},GROUP[1]],
    [{"body_index":0,"face_index":8192},GROUP[1]],
    [{"body_index":0,"face_index":0,"area":1.0},GROUP[1]],
    [{"body_index":0,"face_index":i} for i in range(33)],
])
def test_bad_group_is_rejected_before_native(scene,group):
    scene["params"]["equivalent_face_group"]=group
    assert prepare(scene)["status"]=="error"
    assert scene["guards"]==0 and scene["calls"]==[]


def group_capture(scene,monkeypatch):
    original=repair._select_cylinder
    state={"area":1.0}
    def select(model,snapshot,owner,cylinder,*,equivalent_face_group=None):
        entity,candidate=original(model,snapshot,owner,cylinder)
        candidate["equivalent_face_group"]=deepcopy(equivalent_face_group)
        candidate["all_group_areas"]=[state["area"],100.0]
        return entity,candidate
    monkeypatch.setattr(repair,"_select_cylinder",select)
    scene["params"]["equivalent_face_group"]=deepcopy(GROUP)
    return state


def test_group_prepare_apply_keeps_original_budget_and_reverseflags(scene,monkeypatch):
    group_capture(scene,monkeypatch)
    prepared=prepare(scene)
    assert prepared["prepared_state"]["equivalent_face_group"]==GROUP
    assert prepared["motion_review_required"] is True
    assert prepared["native_direction_equivalence_verified"] is False
    result=apply(scene)
    assert result["repair_verified"] is True and result["completed_setters"]==4
    assert result["after_reverse_flags"]==prepared["prepared_state"]["reverse_flags"]
    assert result["status"]=="review_required" and result["model_saved"] is False


@pytest.mark.parametrize("change",["area","group","remove_group"])
def test_group_state_change_blocks_before_first_setter(scene,monkeypatch,change):
    state=group_capture(scene,monkeypatch);prepare(scene)
    if change=="area":state["area"]+=1.0
    elif change=="group":scene["params"]["equivalent_face_group"][1]["face_index"]=3
    else:scene["params"]["equivalent_face_group"]=None
    result=apply(scene)
    assert result["status"]=="error" and scene["calls"]==[]
    assert not Path(str(scene["prepare_path"])+".apply_attempt.json").exists()


@pytest.mark.parametrize("mode",["reverse","configuration","scalar","second_raise"])
def test_group_mode_preserves_partial_failure_no_replay_guards(scene,monkeypatch,mode):
    group_capture(scene,monkeypatch);prepare(scene);scene["mode"]=mode
    result=apply(scene)
    assert result["status"]=="uncertain" and not result["repair_verified"]
    count=len(scene["calls"])
    assert count==(2 if mode=="second_raise" else 1)
    assert apply(scene,"retry.json")["status"]=="error"
    assert len(scene["calls"])==count
