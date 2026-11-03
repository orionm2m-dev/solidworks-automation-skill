"""Synthetic native traversal and durable one-dispatch failure qualification."""
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
from scripts import sw_cam_turn_variable_allowance as common
from scripts import sw_cam_turn_reverse_setup as core


@pytest.fixture
def insertion(current, monkeypatch, tmp_path):
    e=current
    e["inventory"]["stock"]=dict(type=0,parameters_modified=False,length_units="native_API_units_not_assumed")
    e["operation"]["IGetTool"]={"native_id":55}
    e["args"].update(expected_feature_setup_native_id=100,expected_operation_setup_native_id=200,
        protected_part_pins=[dict(path=r"C:\review\original.SLDPRT",sha256="b"*64),
            dict(path=r"C:\review\archive.SLDPRT",sha256="a"*64)],qualification_only=True,message_policy="vendor_default")
    for name in ("CamMessageSession","_member","_typed","document_snapshot","_context","_inventory","_items","_object_id"):
        monkeypatch.setattr(core,name,getattr(common,name))
    monkeypatch.setattr(core,"insertion_abi",lambda path:None)
    monkeypatch.setattr(core,"_bootstrap",lambda *args:e["app"])
    def isolated(sw, config, check):
        assert e["process"]["alive"] and e["process"]["process_id"]==config["process_id"]
        if e["process"]["create_time"] != config["expected_process_create_time"]:raise ValueError("Process lifetime changed")
        check()
    monkeypatch.setattr(core.guard,"isolated",isolated)
    def files(config,protected):
        if e["digest"]!=config["expected_source_sha256"] or e.get("protected_changed"):raise ValueError("Source changed")
        return dict(device=1,inode=123)
    monkeypatch.setattr(core,"files",files)
    monkeypatch.setattr(core,"local_evidence_root",lambda:tmp_path)
    e["marker"]=core.marker_path(dict(device=1,inode=123))
    e["receipt"]=tmp_path/"apply.json"
    e["insertions"]=[]
    def insert(reverse,anchor):
        assert reverse is True and anchor["native_id"]==100
        assert e["marker"].exists()
        pending=json.loads(e["receipt"].read_text(encoding="utf-8"))
        assert pending["native_dispatch_pending"] and pending["native_call_count"]==1
        assert pending["mutation_attempted"]
        e["insertions"].append((reverse,anchor["native_id"]))
        if e.get("raise_dispatch"):raise OSError("Native reply lost")
        new=dict(e["feature_setup"],native_id=300,IGetEnumFeatures=e["collection"]([]),
            Axis=(0.,0.,-1000.),IsReverseDirection=True,QueryInterface=lambda iid:"new_identity")
        e["new_feature_setup"]=new
        e["machine"]["IGetEnumSetups"]=e["collection"]([e["feature_setup"],new])
        e["inventory"].update(feature_setup_count=2,feature_counts_by_setup=[1,0])
        if e.get("new_op_setup"):
            new_op=dict(native_id=400,IGetEnumOperations=e["collection"]([]),GetSetup=lambda:new,
                Axis=(0.,0.,-1.),GetSetupOriginInFCSSpace=(0.,0.,0.),IGetXYTransform=lambda:e["transforms"][1])
            e["new_operation_setup"]=new_op
            e["machine"]["IGetEnumOpSetups"]=e["collection"]([e["setup"],new_op])
            e["inventory"]["operation_setup_count"]=2
        e["dirty"]=True
        if e.get("after_insert"):e["after_insert"](e)
        return None if e.get("null_return") else dict(new,native_id=999) if e.get("wrong_return") else new
    e["machine"]["InsertTurnSetup1"]=insert
    e["run"]=lambda **kw:core.qualify_turn_reverse_setup(e["sw"],"clsid","fixture.tlb",**dict(e["args"],**kw))
    def apply(**kw):
        prepared=e["run"]()
        assert prepared["status"]=="prepared",prepared
        e["prepared"]=prepared
        return e["run"](action="apply",expected_state_sha256=prepared["state_sha256"],receipt_path=str(e["receipt"]),**kw)
    e["apply"]=apply
    return e


def test_prepare_reads_two_real_full_captures_without_claim(insertion):
    e=insertion;r=e["run"]()
    assert r["status"]=="prepared" and r["apply_eligible"] and not r["mutation_attempted"]
    assert [x["label"] for x in r["captures"]]==["before","confirm_before"]
    assert r["captures"][0]["state"]==r["captures"][1]["state"]
    assert not e["marker"].exists() and not e["receipt"].exists()
    assert not e["insertions"]
    assert e["calls"].count("GetData")==8
    assert not set(e["calls"]) & {"IGetAllDefaultOperations","GenerateOperation","GenerateToolpath","Save","SetData","InsertTurnOpSetup"}


@pytest.mark.parametrize("optional",[False,True])
def test_single_insert_preserves_every_old_operation_and_observed_frame(insertion,optional):
    e=insertion;e["new_op_setup"]=optional;r=e["apply"]()
    assert r["status"]=="review_required" and r["readback_verified"],r
    assert e["insertions"]==[(True,100)]
    assert r["native_call_count"]==r["native_calls_returned_count"]==1 and not r["native_dispatch_pending"]
    assert [x["label"] for x in r["captures"]]==["before","confirm_before","dispatch_guard","after","confirm_after"]
    assert r["captures"][0]["state"]==r["captures"][2]["state"]
    assert r["captures"][3]["state"]==r["captures"][4]["state"]
    assert r["verification"]["new_feature_setup_native_id"]==300
    assert r["verification"]["new_operation_setup_native_ids"]==([400] if optional else [])
    assert r["before"]["operation_setups"]==r["after"]["operation_setups"][:1]
    assert e["marker"].exists() and json.loads(e["receipt"].read_text())["status"]=="review_required"
    for name in ("model_saved","GOP_attempted","GTP_attempted","persistence_verified","protected_CL_bytes_compared",
                 "raw_transform_matrix_preserved","coordinate_frame_verified","physical_access_qualified","production_qualified"):
        assert r[name] is False
    assert r["messages"]["disconnected"] and not r["messages"]["event_count"]


@pytest.mark.parametrize("getter",["context","inventory","Count","Item","native_id","IGetAllFeatures","OpernType",
    "GetSetup","QueryInterface","Axis","IsReverseDirection","IGetRefPoint","GetCoordinates",
    "IGetXYTransform","GetTypeInfo","GetTypeAttr","GetData","IGetTool","Suppressed"])
def test_event_in_capture_stops_every_following_native_getter(insertion,getter):
    e=insertion
    def hook(name):
        if name==getter:e["session"].state["event_count"]=1
    e["hook"]=hook;r=e["run"]()
    assert r["status"]=="error" and e["calls"][-1]==getter and not e["insertions"]
    assert not e["marker"].exists()


@pytest.mark.parametrize("field,value",[
    ("process_id",True),("expected_process_create_time",True),("expected_process_create_time",float("inf")),
    ("expected_source_sha256","invalid"),("expected_operation_native_id",0),
    ("expected_feature_setup_native_id",None),("expected_operation_setup_native_id",False),
    ("expected_feature_setup_count",2),("expected_operation_setup_count",2),("setup_index",1),
    ("expected_operation_type",7),("expected_linked_feature_ids",[True]),
    ("expected_linked_feature_ids",[11,11]),("expected_operation_count",True),
    ("expected_generated_operation_count",2),("qualification_only",1),("message_policy","accept_all"),
    ("action","probe"),("expected_state_sha256","c"*64),("receipt_path",r"C:\review\apply.json")])
def test_invalid_input_before_native_or_marker(insertion,field,value):
    e=insertion;r=e["run"](**{field:value})
    assert r["status"]=="error" and not e["calls"] and not e["marker"].exists()


@pytest.mark.parametrize("fault",["archive_missing","duplicate","target","bad_sha","unexpected_key"])
def test_protected_archive_request_is_strict(insertion,fault):
    e=insertion;pins=deepcopy(e["args"]["protected_part_pins"])
    if fault=="archive_missing":pins[1]["sha256"]="c"*64
    elif fault=="duplicate":pins[1]=deepcopy(pins[0])
    elif fault=="target":pins[1]["path"]=e["args"]["expected_document_path"]
    elif fault=="bad_sha":pins[0]["sha256"]="x"*64
    else:pins[0]["extra"]=1
    r=e["run"](protected_part_pins=pins)
    assert r["status"]=="error" and not e["calls"]


def test_changed_prepared_digest_prevents_claim(insertion):
    e=insertion;r=e["run"](action="apply",expected_state_sha256="c"*64,receipt_path=str(e["receipt"]))
    assert r["status"]=="error" and not e["marker"].exists() and not e["insertions"]
    assert e["receipt"].exists()


@pytest.mark.parametrize("fault",["null_return","wrong_return","raise_dispatch"])
def test_lost_or_wrong_return_is_uncertain_and_never_replayed(insertion,fault):
    e=insertion;e[fault]=True;r=e["apply"]()
    assert r["status"]=="uncertain" and not r["readback_verified"] and len(e["insertions"])==1
    assert e["marker"].exists()
    replay=e["run"]()
    assert replay["status"]=="error" and len(e["insertions"])==1
    if fault=="raise_dispatch":assert r["native_dispatch_pending"] and r["native_calls_returned_count"]==0


@pytest.mark.parametrize("fault",["feature_added","operation_added","feature_moved","old_tool","old_paths",
    "old_frame","old_feature_axis","reverse_false","wrong_axis","zero_axis","wrong_new_link","nonempty_new_op","second_new_feature"])
def test_side_effect_or_wrong_direction_is_uncertain_no_retry(insertion,fault):
    e=insertion
    e["new_op_setup"]=fault in ("wrong_new_link","nonempty_new_op")
    def change(e):
        if fault=="feature_added":
            e["new_feature_setup"]["IGetEnumFeatures"]=e["collection"]([dict(native_id=999)])
            e["inventory"]["feature_count"]=2;e["inventory"]["feature_counts_by_setup"]=[1,1]
        elif fault=="operation_added":e["inventory"]["operation_count"]=2
        elif fault=="feature_moved":
            e["feature_setup"]["IGetEnumFeatures"]=e["collection"]([])
            e["new_feature_setup"]["IGetEnumFeatures"]=e["collection"]([e["feature"]])
        elif fault=="old_tool":e["operation"]["IGetTool"]={"native_id":56}
        elif fault=="old_paths":e["inventory"]["operations"][0]["toolpath_record_counts"]=[6,6]
        elif fault=="old_frame":e["setup"]["GetSetupOriginInFCSSpace"]=(0.,0.,9.)
        elif fault=="old_feature_axis":e["feature_setup"]["Axis"]=(1.,0.,0.)
        elif fault=="reverse_false":e["new_feature_setup"]["IsReverseDirection"]=False
        elif fault=="wrong_axis":e["new_feature_setup"]["Axis"]=(0.,0.,1.)
        elif fault=="zero_axis":e["new_feature_setup"]["Axis"]=(0.,0.,0.)
        elif fault=="wrong_new_link":e["new_operation_setup"]["GetSetup"]=lambda:e["feature_setup"]
        elif fault=="nonempty_new_op":
            e["new_operation_setup"]["IGetEnumOperations"]=e["collection"]([e["operation"]])
        else:e["inventory"]["feature_setup_count"]=3
    e["after_insert"]=change;r=e["apply"]()
    assert r["status"]=="uncertain" and not r["readback_verified"] and len(e["insertions"])==1,r
    assert e["marker"].exists()


@pytest.mark.parametrize("where",["InsertTurnSetup1","after_getter"])
def test_event_after_insertion_stops_readback_immediately(insertion,where):
    e=insertion
    def hook(name):
        if name=="InsertTurnSetup1" and where=="InsertTurnSetup1":e["session"].state["event_count"]=1
        if e["insertions"] and name=="Axis" and where=="after_getter":e["session"].state["event_count"]=1
    e["hook"]=hook;r=e["apply"]()
    assert r["status"]=="uncertain" and len(e["insertions"])==1
    assert e["calls"][-1]==("InsertTurnSetup1" if where=="InsertTurnSetup1" else "Axis")


@pytest.mark.parametrize("fault",["source","protected","process","dirty"])
def test_boundary_change_stops_before_claim(insertion,fault):
    e=insertion
    def hook(name):
        if name=="GetData":
            if fault=="source":e["digest"]="c"*64
            elif fault=="protected":e["protected_changed"]=True
            elif fault=="process":e["process"]["create_time"]+=1
            else:e["dirty"]=True
    e["hook"]=hook;r=e["run"]()
    assert r["status"]=="error" and not e["marker"].exists() and not e["insertions"]


def test_state_change_after_pending_receipt_stops_before_dispatch(insertion,monkeypatch):
    e=insertion;writer=core._write_receipt
    def write(path,report,**kw):
        writer(path,report,**kw)
        if report.get("native_dispatch_pending"):e["operation"]["IGetTool"]={"native_id":77}
    monkeypatch.setattr(core,"_write_receipt",write)
    r=e["apply"]()
    assert r["status"]=="uncertain" and not e["insertions"] and e["marker"].exists()
    assert r["captures"][-1]["state"]["operation_setups"][0]["operations"][0]["tool_native_id"] == 77


@pytest.mark.parametrize("target",["marker","pending"])
def test_durable_write_failure_prevents_native_call(insertion,monkeypatch,target):
    e=insertion;writer=core._write_receipt
    def write(path,report,**kw):
        if target=="marker" and report.get("status")=="claimed_no_replay":raise OSError("disk failed")
        if target=="pending" and report.get("native_dispatch_pending"):raise OSError("disk failed")
        return writer(path,report,**kw)
    monkeypatch.setattr(core,"_write_receipt",write)
    r=e["apply"]()
    assert r["status"] in ("error","uncertain") and not e["insertions"]
    assert e["marker"].exists() is (target=="pending")


def test_second_post_capture_drift_is_uncertain(insertion,monkeypatch):
    e=insertion;capture=core._capture;count=0
    def wrapped(*args,**kwargs):
        nonlocal count
        if kwargs.get("after"):
            count+=1
            if count==2:e["new_feature_setup"]["Axis"]=(0.,0.,-2.)
        return capture(*args,**kwargs)
    monkeypatch.setattr(core,"_capture",wrapped)
    r=e["apply"]()
    assert r["status"]=="uncertain" and len(e["insertions"])==1
    assert r["captures"][-1]["state"] != r["captures"][-2]["state"]


def test_canonical_inequality_is_observed_without_alias_claim(insertion):
    e=insertion
    e["setup"]["GetSetup"]=lambda:dict(e["feature_setup"],QueryInterface=lambda iid:"other")
    r=e["apply"]()
    assert r["status"]=="review_required"
    assert r["after"]["operation_setups"][0]["feature_setup_canonical_identity_equal"] is False


def test_marker_is_bound_to_copy_identity_not_selector(monkeypatch,tmp_path):
    monkeypatch.setattr(core,"local_evidence_root",lambda:tmp_path)
    a=core.marker_path(dict(device=1,inode=7))
    assert a==core.marker_path(dict(inode=7,device=1))
    assert a!=core.marker_path(dict(device=1,inode=8))


def test_abi_requires_exact_current_signature(monkeypatch):
    from comtypes.automation import IDispatch
    method=SimpleNamespace(name="InsertTurnSetup1",restype=HRESULT,idlflags=(25,),
        argtypes=(VARIANT_BOOL,POINTER(IDispatch),POINTER(POINTER(IDispatch))),
        paramflags=((1,"reverse"),(1,"after"),(10,"new")))
    interface=SimpleNamespace(_iid_=core._INTERFACES["ICWTurnMachine"],_methods_=[method])
    monkeypatch.setattr(core,"_interface_class",lambda *a:interface)
    check=Mock();monkeypatch.setattr(core.frame,"setup_abi",check)
    core.insertion_abi("fixture");check.assert_called_once_with("fixture")
    method.argtypes=(c_int,)
    with pytest.raises(ValueError):core.insertion_abi("fixture")
