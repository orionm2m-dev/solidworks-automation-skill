"""精镗只读双属性：身份、ABI、事件、部分结果与原有粗镗边界。"""
from copy import deepcopy
from types import SimpleNamespace
import importlib
import pytest
from test_sw_cam_turn_variable_allowance import env
from test_sw_cam_turn_bore_options import bore
from scripts import sw_cam_turn_variable_allowance as m
from scripts import sw_cam_comtypes as bridge

@pytest.fixture
def finish(bore,monkeypatch):
    bore["operation"].update(OpernType=6,GenerateLeftOver=True,LEFTOVER_TYPE=1)
    bore["args"].update(expected_operation_type=6,include_leftover_control=True)
    monkeypatch.setattr(m,"_finish_leftover_abi",lambda path:dict(interface="ICWTurnBoreFinishOp",getter_count=2,native_calls=0))
    return bore

@pytest.mark.parametrize("kind",range(5))
def test_finish_exact_two_properties_no_rough_tool_profile_or_mutation(finish,kind,monkeypatch):
    finish["operation"]["LEFTOVER_TYPE"]=kind;typed=[]
    monkeypatch.setattr(m,"_typed",lambda obj,name,path:(typed.append(name),obj)[1])
    r=finish["run"]()
    assert r["status"]=="ok" and r["readback_verified"] and r["before"]==r["after"]
    assert r["inspection_scope"]=="bore_finish_leftover" and r["getter_abi"]["getter_count"]==2
    assert r["before"]["bore_options_native"]==dict(GenerateLeftOver=True,LEFTOVER_TYPE=kind)
    assert typed.count("ICWTurnBoreFinishOp")==2 and "ICWTurnBoreRoughOp" not in typed
    assert finish["calls"].count("GenerateLeftOver")==2 and finish["calls"].count("LEFTOVER_TYPE")==2
    assert finish["calls"].count("inventory")==4
    assert not set(finish["calls"])&set((*m._BORE_BOOL,*m._BORE_NUMBER,"GetAllowanceMethodVariable","IGetTool","profile","GetAllVariableAllowances","SetTool","GenerateToolpath","Save"))
    assert not any(r[k] for k in ("mutation_attempted","GOP_attempted","GTP_attempted","model_saved","production_qualified","incoming_stock_geometry_verified"))

@pytest.mark.parametrize("changes",[
 {"include_leftover_control":False},{"include_leftover_control":1},{"include_tool_contours":True,"expected_tool_native_id":9},
 {"expected_tool_native_id":9},{"action":"identify"},{"action":"apply"},{"expected_operation_type":7},
 {"expected_process_create_time":None},{"expected_operation_native_id":None},{"expected_linked_feature_ids":None}])
def test_finish_narrow_admission_before_CAM(finish,changes):
    r=finish["run"](**changes);assert r["status"]=="error" and not finish["calls"]

@pytest.mark.parametrize("change",["operation","feature","type","source","process"])
def test_finish_identity_before_property_read(finish,change):
    if change=="operation":finish["operation"]["native_id"]=99
    elif change=="feature":finish["feature"]["native_id"]=99
    elif change=="type":finish["operation"]["OpernType"]=5
    elif change=="source":finish["digest"]="b"*64
    else:finish["process"]["create_time"]+=1
    r=finish["run"]();assert r["status"]=="error"
    assert not set(finish["calls"])&{"GenerateLeftOver","LEFTOVER_TYPE"}

@pytest.mark.parametrize("field,value",[("GenerateLeftOver",1),("GenerateLeftOver",None),("LEFTOVER_TYPE",True),("LEFTOVER_TYPE",2.),("LEFTOVER_TYPE",-1),("LEFTOVER_TYPE",5)])
def test_finish_strict_native_types_stop_first(finish,field,value):
    finish["operation"][field]=value;r=finish["run"]()
    assert r["status"]=="error" and not r["readback_verified"]
    assert finish["calls"][-1]==field and finish["calls"].count(field)==1

@pytest.mark.parametrize("field",["GenerateLeftOver","LEFTOVER_TYPE"])
def test_finish_event_stops_and_no_second_capture(finish,field):
    def hook(name):
        if name==field:finish["session"].state["event_count"]=1
    finish["hook"]=hook;r=finish["run"]()
    assert r["status"]=="error" and finish["calls"][-1]==field and finish["calls"].count(field)==1

@pytest.mark.parametrize("change",["value","inventory","source","process"])
def test_finish_detects_midread_change(finish,change):
    def hook(name):
        if name=="GenerateLeftOver":
            if change=="value":finish["operation"]["GenerateLeftOver"]=False
            elif change=="inventory":finish["inventory"]["operation_count"]+=1
            elif change=="source":finish["digest"]="b"*64
            else:finish["process"]["create_time"]+=1
    finish["hook"]=hook;r=finish["run"]();assert r["status"]=="error" and not r["readback_verified"]
    if change=="value":assert r["before"]["bore_options_native"]["GenerateLeftOver"] is True and r["after"]["bore_options_native"]["GenerateLeftOver"] is False


def test_finish_partial_error_keeps_first_value(finish):
    def fail():raise OSError("getter failed")
    finish["operation"]["LEFTOVER_TYPE"]=fail;r=finish["run"]()
    assert r["status"]=="error" and r["before"]["bore_options_native"]=={"GenerateLeftOver":True}
    assert finish["calls"].count("LEFTOVER_TYPE")==1 and not r["before"]["capture_complete"]


def test_finish_stable_unsaved_RAM_allowed_without_persistence(finish):
    finish["dirty"]=True;r=finish["run"]();assert r["readback_verified"] and r["unsaved_memory_present"] and not r["persistence_verified"]


def test_finish_exact_generated_metadata_and_IID_no_native(monkeypatch):
    mod=importlib.import_module("comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0")
    monkeypatch.setattr(bridge,"_load_type_library",lambda path:mod)
    result=m._finish_leftover_abi("no-native")
    assert result==dict(interface="ICWTurnBoreFinishOp",iid="{09A8BB10-1EFD-4FD7-A9BA-011D20A8151B}",getter_count=2,native_calls=0)
    bad=SimpleNamespace(ICWTurnBoreFinishOp=SimpleNamespace(_iid_="{00000000-0000-0000-0000-000000000000}"))
    monkeypatch.setattr(bridge,"_load_type_library",lambda path:bad)
    with pytest.raises(ValueError):m._finish_leftover_abi("bad-iid")

@pytest.mark.parametrize("corruption",["missing","duplicate","dispid","type","direction","property"])
def test_finish_rejects_wrong_ABI(monkeypatch,corruption):
    mod=importlib.import_module("comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0")
    real=mod.ICWTurnBoreFinishOp
    methods=[SimpleNamespace(name=x.name,restype=x.restype,idlflags=list(x.idlflags),argtypes=x.argtypes,paramflags=x.paramflags)
             for x in real._methods_ if x.name in ("_get_GenerateLeftOver","_get_LEFTOVER_TYPE")]
    if corruption=="missing":methods.pop()
    elif corruption=="duplicate":methods.append(methods[0])
    elif corruption=="dispid":methods[0].idlflags[0]=21
    elif corruption=="type":methods[0].argtypes=(int,)
    elif corruption=="direction":methods[0].paramflags=((2,"x"),)
    else:methods[0].idlflags=[22,"propput"]
    monkeypatch.setattr(m,"_interface_class",lambda *args:SimpleNamespace(_iid_=real._iid_,_methods_=methods))
    with pytest.raises(ValueError):m._finish_leftover_abi("bad-abi")
