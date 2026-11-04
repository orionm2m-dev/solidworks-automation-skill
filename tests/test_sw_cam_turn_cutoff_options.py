"""Exact read-only CutOff contract; fake CAM, native declarations only in one metadata test."""
from copy import deepcopy
from types import SimpleNamespace
import importlib
import pytest
from test_sw_cam_turn_variable_allowance import env
from scripts import sw_cam_turn_variable_allowance as base
from scripts import sw_cam_turn_cutoff_options as cut
from scripts import sw_cam_comtypes as bridge

@pytest.fixture
def cutoff(env,monkeypatch):
    env["operation"]["OpernType"]=13
    for name,_d,kind in cut._FIELDS:
        env["operation"][name]=False if kind=="bool" else 1 if kind=="long" else .25
    env["process"]=dict(alive=True,process_id=123,create_time=100.25,executable=r"C:\SOLIDWORKS\sldworks.exe")
    monkeypatch.setattr(base,"_process_identity",lambda pid:deepcopy(env["process"]))
    monkeypatch.setattr(cut,"_typed",lambda obj,*args:obj)
    monkeypatch.setattr(cut,"_cutoff_options_abi",lambda path:dict(getter_count=18,native_calls=0))
    env["args"].update(expected_operation_type=13,expected_process_create_time=100.25)
    env["run"]=lambda **kw:cut.inspect_turn_cutoff_options(env["sw"],"clsid","fixture.tlb",**dict(env["args"],**kw))
    return env

def test_two_complete_exact_scalar_captures_no_mutating_calls(cutoff):
    r=cutoff["run"]()
    assert r["status"]=="ok" and r["readback_verified"] and r["before"]==r["after"]
    assert r["getter_abi"]["getter_count"]==18
    assert r["before"]["cutoff_options_native"]["MirrorAboutCenterline"] is False
    assert all(cutoff["calls"].count(name)==2 for name,_,_ in cut._FIELDS)
    assert cutoff["calls"].count("inventory")==4
    assert not set(cutoff["calls"])&{"profile","IGetTool","GetAllVariableAllowances","GetOverrideFeatureExtents","GetOverrideFeatureExtentsTypes","GenerateToolpath","GenerateOperationPlan","Save","Save3"}
    assert not any(n.startswith("Set") or n.startswith("_set_") for n in cutoff["calls"])
    assert all(r[k] is False for k in ["mutation_attempted","GOP_attempted","GTP_attempted","model_saved","units_verified","production_qualified","tool_readers_used"])
    assert r["messages"]["disconnected"] and not r["messages"]["active"]
    assert r["unavailable_requested_parameters"]==["final_diameter","feature_start_end_extension_lengths","machining_side"]

@pytest.mark.parametrize("field,value",[("process_id",True),("expected_process_create_time",None),("expected_process_create_time",True),("expected_process_create_time",0),("expected_process_create_time",float("nan")),("expected_operation_type",5),("expected_operation_type",13.),("expected_operation_type",True),("expected_operation_native_id",None),("expected_operation_native_id",True),("expected_linked_feature_ids",None),("expected_linked_feature_ids",[]),("expected_linked_feature_ids",[True]),("expected_linked_feature_ids",[11,11]),("expected_source_sha256","x"*64),("expected_document_path","relative.sldprt"),("setup_index",-1),("operation_index",512),("action","identify"),("action","apply"),("message_policy","auto_accept")])
def test_bad_admission_never_calls_app(cutoff,field,value):
    r=cutoff["run"](**{field:value}); assert r["status"]=="error" and not cutoff["calls"]

@pytest.mark.parametrize("field,value",[("alive",False),("process_id",124),("create_time",100.26),("executable","other.exe")])
def test_wrong_process_lifetime_never_bootstraps(cutoff,field,value):
    cutoff["process"][field]=value;r=cutoff["run"]()
    assert r["status"]=="error" and not cutoff["calls"]

@pytest.mark.parametrize("kind",["operation","feature","type","source","document","pid"])
def test_wrong_actual_identity_stops_before_scalar(cutoff,kind):
    if kind=="operation":cutoff["operation"]["native_id"]=23
    elif kind=="feature":cutoff["feature"]["native_id"]=12
    elif kind=="type":cutoff["operation"]["OpernType"]=5
    elif kind=="source":cutoff["digest"]="b"*64
    elif kind=="document":cutoff["args"]["expected_document_path"]=r"C:\review\other.SLDPRT"
    else:cutoff["sw"]["GetProcessID"]=124
    r=cutoff["run"]();assert r["status"]=="error"
    assert not set(cutoff["calls"])&{n for n,_,_ in cut._FIELDS}

@pytest.mark.parametrize("field,value",[("MirrorAboutCenterline",0),("GenerateLeftOver",1),("DepthClearance",True),("FirstPeckAmt",float("inf")),("SubPeckAmt",float("nan")),("MinPeckAmt","1"),("CutOff_GrvType",True),("CornerBreakType",1.),("CNCCompMethod",2**31),("ProgramPoint_GrooveTool_Shift",-(2**31)-1)])
def test_bad_native_scalar_stops_at_first_result(cutoff,field,value):
    cutoff["operation"][field]=value;r=cutoff["run"]()
    assert r["status"]=="error" and r["readback_verified"] is False
    assert cutoff["calls"][-1]==field and cutoff["calls"].count(field)==1
    assert r["before"]["capture_complete"] is False

@pytest.mark.parametrize("field",[n for n,_,_ in cut._FIELDS])
def test_each_getter_event_stops_further_cam_reads(cutoff,field):
    def hook(name):
        if name==field:cutoff["session"].state["event_count"]=1
    cutoff["hook"]=hook;r=cutoff["run"]()
    assert r["status"]=="error" and cutoff["calls"][-1]==field
    assert cutoff["calls"].count(field)==1 and r["messages"]["disconnected"]

@pytest.mark.parametrize("what",["scalar","operation_id","feature_id","inventory","source","dirty","process"])
def test_drift_cannot_claim_stable_readback(cutoff,what):
    def hook(name):
        if name!="DepthClearance":return
        if what=="scalar":cutoff["operation"]["DepthClearance"]+=1
        elif what=="operation_id":cutoff["operation"]["native_id"]+=1
        elif what=="feature_id":cutoff["feature"]["native_id"]+=1
        elif what=="inventory":cutoff["inventory"]["operation_count"]+=1
        elif what=="source":cutoff["digest"]="b"*64
        elif what=="dirty":cutoff["dirty"]=True
        else:cutoff["process"]["create_time"]+=1
    cutoff["hook"]=hook;r=cutoff["run"]()
    assert r["status"]=="error" and not r["readback_verified"]
    assert r["before"]["cutoff_options_native"]["DepthClearance"]==.25

def test_com_failure_keeps_partial_values_and_no_retry(cutoff):
    def fail():raise OSError("native getter failure")
    cutoff["operation"]["DepthClearance"]=fail;r=cutoff["run"]()
    assert r["status"]=="error" and cutoff["calls"].count("DepthClearance")==1
    assert r["before"]["cutoff_options_native"]["PercentPeckAmt"]==.25
    assert "DepthClearance" not in r["before"]["cutoff_options_native"]

def test_exact_real_declared_metadata_without_CAD(monkeypatch):
    mod=importlib.import_module("comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0")
    monkeypatch.setattr(cut,"_interface_class",lambda name,path:getattr(mod,name))
    result=cut._cutoff_options_abi("no-application")
    assert result["getter_count"]==18 and result["iid"]==bridge._INTERFACES["ICWTurnCutOffOp"]

@pytest.mark.parametrize("defect",["iid","dispid","in_flag","return","type","duplicate","missing","propput"])
def test_corrupted_getter_ABI_rejected_before_application(monkeypatch,defect):
    from ctypes import HRESULT,POINTER,c_double,c_int
    from ctypes.wintypes import VARIANT_BOOL
    types={"long":c_int,"double":c_double,"bool":VARIANT_BOOL}
    methods=[SimpleNamespace(name="_get_"+n,restype=HRESULT,idlflags=[d,"propget"],argtypes=(POINTER(types[k]),),paramflags=((10,"v"),)) for n,d,k in cut._FIELDS]
    cls=SimpleNamespace(_iid_=cut._IID,_methods_=methods)
    if defect=="iid":cls._iid_="wrong"
    elif defect=="dispid":methods[0].idlflags[0]=99
    elif defect=="in_flag":methods[0].paramflags=((1,"v"),)
    elif defect=="return":methods[0].restype=c_int
    elif defect=="type":methods[0].argtypes=(POINTER(c_double),)
    elif defect=="duplicate":methods.append(methods[0])
    elif defect=="missing":methods.pop(0)
    else:methods[0].idlflags=[1,"propput"]
    monkeypatch.setattr(cut,"_interface_class",lambda *args:cls)
    with pytest.raises(ValueError):cut._cutoff_options_abi("no-application")
