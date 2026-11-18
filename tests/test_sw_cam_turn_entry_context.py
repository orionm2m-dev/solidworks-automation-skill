"""Independent contract checks: no SOLIDWORKS, COM activation or runtime writes."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

RUNTIME = Path(os.environ.get("SWMCP_RUNTIME_ROOT", Path(__file__).resolve().parents[1]))
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))
MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/sw_cam_turn_entry_context.py"
SPEC = importlib.util.spec_from_file_location("independent_turn_entry_context", MODULE_PATH)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def request(root):
    source = root / "BASE_TEST.SLDPRT"
    source.write_bytes(b"offline guard fixture, not CAD")
    return dict(process_id=123, expected_process_create_time=1234.5,
        expected_document_path=str(source), expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        expected_feature_count=1, expected_operation_count=2, expected_operation_setup_count=1,
        expected_generated_operation_count=1, expected_total_record_count=42,
        targets=[dict(operation_native_id=90, feature_native_id=76, setup_index=0, operation_index=0, operation_type=7),
                 dict(operation_native_id=91, feature_native_id=76, setup_index=0, operation_index=1, operation_type=8)],
        receipt_path=str(root / "fresh.json"), qualification_only=True, message_policy="vendor_default",
        post_parameter_index_policy="probe_zero_through_count_inclusive")


def report():
    return dict(status="started", phase="preflight", observations=[], native_read_count=0,
        readback_verified=False, observation_verified=False, saved_source_unchanged=False,
        runtime_unchanged=False, inventory_unchanged=False)


class FakeBackend:
    def __init__(self, failure=None):
        self.failure = failure
        self.calls = []
        self.finish_calls = 0
        self.capture_calls = 0
    def start(self):
        self.calls.append("start")
        if self.failure == "start": raise RuntimeError("start failed")
    def capture(self):
        self.calls.append("capture")
        self.capture_calls += 1
        return {"inventory": {"protected_operation": 1 + int(self.failure == "changed" and self.capture_calls == 2)}}
    def selected(self, target, progress):
        self.calls.append("selected")
        progress({"observed_native_id": target["operation_native_id"]})
        if self.failure == "selected": raise RuntimeError("native read failed")
        progress({"complete": True, "home_point_verified": False})
    def finish(self):
        self.calls.append("finish")
        self.finish_calls += 1
        if self.failure == "finish" or self.failure == "second_finish" and self.finish_calls == 2:
            raise RuntimeError("disconnect failed")
    def boundary(self):
        self.calls.append("boundary")
        if self.failure == "boundary": raise RuntimeError("source changed")


class RequestContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix="offline_contract_")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.v = request(self.root)
    def test_exact_valid_request(self):
        source, output = m.validate(self.v)
        self.assertEqual(source, Path(self.v["expected_document_path"]))
        self.assertFalse(output.exists())
    def test_malformed_selectors_are_rejected(self):
        variants = [("process_id", True), ("process_id", 0), ("expected_process_create_time", float("nan")),
            ("expected_process_create_time", True), ("expected_source_sha256", "A"*64),
            ("expected_document_path", "relative.SLDPRT"), ("qualification_only", False),
            ("message_policy", "accept_all"), ("post_parameter_index_policy", "guess_base")]
        for key, value in variants:
            with self.subTest(key=key, value=value):
                v = deepcopy(self.v); v[key] = value
                with self.assertRaises((ValueError, TypeError)): m.validate(v)
    def test_ids_positions_and_face_types_are_strict(self):
        for key, value in [("operation_native_id", True), ("operation_native_id", 0),
            ("feature_native_id", -1), ("setup_index", 1), ("operation_index", True),
            ("operation_type", 1), ("operation_type", True)]:
            with self.subTest(key=key, value=value):
                v = deepcopy(self.v); v["targets"][0][key] = value
                with self.assertRaises(ValueError): m.validate(v)
        for changed in ("duplicate_id", "duplicate_position", "extra_field", "three_targets"):
            with self.subTest(changed=changed):
                v = deepcopy(self.v)
                if changed == "duplicate_id": v["targets"][1]["operation_native_id"] = 90
                if changed == "duplicate_position": v["targets"][1]["operation_index"] = 0
                if changed == "extra_field": v["targets"][0]["write"] = True
                if changed == "three_targets": v["targets"].append(deepcopy(v["targets"][0]))
                with self.assertRaises(ValueError): m.validate(v)
    def test_source_and_existing_receipt_are_rejected(self):
        Path(self.v["expected_document_path"]).write_bytes(b"changed")
        with self.assertRaises(ValueError): m.validate(self.v)
        self.v = request(self.root)
        Path(self.v["receipt_path"]).write_text("prior immutable evidence")
        with self.assertRaises(ValueError): m.validate(self.v)
    def test_unknown_request_field_is_rejected(self):
        self.v["apply"] = True
        with self.assertRaises(ValueError): m.validate(self.v)


class ObservationContract(unittest.TestCase):
    def observe(self, count, replies=None, fail_index=None, kind=7):
        calls, progress = [], []
        def read(owner, name, *args):
            calls.append((owner, name, args))
            if name == "GetNumPostParam": return count
            if name == "GetPostParam":
                if args[0] == fail_index: raise RuntimeError("native parameter read exception")
                return replies.get(args[0], (None, None, False)) if replies is not None else ("field_"+str(args[0]), "raw", True)
            if name == "GetCannedCycleOutput": return False
            if name == "GetCannedCycleStartPoint": return (0, 0.1, 0.1)
            if name.startswith("ProgramPoint"): return False
            return 1.25
        try:
            result = m.observe("op", "turn", "face", "nc", kind, read, lambda row: progress.append(deepcopy(row)))
            return result, calls, progress
        except Exception as error:
            error.observed_calls = calls
            error.observed_progress = progress
            raise
    def test_zero_count_never_probes_an_index(self):
        result, calls, _ = self.observe(0)
        self.assertFalse(any(name == "GetPostParam" for _, name, _ in calls))
        self.assertEqual(result["actual_named_parameters"], [])
        self.assertTrue(result["complete"])
    def test_limit32_is33_explicit_probes_without_base_inference(self):
        result, calls, _ = self.observe(32, replies={1:("known", "raw_value", True)})
        indices = [args[0] for _, name, args in calls if name == "GetPostParam"]
        self.assertEqual(indices, list(range(33)))
        self.assertEqual([x["name_raw"] for x in result["actual_named_parameters"]], ["known"])
        for flag in ("catalog_complete", "index_base_verified", "home_point_verified", "preset_values_verified", "units_verified", "canned_cycle_is_general_home", "cutting_mode_semantics_verified"):
            self.assertIs(result[flag], False)
    def test_false_at_zero_retained_without_retry_or_assumed_one_base(self):
        result, calls, _ = self.observe(2, {0:(None,None,False),1:("alpha","x",True),2:("beta","y",True)})
        self.assertEqual([args[0] for _,name,args in calls if name=="GetPostParam"], [0,1,2])
        self.assertIs(result["post_parameter_probes"][0]["found"], False)
        self.assertIs(result["index_base_verified"], False)
    def test_invalid_count_aborts_before_any_other_native_read(self):
        for count in (-1, 33, True, 1.0, None):
            with self.subTest(count=count):
                with self.assertRaises(ValueError) as caught: self.observe(count)
                self.assertEqual([x[1] for x in caught.exception.observed_calls], ["GetNumPostParam"])
    def test_exception_stops_all_later_parameter_and_scalar_reads(self):
        with self.assertRaises(RuntimeError) as caught: self.observe(4, fail_index=1)
        self.assertEqual([x[1] for x in caught.exception.observed_calls], ["GetNumPostParam","GetPostParam","GetPostParam"])
        self.assertEqual([r["index"] for r in caught.exception.observed_progress[-1]["post_parameter_probes"]], [0])
    def test_post_parameter_strict_shape_and_bstr(self):
        invalid = [("n","v",1), ("n","v"), ("", "v", True), (None,"v",True), ("n",5,True), ("n","x"*4097,True)]
        for raw in invalid:
            with self.subTest(raw=str(raw)[:40]):
                with self.assertRaises(ValueError): m.post_parameter(raw,0)
    def test_face_readers_use_face_specific_fields(self):
        rough, calls, _ = self.observe(0,kind=7)
        self.assertEqual(rough["face_interface"],"ICWTurnFaceRoughOp")
        self.assertNotIn("PrevAllowance",rough["face_parameters"])
        finish, calls, _ = self.observe(0,kind=8)
        self.assertEqual(finish["face_interface"],"ICWTurnFaceFinishOp")
        self.assertIn("PrevAllowance",finish["face_parameters"])
        self.assertIn("ProgramPoint_FeatureGeometry_GougeCheck",finish["face_parameters"])


class ExecutionContract(unittest.TestCase):
    def test_success_is_observation_only_and_calls_cleanup(self):
        r = report(); b = FakeBackend(); publishes=[]
        result=m.run_read({"targets":[{"operation_native_id":90},{"operation_native_id":91}]},r,b,lambda:publishes.append(deepcopy(r)))
        self.assertEqual(result["status"],"review_required")
        self.assertTrue(result["readback_verified"])
        self.assertEqual(b.calls[:2],["start","capture"])
        self.assertEqual(b.capture_calls,2)
        self.assertGreaterEqual(b.finish_calls,1)
        self.assertTrue(all(x["complete"] for x in result["observations"]))
        self.assertGreater(len(publishes),3)
    def test_failures_always_cleanup_and_fail_closed(self):
        for failure in ("start","selected","changed","finish","boundary","second_finish"):
            with self.subTest(failure=failure):
                r=report(); b=FakeBackend(failure)
                result=m.run_read({"targets":[{"operation_native_id":90}]},r,b,lambda:None)
                self.assertEqual(result["status"],"error")
                self.assertGreaterEqual(b.finish_calls,1)
                for flag in ("readback_verified","observation_verified","saved_source_unchanged","runtime_unchanged","inventory_unchanged"):
                    self.assertIs(result.get(flag,False),False,(failure,flag))
    def test_native_gate_rejects_mutators_before_call(self):
        b=m.NativeRead(None,None,None,{},report(),{},[],lambda:None)
        b.session=type("Session",(),{"summary":lambda self:{"active":True,"subscribed":True}})()
        for name in ("SetPostParam","_set_AxialStockAmt","GenerateToolpath","GenerateOpPlan","Save3","SaveAs","DeleteFeature","InsertOperation"):
            with self.subTest(name=name),patch.object(m,"_member",side_effect=AssertionError("native mutator escaped gate")):
                with self.assertRaises(ValueError): b.read(object(),name)
    def test_event_detected_before_read_prevents_native_call(self):
        b=m.NativeRead(None,None,None,{},report(),{},[],lambda:None)
        b.session=type("Session",(),{"summary":lambda self:{"active":True,"subscribed":True,"event_count":1}})()
        with patch.object(m,"_member",side_effect=AssertionError("read after event")):
            with self.assertRaises(ValueError): b.read(object(),"GetNumPostParam")
    def test_boundary_rejects_pid_lifetime_and_source_change(self):
        v={"process_id":123,"expected_process_create_time":100.0,"expected_document_path":str(Path(__file__).resolve().parent / "offline_fixture" / "BASE.SLDPRT")}
        state={"alive":True,"process_id":123,"create_time":100.0,"executable":str(Path(__file__).resolve().parent / "offline_fixture" / "SLDWORKS.exe")}
        b=m.NativeRead(object(),None,None,v,report(),{},[{"path":"pin","sha256":"expected"}],lambda:None)
        for changed in ("hash","process_id","create_time","alive","application_pid"):
            st=deepcopy(state)
            if changed in st:st[changed]=False if changed=="alive" else -1
            with self.subTest(changed=changed),patch.object(m,"_file_hash",return_value="bad" if changed=="hash" else "expected"),patch.object(m,"_process_identity",return_value=st),patch.object(m,"_member",return_value=999 if changed=="application_pid" else 123):
                with self.assertRaises(ValueError):b.boundary()


class NativeCaptureContract(unittest.TestCase):
    def make_capture(self, change=None):
        v = dict(expected_feature_count=1, expected_operation_count=2, expected_operation_setup_count=1,
            expected_generated_operation_count=1, expected_total_record_count=42, expected_source_sha256="a"*64,
            targets=[dict(operation_native_id=90,feature_native_id=76,setup_index=0,operation_index=0,operation_type=7),
                     dict(operation_native_id=91,feature_native_id=76,setup_index=0,operation_index=1,operation_type=8)])
        inv = dict(feature_count=1,operation_count=2,operation_setup_count=1,operations=[
            dict(setup_index=0,operation_index=0,turn_operation_type=7,toolpath_generated=True,toolpath_record_counts=[42]),
            dict(setup_index=0,operation_index=1,turn_operation_type=8,toolpath_generated=False,toolpath_record_counts=[])])
        ops=[{"native_id":90,"IGetAllFeatures":[{"native_id":76}]}, {"native_id":91,"IGetAllFeatures":[{"native_id":76}]}]
        if change=="id": ops[0]["native_id"]=999
        if change=="feature":ops[0]["IGetAllFeatures"]=[{"native_id":999}]
        if change=="duplicate_id":ops[1]["native_id"]=90
        if change=="type": inv["operations"][0]["turn_operation_type"]=1
        if change=="order": inv["operations"][0]["operation_index"]=1
        if change=="records": inv["operations"][0]["toolpath_record_counts"]=[43]
        b=m.NativeRead(None,None,None,v,report(),{},[],lambda:None)
        b.initial={"path":"saved part"};b.doc=object()
        b.machine={"IGetEnumOpSetups":[{"IGetEnumOperations":ops}]}
        b.boundary=lambda:None;b.check=lambda:None
        b.read=lambda obj,name,*args:obj[name]
        with patch.object(m,"_inventory",return_value=inv),patch.object(m,"_items",side_effect=lambda raw,*a,**k:raw),patch.object(m,"_typed",side_effect=lambda raw,*a:raw),patch.object(m,"_object_id",side_effect=lambda doc,raw,read:raw["native_id"]):
            return b.capture()
    def test_exact_native_identity_projection_passes(self):
        result=self.make_capture()
        self.assertEqual([x["native_id"] for x in result["operation_identities"]],[90,91])
    def test_native_id_type_link_order_and_records_fail_closed(self):
        for change in ("id","feature","duplicate_id","type","order","records"):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):self.make_capture(change)
    def test_native_read_budget_blocks_call4097(self):
        r=report();r["native_read_count"]=4096
        b=m.NativeRead(None,None,None,{},r,{},[],lambda:None)
        b.session=type("Session",(),{"summary":lambda self:{"active":True,"subscribed":True}})()
        with patch.object(m,"_member",side_effect=AssertionError("read beyond bound")):
            with self.assertRaises(ValueError):b.read(object(),"GetNumPostParam")
    def test_unrelated_QI_is_rejected(self):
        b=m.NativeRead(None,None,None,{},report(),{m.FACE[7]:object(),m.FACE[8]:object()},[],lambda:None)
        b.session=type("Session",(),{"summary":lambda self:{"active":True,"subscribed":True}})()
        with patch.object(m,"_member",side_effect=AssertionError("unrelated QI escaped")):
            with self.assertRaises(ValueError):b.read(object(),"QueryInterface",object())


if __name__ == "__main__":
    unittest.main()
