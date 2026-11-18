"""Independent owner-STA record contract tests: fake host, no application."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get("SWMCP_RUNTIME_ROOT",ROOT))
if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))
SPEC=importlib.util.spec_from_file_location("independent_owner_records",ROOT/"scripts/sw_cam_inprocess_records.py")
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)


def fixture(root):
    paths={key:root/name for key,name in [("part","BASE.SLDPRT"),("dll","Host.dll"),("host_tlb","Host.tlb"),("cam_tlb","Cam.tlb")]}
    for key,path in paths.items():path.write_bytes(("offline fixture "+key).encode())
    sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    p=dict(process_id=123,expected_process_creation_time=100.5,expected_document_path=str(paths["part"]),
        expected_source_sha256=sha(paths["part"]),host_dll_path=str(paths["dll"]),host_dll_sha256=sha(paths["dll"]),
        host_tlb_path=str(paths["host_tlb"]),host_tlb_sha256=sha(paths["host_tlb"]),
        expected_host_module_version_id="00000000-0000-0000-0000-000000000001",max_operations=64,max_tools=4,
        receipt_path=str(root/"fresh.json"),reference_receipt_path=None,reference_receipt_sha256=None,nc_operation_ids=[],
        cam_typelib_path=str(paths["cam_tlb"]),cam_typelib_sha256=sha(paths["cam_tlb"]),qualification_only=True,message_policy="vendor_default",
        record_read=dict(operation_native_id=90,feature_native_id=76,operation_type=7,setup_index=0,operation_index=0,expected_operation_count=16,expected_setup_count=2,expected_record_count=40))
    ops=[]
    for i in range(16):ops.append(dict(setup_index=0 if i<14 else 1,operation_index=i if i<14 else i-14,native_id=90+i,
        turn_operation_type=7 if i==0 else 8,linked_feature_ids=[76+i],suppressed=False,toolpath_generated=i==0,toolpath_record_counts=[40] if i==0 else []))
    inv=dict(machine_type=3,operation_setup_count=2,operation_count=16,operations=ops)
    doc=dict(path=p["expected_document_path"],title="BASE.SLDPRT",type=1,needs_save=False,configuration="Default")
    rows=[]
    for i in range(40):
        row=dict(index=i,type_raw=7 if i%3==0 else 99,position_read=i%3==0)
        if i%3==0:row.update(rapid_raw=1,point_native=[float(i),.1,0.0])
        rows.append(row)
    rec=dict(schema_version=1,status="observed",stage="finished",accessor="GetEnumRecords",fallback_attempted=False,
        units_verified=False,frame_verified=False,tool_vector_read=False,complete_payload_read=False,expected_record_count=40,records=rows)
    r=dict(schema_version=1,scope="TURN_INPROCESS_READ_V1",engine_version="turn-reader-1",status="observed",stage="finished",
        read_only=True,mutation_attempted=False,process_id=123,host_module_version_id=p["expected_host_module_version_id"],
        host_assembly_location=p["host_dll_path"],elapsed_ms=1.0,readback_verified=True,
        document_before=doc,document_after=deepcopy(doc),inventory=inv,inventory_after=deepcopy(inv),record_inventory_unchanged=True,
        owner_thread=dict(expected_managed_thread_id=9,actual_managed_thread_id=9,apartment="STA",in_process=True),
        tools=[],nc_parameters=[],nc_parameters_complete=True,record_read=rec)
    return p,r


class FakeBackend:
    def __init__(self,p,response,*,events=0,change_source=False,owner_changed=False):
        self.p=p;self.response=response;self.events=events;self.change_source=change_source;self.owner_changed=owner_changed
        self.calls=[];self.owner_calls=0
    def owner(self):
        self.calls.append("owner");self.owner_calls+=1
        return dict(alive=True,process_id=self.p["process_id"],create_time=self.p["expected_process_creation_time"]+(1 if self.owner_changed and self.owner_calls>1 else 0),executable=str(Path(self.p["expected_document_path"]).parent/"SLDWORKS.exe"))
    def start(self):self.calls.append("start")
    def read_once(self,text):
        self.calls.append("read_once");self.request=json.loads(text)
        if self.change_source:Path(self.p["expected_document_path"]).write_bytes(b"changed fake file")
        return json.dumps(self.response)
    def finish(self):
        self.calls.append("finish")
        return dict(subscribed=True,disconnected=True,active=False,event_count=self.events,events=[] if not self.events else ["test event"],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix="offline_records_")
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve();self.p,self.r=fixture(self.root)
    def check(self,r=None,p=None):return m.validate_response(json.dumps(r or self.r),p or self.p)
    def test_valid40_records_and_unknown_types_remain_raw(self):
        self.assertEqual(len(self.check()["record_read"]["records"]),40)
        self.assertEqual(self.check()["record_read"]["records"][1],dict(index=1,type_raw=99,position_read=False))
        native=m.native_request(m.validate(self.p));self.assertEqual(native["record_read"],self.p["record_read"])
        self.assertNotIn("nc_operation_ids",native)
    def test_request_selection_strict_and_bounded(self):
        for key,value in [("operation_native_id",True),("feature_native_id",0),("operation_type",1),("setup_index",2),("operation_index",16),("expected_record_count",0),("expected_record_count",257),("expected_record_count",40.0)]:
            p=deepcopy(self.p);p["record_read"][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):m.validate(p)
    def test_no_NC_or_reference_or_old_policy_requests(self):
        variants=[{"nc_operation_ids":[90]},{"qualification_only":False},{"message_policy":"accept_all"},{"fallback":True},{"reference_receipt_path":str(self.root/"prior.json"),"reference_receipt_sha256":"a"*64}]
        for changes in variants:
            p={**deepcopy(self.p),**changes}
            with self.subTest(changes=changes),self.assertRaises(ValueError):m.validate(p)
    def test_selected_identity_type_link_path_and40_count_must_match(self):
        cases=[("native_id",999),("turn_operation_type",8),("linked_feature_ids",[77]),("suppressed",True),("toolpath_generated",False),("toolpath_record_counts",[39]),("toolpath_record_counts",[20,20]),("operation_index",20)]
        for key,value in cases:
            r=deepcopy(self.r);r["inventory"]["operations"][0][key]=value;r["inventory_after"]=deepcopy(r["inventory"])
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):self.check(r)
    def test_full_after_inventory_or_document_changes_rejected(self):
        for case in ("inventory","document","dirty","after_flag"):
            r=deepcopy(self.r)
            if case=="inventory":r["inventory_after"]["operations"][10]["suppressed"]=True
            if case=="document":r["document_after"]["configuration"]="changed"
            if case=="dirty":r["document_before"]["needs_save"]=r["document_after"]["needs_save"]=True
            if case=="after_flag":r["record_inventory_unchanged"]=False
            with self.subTest(case=case),self.assertRaises(ValueError):self.check(r)
    def test_owner_STA_identity_is_mandatory(self):
        for key,value in [("actual_managed_thread_id",10),("expected_managed_thread_id",True),("expected_managed_thread_id",0),("apartment","MTA"),("in_process",False)]:
            r=deepcopy(self.r);r["owner_thread"][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.check(r)
        r=deepcopy(self.r);del r["owner_thread"]
        with self.assertRaises(ValueError):self.check(r)
    def test_wrong_accessor_fallback_or_extra_payload_cannot_pass(self):
        for key,value in [("accessor","GetAllRecords"),("fallback_attempted",True),("complete_payload_read",True),("tool_vector_read",True),("status","error"),("hresult",-2147467259),("expected_record_count",39)]:
            r=deepcopy(self.r);r["record_read"][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.check(r)
    def test_record_rows_exact_complete_finite_and_GOTO_only(self):
        for case in ("short","duplicate_index","boolean_type","boolean_rapid","nonfinite","boolean_coordinate","wrong_dimension","nongoto_payload","missing_goto"):
            r=deepcopy(self.r);rows=r["record_read"]["records"]
            if case=="short":rows.pop()
            if case=="duplicate_index":rows[1]["index"]=0
            if case=="boolean_type":rows[0]["type_raw"]=True
            if case=="boolean_rapid":rows[0]["rapid_raw"]=True
            if case=="nonfinite":rows[0]["point_native"][0]=float("nan")
            if case=="boolean_coordinate":rows[0]["point_native"][0]=True
            if case=="wrong_dimension":rows[0]["point_native"]=[1,2]
            if case=="nongoto_payload":rows[1]["point_native"]=[1,2,3]
            if case=="missing_goto":del rows[0]["rapid_raw"]
            with self.subTest(case=case),self.assertRaises(ValueError):self.check(r)
    def test_unrequested_NC_or_tools_rejected(self):
        for key in ("tools","nc_parameters"):
            r=deepcopy(self.r);r[key]=[{"unexpected":True}]
            with self.subTest(key=key),self.assertRaises(ValueError):self.check(r)
    def test_single_batch_success_and_clean_end(self):
        b=FakeBackend(self.p,self.r);r=m.run_read(self.p,backend=b)
        self.assertEqual(r["status"],"observed");self.assertTrue(r["readback_verified"])
        self.assertEqual(b.calls.count("read_once"),1);self.assertEqual(b.calls.count("finish"),1)
        self.assertEqual(b.request["record_read"]["expected_record_count"],40)
        self.assertTrue(r["source_unchanged"]);self.assertTrue(r["cleanup_verified"])
    def test_original_inner_hresult_and_partial_rows_preserved(self):
        r=deepcopy(self.r);r.update(status="error",readback_verified=False,stage="record_read_failed",hresult=-2147467259,error_type="OuterError",message="outer")
        r["record_read"].update(status="error",stage="GetEnumRecords",record_index=2,hresult=-2147418113,error_type="COMException",message="inner")
        r["record_read"]["records"]=r["record_read"]["records"][:2]
        b=FakeBackend(self.p,r);out=m.run_read(self.p,backend=b)
        self.assertEqual(out["status"],"error");self.assertFalse(out["readback_verified"])
        self.assertEqual(out["native_issue"],dict(stage="GetEnumRecords",record_index=2,hresult=-2147418113,error_type="COMException",message="inner"))
        self.assertEqual(len(out["host_response"]["record_read"]["records"]),2)
        self.assertEqual(out["host_response"]["inventory"],out["host_response"]["inventory_after"])
        self.assertEqual(b.calls.count("read_once"),1);self.assertIn("finish",b.calls)
    def test_cleanup_source_or_lifetime_failure_not_verified(self):
        for case in ("event","source","owner"):
            with self.subTest(case=case):
                self.p,self.r=fixture(self.root);self.p["receipt_path"]=str(self.root/(case+".json"))
                b=FakeBackend(self.p,self.r,events=1 if case=="event" else 0,change_source=case=="source",owner_changed=case=="owner")
                out=m.run_read(self.p,backend=b)
                self.assertEqual(out["status"],"error");self.assertFalse(out["readback_verified"]);self.assertFalse(out["inventory_unchanged"])
                self.assertEqual(b.calls.count("read_once"),1);self.assertIn("finish",b.calls)
    def test_old_snapshot_NC_branch_remains_accepted_by_existing_validator(self):
        p={k:v for k,v in self.p.items() if k not in m.EXTRA};p["nc_operation_ids"]=[90]
        r=deepcopy(self.r)
        for key in ("record_read","owner_thread","inventory_after","record_inventory_unchanged"):del r[key]
        r["nc_parameters"]=[dict(operation_native_id=90,status="observed",spindle_speed_native=548.64,feed_rate_ipm_native=1403.07)]
        m.core.validate_params(p);m.core.validate_response(json.dumps(r),p)
        self.assertNotIn("record_read",m.core.native_request(p))
        self.assertEqual(m.core.native_request(p)["nc_operation_ids"],[90])


if __name__=="__main__":unittest.main()
