from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from scripts import sw_cam_mill_saved_plan_rebind as m
from scripts import sw_cam_mill_saved_plan_tools as common
from scripts import sw_cam_add_circular_pocket as pocket
from scripts import sw_cam_added_pocket_evidence as saved
from test_sw_cam_mill_saved_plan_rebind import case, binding, digest_file, FakeSession
from test_add_circular_pocket import engine
from test_added_pocket_integration import schema_class

@pytest.fixture
def appended(binding,monkeypatch):
    b=binding;c=b["case"]
    raw=common.load_saved_plan_tools_evidence(str(c["pin"]),b["args"]["saved_plan_receipt_sha256"],**c["args"])
    details=deepcopy(b["details"])
    compound=dict(three_step_profile={"steps":[1,2,3]},strategy={"attribute":1})
    data=dict(scope=m.APPENDED_SCOPE,process_id=16516,saved_file_sha256=c["args"]["expected_source_sha256"],
        saved_details=dict(selected_tool_details=details,**compound),
        request=dict(target_feature_native_id=64,target_owner_setup_native_id=69))
    c["pin"].write_text(json.dumps(data),encoding="utf-8")
    pin=m.read_pin(str(c["pin"]),digest_file(c["pin"]))[1]
    original=SimpleNamespace(data=data,state=raw.state,selected=raw.selected,operation_ids=raw.operation_ids,
        tool_id=145,receipt_pin=pin,pins=[pin],profile={"header":{"native_id":64}},
        verify=raw.verify,read_stock=raw.read_stock)
    def checked_files():
        assert m.read_pin(pin["path"],pin["sha256"])[1]==pin
    original.check_files=checked_files
    original.summary=lambda:dict(scope="MILL_APPENDED_PLAN_CONTINUATION_V1",saved_append_receipt=deepcopy(pin))
    real_loader=common.load_saved_plan_tools_evidence
    def loader(path,sha,**args):
        if path==str(c["pin"]) and args["process_id"]==16516:
            assert m._historical_pid.get()==16516
            checked_files()
            return original
        return real_loader(path,sha,**args)
    monkeypatch.setattr(common,"load_saved_plan_tools_evidence",loader)
    b["args"].update(saved_plan_receipt_sha256=pin["sha256"],
        tool_receipt_path=pin["path"],tool_receipt_sha256=pin["sha256"])
    b.update(original=original,compound=compound)
    return b

def execute(b,monkeypatch,mode="ok"):
    import scripts.sw_cam_events as events
    monkeypatch.setattr(events,"CamMessageSession",FakeSession)
    c=b["case"];calls=[]
    monkeypatch.setattr(m,"_member",lambda *a:13484)
    monkeypatch.setattr(m,"raw_part_identity",lambda sw:deepcopy(c["data"]["after"]["document"]))
    def process(pid):
        assert pid==13484, "retired process must not be queried"
        row=deepcopy(b["owner"]["process_identity"])
        if mode=="pid_reused":row["create_time"]+=1
        return row
    monkeypatch.setattr(m,"_process_identity",process)
    monkeypatch.setattr(m,"_bootstrap",lambda *a:"app")
    def capture(*args,**kw):
        calls.append(1);kw["check"]()
        state=deepcopy(b["original"].state);details=deepcopy(b["details"]);compound=deepcopy(b["compound"])
        if mode=="stock":state["stock"]["stl_sha256"]="0"*64
        if mode=="operation":state["operations"][0]["linked_feature_ids"]=[64]
        if mode=="CAD":state["sw_reference"]["feature_tree"].append("unexpected")
        if mode=="tool":details["items"][0]["full_tool"]["mill_tool"]["overall_length_native"]=3
        if mode=="strategy":compound["strategy"]["attribute"]=9
        if mode=="steps":compound["three_step_profile"]["steps"][0]=9
        if mode=="event":FakeSession.last.event=True
        if mode=="file":c["part"].write_bytes(b"drift")
        if mode=="dirty":state["document"]["needs_save"]=True
        if mode=="incomplete":details["profile_complete"]=False
        kw["diagnostic"]["operation_details"]=dict(selected_tool_details=details,**compound)
        return state,{}
    monkeypatch.setattr(m,"capture_selected_plan",capture)
    path=c["pin"].with_name("new_binding.json")
    report=m.verify_saved_plan_session(None,"clsid","tlb",**b["args"],
        qualification_only=True,acknowledge_disposable_copy=True,receipt_path=str(path))
    return report,path,calls

def test_appended_rebind_and_common_consumer_preserve_history(appended,monkeypatch):
    b=appended;old=Path(b["args"]["saved_plan_receipt_path"]).read_bytes()
    report,path,calls=execute(b,monkeypatch)
    assert report["session_rebind_verified"] is True,report
    assert len(calls)==2 and all(report[k] is False for k in m.FALSE_FLAGS)
    args=dict(b["case"]["args"],process_id=13484)
    e=common.load_saved_plan_tools_evidence(b["args"]["saved_plan_receipt_path"],
        b["args"]["saved_plan_receipt_sha256"],**args,
        session_rebind_receipt_path=str(path),session_rebind_receipt_sha256=digest_file(path))
    assert e.bound_process_id==13484 and e.data["process_id"]==16516
    assert e.profile==b["original"].profile and e.receipt_pin==b["original"].receipt_pin
    e.check_runtime_identity()
    assert Path(b["args"]["saved_plan_receipt_path"]).read_bytes()==old
    assert m._historical_pid.get() is None

@pytest.mark.parametrize("mode",["pid_reused","stock","operation","CAD","tool","strategy","steps","event","file","dirty","incomplete"])
def test_rebind_fails_closed(appended,monkeypatch,mode):
    report,_,_=execute(appended,monkeypatch,mode)
    assert report["status"]=="error" and report["session_rebind_verified"] is False
    assert all(report[k] is False for k in m.FALSE_FLAGS)
    assert m._historical_pid.get() is None

def test_historical_scope_cannot_mask_other_or_current_process(binding,monkeypatch):
    e=m._load_baseline(**binding["args"])
    monkeypatch.setattr(m,"_process_identity",lambda pid:(_ for _ in ()).throw(AssertionError("live queried")))
    with m._historical_validation(16516):
        with pytest.raises(ValueError):e.check_runtime_identity()
    with pytest.raises(AssertionError):e.check_runtime_identity()
    with pytest.raises(RuntimeError):
        with m._historical_validation(13484):
            e.check_runtime_identity()
            raise RuntimeError("exit")
    assert m._historical_pid.get() is None

def test_appended_anchor_requires_exact_saved_tool_pin(appended):
    b=appended
    with pytest.raises(ValueError):
        m.load_complete_tool_anchor(str(b["tool_path"]),digest_file(b["tool_path"]),
            b["original"],16516)

def test_compound_reader_retains_two_observations(appended,monkeypatch):
    import scripts.sw_cam_mill_compound_strategy as compound
    e=m._load_baseline(**appended["args"]);seen=[]
    monkeypatch.setattr(m,"read_selected_operation_tool_details",lambda *a,**kw:seen.append(("tool",kw["feature_native_id"])))
    monkeypatch.setattr(compound,"read_compound_strategy",lambda *a,**kw:seen.append((kw["observation"],kw["feature_id"])))
    m._read_session_details(e,{}, {},None,None,{},lambda:None)
    assert seen==[("tool",79),("three_step_profile",64),("strategy",64)]

def test_create_sketch_forwards_rebind_pair(engine,monkeypatch):
    seen=[]
    def load(*a,**kw):
        seen.append(kw);return engine.anchor
    monkeypatch.setattr(pocket,"load_saved_plan_tools_evidence",load)
    engine.args.update(session_rebind_receipt_path="binding",session_rebind_receipt_sha256="f"*64)
    result=pocket.add_circular_pocket_plan(None,None,None,**engine.args)
    assert result["sketch_save_readback_verified"] is True,result
    assert seen[0]["session_rebind_receipt_path"]=="binding"
    assert result["request"]["session_rebind_receipt_sha256"]=="f"*64
    assert engine.calls==["sketch","save_sketch"]

def test_schema_retains_pair_only_for_create_sketch(monkeypatch,tmp_path):
    cls=schema_class()
    # The base schema already validates complete pins. Check this validator without filesystem fixtures.
    called=[]
    monkeypatch.setattr(pocket,"validate_add_pocket_request",lambda **a:called.append(a))
    obj=cls.model_construct(action="create_sketch",session_rebind_receipt_path="binding",session_rebind_receipt_sha256="f"*64)
    obj.additive_pocket_contract()
    assert called[0]["session_rebind_receipt_path"]=="binding"
    obj.action="create_pocket_plan"
    with pytest.raises(ValueError):obj.additive_pocket_contract()

def test_saved_sketch_continuation_forwards_its_recorded_rebind(engine,monkeypatch):
    engine.args.update(session_rebind_receipt_path="binding",session_rebind_receipt_sha256="f"*64)
    data=pocket.add_circular_pocket_plan(None,None,None,**engine.args)
    original=engine.original_anchor;seen=[]
    def read_pin(path,sha):
        if path=="sketch":return data,{"path":"sketch","sha256":"d"*64}
        if path=="saved":return original.data,original.receipt_pin
        if path=="profile":return {},original.profile["pin"]
        raise AssertionError(path)
    monkeypatch.setattr(saved,"read_pin",read_pin)
    monkeypatch.setattr(saved,"load_circle_route",lambda *a:engine.route)
    monkeypatch.setattr(saved,"check_circle_route",lambda *a:None)
    monkeypatch.setattr(saved.AppendedPlanEvidence,"check_files",lambda *a:None)
    monkeypatch.setattr(common,"load_saved_plan_tools_evidence",lambda *a,**kw:seen.append(kw) or original)
    args={key:engine.args[key] for key in pocket.BINDING_KEYS}
    args["expected_source_sha256"]=data["saved_file_sha256"]
    e=saved.load_added_pocket_evidence("sketch","d"*64,**args)
    assert seen[0]["session_rebind_receipt_path"]=="binding"
    assert e.operation_ids==[143,144] and e.tool_id==145


@pytest.mark.parametrize("change",["missing","strategy","steps"])
def test_saved_rebind_rejects_missing_or_changed_compound(appended,monkeypatch,change):
    b=appended;report,path,_=execute(b,monkeypatch)
    assert report["session_rebind_verified"]
    if change=="missing":
        report.pop("before_compound_details")
        report.pop("after_compound_details")
    elif change=="strategy":
        report["after_compound_details"]["strategy"]["attribute"]=9
    else:
        report["before_compound_details"]["three_step_profile"]["steps"][0]=9
    path.write_text(json.dumps(report),encoding="utf-8")
    args=dict(b["case"]["args"],process_id=13484)
    with pytest.raises(ValueError):
        common.load_saved_plan_tools_evidence(b["args"]["saved_plan_receipt_path"],
            b["args"]["saved_plan_receipt_sha256"],**args,
            session_rebind_receipt_path=str(path),session_rebind_receipt_sha256=digest_file(path))
