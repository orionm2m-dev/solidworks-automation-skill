"""Read-only bore options preserve exact metadata and fail at the first anomaly."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_sw_cam_turn_variable_allowance import env
from scripts import sw_cam_turn_variable_allowance as m
from scripts import sw_cam_comtypes as bridge


@pytest.fixture
def bore(env,monkeypatch):
    env["operation"].update(OpernType=5,RadialCut=False,AxialCut=True,ReverseCut=False,
        MirrorAboutCenterline=False,Undercut=False,FirstCutAmt=1.5,MaxCutAmt=3.,FinalCutAmt=.5,
        RadialStockAmt=.5,AxialStockAmt=.2,GetAllowanceMethodVariable=0)
    env["process"]=dict(alive=True,process_id=123,create_time=100.25,executable=r"C:\SOLIDWORKS\sldworks.exe")
    monkeypatch.setattr(m,"_process_identity",lambda pid:deepcopy(env["process"]))
    monkeypatch.setattr(m,"_bore_options_abi",lambda path:dict(getter_count=11,native_calls=0))
    env["args"].update(expected_operation_type=5,expected_process_create_time=100.25)
    env["run"]=lambda **kw:m.inspect_turn_bore_options(env["sw"],"clsid","fixture.tlb",**dict(env["args"],**kw))
    return env


def test_exact_two_scalar_snapshots_without_profile_or_tools(bore):
    r=bore["run"]()
    assert r["status"]=="ok" and r["readback_verified"] and r["before"]==r["after"]
    assert r["inspection_scope"]=="bore_rough_options"
    assert len(r["before"]["bore_options_native"])==11
    assert r["before"]["bore_options_native"]["Undercut"] is False
    assert r["before"]["bore_options_native"]["RadialStockAmt"]==.5
    for field in (*m._BORE_BOOL,*m._BORE_NUMBER,"GetAllowanceMethodVariable"):
        assert bore["calls"].count(field)==2
    assert bore["calls"].count("inventory")==4
    assert not set(bore["calls"]) & {"profile","GetAllVariableAllowances","IGetTool","SetTool","GenerateToolpath","Save"}
    assert not any(r[k] for k in ["mutation_attempted","model_saved","GOP_attempted","GTP_attempted","units_verified","full_model_geometry_verified","production_qualified"])
    assert r["messages"]["disconnected"] and not r["messages"]["active"]


@pytest.mark.parametrize("field,value",[("expected_process_create_time",None),("expected_process_create_time",True),
 ("expected_process_create_time",float("nan")),("expected_process_create_time",0),("expected_operation_type",1),
 ("expected_operation_type",6),("action","identify"),("action","apply"),("expected_operation_native_id",None),
 ("expected_linked_feature_ids",None),("expected_linked_feature_ids",[True]),("expected_source_sha256","x"*64)])
def test_bad_input_before_native(bore,field,value):
    r=bore["run"](**{field:value});assert r["status"]=="error" and not bore["calls"]


@pytest.mark.parametrize("field,value",[("alive",False),("process_id",124),("create_time",100.26),("executable","other.exe")])
def test_wrong_process_lifetime_before_cam(bore,field,value):
    bore["process"][field]=value
    r=bore["run"]();assert r["status"]=="error" and not bore["calls"]


@pytest.mark.parametrize("field,value",[("Undercut",0),("ReverseCut",1.0),("AxialCut","true"),
 ("RadialStockAmt",True),("FirstCutAmt",float("inf")),("MaxCutAmt",float("nan")),
 ("FinalCutAmt",".5"),("GetAllowanceMethodVariable",True),("GetAllowanceMethodVariable",2**31)])
def test_exact_scalar_types_stop_first_bad_getter(bore,field,value):
    bore["operation"][field]=value
    r=bore["run"]();assert r["status"]=="error" and not r["readback_verified"]
    assert bore["calls"][-1]==field and bore["calls"].count(field)==1
    assert r["before"]["capture_complete"] is False


@pytest.mark.parametrize("field",["Undercut","RadialStockAmt","GetAllowanceMethodVariable"])
def test_first_vendor_event_stops_remaining_reads(bore,field):
    def hook(name):
        if name==field:bore["session"].state["event_count"]=1
    bore["hook"]=hook
    r=bore["run"]();assert r["status"]=="error" and bore["calls"][-1]==field
    assert bore["calls"].count(field)==1 and r["messages"]["disconnected"]


def test_scalar_drift_between_snapshots(bore):
    def hook(name):
        if name=="Undercut":bore["operation"]["Undercut"]=True
    bore["hook"]=hook
    r=bore["run"]();assert r["status"]=="error" and not r["readback_verified"]
    assert r["before"]["bore_options_native"]["Undercut"] is False
    assert r["after"]["bore_options_native"]["Undercut"] is True


@pytest.mark.parametrize("change",["inventory","source","dirty","process"])
def test_changed_boundary_stops_before_second_capture(bore,change):
    def hook(name):
        if name=="Undercut":
            if change=="inventory":bore["inventory"]["operation_count"]=2
            elif change=="source":bore["digest"]="b"*64
            elif change=="dirty":bore["dirty"]=True
            else:bore["process"]["create_time"]+=1
    bore["hook"]=hook
    r=bore["run"]();assert r["status"]=="error" and bore["calls"].count("Undercut")==1


def test_vendor_getter_failure_keeps_partial_native_evidence(bore):
    def fail():raise OSError("vendor read failed")
    bore["operation"]["MaxCutAmt"]=fail
    r=bore["run"]();assert r["status"]=="error" and bore["calls"][-1]=="MaxCutAmt"
    assert r["before"]["bore_options_native"]["FirstCutAmt"]==1.5
    assert "MaxCutAmt" not in r["before"]["bore_options_native"]


def test_quiet_disconnect_required(bore,monkeypatch):
    original=bore["Session"].__exit__
    def bad_exit(self,*args):
        original(self,*args);self.state["disconnect_errors"]=["disconnect failed"]
    monkeypatch.setattr(bore["Session"],"__exit__",bad_exit)
    r=bore["run"]();assert r["status"]=="error" and not r["readback_verified"]


def test_stable_dirty_ram_is_explicit_read_only_scope(bore):
    bore["dirty"]=True
    r=bore["run"]();assert r["status"]=="ok" and r["unsaved_memory_present"]
    assert not r["persistence_verified"]


def test_source_changed_after_disconnect_fails(bore,monkeypatch):
    original=bore["Session"].__exit__
    def changed(self,*args):original(self,*args);bore["digest"]="b"*64
    monkeypatch.setattr(bore["Session"],"__exit__",changed)
    r=bore["run"]();assert r["status"]=="error" and not r["readback_verified"]


def test_legacy_allowance_entry_does_not_accept_bore_type(bore):
    args={k:v for k,v in bore["args"].items() if k!="expected_process_create_time"}
    r=m.inspect_turn_variable_allowance(bore["sw"],"clsid","fixture",**args)
    assert r["status"]=="error" and not bore["calls"]


def abi_interface():
    from ctypes import HRESULT,POINTER,c_double,c_int
    from ctypes.wintypes import VARIANT_BOOL
    entries=[("_get_"+name,dispid,VARIANT_BOOL) for name,dispid in m._BORE_BOOL.items()]
    entries += [("_get_"+name,dispid,c_double) for name,dispid in m._BORE_NUMBER.items()]
    entries += [("GetAllowanceMethodVariable",23,c_int)]
    methods=[SimpleNamespace(name=name,restype=HRESULT,idlflags=(dispid,"propget") if name.startswith("_get_") else (dispid,),
        argtypes=(POINTER(scalar),),paramflags=((10,"value"),)) for name,dispid,scalar in entries]
    return SimpleNamespace(_iid_="{6FDE22B6-C52D-448D-8065-A9CFD8839718}",_methods_=methods)


def test_exact_primary_bore_iid_and_getter_abi(monkeypatch):
    interface=abi_interface();monkeypatch.setattr(bridge,"_load_type_library",lambda p:SimpleNamespace(ICWTurnBoreRoughOp=interface))
    result=m._bore_options_abi("fixture");assert result["getter_count"]==11 and result["native_calls"]==0
    interface._iid_="{00000000-0000-0000-0000-000000000000}"
    with pytest.raises(ValueError):m._bore_options_abi("fixture")


@pytest.mark.parametrize("corruption",["missing","duplicate","type","flags","dispid","property"])
def test_exact_abi_rejects_changed_vendor_signature(monkeypatch,corruption):
    interface=abi_interface()
    if corruption=="missing":interface._methods_.pop()
    elif corruption=="duplicate":interface._methods_.append(interface._methods_[0])
    elif corruption=="type":interface._methods_[0].argtypes=(int,)
    elif corruption=="flags":interface._methods_[0].paramflags=((2,"value"),)
    elif corruption=="dispid":interface._methods_[0].idlflags=(900,"propget")
    else:interface._methods_[0].idlflags=(8,"propput")
    monkeypatch.setattr(m,"_interface_class",lambda *args:interface)
    with pytest.raises(ValueError):m._bore_options_abi("fixture")
