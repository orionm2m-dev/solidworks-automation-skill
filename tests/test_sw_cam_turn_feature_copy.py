"""Real guarded source/copy line+arc reads and one-call copy qualification."""
from copy import deepcopy
from ctypes import HRESULT, POINTER, c_int
from ctypes.wintypes import VARIANT_BOOL
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_sw_cam_turn_variable_allowance import env
from test_sw_cam_turn_bore_options import bore
from test_sw_cam_turn_setup_context import current
from test_sw_cam_turn_reverse_setup import insertion
from scripts import sw_cam_turn_reverse_setup as reverse
from scripts import sw_cam_turn_feature_copy as core


@pytest.fixture
def copying(insertion,monkeypatch):
    e=insertion
    for name in ("CamMessageSession","_member","_typed","document_snapshot","_items","_object_id","_inventory","files","_bootstrap","local_evidence_root"):
        monkeypatch.setattr(core,name,getattr(reverse,name))
    monkeypatch.setattr(core,"copy_abi",lambda path:None)
    def make_feature(native_id,shift=0.):
        def point(x,y,z):return {"GetCoordinates":(x,y,z+shift)}
        first=point(0.,0.,1.);last=point(0.,0.,3.);centre=point(1.,0.,2.)
        line=dict(GetTurnSegmentType=0,GetStartPosition=lambda:first,GetEndPosition=lambda:last,
            GetLineSegmentParam=lambda owner:(20.,22.,2.,2.1,5.,True))
        arc=dict(GetTurnSegmentType=1,GetStartPosition=lambda:last,GetEndPosition=lambda:first,
            GetArcSegmentParam=lambda owner:(22.,20.,2.,.3,centre,True))
        return dict(native_id=native_id,FeatureName="Bore" if native_id==11 else "Bore copy",
            FeatType=2,GetTurnFeatureType=3,Attribute=4,GetAttributeName="native bore",
            GetMinMaxDiameter=(20.,30.),GetStartPosition=(0.,0.,1.+shift),GetEndPosition=(0.,0.,3.+shift),
            IGetEnumTurnSegments=e["collection"]([line,arc]),GetSpindleType=0)
    e["feature"].update(make_feature(11))
    target=dict(e["feature_setup"],native_id=300,IGetEnumFeatures=e["collection"]([]),
        Axis=(0.,0.,-1000.),IsReverseDirection=True,QueryInterface=lambda iid:"target")
    target_op=dict(native_id=400,IGetEnumOperations=e["collection"]([]),GetSetup=lambda:target,
        Axis=(0.,0.,-1.),GetSetupOriginInFCSSpace=(0.,0.,0.),IGetXYTransform=lambda:e["transforms"][1])
    e.update(target=target,target_op=target_op,copy_calls=[],make_feature=make_feature)
    e["machine"]["IGetEnumSetups"]=e["collection"]([e["feature_setup"],target])
    e["machine"]["IGetEnumOpSetups"]=e["collection"]([e["setup"],target_op])
    e["inventory"].update(feature_setup_count=2,operation_setup_count=2,feature_counts_by_setup=[1,0])
    e["args"].update(expected_feature_setup_count=2,expected_operation_setup_count=2,
        expected_source_feature_native_id=11,target_feature_setup_native_id=300,target_operation_setup_native_id=400)
    e["marker"]=core.marker_path(dict(device=1,inode=123))
    def copy(source,anchor,make_copy,clone_operations):
        assert source["native_id"]==11 and anchor is None and make_copy is True and clone_operations is False
        assert e["marker"].exists()
        pending=json.loads(e["receipt"].read_text(encoding="utf-8"))
        assert pending["native_dispatch_pending"] and pending["native_call_count"]==1
        e["copy_calls"].append((source["native_id"],anchor,make_copy,clone_operations))
        if e.get("exception"):raise OSError("reply lost")
        if not e.get("no_add"):
            e["new_feature"]=make_feature(33,e.get("coordinate_shift",0.))
            target["IGetEnumFeatures"]=e["collection"]([e["new_feature"]])
            e["inventory"].update(feature_count=2,feature_counts_by_setup=[1,1])
            e["dirty"]=True
        if e.get("after_copy"):e["after_copy"](e)
        return e.get("return_value",True)
    target["CopyFeatureToThisSetup"]=copy
    e["run"]=lambda **kw:core.qualify_turn_feature_copy(e["sw"],"clsid","fixture.tlb",**dict(e["args"],**kw))
    return e


def test_prepare_two_complete_profiles_without_mutation(copying):
    e=copying;r=e["run"]()
    assert r["status"]=="prepared" and r["apply_eligible"],r
    assert r["before"]==r["after"] and len(r["captures"])==2
    profile=r["before"]["source_feature"]["profile"]
    assert profile["segment_count"]==2
    assert profile["segments"][0]["line_native"]["length_along_axis"]==2.
    assert profile["segments"][1]["arc_native"]["radius"]==.3
    assert e["calls"].count("GetLineSegmentParam")==2 and e["calls"].count("GetArcSegmentParam")==2
    assert not e["copy_calls"] and not e["marker"].exists()
    assert not set(e["calls"]) & {"IGetAllDefaultOperations","GenerateOpPlan","GenerateToolpath","SetData","InsertTurnSetup1","Save"}


@pytest.mark.parametrize("coordinate_shift",[0.,10.])
def test_one_fixed_null_anchor_copy_preserves_originals_without_geometry_claim(copying,coordinate_shift):
    e=copying;e["coordinate_shift"]=coordinate_shift;r=e["apply"]()
    assert r["status"]=="review_required" and r["readback_verified"],r
    assert e["copy_calls"]==[(11,None,True,False)]
    assert r["native_call_count"]==r["native_calls_returned_count"]==1 and not r["native_dispatch_pending"]
    assert r["before"]["source_feature"]==r["after"]["source_feature"]
    assert r["before"]["operation_setups"]==r["after"]["operation_setups"]
    assert r["after"]["copied_feature"]["native_id"]==33
    assert r["after"]["feature_setups"][1]["feature_native_ids"]==[33]
    assert r["after"]["operation_setups"][1]["operations"]==[]
    assert len(r["captures"])==5 and r["captures"][0]["state"]==r["captures"][2]["state"]
    assert r["captures"][-1]["state"]==r["captures"][-2]["state"]
    assert not r["profile_geometry_equivalence_verified"] and not r["null_anchor_semantics_qualified"]
    assert not r["verification"]["profile_geometry_equivalence_verified"]
    assert not any(r[x] for x in ("model_saved","GOP_attempted","GTP_attempted","automatic_retry","automatic_rollback","physical_access_qualified"))
    assert e["marker"].exists()
    assert e["run"]()["status"]=="error" and len(e["copy_calls"])==1


@pytest.mark.parametrize("getter",["context","inventory","GetSetup","Axis","IsReverseDirection","GetData",
    "IGetTool","Suppressed","FeatureName","FeatType","GetTurnFeatureType","Attribute","GetAttributeName",
    "GetMinMaxDiameter","GetStartPosition","GetEndPosition","IGetEnumTurnSegments","GetTurnSegmentType",
    "GetCoordinates","GetLineSegmentParam","GetArcSegmentParam","GetSpindleType"])
def test_event_in_old_profile_or_setup_stops_all_following_getters(copying,getter):
    e=copying
    def hook(name):
        if name==getter:e["session"].state["event_count"]=1
    e["hook"]=hook;r=e["run"]()
    assert r["status"]=="error" and e["calls"][-1]==getter and not e["copy_calls"]
    assert not e["marker"].exists()


@pytest.mark.parametrize("field,value",[
    ("expected_source_feature_native_id",True),("expected_source_feature_native_id",99),
    ("target_feature_setup_native_id",100),("target_operation_setup_native_id",200),
    ("target_feature_setup_native_id",400),("expected_feature_setup_count",1),
    ("expected_operation_setup_count",1),("expected_feature_count",64),
    ("process_id",True),("expected_process_create_time",float("nan")),("expected_source_sha256","x"*64),
    ("qualification_only",1),("message_policy","accept"),("expected_linked_feature_ids",[True]),
    ("action","copy"),("expected_state_sha256","a"*64),("receipt_path",r"C:\review\apply.json")])
def test_invalid_request_rejected_before_native(copying,field,value):
    e=copying;r=e["run"](**{field:value})
    assert r["status"]=="error" and not e["calls"] and not e["marker"].exists()


@pytest.mark.parametrize("fault",["feature_nonempty","op_nonempty","wrong_target_link","reverse_false","wrong_axis","source_absent"])
def test_source_and_empty_reverse_target_are_exact(copying,fault):
    e=copying
    if fault=="feature_nonempty":e["target"]["IGetEnumFeatures"]=e["collection"]([e["make_feature"](77)])
    elif fault=="op_nonempty":e["target_op"]["IGetEnumOperations"]=e["collection"]([e["operation"]])
    elif fault=="wrong_target_link":e["target_op"]["GetSetup"]=lambda:e["feature_setup"]
    elif fault=="reverse_false":e["target"]["IsReverseDirection"]=False
    elif fault=="wrong_axis":e["target"]["Axis"]=(1.,0.,0.)
    else:e["feature_setup"]["IGetEnumFeatures"]=e["collection"]([])
    r=e["run"]()
    assert r["status"]=="error" and not e["copy_calls"] and not e["marker"].exists()


@pytest.mark.parametrize("returned,no_add",[(False,False),(False,True),(1,False),(None,False)])
def test_false_or_ambiguous_return_never_qualifies_or_retries(copying,returned,no_add):
    e=copying;e.update(return_value=returned,no_add=no_add);r=e["apply"]()
    assert r["status"]=="uncertain" and not r["readback_verified"]
    assert len(e["copy_calls"])==1 and e["marker"].exists()
    if returned is False and not no_add:
        assert len(r["captures"])==5 and r["captures"][-1]["state"]["copied_feature"]["native_id"]==33
    assert e["run"]()["status"]=="error" and len(e["copy_calls"])==1


@pytest.mark.parametrize("fault",["extra_feature","operation_cloned","source_moved","old_profile","old_tool","old_paths",
    "old_frame","new_type","new_attribute","new_spindle","new_segment_count","new_incomplete_segment","wrong_setup"])
def test_unexpected_delta_is_uncertain_without_second_copy(copying,fault):
    e=copying
    def change(e):
        if fault=="extra_feature":
            e["target"]["IGetEnumFeatures"]=e["collection"]([e["new_feature"],e["make_feature"](34)])
            e["inventory"]["feature_count"]=3;e["inventory"]["feature_counts_by_setup"]=[1,2]
        elif fault=="operation_cloned":e["inventory"]["operation_count"]=2
        elif fault=="source_moved":e["feature_setup"]["IGetEnumFeatures"]=e["collection"]([])
        elif fault=="old_profile":e["feature"]["GetStartPosition"]=(2.,0.,1.)
        elif fault=="old_tool":e["operation"]["IGetTool"]={"native_id":99}
        elif fault=="old_paths":e["inventory"]["operations"][0]["toolpath_record_counts"]=[6,6]
        elif fault=="old_frame":e["setup"]["GetSetupOriginInFCSSpace"]=(1.,0.,8.)
        elif fault=="new_type":e["new_feature"]["GetTurnFeatureType"]=7
        elif fault=="new_attribute":e["new_feature"]["Attribute"]=5
        elif fault=="new_spindle":e["new_feature"]["GetSpindleType"]=1
        elif fault=="new_segment_count":
            original=e["new_feature"]["IGetEnumTurnSegments"]
            e["new_feature"]["IGetEnumTurnSegments"]=e["collection"]([original["Item"](0)])
        elif fault=="new_incomplete_segment":
            e["new_feature"]["IGetEnumTurnSegments"]["Item"](0)["GetLineSegmentParam"]=lambda owner:(20.,22.,2.,2.,5.,False)
        else:
            e["feature_setup"]["IGetEnumFeatures"]=e["collection"]([e["feature"],e["new_feature"]])
            e["target"]["IGetEnumFeatures"]=e["collection"]([])
    e["after_copy"]=change;r=e["apply"]()
    assert r["status"]=="uncertain" and not r["readback_verified"] and len(e["copy_calls"])==1,r
    assert e["marker"].exists()


@pytest.mark.parametrize("getter",["CopyFeatureToThisSetup","GetLineSegmentParam","GetArcSegmentParam"])
def test_event_during_copy_or_new_profile_stops_following_getters(copying,getter):
    e=copying
    def hook(name):
        if e["copy_calls"] and name==getter:e["session"].state["event_count"]=1
    e["hook"]=hook;r=e["apply"]()
    assert r["status"]=="uncertain" and len(e["copy_calls"])==1
    assert e["calls"][-1]==getter


def test_lost_native_reply_is_pending_and_not_replayed(copying):
    e=copying;e["exception"]=True;r=e["apply"]()
    assert r["status"]=="uncertain" and r["native_dispatch_pending"] and r["native_calls_returned_count"]==0
    assert e["marker"].exists() and len(e["copy_calls"])==1
    assert e["run"]()["status"]=="error" and len(e["copy_calls"])==1


def test_pending_receipt_precedes_fresh_guard_and_blocks_changed_source_profile(copying,monkeypatch):
    e=copying;write=core._write_receipt
    def changed(path,report,**kwargs):
        write(path,report,**kwargs)
        if report.get("native_dispatch_pending"):e["feature"]["Attribute"]=99
    monkeypatch.setattr(core,"_write_receipt",changed)
    r=e["apply"]()
    assert r["status"]=="uncertain" and not e["copy_calls"] and e["marker"].exists()


@pytest.mark.parametrize("fault",["pending_write","marker_write","disconnect"])
def test_durable_failure_or_event_cleanup_cannot_report_success(copying,monkeypatch,fault):
    e=copying
    if fault=="disconnect":
        original=core.CamMessageSession
        class Broken(original):
            def __exit__(self,*args):
                super().__exit__(*args);self.state["disconnect_errors"]=["failed"]
        monkeypatch.setattr(core,"CamMessageSession",Broken)
        prepared=e["run"]()
        assert prepared["status"]=="error"
        monkeypatch.setattr(core,"CamMessageSession",original)
        good=e["run"]();assert good["status"]=="prepared"
        monkeypatch.setattr(core,"CamMessageSession",Broken)
        r=e["run"](action="apply",expected_state_sha256=good["state_sha256"],receipt_path=str(e["receipt"]))
        assert r["status"]=="uncertain" and len(e["copy_calls"])==1
    else:
        writer=core._write_receipt
        def fail(path,report,**kwargs):
            if fault=="pending_write" and report.get("native_dispatch_pending"):raise OSError("durability")
            if fault=="marker_write" and report.get("status")=="claimed_no_replay":raise OSError("durability")
            return writer(path,report,**kwargs)
        monkeypatch.setattr(core,"_write_receipt",fail)
        r=e["apply"]()
        assert r["status"] in ("error","uncertain") and not e["copy_calls"]


@pytest.mark.parametrize("fault",["source","process","protected"])
def test_boundary_pins_before_mutation(copying,fault):
    e=copying
    def hook(name):
        if name=="GetLineSegmentParam":
            if fault=="source":e["digest"]="c"*64
            elif fault=="process":e["process"]["create_time"]+=1
            else:e["protected_changed"]=True
    e["hook"]=hook;r=e["run"]()
    assert r["status"]=="error" and not e["copy_calls"]


def test_second_post_profile_capture_drift_is_uncertain(copying,monkeypatch):
    e=copying;capture=core._capture;calls=0
    def wrapped(*args,**kwargs):
        nonlocal calls
        if kwargs.get("after"):
            calls+=1
            if calls==2:e["new_feature"]["GetStartPosition"]=(9.,0.,1.)
        return capture(*args,**kwargs)
    monkeypatch.setattr(core,"_capture",wrapped)
    r=e["apply"]()
    assert r["status"]=="uncertain" and len(e["copy_calls"])==1
    assert r["captures"][-1]["state"]!=r["captures"][-2]["state"]


@pytest.mark.parametrize("fault",["none","iid","args","flags","dispid","return","duplicate"])
def test_exact_copy_abi_is_metadata_only(monkeypatch,fault):
    from comtypes.automation import IDispatch
    method=SimpleNamespace(name="CopyFeatureToThisSetup",restype=HRESULT,idlflags=(13,),
        argtypes=(POINTER(IDispatch),POINTER(IDispatch),VARIANT_BOOL,VARIANT_BOOL,POINTER(VARIANT_BOOL)),
        paramflags=((1,"pFeat"),(1,"pAfter"),(1,"bMakeCopy"),(1,"bCloneOperation"),(10,"pRet")))
    interface=SimpleNamespace(_iid_=core._INTERFACES["ICWBaseSetup"],_methods_=[method])
    if fault=="iid":interface._iid_="{00000000-0000-0000-0000-000000000000}"
    elif fault=="args":method.argtypes=(c_int,)
    elif fault=="flags":method.paramflags=((1,"x"),)*5
    elif fault=="dispid":method.idlflags=(9,)
    elif fault=="return":method.restype=c_int
    elif fault=="duplicate":interface._methods_.append(method)
    monkeypatch.setattr(core,"_interface_class",lambda *args:interface)
    check=Mock();monkeypatch.setattr(core.frame,"setup_abi",check)
    if fault=="none":core.copy_abi("fixture");check.assert_called_once_with("fixture")
    else:
        with pytest.raises(ValueError):core.copy_abi("fixture")
        check.assert_not_called()


def test_source_too_large_for_two_profile_readback_stops_before_segments(copying):
    e=copying
    e["feature"]["IGetEnumTurnSegments"]={"Count":257}
    r=e["run"]()
    assert r["status"]=="error" and not e["copy_calls"] and not e["marker"].exists()
    assert "GetLineSegmentParam" not in e["calls"]
