from copy import deepcopy
import importlib
import pytest
from test_sw_cam_turn_variable_allowance import env
from test_sw_cam_turn_bore_options import bore
from scripts import sw_cam_turn_variable_allowance as m

@pytest.fixture
def leftover(bore,monkeypatch):
    bore["operation"].update(GenerateLeftOver=False,LEFTOVER_TYPE=2)
    monkeypatch.setattr(m,"_bore_options_abi",lambda path,**kw:dict(getter_count=13 if kw.get("include_leftover_control") else 11,native_calls=0))
    return bore

def test_optional_default_off_keeps_exact_eleven(leftover):
    r=leftover["run"]();assert r["status"]=="ok"
    assert len(r["before"]["bore_options_native"])==11
    assert "GenerateLeftOver" not in leftover["calls"] and "LEFTOVER_TYPE" not in leftover["calls"]

@pytest.mark.parametrize("kind",range(5))
def test_opt_in_two_extra_scalar_reads_only(leftover,kind):
    leftover["operation"]["LEFTOVER_TYPE"]=kind
    r=leftover["run"](include_leftover_control=True)
    assert r["status"]=="ok" and r["before"]==r["after"]
    assert r["getter_abi"]["getter_count"]==13 and len(r["before"]["bore_options_native"])==13
    assert r["before"]["bore_options_native"]["GenerateLeftOver"] is False
    assert r["before"]["bore_options_native"]["LEFTOVER_TYPE"]==kind
    assert leftover["calls"].count("GenerateLeftOver")==2 and leftover["calls"].count("LEFTOVER_TYPE")==2
    assert not set(leftover["calls"])&{"IGetTool","GetAllVariableAllowances","profile","SetTool","GenerateToolpath","Save"}

@pytest.mark.parametrize("value",[1,"true",None,0.])
def test_strict_optional_flag_before_calls(leftover,value):
    r=leftover["run"](include_leftover_control=value);assert r["status"]=="error" and not leftover["calls"]

@pytest.mark.parametrize("field,value",[("GenerateLeftOver",1),("GenerateLeftOver","false"),("LEFTOVER_TYPE",True),("LEFTOVER_TYPE",2.),("LEFTOVER_TYPE",-1),("LEFTOVER_TYPE",5)])
def test_exact_native_types_and_declared_enum(leftover,field,value):
    leftover["operation"][field]=value;r=leftover["run"](include_leftover_control=True)
    assert r["status"]=="error" and leftover["calls"][-1]==field and leftover["calls"].count(field)==1

@pytest.mark.parametrize("field",["GenerateLeftOver","LEFTOVER_TYPE"])
def test_drift_and_partial_values(leftover,field):
    def hook(name):
        if name==field:leftover["operation"][field]=True if field=="GenerateLeftOver" else 3
    leftover["hook"]=hook;r=leftover["run"](include_leftover_control=True)
    assert r["status"]=="error" and not r["readback_verified"]

@pytest.mark.parametrize("field",["GenerateLeftOver","LEFTOVER_TYPE"])
def test_first_event_stops_extra_read(leftover,field):
    def hook(name):
        if name==field:leftover["session"].state["event_count"]=1
    leftover["hook"]=hook;r=leftover["run"](include_leftover_control=True)
    assert r["status"]=="error" and leftover["calls"][-1]==field

def test_real_declared_Bore_metadata(monkeypatch):
    mod=importlib.import_module("comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0")
    monkeypatch.setattr(m,"_interface_class",lambda name,path:getattr(mod,name))
    assert m._bore_options_abi("no-app",include_leftover_control=True)["getter_count"]==13
    assert m._bore_options_abi("no-app")["getter_count"]==11
