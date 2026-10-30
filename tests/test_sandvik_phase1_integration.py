"""Fault-injection test of the complete bounded orchestration without native calls."""
import hashlib
import json
import sys
from types import SimpleNamespace, ModuleType
from contextlib import nullcontext
from pathlib import Path
import pytest
from test_sandvik_phase1 import m, stl

@pytest.fixture
def simulation(tmp_path,monkeypatch):
    def file(name,data=b"pin"):
        p=tmp_path/name;p.write_bytes(data);return str(p),hashlib.sha256(data).hexdigest()
    source,sha=file("part.SLDPRT")
    pins=[dict(zip(("path","sha256"),file(str(i)+".json"))) for i in range(7)]
    doc=dict(path=source,title="part.SLDPRT",type=1,needs_save=True)
    settings={"direct_type":0,"toolpath_parameters":{"first_cut_Z_type_raw":0}}
    firstcut=ModuleType("scripts.sw_cam_rough_firstcut")
    firstcut.load_firstcut_receipt=lambda *a,**kw:{"after_settings":settings,"after_document":dict(doc)}
    firstcut.read_firstcut_settings=lambda *a,**kw:dict(settings)
    monkeypatch.setitem(sys.modules,"scripts.sw_cam_rough_firstcut",firstcut)
    state=dict(document=dict(doc,needs_save=False),features=[{} for _ in range(19)],
               operations=[dict(toolpath_generated=False,toolpath_record_counts=[]) for _ in range(6)])
    anchor=SimpleNamespace(state=state,data=dict(scope="MILL_ADDED_CIRCULAR_POCKET_PLAN_V1",
        new_operations=[dict(native_id=247,mill_operation_type=0,setup_native_id=93)],
        new_feature_native_id=244),pins=[pins[0]],check_runtime_identity=lambda:None,
        check_files=lambda:None,summary=lambda:dict(scope="test"),verify=lambda s:None)
    monkeypatch.setattr(m,"load_saved_plan_tools_evidence",lambda *a,**kw:anchor)
    monkeypatch.setattr(m,"raw_part_identity",lambda sw:dict(doc))
    candidate=dict(pins=pins[1:5])
    monkeypatch.setattr(m,"load_candidate_contract",lambda *a,**kw:candidate)
    monkeypatch.setattr(m,"render_candidate_mt",lambda c:b"candidate")
    def write(c,path,**kw):
        Path(path).write_bytes(b"candidate")
        return dict(path=path,sha256=hashlib.sha256(b"candidate").hexdigest())
    monkeypatch.setattr(m,"write_candidate_mt",write)
    holder_recipe=dict(pins=pins[5:],records=[{"kind":"arc" if i<3 else "line"} for i in range(17)])
    monkeypatch.setattr(m,"read_holder_recipe",lambda *a:holder_recipe)
    monkeypatch.setattr(m,"validate_native_profiles",lambda *a:dict(raw_numeric_profile_match=True))
    monkeypatch.setattr(m,"verify_holder_profile",lambda *a:dict(native_holder_shape_verified=True))
    monkeypatch.setattr(m,"read_segment_chains",lambda *a,**kw:kw["diagnostic"]["state"].update(status="observed"))
    old_holder=SimpleNamespace(name="old")
    new_holder=SimpleNamespace(name="new")
    new_holder.GetName=lambda:new_holder.name
    new_holder.SetFilePathForUserDefinedHolder=lambda path:(setattr(new_holder,"name",path),0)[1]
    tool=SimpleNamespace(native_id=250,ToolType=14,IsMillTool=True,CutDiameter=0.,Protrusion=0.,
        IGetMillToolHolder=lambda:new_holder,ShankDia=0.,CutLength=0.,OverallLength=0.,Flutes=0,
        TipOffset=0.,TipLength=0.,MillUDToolOutputType=0,name="")
    tool.SetToolName=lambda name:(setattr(tool,"name",name),0)[1]
    tool.GetToolName=lambda:tool.name
    tool.CreateSTLOfCuttingPortion=lambda path:(stl(Path(path),[(3.8,0),(4,.2),(4,19)]),0)[1]
    tool.CreateSTLOfNonCuttingPortion=lambda path:(stl(Path(path),[(4,19),(4,62.4),(3.4,63)]),0)[1]
    old_tools=[dict(native_id=145,tool_type_raw=1,CutDiameter=2.,Protrusion=20.,StnNo=1.)]
    created=[]
    crib=SimpleNamespace(AddNewTool3=lambda kind:(created.append(tool),tool)[1])
    native=dict(machine=SimpleNamespace(IGetToolcrib=lambda:crib),doc=object(),operations={247:object()})
    sw=SimpleNamespace(GetProcessID=lambda:23824,ActiveDoc=object())
    app=object()
    monkeypatch.setattr(m,"_bootstrap",lambda *a:app)
    monkeypatch.setattr(m,"_member",lambda obj,name,*a:getattr(obj,name)(*a) if callable(getattr(obj,name)) else getattr(obj,name))
    monkeypatch.setattr(m,"_object_id",lambda doc,obj,read:obj.native_id)
    monkeypatch.setattr(m,"holder_objects",lambda *a:{145:old_holder})
    monkeypatch.setattr(m,"com_identity",lambda obj,read=None:id(obj))
    monkeypatch.setattr(m,"capture_local_tools",lambda *a:old_tools+(
        [dict(native_id=250,tool_type_raw=14,CutDiameter=tool.CutDiameter,Protrusion=tool.Protrusion,StnNo=2.)] if created else []))
    def capture(*a,**kw):
        return dict(state,document=dict(doc)),native
    monkeypatch.setattr(m,"capture_selected_plan",capture)
    monkeypatch.setattr(m,"read_ud14_tool",lambda *a,**kw:dict(native_id=250,tool_type_raw=14,
        parameters={k:getattr(tool,k) for k,v in m.FIELDS},profiles=dict(tool={},shank={})))
    monkeypatch.setattr(m,"read_document_cam_unit_scope",lambda *a,**kw:dict(
        SW_document_units_raw=[0,1,2,0,0],CAM_use_document_units_raw=True))
    import scripts.sw_cam_events as events
    class Events:
        def __init__(self,*a):self.active=False
        def __enter__(self):self.active=True;return self
        def __exit__(self,*a):self.active=False
        def summary(self):return dict(subscribed=True,active=self.active,disconnected=not self.active)
    monkeypatch.setattr(events,"CamMessageSession",Events)
    calls=[];fault={"label":None};mutable={"returned":False}
    class Guard:
        def __init__(self,*a,**kw):self.kw=kw
        def __enter__(self):self.kw["verify_evidence"]();return self
        def __exit__(self,*a):pass
        def summary(self):return {"fake":True}
        def read(self,obj,name,*a):return m._member(obj,name,*a)
        def typed(self,obj,name):return obj
        def dispatch_once(self,fn,persist_pending):
            persist_pending()
            receipt=json.loads(Path(args["receipt_path"]).read_text())
            label=receipt["dispatches"][-1]["label"];calls.append(label)
            marker=json.loads(Path(receipt["dispatch_marker_path"]).read_text())
            assert marker["native_dispatch_pending"] is True
            if fault["label"]==label:raise RuntimeError("injected native outcome unknown")
            value=fn();mutable["returned"]=True;return value
    monkeypatch.setattr(m,"ScopedCamDispatchGuard",Guard)
    args=dict(process_id=23824,expected_document_path=source,expected_source_sha256=sha,
        expected_feature_native_id=79,expected_operation_native_ids=[143,144],expected_operation_setup_native_id=93,
        expected_tool_native_id=145,saved_plan_receipt_path=pins[0]["path"],saved_plan_receipt_sha256=pins[0]["sha256"],
        qualification_only=True,acknowledge_disposable_copy=True,receipt_path=str(tmp_path/"receipt.json"),
        message_policy="vendor_default",candidate_contract_path=pins[1]["path"],candidate_contract_sha256=pins[1]["sha256"],
        source_cad_path=pins[2]["path"],source_cad_sha256=pins[2]["sha256"],
        reference_mt_path=pins[3]["path"],reference_mt_sha256=pins[3]["sha256"],
        profile_analysis_path=pins[4]["path"],profile_analysis_sha256=pins[4]["sha256"],
        candidate_mt_path=str(tmp_path/"candidate.mt"),holder_file_path=pins[5]["path"],
        holder_file_sha256="f6a30a764a148467e06c674b6492672da76656060156222a97183cd4444a2157",
        holder_recipe_path=pins[6]["path"],holder_recipe_sha256=pins[6]["sha256"],
        cutting_stl_path=str(tmp_path/"cut.stl"),noncutting_stl_path=str(tmp_path/"noncut.stl"),
        expected_sw_document_units_raw=[0,1,2,0,0],expected_cam_use_document_units=True,
        acknowledge_experimental=True,firstcut_receipt_path=pins[0]["path"],firstcut_receipt_sha256=pins[0]["sha256"])
    return SimpleNamespace(run=lambda:m.qualify_sandvik_ud14(sw,"clsid","tlb",**args),
        args=args,calls=calls,fault=fault,tool=tool,doc=doc,created=created)

def test_complete_observation_still_not_production(simulation):
    r=simulation.run()
    assert r["status"]=="review_required",r
    assert r["readback_verified"] and r["exports_verified"] and r["protected_context_unchanged"]
    assert r["exact_one_tool_created"] and r["new_tool_native_id"]==250
    assert not r["cutting_partition_verified"] and not r["units_verified"]
    assert not r["model_saved"] and not r["GTP_attempted"]
    assert simulation.calls.count("AddNewTool3")==1
    assert r["before_document"]["needs_save"] is True

@pytest.mark.parametrize("label",["AddNewTool3","SetToolName","property:CutDiameter",
    "SetFilePathForUserDefinedHolder","CreateSTLOfCuttingPortion","CreateSTLOfNonCuttingPortion"])
def test_unknown_dispatch_stops_and_keeps_durable_pending(simulation,label):
    simulation.fault["label"]=label;r=simulation.run()
    assert r["status"]=="uncertain" and r["native_dispatch_pending"] is True,r
    assert simulation.calls[-1]==label
    assert simulation.calls.count(label)==1
    marker=json.loads(Path(r["dispatch_marker_path"]).read_text())
    assert marker["native_dispatch_pending"] is True and marker["automatic_replay"] is False
    assert not r["readback_verified"] and not r["model_saved"]

def test_unexpected_final_scalar_is_detected(simulation):
    original=simulation.tool.CreateSTLOfNonCuttingPortion
    def changed(path):
        result=original(path);simulation.tool.CutLength=20.;return result
    simulation.tool.CreateSTLOfNonCuttingPortion=changed
    r=simulation.run()
    assert r["status"]=="uncertain"
    assert r["final_scalar_observation"]["CutLength"]==20. and r["failed_phase"]=="after"
    assert not r["readback_verified"]

def test_existing_marker_blocks_new_output_names(simulation):
    r=simulation.run()
    base=Path(simulation.args["receipt_path"]).parent
    for key,suffix in (("receipt_path",".json"),("candidate_mt_path",".mt"),
                       ("cutting_stl_path",".stl"),("noncutting_stl_path",".stl")):
        simulation.args[key]=str(base/(key+"2"+suffix))
    count=len(simulation.calls)
    r2=simulation.run()
    assert r2["status"]=="error" and r2["failed_phase"]=="preflight"
    assert len(simulation.calls)==count


def test_healthy_undocumented_noncutting_contents_remain_observation(simulation):
    simulation.tool.CreateSTLOfNonCuttingPortion=lambda path:(
        stl(Path(path),[(4.,19.),(10.,25.),(10.,70.)]),0)[1]
    result=simulation.run()
    assert result["status"]=="review_required" and result["readback_verified"],result
    noncut=result["exports"]["noncutting"]
    assert noncut["mesh_health_verified"] and not noncut["expected_shank_envelope_compatible"]
    assert noncut["classification_pending"] and not noncut["holder_inclusion_verified"]
    assert not result["physical_tool_qualified"] and not result["cutting_partition_verified"]
    assert not result["GTP_attempted"] and not result["model_saved"]

