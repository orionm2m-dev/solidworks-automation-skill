"""Actual bounded snapshot traversal and one-dispatch lifecycle over native-shaped data."""
from copy import deepcopy
from ctypes import HRESULT, c_long, c_double
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_sw_cam_turn_variable_allowance import env
from test_sw_cam_turn_bore_options import bore
from test_sw_cam_turn_setup_context import current
from test_sw_cam_turn_reverse_setup import insertion
from test_sw_cam_turn_feature_copy import copying
from scripts import sw_cam_turn_feature_copy as copying_core
from scripts import sw_cam_turn_feature_plan_append as core
from scripts import sw_cam_operation_profile as profile
from scripts import sw_cam_turn_feature_attribute as feature_reader


@pytest.fixture
def planning(copying, monkeypatch):
    e = copying
    for name in ("CamMessageSession", "_member", "_typed", "document_snapshot", "_items", "_object_id",
                 "files", "_bootstrap", "local_evidence_root"):
        monkeypatch.setattr(core, name, getattr(copying_core, name))
    monkeypatch.setattr(core, "gop_abi", lambda path: None)
    # Traverse the actual inventory implementation, not a preconstructed snapshot.
    monkeypatch.setattr(feature_reader, "_typed", lambda obj, *args: obj)
    monkeypatch.setattr(feature_reader, "_items", core._items)
    monkeypatch.setattr(core, "_inventory", feature_reader._inventory)
    monkeypatch.setattr(core.reverse, "_inventory", feature_reader._inventory)
    e["feature"].update(GetTurnFeatureType=2, Attribute=50, GetAttributeName="Rough-Finish")
    copied = e["make_feature"](33)
    copied.update(GetTurnFeatureType=2, Attribute=50, GetAttributeName="Rough-Finish")
    e["new_feature"] = copied
    e["target"]["IGetEnumFeatures"] = e["collection"]([copied])
    e["machine"]["IGetWorkpiece"] = {"GetTurnWorkpieceType": 0}
    holder = dict(GetHolderType=2, GetHolderId=71, GetToolOrientationForOperation=lambda op: 0,
        HolderShape=1, GetHolderThickness=5., ShankLength=80., LeadAngle=95., BackClearAngle=5.,
        FrontClearAngle=5., ZInsertOffset=2., XInsertOffset=2., Protrusion=20., BoringBarDiameter=12.)
    insert = dict(ToolType=1, InsertType=1, Thickness=3., IncludedAngle=80., NoseRadius=.4,
        InscribedCircle=9., IGetTurnToolHolder=lambda: holder)
    tool = dict(native_id=55, ToolType=15, GetToolInfoString="bounded own tool", turn=insert)
    def typed(obj, kind, *args):
        return obj["turn"] if kind == "ICWTurnTool" else obj
    monkeypatch.setattr(profile, "_typed", typed)
    old = []
    for i in range(11):
        op = dict(e["operation"], native_id=22+i, IGetTool=lambda: tool,
            GetIsToolpathGenerated=True, IGetEnumToolpaths=e["collection"]([{"RecordCount":12+i}]))
        old.append(op)
    e["operation"] = old[0]
    e["setup"]["IGetEnumOperations"] = e["collection"](old)
    e["args"].update(expected_feature_count=2, expected_operation_count=11,
        expected_generated_operation_count=11, expected_toolpath_record_count=sum(range(12,23)),
        expected_copied_feature_native_id=33, expected_new_operation_types=[14,9,5,6])
    with core.CamMessageSession(e["app"], "fixture"):
        observed = copying_core._profile({}, copied, 300, "fixture", core._member, [0])
    e["args"]["expected_copied_feature_sha256"] = core._digest(observed)
    e["calls"].clear()
    e["marker"] = core.marker_path(dict(device=1,inode=123),33)
    e.update(gop_calls=[], old=old, own_tool=tool, own_insert=insert, holder=holder)
    def generate(preference):
        assert type(preference) is int and preference == 1
        assert e["marker"].exists()
        pending = json.loads(e["receipt"].read_text(encoding="utf-8"))
        assert pending["native_dispatch_pending"] and pending["native_call_count"] == 1
        e["gop_calls"].append(preference)
        if e.get("lost_reply"): raise OSError("native reply lost")
        new = [dict(native_id=90+i, OpernType=kind, Suppressed=False, IGetTool=lambda: tool,
            IGetAllFeatures=e["collection"]([copied]), GetIsToolpathGenerated=False)
            for i,kind in enumerate(e["args"]["expected_new_operation_types"])]
        e["created"] = new
        e["target_op"]["IGetEnumOperations"] = e["collection"](new)
        e["dirty"] = True
        if e.get("after_gop"): e["after_gop"](e)
        return None
    copied["GenerateOpPlan"] = generate
    e["run"] = lambda **kw: core.qualify_turn_feature_plan_append(e["sw"],"clsid","fixture.tlb",**dict(e["args"],**kw))
    return e


def test_prepare_traverses_two_snapshots_with_profiles_and_own_tools_without_mutation(planning):
    e=planning; r=e["run"]()
    assert r["status"] == "prepared", r
    assert len(r["captures"]) == 2 and r["before"] == r["after"]
    assert len(r["before"]["operation_setups"][0]["operations"]) == 11
    assert r["before"]["operation_setups"][0]["operations"][0]["observed_own_tool"]["holder"]["dimensions_native"]["BoringBarDiameter"] == 12.
    assert not e["gop_calls"] and not e["marker"].exists()
    assert not set(e["calls"]) & {"IGetAllDefaultOperations", "GenerateOpPlan", "GenerateToolpath", "Save", "SetData", "CopyFeatureToThisSetup"}


def test_none_return_qualifies_only_exact_append_and_preserves_eleven_old_operations(planning):
    e=planning; r=e["apply"]()
    assert r["status"] == "review_required" and r["readback_verified"], r
    assert e["gop_calls"] == [1] and r["native_return_type"] == "NoneType"
    assert r["native_call_count"] == r["native_calls_returned_count"] == 1 and not r["native_dispatch_pending"]
    assert r["verification"]["new_operation_types"] == [14,9,5,6]
    assert r["before"]["operation_setups"][0] == r["after"]["operation_setups"][0]
    assert r["before"]["source_feature"] == r["after"]["source_feature"]
    assert r["before"]["copied_feature"] == r["after"]["copied_feature"]
    assert len(r["captures"]) == 5 and r["captures"][-1]["state"] == r["captures"][-2]["state"]
    assert not any(r[k] for k in ("tool_holder_content_preserved", "model_saved", "GTP_attempted", "attribute_write_attempted", "automatic_retry", "production_qualified"))
    assert e["run"]()["status"] == "error" and e["gop_calls"] == [1]
    assert json.loads(e["receipt"].read_text())["readback_verified"]
    assert r["receipt_created"] is True and r["receipt_path"] == str(e["receipt"])


@pytest.mark.parametrize("fault", ["old_order", "old_tool_id", "same_tool_insert", "same_tool_holder", "old_paths", "old_profile", "copied_attribute", "old_frame", "new_type", "new_order", "new_link", "new_suppression", "new_generated", "extra", "missing"])
def test_side_effects_revoke_success_and_never_replay(planning, fault):
    e=planning
    def change(e):
        if fault=="old_order": e["setup"]["IGetEnumOperations"] = e["collection"](e["old"][:1]+list(reversed(e["old"][1:])))
        elif fault=="old_tool_id": e["old"][1]["IGetTool"] = dict(e["own_tool"], native_id=999)
        elif fault=="same_tool_insert": e["own_insert"]["NoseRadius"] = .8
        elif fault=="same_tool_holder": e["holder"]["BoringBarDiameter"] = 20.
        elif fault=="old_paths": e["old"][1]["IGetEnumToolpaths"] = e["collection"]([{"RecordCount":6},{"RecordCount":7}])
        elif fault=="old_profile": e["feature"]["GetStartPosition"] = (5.,0.,0.)
        elif fault=="copied_attribute": e["new_feature"]["Attribute"] = 99
        elif fault=="old_frame": e["setup"]["GetSetupOriginInFCSSpace"] = (2.,3.,4.)
        elif fault=="new_type": e["created"][0]["OpernType"] = 5
        elif fault=="new_order": e["target_op"]["IGetEnumOperations"] = e["collection"](list(reversed(e["created"])))
        elif fault=="new_link": e["created"][0]["IGetAllFeatures"] = e["collection"]([])
        elif fault=="new_suppression": e["created"][0]["Suppressed"] = True
        elif fault=="new_generated": e["created"][0].update(GetIsToolpathGenerated=True, IGetEnumToolpaths=e["collection"]([]))
        elif fault=="extra": e["target_op"]["IGetEnumOperations"] = e["collection"](e["created"]+[dict(e["created"][0],native_id=100)])
        else: e["target_op"]["IGetEnumOperations"] = e["collection"](e["created"][:-1])
    e["after_gop"] = change; r=e["apply"]()
    assert r["status"]=="uncertain" and not r["readback_verified"] and e["gop_calls"]==[1],r
    assert e["run"]()["status"]=="error" and e["gop_calls"]==[1]


@pytest.mark.parametrize("getter", ["Count", "Item", "GetIsToolpathGenerated", "RecordCount", "IGetTool", "GetToolInfoString", "NoseRadius", "BoringBarDiameter", "GetLineSegmentParam", "GetArcSegmentParam"])
def test_events_halt_at_first_affected_getter(planning, getter):
    e=planning
    def hook(name):
        if name==getter: e["session"].state["event_count"] = 1
    e["hook"] = hook; r=e["run"]()
    assert r["status"]=="error" and e["calls"][-1]==getter and not e["gop_calls"]


@pytest.mark.parametrize("getter", ["GenerateOpPlan", "GetLineSegmentParam", "BoringBarDiameter"])
def test_event_during_dispatch_or_readback_is_uncertain(planning, getter):
    e=planning
    def hook(name):
        if e["gop_calls"] and name==getter: e["session"].state["event_count"] = 1
    e["hook"] = hook; r=e["apply"]()
    assert r["status"]=="uncertain" and e["calls"][-1]==getter and e["gop_calls"]==[1]


def test_lost_reply_remains_pending_and_cannot_replay(planning):
    e=planning; e["lost_reply"]=True; r=e["apply"]()
    assert r["status"]=="uncertain" and r["native_dispatch_pending"] and not r["native_calls_returned_count"]
    assert e["run"]()["status"]=="error" and e["gop_calls"]==[1]


def test_pending_receipt_precedes_full_fresh_capture(planning, monkeypatch):
    e=planning; write=core._write_receipt
    def changed(path, report, **kwargs):
        write(path,report,**kwargs)
        if report.get("native_dispatch_pending"): e["holder"]["BoringBarDiameter"]=30.
    monkeypatch.setattr(core,"_write_receipt",changed); r=e["apply"]()
    assert r["status"]=="uncertain" and e["marker"].exists() and not e["gop_calls"]


@pytest.mark.parametrize("fault",["marker_write","pending_write","cleanup"])
def test_durable_or_event_cleanup_failure_cannot_qualify(planning, monkeypatch, fault):
    e=planning; write=core._write_receipt
    if fault=="cleanup":
        original=core.CamMessageSession
        class Broken(original):
            def __exit__(self,*args):
                super().__exit__(*args); self.state["disconnect_errors"]=["failed"]
        prepared=e["run"](); monkeypatch.setattr(core,"CamMessageSession",Broken)
        r=e["run"](action="apply",expected_state_sha256=prepared["state_sha256"],receipt_path=str(e["receipt"]))
    else:
        def failed(path,report,**kw):
            if (fault=="marker_write" and report.get("status")=="claimed_no_replay") or (fault=="pending_write" and report.get("native_dispatch_pending")):
                raise OSError("durability unavailable")
            write(path,report,**kw)
        monkeypatch.setattr(core,"_write_receipt",failed); r=e["apply"]()
    assert not r["readback_verified"] and r["status"] in ("error","uncertain")
    if fault!="cleanup": assert not e["gop_calls"]


@pytest.mark.parametrize("field,value", [("expected_copied_feature_native_id",True),("expected_copied_feature_native_id",11),
    ("expected_copied_feature_sha256","x"*64),("expected_new_operation_types",[]),
    ("expected_new_operation_types",[True]),("expected_new_operation_types",[12]),
    ("expected_new_operation_types",[5,5]),("expected_new_operation_types",[5.]),("expected_operation_count",512)])
def test_new_request_gates_precede_native(planning, field, value):
    e=planning; r=e["run"](**{field:value})
    assert r["status"]=="error" and not e["calls"] and not e["gop_calls"]


@pytest.mark.parametrize("fault",["none","helpstring","property","iid","args","out","dispid","restype","duplicate"])
def test_exact_hresult_only_abi(monkeypatch, fault):
    method=SimpleNamespace(name="GenerateOpPlan",restype=HRESULT,idlflags=(3,),argtypes=(c_long,),paramflags=((1,"preference"),))
    interface=SimpleNamespace(_iid_=core._INTERFACES["ICWFeature"],_methods_=[method])
    if fault=="helpstring": method.idlflags=(3,"method GenerateOpPlan")
    elif fault=="property": method.idlflags=(3,"propget")
    elif fault=="iid": interface._iid_="{00000000-0000-0000-0000-000000000000}"
    elif fault=="args": method.argtypes=(c_double,)
    elif fault=="out": method.paramflags=((2,"preference"),)
    elif fault=="dispid": method.idlflags=(4,)
    elif fault=="restype": method.restype=c_double
    elif fault=="duplicate": interface._methods_.append(method)
    monkeypatch.setattr(core,"_interface_class",lambda *args:interface)
    check=Mock(); monkeypatch.setattr(core.frame,"setup_abi",check)
    if fault in ("none","helpstring"): core.gop_abi("fixture"); check.assert_called_once_with("fixture")
    else:
        with pytest.raises(ValueError): core.gop_abi("fixture")
        check.assert_not_called()


def test_existing_drill_is_bounded_and_unavailable_geometry_is_explicit(planning):
    e=planning
    drill=dict(native_id=56,ToolType=15,GetToolInfoString="observed drill",turn=dict(ToolType=2))
    e["old"][1]["IGetTool"] = lambda:drill
    r=e["apply"]()
    assert r["status"]=="review_required" and r["readback_verified"],r
    observed=r["before"]["operation_setups"][0]["operations"][1]["observed_own_tool"]
    assert observed["parameters_status"]=="unavailable" and not observed["interface_probe_attempted"]
    assert not r["tool_holder_content_preserved"] and "IGetDrillTool" not in e["calls"]


def test_valid_but_wrong_copied_profile_digest_blocks_before_claim(planning):
    e=planning; r=e["run"](expected_copied_feature_sha256="b"*64)
    assert r["status"]=="error" and not e["marker"].exists() and not e["gop_calls"]


def test_second_post_snapshot_must_agree(planning, monkeypatch):
    e=planning; capture=core._capture; count=[0]
    def drift(*args,**kwargs):
        result=capture(*args,**kwargs)
        if kwargs.get("after"):
            count[0]+=1
            if count[0]==1: e["holder"]["BoringBarDiameter"]=18.
        return result
    monkeypatch.setattr(core,"_capture",drift)
    r=e["apply"]()
    assert r["status"]=="uncertain" and not r["readback_verified"] and e["gop_calls"]==[1]


@pytest.mark.parametrize("where", ["source", "copied", "both"])
def test_type_three_is_rejected_even_with_matching_copied_digest(planning, where):
    e=planning
    if where in ("source","both"): e["feature"]["GetTurnFeatureType"]=3
    if where in ("copied","both"): e["new_feature"]["GetTurnFeatureType"]=3
    with core.CamMessageSession(e["app"], "fixture"):
        observed=copying_core._profile({},e["new_feature"],300,"fixture",core._member,[0])
    e["args"]["expected_copied_feature_sha256"]=core._digest(observed)
    r=e["run"]()
    assert r["status"]=="error" and not e["marker"].exists() and not e["gop_calls"]


def test_internal_profile_enum_two_matches_source_and_copy(planning):
    e=planning; r=e["run"]()
    assert r["status"]=="prepared",r
    for key in ("source_feature","copied_feature"):
        assert r["before"][key]["profile"]["feature_type_raw"]==2
        assert r["before"][key]["profile"]["turn_feature_type_raw"]==2
        assert r["before"][key]["profile"]["attribute_id_raw"]==50
        assert r["before"][key]["profile"]["attribute_name"]=="Rough-Finish"
