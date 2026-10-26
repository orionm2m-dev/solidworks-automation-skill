"""单线车削特征资格验证的离线回归；无 CAD/保存/生成真实调用。"""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest

from scripts import sw_cam_events as events
from scripts import sw_cam_feature_sketch as sketches
from scripts import sw_cam_turn_feature as cam

REAL_SNAPSHOT = cam._snapshot
TLB = "verified/camworks.tlb"


def add_sketch(before):
    state = deepcopy(before)
    state["document"]["needs_save"] = True
    state["model_features"].append(dict(name=before["config"]["sketch_name"], type="ProfileFeature"))
    return state


def add_feature(before):
    state = add_sketch(before)
    state["features"].append(dict(setup_index=0, native_id=99,
        profile=dict(turn_feature_type_raw=1, segment_count=1, segments=[deepcopy(before["source_line"])])))
    state["inventory"]["feature_count"] += 1
    state["inventory"]["feature_counts_by_setup"][0] += 1
    return state


@pytest.fixture
def probe(monkeypatch, tmp_path):
    path = tmp_path / "qualification.sldprt"
    path.write_bytes(b"saved qualification part")
    receipt = tmp_path / "attempt.json"
    config = dict(expected_document_path=str(path), setup_index=0, operation_index=0,
        expected_operation_type=2, linked_feature_index=0, segment_index=0,
        feature_setup_index=0, candidate_feature_type=1, native_to_model_scale=.001,
        sketch_name="SingleLineQualification")
    line = dict(curve_type_raw=0, curve_parameters_available=True,
        start_native=[30., 0., 10.], end_native=[30., 0., 6.],
        line_native=dict(start_diameter=60., end_diameter=60., length_along_axis=4., true_length=4.))
    profile = dict(turn_feature_type_raw=1, segment_count=1, segments=[deepcopy(line)])
    before = dict(config=deepcopy(config), document=dict(path=str(path),title=path.name,type=1,needs_save=False),
        saved_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), source_line=line,
        endpoints_model_m=[[.03, 0., .010], [.03, 0., .006]], plane=dict(name="Actual meridian"),
        model_features=[dict(name="Base solid",type="Boss")],
        solids=[dict(box_model_m=[0.,0.,0.,.06,.06,.02],mass_properties_native=[0.,0.,0.,.001])],
        inventory=dict(feature_count=1,feature_counts_by_setup=[1],operation_count=2,
            operations=[dict(native_id=10,toolpath_generated=True,toolpath_records=31),
                        dict(native_id=11,toolpath_generated=True,toolpath_records=7)]),
        features=[dict(setup_index=0,native_id=50,profile=deepcopy(profile))],
        selected_profile=profile, selected_feature_id=50)
    after = add_feature(before)
    state = dict(current=deepcopy(before),on_capture=None,on_sketch=None,on_create=None,on_exit=None,on_save=None)
    forbidden = [Mock(side_effect=AssertionError("No GTP/GOP/SW save")) for _ in range(3)]
    sw = N(Save3=forbidden[0])
    raw_new = object()
    doc = N(GetCWObjectID=Mock(return_value=(99,True)))
    model = object()
    app = N(ActiveDocGTP=forbidden[1],ActiveDocGOP=forbidden[2])
    class Session:
        def __init__(self):
            self.data=dict(subscribed=False,disconnected=False,event_count=0,overflow=0,
                callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
        def __enter__(self):self.data["subscribed"]=True;return self
        def __exit__(self,*_):
            self.data["disconnected"]=True
            if state["on_exit"]:state["on_exit"]()
        def summary(self):return deepcopy(self.data)
    session=Session()
    factory=Mock(return_value=session)
    def create_native(kind,name):
        durable=json.loads(receipt.read_text())
        assert durable["phase"]=="CreateTurnFeature" and durable["feature_call_attempted"]
        assert durable["sketch"]["verified"] is True
        assert not durable["native_call_returned"]
        assert (kind,name)==(1,config["sketch_name"])
        state["current"]=deepcopy(after)
        if state["on_create"]:state["on_create"]()
        return raw_new
    setup=N(CreateTurnFeature=Mock(side_effect=create_native))
    def sketch_native(_sw,_model,**kwargs):
        durable=json.loads(receipt.read_text())
        assert durable["phase"]=="create_sketch" and durable["mutation_attempted"]
        assert not durable["feature_call_attempted"]
        assert kwargs["endpoints_model_m"]==before["endpoints_model_m"]
        assert kwargs["expected_plane"]==before["plane"]
        kwargs["check"]()
        state["current"]=add_sketch(before)
        kwargs["diagnostic"].update(verified=True,sketch_name=config["sketch_name"],
            endpoints_model_m=before["endpoints_model_m"],plane=before["plane"])
        if state["on_sketch"]:state["on_sketch"]()
        kwargs["check"]()
        return deepcopy(kwargs["diagnostic"])
    sketch_factory=Mock(side_effect=sketch_native)
    def save_native():
        durable=json.loads(receipt.read_text())
        assert durable["phase"]=="native_save" and durable["mutation_attempted"]
        state["current"]["document"]["needs_save"]=False
        state["current"]["saved_file_sha256"]="b"*64
        if state["on_save"]:state["on_save"]()
    app.SaveActiveDocument=Mock(side_effect=save_native)
    handles=dict(doc=doc,app=app,model=model,target_setup=setup)
    def snapshot(*args,check=lambda:None,diagnostic=None):
        check()
        diagnostic["stage"]="mock_snapshot"
        if state["on_capture"]:state["on_capture"](diagnostic["phase"])
        check()
        return deepcopy(state["current"]),handles
    captures=Mock(side_effect=snapshot)
    monkeypatch.setattr(cam,"_snapshot",captures)
    monkeypatch.setattr(cam,"_typed",lambda obj,*_:obj)
    monkeypatch.setattr(cam,"document_snapshot",lambda *_:deepcopy(state["current"]["document"]))
    monkeypatch.setattr(events,"CamMessageSession",factory)
    monkeypatch.setattr(sketches,"create_single_line_sketch",sketch_factory)
    defaults=config|dict(qualification_only=True,acknowledge_unverified_type_mapping=True,message_policy="vendor_default")
    def prepare(**changes):
        return cam.qualify_turn_feature(sw,"clsid",TLB,**(defaults|dict(action="prepare")|changes))
    def apply(**changes):
        return cam.qualify_turn_feature(sw,"clsid",TLB,**(defaults|dict(action="apply",
            receipt_path=str(receipt),expected_state_sha256=cam._state_digest(before))|changes))
    def save(**changes):
        return cam.qualify_turn_feature(sw,"clsid",TLB,**(defaults|dict(action="save_candidate",
            receipt_path=str(receipt),expected_state_sha256=cam._state_digest(state["current"]),
            expected_new_feature_native_id=99)|changes))
    return N(**locals())


def no_generation(probe,report):
    assert not report["generation_attempted"] and not report["thread_created"]
    assert not report["may_continue"] and not report["persistence_verified"]
    for call in probe.forbidden:call.assert_not_called()


def test_prepare_is_readonly_with_exact_state_hash(probe):
    result=probe.prepare()
    assert result["status"]=="ok" and result["state_sha256"]==cam._state_digest(probe.before)
    assert not result["mutation_attempted"] and not probe.receipt.exists()
    probe.sketch_factory.assert_not_called();probe.setup.CreateTurnFeature.assert_not_called()
    probe.factory.assert_not_called();probe.app.SaveActiveDocument.assert_not_called()
    no_generation(probe,result)


def test_apply_one_native_feature_after_durable_phases_without_save_or_gtp(probe):
    result=probe.apply()
    assert result["status"]=="review_required" and result["mapping_verified"]
    assert result["readback_verified"] and result["new_feature_native_id"]==99
    assert result["final_state"]==probe.after
    probe.sketch_factory.assert_called_once()
    probe.setup.CreateTurnFeature.assert_called_once_with(1,probe.config["sketch_name"])
    probe.app.SaveActiveDocument.assert_not_called()
    assert not result["model_saved"]
    assert json.loads(probe.receipt.read_text())["readback_verified"]
    assert result["after"]["inventory"]["operations"]==probe.before["inventory"]["operations"]
    no_generation(probe,result)


@pytest.mark.parametrize("key,value",[("setup_index",True),("segment_index",True),("segment_index",512),
    ("linked_feature_index",64),("feature_setup_index",-1),("candidate_feature_type",False),
    ("native_to_model_scale",True),("native_to_model_scale",0),("native_to_model_scale",float("nan")),
    ("native_to_model_scale",2),("sketch_name","bad/name"),("sketch_name",""),
    ("qualification_only",1),("acknowledge_unverified_type_mapping",1),
    ("message_policy","accept"),("expected_document_path","relative.sldprt"),("action","insert")])
def test_invalid_inputs_fail_before_snapshot(probe,key,value):
    result=probe.prepare(**{key:value})
    assert result["status"]=="error" and not result["mutation_attempted"]
    probe.captures.assert_not_called();probe.sketch_factory.assert_not_called()


@pytest.mark.parametrize("changes",[dict(expected_state_sha256="0"*64),dict(receipt_path="unused.json"),
    dict(expected_new_feature_native_id=99)])
def test_prepare_forbids_mutation_inputs(probe,changes):
    assert probe.prepare(**changes)["status"]=="error"
    probe.captures.assert_not_called()


def test_wrong_hash_stops_before_event_subscription_and_sketch(probe):
    result=probe.apply(expected_state_sha256="0"*64)
    assert result["status"]=="error" and not result["mutation_attempted"]
    probe.factory.assert_not_called();probe.sketch_factory.assert_not_called()


@pytest.mark.parametrize("kind",["dirty","name_collision"])
def test_creation_preconditions_reject_before_mutation(probe,kind):
    if kind=="dirty":probe.state["current"]["document"]["needs_save"]=True
    else:probe.state["current"]["model_features"].append(dict(name=probe.config["sketch_name"],type="ProfileFeature"))
    assert probe.prepare()["status"]=="error"
    probe.sketch_factory.assert_not_called()


def test_existing_receipt_is_never_overwritten_including_finally(probe):
    probe.receipt.write_bytes(b"immutable previous attempt")
    result=probe.apply()
    assert result["status"]=="error"
    assert probe.receipt.read_bytes()==b"immutable previous attempt"
    probe.captures.assert_not_called()


@pytest.mark.parametrize("phase",["create_sketch","CreateTurnFeature"])
def test_receipt_write_failure_prevents_corresponding_mutation(probe,monkeypatch,phase):
    original=cam._write_receipt
    def write(path,result,**options):
        if result["phase"]==phase:raise OSError("disk unavailable")
        return original(path,result,**options)
    monkeypatch.setattr(cam,"_write_receipt",write)
    result=probe.apply()
    assert result["status"]=="uncertain"
    probe.setup.CreateTurnFeature.assert_not_called()
    if phase=="create_sketch":probe.sketch_factory.assert_not_called()


@pytest.mark.parametrize("when",["before_mutation","sketch","after_sketch","create_return","cleanup"])
def test_events_stop_before_next_native_step(probe,when):
    def message():probe.session.data["event_count"]=1
    if when in {"before_mutation","after_sketch"}:
        probe.state["on_capture"]=lambda phase:message() if phase==when else None
    elif when=="sketch":probe.state["on_sketch"]=message
    elif when=="create_return":probe.state["on_create"]=message
    else:probe.state["on_exit"]=message
    result=probe.apply()
    assert result["status"] in {"error","uncertain"} and not result["mapping_verified"]
    if when in {"before_mutation","sketch","after_sketch"}:probe.setup.CreateTurnFeature.assert_not_called()
    if when=="before_mutation":probe.sketch_factory.assert_not_called()
    if when=="create_return":probe.doc.GetCWObjectID.assert_not_called()
    no_generation(probe,result)


def test_creator_exception_has_no_readback_retry_or_save(probe):
    probe.setup.CreateTurnFeature.side_effect=RuntimeError("native fault")
    result=probe.apply()
    assert result["status"]=="uncertain" and not result["native_call_returned"]
    probe.setup.CreateTurnFeature.assert_called_once()
    probe.doc.GetCWObjectID.assert_not_called()
    assert [c.kwargs["diagnostic"]["phase"] for c in probe.captures.call_args_list]==[
        "initial","before_mutation","after_sketch"]
    probe.app.SaveActiveDocument.assert_not_called()


@pytest.mark.parametrize("returned",[None,False])
def test_null_native_result_stops_before_id_read(probe,returned):
    probe.setup.CreateTurnFeature.side_effect=None;probe.setup.CreateTurnFeature.return_value=returned
    result=probe.apply()
    assert result["status"]=="uncertain" and result["native_call_returned"]
    probe.doc.GetCWObjectID.assert_not_called()


def test_cleanup_drift_invalidates_mapping(probe):
    probe.state["on_exit"]=lambda:probe.state["current"]["solids"][0]["box_model_m"].__setitem__(0,99.)
    result=probe.apply()
    assert result["status"]=="uncertain" and not result["mapping_verified"]


@pytest.mark.parametrize("change",["path","body","old_profile","old_toolpath","saved_hash","extra_feature",
    "new_type","new_setup","new_curve","new_geometry","new_length","feature_count","extra_sketch"])
def test_verify_rejects_unexpected_model_and_cam_deltas(probe,change):
    after=deepcopy(probe.after)
    if change=="path":after["document"]["path"]="another.sldprt"
    elif change=="body":after["solids"][0]["box_model_m"][0]=99.
    elif change=="old_profile":after["features"][0]["profile"]["segments"][0]["start_native"][0]=99.
    elif change=="old_toolpath":after["inventory"]["operations"][0]["toolpath_records"]=0
    elif change=="saved_hash":after["saved_file_sha256"]="f"*64
    elif change=="extra_feature":after["features"].append(dict(native_id=100,setup_index=0,profile={}))
    elif change=="new_type":after["features"][-1]["profile"]["turn_feature_type_raw"]=2
    elif change=="new_setup":after["features"][-1]["setup_index"]=1
    elif change=="new_curve":after["features"][-1]["profile"]["segments"][0]["curve_type_raw"]=1
    elif change=="new_geometry":after["features"][-1]["profile"]["segments"][0]["start_native"][0]+=1
    elif change=="new_length":after["features"][-1]["profile"]["segments"][0]["line_native"]["true_length"]+=1
    elif change=="feature_count":after["inventory"]["feature_count"]+=1
    else:after["model_features"].append(dict(name="Unrequested",type="ProfileFeature"))
    with pytest.raises(ValueError):cam._verify(probe.before,after,sketch_added=True,new_id=99)


def test_verify_accepts_only_one_reversed_native_line_with_same_dimensions(probe):
    after=deepcopy(probe.after);line=after["features"][-1]["profile"]["segments"][0]
    line["start_native"],line["end_native"]=line["end_native"],line["start_native"]
    cam._verify(probe.before,after,sketch_added=True,new_id=99)


def test_save_candidate_is_explicit_single_call_and_not_persistence_proof(probe):
    probe.state["current"]=deepcopy(probe.after)
    result=probe.save()
    assert result["status"]=="review_required" and result["model_saved"]
    assert result["native_save_call_returned"] and not result["persistence_verified"]
    assert result["reason"]=="SAVE_RETURNED_PERSISTENCE_REQUIRES_REOPEN"
    probe.app.SaveActiveDocument.assert_called_once()
    probe.sketch_factory.assert_not_called();probe.setup.CreateTurnFeature.assert_not_called()
    assert result["final_state"]["saved_file_sha256"]=="b"*64
    no_generation(probe,result)


@pytest.mark.parametrize("changes",[dict(expected_new_feature_native_id=0),dict(expected_new_feature_native_id=True),
    dict(expected_new_feature_native_id=100),dict(expected_state_sha256="0"*64)])
def test_save_candidate_requires_exact_present_new_id_and_hash(probe,changes):
    probe.state["current"]=deepcopy(probe.after)
    result=probe.save(**changes)
    assert result["status"]=="error" and not result["model_saved"]
    probe.app.SaveActiveDocument.assert_not_called()


def test_save_cannot_change_old_native_features(probe):
    probe.state["current"]=deepcopy(probe.after)
    probe.state["on_save"]=lambda:probe.state["current"]["features"].pop()
    result=probe.save()
    assert result["status"]=="uncertain" and not result["model_saved"]
    probe.app.SaveActiveDocument.assert_called_once()


@pytest.mark.parametrize("change",["type","missing_segment","arc","unavailable","zero_length"])
def test_snapshot_rejects_unqualified_source_before_sw_sketch_reads(probe,monkeypatch,change):
    state=deepcopy(probe.before)
    line=state["selected_profile"]["segments"][0]
    if change=="type":state["selected_profile"]["turn_feature_type_raw"]=2
    elif change=="missing_segment":state["selected_profile"]["segments"]=[]
    elif change=="arc":line["curve_type_raw"]=1
    elif change=="unavailable":line["curve_parameters_available"]=False
    else:line["end_native"]=line["start_native"][:]
    monkeypatch.setattr(cam,"_capture",Mock(return_value=(state,{})))
    with pytest.raises(ValueError):REAL_SNAPSHOT(probe.sw,"clsid",TLB,probe.config)
    probe.sketch_factory.assert_not_called()


MASS_ORIGINAL = [.0002956254783365533, 1.7184100371695307e-14, 0.0, .001]
MASS_DRIFT = [.000295625478336554, 1.7184100371698866e-14, -0.0, .001]


def test_observed_mass_noise_has_stable_hash_and_retains_raw(probe):
    before, after = deepcopy(probe.before), deepcopy(probe.before)
    before["solids"][0]["mass_properties_native"] = MASS_ORIGINAL[:]
    after["solids"][0]["mass_properties_native"] = MASS_DRIFT[:]
    assert cam._state_digest(before) == cam._state_digest(after)
    assert cam._states_equal(before, after)
    cam._verify(before, after)
    assert before["solids"][0]["mass_properties_native"] == MASS_ORIGINAL
    assert after["solids"][0]["mass_properties_native"] == MASS_DRIFT


def test_mass_noise_allowed_at_all_stages_without_weakening_other_guards(probe):
    for state in (probe.before, probe.after, probe.state["current"]):
        state["solids"][0]["mass_properties_native"] = MASS_ORIGINAL[:]
    def drift(_phase):
        probe.state["current"]["solids"][0]["mass_properties_native"] = MASS_DRIFT[:]
    probe.state["on_capture"] = drift
    prepared = probe.prepare()
    result = probe.apply(expected_state_sha256=prepared["state_sha256"])
    assert result["readback_verified"] and result["mapping_verified"]
    assert result["before"]["solids"][0]["mass_properties_native"] == MASS_DRIFT
    assert result["mass_comparison"]["absolute_tolerance"] == 0.0
    assert result["mass_comparison"]["hash_significant_digits"] == 12


@pytest.mark.parametrize("index,value", [(0, .000296), (1, 1.719e-14), (2, 1e-30)])
def test_material_mass_change_and_zero_to_nonzero_are_rejected(probe, index, value):
    before, after = deepcopy(probe.before), deepcopy(probe.before)
    before["solids"][0]["mass_properties_native"] = MASS_ORIGINAL[:]
    after["solids"][0]["mass_properties_native"] = MASS_ORIGINAL[:]
    after["solids"][0]["mass_properties_native"][index] = value
    assert cam._state_digest(before) != cam._state_digest(after)
    assert not cam._states_equal(before, after)
    with pytest.raises(ValueError, match="Unexpected change"):
        cam._verify(before, after)


@pytest.mark.parametrize("field", ["box", "profile", "file", "operation"])
def test_mass_tolerance_never_relaxes_other_fields(probe, field):
    after = deepcopy(probe.before)
    if field == "box": after["solids"][0]["box_model_m"][3] += 1e-14
    elif field == "profile": after["source_line"]["start_native"][0] += 1e-12
    elif field == "file": after["saved_file_sha256"] = "d" * 64
    else: after["inventory"]["operations"][0]["toolpath_records"] += 1
    assert cam._state_digest(probe.before) != cam._state_digest(after)
    with pytest.raises(ValueError, match="Unexpected change"):
        cam._verify(probe.before, after)


def test_mass_array_shape_change_is_not_accepted(probe):
    after = deepcopy(probe.before)
    after["solids"][0]["mass_properties_native"].append(0.)
    assert not cam._states_equal(probe.before, after)


def test_material_mass_change_before_mutation_blocks_sketch(probe):
    def change(phase):
        if phase == "before_mutation":
            probe.state["current"]["solids"][0]["mass_properties_native"][3] *= 1.001
    probe.state["on_capture"] = change
    result = probe.apply()
    assert not result["mutation_attempted"]
    probe.sketch_factory.assert_not_called()
    probe.setup.CreateTurnFeature.assert_not_called()


def test_body_count_change_is_not_accepted(probe):
    after = deepcopy(probe.before)
    after["solids"].append(deepcopy(after["solids"][0]))
    assert not cam._states_equal(probe.before, after)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_mass_fingerprint_rejects_nonfinite_or_boolean_values(probe, value):
    after = deepcopy(probe.before)
    after["solids"][0]["mass_properties_native"][0] = value
    with pytest.raises(ValueError): cam._state_digest(after)
    with pytest.raises(ValueError): cam._states_equal(probe.before, after)


@pytest.mark.parametrize("added", [False, True])
def test_inspect_dirty_existing_sketch_returns_full_snapshot_without_preparing(probe, added):
    probe.state["current"] = deepcopy(probe.after if added else add_sketch(probe.before))
    result = probe.prepare(action="inspect")
    assert result["phase"] == "inspected" and result["snapshot_readback_completed"]
    assert result["before"] == probe.state["current"]
    assert result["prepared"] is False and result["apply_eligible"] is False
    assert not result["mutation_attempted"] and not result["mapping_verified"]
    assert not probe.receipt.exists()
    probe.factory.assert_not_called()
    probe.sketch_factory.assert_not_called()
    probe.setup.CreateTurnFeature.assert_not_called()
    probe.app.SaveActiveDocument.assert_not_called()
    no_generation(probe, result)


@pytest.mark.parametrize("field,value", [("expected_state_sha256", "a"*64),
    ("receipt_path", "unused.json"), ("expected_new_feature_native_id", 99)])
def test_inspect_rejects_mutation_inputs(probe, field, value):
    result = probe.prepare(action="inspect", **{field:value})
    assert result["status"] == "error"
    probe.captures.assert_not_called()


def test_getter_checks_are_local_but_boundaries_keep_exact_document_guard(probe, monkeypatch):
    reader = Mock(side_effect=cam.document_snapshot)
    monkeypatch.setattr(cam, "document_snapshot", reader)
    original = probe.captures.side_effect
    def many_getters(*args, **kwargs):
        for _ in range(200): kwargs["check"]()
        return original(*args, **kwargs)
    probe.captures.side_effect = many_getters
    result = probe.apply()
    assert result["readback_verified"]
    assert 10 <= reader.call_count < 40


def test_document_change_inside_snapshot_stops_at_boundary_before_mutation(probe):
    def change(phase):
        if phase == "before_mutation": probe.state["current"]["document"]["path"] = "other.sldprt"
    probe.state["on_capture"] = change
    result = probe.apply()
    assert not result["mutation_attempted"]
    probe.sketch_factory.assert_not_called()
    probe.setup.CreateTurnFeature.assert_not_called()


def test_cam_event_between_getters_stops_snapshot_without_later_native_calls(probe):
    original = probe.captures.side_effect
    reads = []
    def snapshot(*args, **kwargs):
        if kwargs["diagnostic"]["phase"] == "before_mutation":
            kwargs["check"]()
            reads.append("first")
            probe.session.data["event_count"] = 1
            kwargs["check"]()
            reads.append("forbidden")
        return original(*args, **kwargs)
    probe.captures.side_effect = snapshot
    result = probe.apply()
    assert reads == ["first"] and not result["mutation_attempted"]
    probe.sketch_factory.assert_not_called()


@pytest.mark.parametrize("returned", [None, False])
def test_null_return_with_exact_one_feature_delta_is_recovered_without_replay(probe, returned):
    original = probe.setup.CreateTurnFeature.side_effect
    def create(*args):
        original(*args)
        return returned
    probe.setup.CreateTurnFeature.side_effect = create
    result = probe.apply()
    assert result["readback_verified"] and result["mapping_verified"]
    assert result["native_call_returned"] and not result["native_result_present"]
    assert result["null_result_recovered_by_exact_delta"] is True
    assert result["new_feature_identity_source"] == "snapshot_delta_after_null_return"
    assert result["new_feature_native_id"] == 99
    probe.setup.CreateTurnFeature.assert_called_once()
    probe.doc.GetCWObjectID.assert_not_called()
    probe.app.SaveActiveDocument.assert_not_called()
    no_generation(probe, result)


@pytest.mark.parametrize("change", ["two_new", "old_profile", "operations", "file", "wrong_type", "wrong_line", "zero_id"])
def test_null_return_recovery_requires_full_exact_delta(probe, change):
    original = probe.setup.CreateTurnFeature.side_effect
    def create(*args):
        original(*args)
        state = probe.state["current"]
        if change == "two_new":
            extra = deepcopy(state["features"][-1]); extra["native_id"] = 100
            state["features"].append(extra)
        elif change == "old_profile": state["features"][0]["profile"]["attribute_id_raw"] = 42
        elif change == "operations": state["inventory"]["operations"][0]["toolpath_records"] += 1
        elif change == "file": state["saved_file_sha256"] = "e"*64
        elif change == "wrong_type": state["features"][-1]["profile"]["turn_feature_type_raw"] = 2
        elif change == "wrong_line": state["features"][-1]["profile"]["segments"][0]["start_native"][0] += 1
        else: state["features"][-1]["native_id"] = 0
        return None
    probe.setup.CreateTurnFeature.side_effect = create
    result = probe.apply()
    assert result["status"] == "uncertain" and not result["mapping_verified"]
    assert not result.get("null_result_recovered_by_exact_delta")
    assert "after" in result and result["native_call_returned"]
    probe.setup.CreateTurnFeature.assert_called_once()
    probe.doc.GetCWObjectID.assert_not_called()
    no_generation(probe, result)


def test_null_return_with_event_never_reads_delta_or_replays(probe):
    original = probe.setup.CreateTurnFeature.side_effect
    def create(*args):
        original(*args)
        probe.session.data["event_count"] = 1
        return None
    probe.setup.CreateTurnFeature.side_effect = create
    result = probe.apply()
    assert result["status"] == "uncertain"
    assert "after_feature" not in [c.kwargs["diagnostic"]["phase"] for c in probe.captures.call_args_list]
    probe.setup.CreateTurnFeature.assert_called_once()
    probe.doc.GetCWObjectID.assert_not_called()


@pytest.fixture
def crop_probe(probe,monkeypatch):
    p=probe
    guards=dict(crop_z_native=[9.,7.],process_id=731,expected_source_operation_native_id=11,
        expected_source_feature_native_id=50,expected_source_line_sha256=cam._digest(p.before['source_line']),
        expected_source_sha256=p.before['saved_file_sha256'])
    p.before['selected_operation_id']=11
    p.before['config'].update(guards)
    p.before['creation_line']=cam._crop_line(p.before['source_line'],p.before['config'],p.before)
    p.before['source_line_sha256']=guards['expected_source_line_sha256']
    p.before['endpoints_model_m']=[[v*.001 for v in p.before['creation_line'][key]] for key in ('start_native','end_native')]
    after=add_feature(p.before)
    after['features'][-1]['profile']['segments']=[deepcopy(p.before['creation_line'])]
    p.after.clear();p.after.update(after)
    p.state['current']=deepcopy(p.before);p.defaults.update(guards)
    p.sw.GetProcessID=731;p.sw.GetAddInObject=Mock(return_value=N(GetCWApp=p.app))
    session_type=type(p.session);enter=session_type.__enter__;leave=session_type.__exit__
    def enter_active(self):
        self.data['active']=True;return enter(self)
    def exit_inactive(self,*args):
        self.data['active']=False;return leave(self,*args)
    monkeypatch.setattr(session_type,'__enter__',enter_active);monkeypatch.setattr(session_type,'__exit__',exit_inactive)
    original=p.captures.side_effect
    def subscribed_snapshot(*args,**kw):
        assert p.session.data.get('active') is True,'Crop CAM capture outside subscription'
        return original(*args,**kw)
    p.captures.side_effect=subscribed_snapshot
    p.crop_guards=guards
    return p

@pytest.mark.parametrize('action',['prepare','inspect','apply'])
def test_crop_all_snapshots_subscribed_no_post_cleanup_cam_or_save(crop_probe,action):
    p=crop_probe
    r=p.apply() if action=='apply' else p.prepare(action=action)
    assert r['status'] in ('ok','review_required'),r.get('issue',r.get('cleanup_issue'))
    assert r['post_cleanup_document_file_verified'] and r['messages']['disconnected']
    assert not r['messages']['active'] and not r['post_cleanup_cam_read_performed']
    phases=[c.kwargs['diagnostic']['phase'] for c in p.captures.call_args_list]
    assert 'after_cleanup' not in phases
    assert p.factory.call_count==1
    assert p.app.SaveActiveDocument.call_count==0
    if action=='apply':
        assert r['readback_verified'] and r['mapping_verified']
        assert r['before']['endpoints_model_m']==[[30*.001,0.,9*.001],[30*.001,0.,7*.001]]
    else:p.setup.CreateTurnFeature.assert_not_called()

@pytest.mark.parametrize('which',['pid','file','cleanup','cleanup_document'])
def test_crop_exact_identity_and_cleanup_gate(crop_probe,which):
    p=crop_probe
    if which=='pid':p.sw.GetProcessID=732
    elif which=='file':p.path.write_bytes(b'changed file')
    elif which=='cleanup':p.state['on_exit']=lambda:p.session.data.update(disconnect_errors=['failed'])
    else:p.state['on_exit']=lambda:p.state['current']['document'].update(needs_save=True)
    r=p.prepare()
    assert r['status']=='error'
    p.setup.CreateTurnFeature.assert_not_called()
    p.sketch_factory.assert_not_called()

@pytest.mark.parametrize('field,value',[
 ('crop_z_native',[True,7]),('crop_z_native',[9,9]),('crop_z_native',[9,float('inf')]),
 ('crop_z_native',[9]),('process_id',True),('expected_source_operation_native_id',0),
 ('expected_source_feature_native_id',1.0),('expected_source_sha256','z'*64),
 ('expected_source_line_sha256',None)])
def test_crop_input_validation_before_bootstrap(crop_probe,field,value):
    p=crop_probe;r=p.prepare(**{field:value})
    assert r['status']=='error';p.captures.assert_not_called();p.factory.assert_not_called()
    p.sw.GetAddInObject.assert_not_called()

def test_crop_has_no_embedded_save_action(crop_probe):
    r=crop_probe.save()
    assert r['status']=='error';crop_probe.app.SaveActiveDocument.assert_not_called()
    crop_probe.factory.assert_not_called()

@pytest.mark.parametrize('zpair',[[11,7],[9,5],[7,9],[10,6],[10.000000000001,7],[9,5.999999999999]])
def test_crop_exact_domain_no_reversal_or_whole_line(crop_probe,zpair):
    p=crop_probe;config=dict(p.before['config'],crop_z_native=zpair)
    with pytest.raises(ValueError):cam._crop_line(p.before['source_line'],config,p.before)

@pytest.mark.parametrize('field,value',[('selected_operation_id',99),('selected_feature_id',99),('saved_file_sha256','b'*64)])
def test_crop_source_state_ids_and_file_pinned(crop_probe,field,value):
    p=crop_probe;state=deepcopy(p.before);state[field]=value
    with pytest.raises(ValueError):cam._crop_line(p.before['source_line'],p.before['config'],state)

@pytest.mark.parametrize('change',['endpoint','arc','unavailable','nonaxial'])
def test_crop_source_fingerprint_and_axial_line_requirement(crop_probe,change):
    p=crop_probe;line=deepcopy(p.before['source_line']);config=deepcopy(p.before['config'])
    if change=='endpoint':line['start_native'][2]+=.1
    elif change=='arc':line['curve_type_raw']=1
    elif change=='unavailable':line['curve_parameters_available']=False
    else:line['end_native'][0]+=.001
    if change!='endpoint':config['expected_source_line_sha256']=cam._digest(line)
    with pytest.raises(ValueError):cam._crop_line(line,config,p.before)

def test_crop_direction_and_coordinates_from_source_only(crop_probe):
    p=crop_probe;line=deepcopy(p.before['source_line']);line['start_native'],line['end_native']=line['end_native'],line['start_native']
    config=dict(p.before['config'],crop_z_native=[7.,9.],expected_source_line_sha256=cam._digest(line))
    v=cam._crop_line(line,config,p.before)
    assert v['start_native']==[30.,0.,7.] and v['end_native']==[30.,0.,9.]
    assert v['line_native']['true_length']==2. and v['line_native']['length_along_axis']==2.
    assert v['line_native']['start_diameter']==60.

def test_crop_new_feature_whole_source_is_rejected(crop_probe):
    p=crop_probe;after=deepcopy(p.after);after['features'][-1]['profile']['segments']=[deepcopy(p.before['source_line'])]
    with pytest.raises(ValueError):cam._verify(p.before,after,sketch_added=True,new_id=99)

def test_crop_created_geometry_change_rejected(crop_probe):
    p=crop_probe;after=deepcopy(p.after);after['features'][-1]['profile']['segments'][0]['end_native'][0]+=.01
    with pytest.raises(ValueError):cam._verify(p.before,after,sketch_added=True,new_id=99)

def test_crop_prepared_hash_stale_stops_without_sketch(crop_probe):
    p=crop_probe;r=p.apply(expected_state_sha256='f'*64)
    assert r['status']=='error' and not r['mutation_attempted']
    p.sketch_factory.assert_not_called();p.setup.CreateTurnFeature.assert_not_called()
    assert r['messages']['disconnected']

def test_whole_line_does_not_accept_partial_crop_guards(probe):
    r=probe.prepare(process_id=731)
    assert r['status']=='error';probe.captures.assert_not_called()


@pytest.mark.parametrize('phase',['initial','before_mutation'])
def test_preflight_capture_has_durable_progress_before_any_geometry(probe,phase):
    seen=[]
    def hook(current):
        if current==phase:
            receipt=json.loads(probe.receipt.read_text())
            assert receipt['phase']==phase+'_capture'
            assert receipt['capture_progress'][-1]['status']=='started'
            assert receipt['capture_progress'][-1]['started_at_utc']
            assert not receipt['mutation_attempted'] and not receipt['feature_call_attempted']
            seen.append(current)
            raise RuntimeError('bounded simulated capture stop')
    probe.state['on_capture']=hook
    r=probe.apply()
    assert seen==[phase] and r['status']=='error' and not r['mutation_attempted']
    p=r['capture_progress'][-1]
    assert p['phase']==phase and p['status']=='error' and p['elapsed_seconds']>=0
    probe.sketch_factory.assert_not_called();probe.setup.CreateTurnFeature.assert_not_called()

def test_completed_capture_progress_is_retained(probe):
    r=probe.apply()
    assert r['readback_verified']
    assert [p['phase'] for p in r['capture_progress']][:2]==['initial','before_mutation']
    assert all(p['status']=='completed' and p['elapsed_seconds']>=0 for p in r['capture_progress'])
    assert json.loads(probe.receipt.read_text())['capture_progress']==r['capture_progress']

def test_prepare_capture_progress_does_not_write_receipt(probe):
    r=probe.prepare()
    assert len(r['capture_progress'])==1 and r['capture_progress'][0]['status']=='completed'
    assert not probe.receipt.exists()


@pytest.mark.parametrize('event_getter',['GetCWApp','GetDocType','IGetMachine','IGetEnumSetups','Count','Item','GetCWObjectID'])
def test_crop_guarded_capture_stops_after_first_context_or_collection_event(monkeypatch,tmp_path,event_getter):
    from scripts import sw_cam_turn_feature_attribute as guarded
    state={'event':False,'calls':[]}
    def col(values):return {'Count':len(values),'Item':lambda i:values[i]}
    feature={'id':11}
    operation={'id':22,'OpernType':2,'GetIsToolpathGenerated':False,'IGetAllFeatures':col([feature])}
    setup={'IGetEnumFeatures':col([feature]),'IGetEnumOperations':col([operation])}
    machine={'MachType':3,'IGetEnumSetups':col([setup]),'IGetEnumOpSetups':col([setup]),'IGetWorkpiece':{'GetTurnWorkpieceType':1}}
    doc={'GetDocType':1,'IGetMachine':machine,'GetCWObjectID':lambda obj:(obj['id'],True)}
    sw={'GetAddInObject':lambda clsid:{'GetCWApp':{'IGetActiveDoc':doc}}}
    def member(obj,name,*args):
        state['calls'].append(name);value=obj[name];value=value(*args) if callable(value) else value
        if name==event_getter:state['event']=True
        return value
    def check():
        if state['event']:raise ValueError('CAM event')
    monkeypatch.setattr(cam,'_member',member);monkeypatch.setattr(cam,'_typed',lambda x,*args:x)
    monkeypatch.setattr(guarded,'_typed',lambda x,*args:x)
    monkeypatch.setattr(guarded,'document_snapshot',lambda sw:dict(path=str(tmp_path/'fixture.sldprt'),title='fixture.sldprt',type=1,needs_save=False))
    with pytest.raises(ValueError,match='CAM event'):
        cam._capture_crop(sw,'clsid',TLB,dict(setup_index=0,operation_index=0,expected_operation_type=2),0,
            str(tmp_path/'fixture.sldprt'),check=check,diagnostic={})
    assert state['calls'][-1]==event_getter
    assert state['calls'].count(event_getter)==1

@pytest.mark.parametrize('event_getter',['IGetEnumSetups','Count','Item'])
def test_crop_remaining_feature_snapshot_uses_guarded_collections(crop_probe,monkeypatch,event_getter):
    from scripts import sw_cam_turn_feature_attribute as guarded
    p=crop_probe;state={'event':False,'calls':[]};raw_setup=object()
    collection={'Count':1,'Item':lambda i:raw_setup};machine={'IGetEnumSetups':collection}
    p.sw.ActiveDoc=N(GetActiveSketch2=None)
    monkeypatch.setattr(cam,'_capture_crop',lambda *a,**kw:(deepcopy(p.before),dict(doc=p.doc,machine=machine,app=p.app)))
    monkeypatch.setattr(sketches,'inspect_meridional_plane',lambda *a:(p.before['plane'],object()))
    monkeypatch.setattr(guarded,'_typed',lambda x,*a:x)
    original=cam._member
    def member(obj,name,*args):
        if isinstance(obj,dict):
            state['calls'].append(name);value=obj[name];value=value(*args) if callable(value) else value
            if name==event_getter:state['event']=True
            return value
        return original(obj,name,*args)
    def check():
        if state['event']:raise ValueError('CAM event')
    monkeypatch.setattr(cam,'_member',member)
    with pytest.raises(ValueError,match='CAM event'):
        REAL_SNAPSHOT(p.sw,'clsid',TLB,p.before['config'],check=check)
    assert state['calls'][-1]==event_getter

def test_crop_returned_new_id_getter_event_stops_before_further_capture(crop_probe):
    p=crop_probe
    def returned_id(obj):
        p.session.data['event_count']=1
        return (99,True)
    p.doc.GetCWObjectID.side_effect=returned_id
    r=p.apply()
    assert r['status']=='uncertain' and r['native_call_returned']
    phases=[c.kwargs['diagnostic']['phase'] for c in p.captures.call_args_list]
    assert 'after_feature' not in phases
    assert p.setup.CreateTurnFeature.call_count==1


@pytest.mark.parametrize('reverse',[False,True])
def test_created_crop_reports_actual_native_order_without_reversal_setter(crop_probe,reverse):
    p=crop_probe
    if reverse:
        def flip():
            line=p.state['current']['features'][-1]['profile']['segments'][0]
            line['start_native'],line['end_native']=line['end_native'],line['start_native']
        p.state['on_create']=flip
    r=p.apply()
    assert r['readback_verified']
    order=r['created_feature_orientation']
    assert order['endpoint_order']==('reversed_by_native' if reverse else 'same_as_requested')
    assert order['same_order_verified'] is (not reverse)
    assert not order['thread_direction_verified'] and not order['automatic_reversal_performed']
    assert order['requested_endpoints_native']==[[30.,0.,9.],[30.,0.,7.]]
    assert order['returned_endpoints_native']==(order['requested_endpoints_native'][::-1] if reverse else order['requested_endpoints_native'])
    assert p.setup.CreateTurnFeature.call_count==1
