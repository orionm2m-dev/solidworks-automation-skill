"""Offline safeguards. No application is bound or invoked by these tests."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import pytest

MODULE = Path(__file__).parents[1] / "scripts" / "sw_cam_owner_sta_island.py"
spec = importlib.util.spec_from_file_location("island_client_tested", MODULE)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


def durable(path, payload, *, create=False):
    with Path(path).open("x" if create else "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()


@pytest.fixture
def sample(tmp_path, monkeypatch):
    protected = tmp_path / "source.SLDPRT"
    protected.write_bytes(b"synthetic offline source")
    root = tmp_path / "copy"
    root.mkdir()
    target = root / "copy.SLDPRT"
    target.write_bytes(protected.read_bytes())
    n = dict(schema_version=1, expected_process_id=42,
        expected_process_creation_time=1.25, expected_document_path=str(target),
        expected_source_sha256=client.digest(target),
        protected_document_path=str(protected),
        protected_source_sha256=client.digest(protected), qualification_root=str(root),
        expected_sw_configuration="Default", expected_cam_configuration="Mill - Metric - 0",
        expected_host_module_version_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        native_receipt_path=str(root / "native.json"),
        expected_cad_fingerprint={"feature_tree":[{"name":"Body","type":"BaseBody"}],
                                  "solids":[{"box_m":[0.0]*6,"mass_raw":[0.0]*12}]},
        owner_setup_native_id=64, operation_setup_native_id=65,
        axis_native=[0.0,0.0,-1.0],origin_native=[0.0,0.0,0.0],
        outer_sketch_name="OUTER",island_sketch_names=["A","B","C","D"],
        depth_native=13.2,expected_shape=2,island_count_limit=1)
    copy = dict(scope="EXCLUSIVE_SAVED_FIVE_SKETCH_CAM_COPY_V1",
        source={"path":str(protected),"sha256":client.digest(protected)},
        target={"path":str(target),"sha256":client.digest(target)},
        exclusive_creation_verified=True,source_unchanged=True,bytes=target.stat().st_size,
        native_calls=0,copied_saved_disk_bytes_only=True)
    p = dict(native_request=n,module_sha256=client.digest(MODULE),
             receipt_path=str(root/"client.json"),qualification_only=True,
             acknowledge_ram_only=True)
    for name in client.PIN_NAMES:
        suffix = ".dll" if name=="host_dll" else ".tlb" if name=="host_tlb" else ".json"
        path=tmp_path/(name+suffix)
        path.write_text(json.dumps(copy if name=="copy_receipt" else {"synthetic":True}))
        p[name+"_path"]=str(path);p[name+"_sha256"]=client.digest(path)
    monkeypatch.setattr(client,"authority_proof",lambda _:{"pins":[],
        "saved_five_sketch_authority_verified":True})
    fake = types.ModuleType("scripts.sw_cam_generation")
    fake._write_receipt = durable
    monkeypatch.setitem(sys.modules,"scripts.sw_cam_generation",fake)
    return p


def test_offline_has_no_outputs(sample):
    p=client.prepare(sample)
    result=client.dispatch_request({"action":client.ACTION,"params":sample},validate_only=True)
    assert result["native_called"] is False
    assert not Path(sample["receipt_path"]).exists()
    assert not Path(p["marker_path"]).exists()
    assert not Path(p["client_marker_path"]).exists()


@pytest.mark.parametrize("extra", ["method","script","second_island","retry","save"])
def test_unknown_native_fields_rejected(sample,extra):
    sample["native_request"][extra]=True
    with pytest.raises(ValueError): client.prepare(sample)


@pytest.mark.parametrize("field,value",[
    ("expected_process_id",True),("schema_version",True),("expected_shape",True),
    ("operation_setup_native_id",64),("expected_process_creation_time",float("nan")),
    ("depth_native",0),("depth_native",float("inf")),("expected_shape",3),
    ("island_count_limit",True),("island_count_limit",2),("axis_native",[0,0,0]),("island_sketch_names",["A","A","C","D"]),
])
def test_invalid_native_values_rejected(sample,field,value):
    sample["native_request"][field]=value
    with pytest.raises(ValueError):client.prepare(sample)


def test_current_source_change_rejected(sample):
    Path(sample["native_request"]["protected_document_path"]).write_bytes(b"changed")
    with pytest.raises(ValueError):client.prepare(sample)


def test_copy_proof_change_rejected(sample):
    q=Path(sample["copy_receipt_path"])
    copy=json.loads(q.read_text())
    copy["source_unchanged"]=False
    q.write_text(json.dumps(copy))
    sample["copy_receipt_sha256"]=client.digest(q)
    with pytest.raises(ValueError):client.prepare(sample)


def test_same_file_copy_rejected(sample,monkeypatch):
    monkeypatch.setattr(client.os.path,"samefile",lambda *_:True)
    with pytest.raises(ValueError,match="aliases protected"):client.prepare(sample)


@pytest.mark.parametrize("kind",["host","client","receipt","native_receipt"])
def test_existing_attempt_rejected(sample,kind):
    n=sample["native_request"]
    path={"host":client.marker_path(n),"client":client.client_marker_path(n),
          "receipt":Path(sample["receipt_path"]),
          "native_receipt":Path(n["native_receipt_path"])}[kind]
    path.write_text("{}")
    with pytest.raises(ValueError,match="Fresh receipts"):client.prepare(sample)


def test_sealed_hash_and_pid(sample,tmp_path):
    q=tmp_path/"sealed.json"
    q.write_text(json.dumps({"action":client.ACTION,"params":sample}))
    assert client.sealed_payload(str(q),client.digest(q),42)["action"]==client.ACTION
    with pytest.raises(ValueError):client.sealed_payload(str(q),"0"*64,42)
    with pytest.raises(ValueError):client.sealed_payload(str(q),client.digest(q),43)


@pytest.mark.parametrize("text",['{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}'])
def test_json_duplicates_and_nonfinite_rejected(text):
    with pytest.raises(ValueError):client.decode(text)


class FaultBackend:
    def __init__(self,p):
        self.p=p
        self.calls=0
    def owner(self):
        n=self.p["native_request"]
        return {"alive":True,"process_id":n["expected_process_id"],
                "create_time":n["expected_process_creation_time"],
                "executable":"SLDWORKS.exe"}
    def invoke_once(self,text):
        self.calls+=1
        assert Path(client.client_marker_path(self.p["native_request"])).is_file()
        raise RuntimeError("synthetic RPC boundary fault")


def test_native_fault_is_unknown_and_not_replayed(sample):
    backend=FaultBackend(sample)
    result=client.run(sample,backend=backend)
    assert result["status"]=="uncertain"
    assert result["native_dispatch_pending"] is True
    assert result["readback_verified"] is False
    assert result["batch_calls"]==backend.calls==1
    assert Path(client.client_marker_path(sample["native_request"])).is_file()
    with pytest.raises(ValueError):client.run(sample,backend=backend)
    assert backend.calls==1


def test_owner_drift_prevents_dispatch(sample):
    backend=FaultBackend(sample)
    backend.owner=lambda:{"alive":True,"process_id":42,"create_time":9,
                         "executable":"SLDWORKS.exe"}
    result=client.run(sample,backend=backend)
    assert result["status"]=="error"
    assert backend.calls==0
    assert result["batch_calls"]==0


def test_pending_persistence_failure_prevents_dispatch(sample,monkeypatch):
    def fail(path,payload,*,create=False):
        if payload.get("phase")=="single_owner_sta_call":raise OSError("disk fault")
        durable(path,payload,create=create)
    monkeypatch.setattr(sys.modules["scripts.sw_cam_generation"],"_write_receipt",fail)
    backend=FaultBackend(sample)
    result=client.run(sample,backend=backend)
    assert backend.calls==0
    assert result["status"]=="uncertain"
    assert Path(client.client_marker_path(sample["native_request"])).is_file()


def test_no_ad_hoc_cam_or_arbitrary_invocation():
    text=MODULE.read_text(encoding="utf-8-sig").split("class NativeBackend:")[1].split("def validate_host")[0]
    assert "pointer.QualifyCreatePocketAndIslands(request_json)" in text
    for forbidden in ("GetCWApp(", "CreateMillFeature2(", "AddIslandToFeature(",
                      "LoadAddIn(", "RunMacro", "win32gui", "GetCWObjectFromID"):
        assert forbidden not in text


@pytest.fixture
def load_sample(sample):
    n=sample["native_request"]
    return dict(process_id=n["expected_process_id"],
        expected_process_creation_time=n["expected_process_creation_time"],
        expected_document_path=n["protected_document_path"],
        expected_source_sha256=n["protected_source_sha256"],
        expected_sw_configuration=n["expected_sw_configuration"],expected_needs_save=True,
        host_dll_path=sample["host_dll_path"],host_dll_sha256=sample["host_dll_sha256"],
        host_tlb_path=sample["host_tlb_path"],host_tlb_sha256=sample["host_tlb_sha256"],
        expected_host_module_version_id=n["expected_host_module_version_id"],
        module_sha256=client.digest(MODULE),
        receipt_path=str(Path(sample["receipt_path"]).with_name("load.json")),
        acknowledge_host_load=True)


class FakeLoader:
    def __init__(self,p):
        self.p=p
        self.calls=0
        self.status_calls=0
    def owner(self):
        p=self.p
        return {"alive":True,"process_id":p["process_id"],
            "create_time":p["expected_process_creation_time"],"executable":"SLDWORKS.exe"}
    def document(self):
        p=self.p
        return {"path":p["expected_document_path"],"title":"source.SLDPRT","type":1,
            "needs_save":p["expected_needs_save"],"configuration":p["expected_sw_configuration"]}
    def already_loaded(self):return False
    def load_once(self):self.calls+=1;return 0
    def status(self):
        p=self.p
        return dict(schema_version=1,status="connected",scope=client.NATIVE_SCOPE,
            process_id=p["process_id"],process_creation_time=p["expected_process_creation_time"],
            host_module_version_id=p["expected_host_module_version_id"],
            host_assembly_location=p["host_dll_path"],owner_thread_id=1,current_thread_id=1,
            apartment="STA",dispatcher_ready=True,native_calls=0,visible_ui_created=False)
    def status_once(self):
        self.status_calls+=1
        return json.dumps(self.status())


def test_load_checks_actual_mvid_and_unchanged_dirty_doc(load_sample):
    backend=FakeLoader(load_sample)
    r=client.run_load(load_sample,backend=backend)
    assert r["status"]=="observed" and r["loaded_mvid_verified"] is True
    assert r["document_before"]==r["document_after"]
    assert r["document_before"]["needs_save"] is True
    assert r["CAM_calls"]==0 and backend.calls==backend.status_calls==1


@pytest.mark.parametrize("field,value",[
    ("host_module_version_id","00000000-0000-0000-0000-000000000000"),
    ("process_creation_time",9.0),("current_thread_id",2),("apartment","MTA"),
    ("native_calls",1),("native_calls",False),("visible_ui_created",True),
    ("dispatcher_ready",False),("schema_version",True),
])
def test_loaded_status_drift_rejected(load_sample,field,value):
    backend=FakeLoader(load_sample)
    old=backend.status
    backend.status=lambda:dict(old(),**{field:value})
    r=client.run_load(load_sample,backend=backend)
    assert r["status"]=="uncertain" and r["loaded_mvid_verified"] is False
    assert backend.calls==1


def test_already_loaded_sidecar_not_loaded_again(load_sample):
    backend=FakeLoader(load_sample)
    backend.already_loaded=lambda:True
    r=client.run_load(load_sample,backend=backend)
    assert r["status"]=="error" and backend.calls==0 and backend.status_calls==0


def test_load_doc_change_disallows_success(load_sample):
    backend=FakeLoader(load_sample)
    old=backend.document
    backend.document=lambda:dict(old(),needs_save=not load_sample["expected_needs_save"]
                                  if backend.calls else load_sample["expected_needs_save"])
    r=client.run_load(load_sample,backend=backend)
    assert r["status"]=="uncertain" and r["document_unchanged_verified"] is False


def test_load_fault_no_replay(load_sample):
    backend=FakeLoader(load_sample)
    def fail():
        backend.calls+=1
        raise RuntimeError("synthetic loader fault")
    backend.load_once=fail
    r=client.run_load(load_sample,backend=backend)
    assert r["status"]=="uncertain" and r["native_dispatch_pending"] is True
    assert backend.calls==1 and backend.status_calls==0
    with pytest.raises(ValueError):client.run_load(load_sample,backend=backend)
    assert backend.calls==1


def synthetic_success(plan):
    from copy import deepcopy
    n=plan["native_request"];p=plan["params"];fid=111
    names=[n["outer_sketch_name"]]+n["island_sketch_names"]
    sketches=[dict(name=name,segment_count=1 if i==0 else 4,
                   segment_types=[1] if i==0 else [0,0,1,1],
                   model_to_sketch_transform=[0.0]*16) for i,name in enumerate(names)]
    before=dict(path=n["expected_document_path"],needs_save=False,
                sw_configuration=n["expected_sw_configuration"],
                cam_configuration=n["expected_cam_configuration"],
                feature_count=0,feature_ids=[],operation_count=0,
                cad_fingerprint=deepcopy(n["expected_cad_fingerprint"]),sketches=sketches)
    after=deepcopy(before);after.update(needs_save=True,feature_count=1,feature_ids=[fid])
    def header(count):
        return dict(native_id=fid,owner_setup_native_id=n["owner_setup_native_id"],
                    suppressed=False,volume_type=2,shape=2,axis_native=n["axis_native"],
                    depth_native=n["depth_native"],taper_angle_native=0.0,island_count=count,
                    sketch_count=count+1,sketch_names=names[:count+1])
    actions=[]
    for i,name in enumerate(client.expected_marker(n)["actions"]):
        row=dict(name=name,attempted=True,pending=False,returned=True)
        row["return_is_object" if i==0 else "return_value"]=True;actions.append(row)
    curves=[]
    for i,name in enumerate(names[:n["island_count_limit"]+1]):
        if i==0:
            c=[dict(index=0,curve_type=2,centre_native=[0.0]*3,radius_native=25.0,
                    normal_native=[0.0,0.0,1.0],direction_raw=True)]
        else:
            c=[dict(index=j,curve_type=0,start_native=[0.0]*3,end_native=[1.0]*3) for j in range(2)]
            c += [dict(index=j,curve_type=1,start_native=[0.0]*3,end_native=[1.0]*3,
                       mid_native=[0.5]*3,centre_native=[0.0]*3,radius_native=1.0,
                       normal_native=[0.0,0.0,1.0],sense_raw=True) for j in range(2,4)]
        curves.append(dict(native_index=i,name=name,curves=c,read_complete=True))
    host=dict(schema_version=1,scope=client.NATIVE_SCOPE,engine_version="explicit-island-owner-sta-1",
              status="islands_observed_ram_only",stage="finished",process_id=n["expected_process_id"],
              process_creation_time=n["expected_process_creation_time"],
              host_module_version_id=n["expected_host_module_version_id"],
              host_assembly_location=p["host_dll_path"],owner_thread_id=1,current_thread_id=1,
              apartment="STA",island_count_limit=n["island_count_limit"],request_binding=deepcopy(n),readback_verified=True,
              source_unchanged=True,native_dispatch_pending=False,actions=actions,
              new_feature_native_id=fid,after_create_header=header(0),
              after_add_headers=[header(i) for i in range(1,n["island_count_limit"]+1)],
              before=before,after=after,
              bounded_chain_readback=dict(indexed_chains=curves,read_complete=True,
                  physical_geometry_verified=False,universal_index_base_verified=False),
              messages=dict(subscribed=True,disconnected=True,active=False,event_count=0,events=[],
                  overflow=0,callback_error_count=0,cleanup_error=None,policy="vendor_default"),
              elapsed_ms=1.0)
    for key in ("mutation_attempted","create_attempted","create_returned",
                "add_attempted","add_returned","add_return_value"):host[key]=True
    for key in ("Save_attempted","GOP_attempted","GTP_attempted","AFR_attempted","model_saved",
                "production_qualified","machining_eligible","physical_depth_verified",
                "world_profile_placement_verified","automatic_retry","persistence_qualified"):
        host[key]=False
    return host


def store_success(plan,host):
    durable(plan["native_request"]["native_receipt_path"],host)
    durable(plan["marker_path"],client.expected_marker(plan["native_request"]))


@pytest.mark.parametrize("count",[1,4])
def test_exact_native_success_contract(sample,count):
    sample["native_request"]["island_count_limit"]=count
    plan=client.prepare(sample);host=synthetic_success(plan)
    store_success(plan,host)
    assert client.validate_host(host,plan) is True


@pytest.mark.parametrize("change",[
    "count","shape","header_id","header_names","actions","add_return","operation",
    "fingerprint","source_sketch","chains","event","owner_thread","scope","mvid",
])
def test_native_success_rejects_scope_drift(sample,change):
    plan=client.prepare(sample);host=synthetic_success(plan)
    if change=="count":host["island_count_limit"]=4
    elif change=="shape":host["after_add_headers"][0]["shape"]=3
    elif change=="header_id":host["after_create_header"]["native_id"]=999
    elif change=="header_names":host["after_add_headers"][0]["sketch_names"]=["OUTER","B"]
    elif change=="actions":host["actions"].append(dict(host["actions"][-1]))
    elif change=="add_return":host["actions"][-1]["return_value"]=1
    elif change=="operation":host["after"]["operation_count"]=1
    elif change=="fingerprint":host["after"]["cad_fingerprint"]["feature_tree"].append({"name":"X","type":"Attribute"})
    elif change=="source_sketch":host["after"]["sketches"][0]["model_to_sketch_transform"][0]=99
    elif change=="chains":host["bounded_chain_readback"]["indexed_chains"][1]["name"]="B"
    elif change=="event":host["messages"]["event_count"]=1
    elif change=="owner_thread":host["current_thread_id"]=2
    elif change=="scope":host["scope"]="anything_else"
    elif change=="mvid":host["host_module_version_id"]="00000000-0000-0000-0000-000000000000"
    store_success(plan,host)
    with pytest.raises(ValueError):client.validate_host(host,plan)


def test_marker_binds_exact_native_request(sample):
    plan=client.prepare(sample);host=synthetic_success(plan)
    store_success(plan,host)
    marker=client.expected_marker(plan["native_request"]);marker["island_count_limit"]=4
    durable(plan["marker_path"],marker)
    with pytest.raises(ValueError):client.validate_host(host,plan)


def test_native_receipt_must_equal_return_including_elapsed(sample):
    plan=client.prepare(sample);host=synthetic_success(plan)
    store_success(plan,host)
    host["elapsed_ms"]=2.0
    with pytest.raises(ValueError):client.validate_host(host,plan)


def test_fault_response_cannot_become_verified(sample):
    plan=client.prepare(sample);host=synthetic_success(plan)
    host.update(status="uncertain",readback_verified=False,native_dispatch_pending=True)
    store_success(plan,host)
    assert client.validate_host(host,plan) is False
    host["status"]="error"
    store_success(plan,host)
    with pytest.raises(ValueError):client.validate_host(host,plan)


def test_native_request_preserves_explicit_observed_drive_path(sample):
    n=sample["native_request"]
    n.update(expected_document_path="Z:/explicit-observed/copy/part.SLDPRT",
             protected_document_path="Z:/explicit-observed/source.SLDPRT",
             qualification_root="Z:/explicit-observed/copy",
             native_receipt_path="Z:/explicit-observed/copy/native.json")
    actual=client.validate_native(n)
    assert actual["expected_document_path"]==n["expected_document_path"]
    assert actual["protected_document_path"]==n["protected_document_path"]


def test_saved_producer_identity_survives_owned_restart():
    runtime=Path(r"C:/Users/Denis Fedorov/.codex/skills/solidworks-automation")
    sys.path.insert(0,str(runtime))
    original=Path(__file__).parents[2]/"FIRST1_QUALIFICATION_SEALED_01.json"
    if not original.is_file():
        pytest.skip("Historical producer fixture remains in project evidence")
    before=client.digest(original)
    old=json.loads(original.read_text(encoding="utf-8-sig"))["params"]
    producer=(old["native_request"]["expected_process_id"],
              old["native_request"]["expected_process_creation_time"])
    old["native_request"]["expected_process_id"]=999999
    old["native_request"]["expected_process_creation_time"]=producer[1]+1000.0
    proof=client.authority_proof(old)
    assert proof["historical_producer"]=={"process_id":producer[0],"process_creation_time":producer[1]}
    assert proof["intended_current_owner"]=={"process_id":999999,"process_creation_time":producer[1]+1000.0}
    assert client.digest(original)==before
    old["native_request"]["expected_sw_configuration"]="unrequested configuration"
    with pytest.raises(ValueError):client.authority_proof(old)

