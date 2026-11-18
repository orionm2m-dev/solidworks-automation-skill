"""Independent single-QI contract tests; no application activation/native calls."""
from copy import deepcopy
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get("SWMCP_RUNTIME_ROOT",ROOT))
if str(RUNTIME)not in sys.path:sys.path.insert(0,str(RUNTIME))
SPEC=importlib.util.spec_from_file_location("independent_turn_nc_home",ROOT/"scripts/sw_cam_turn_nc_home_context.py")
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)


def com_error(hr):return m.COMError(hr,"deliberate offline failure",None)
def report():
    return dict(status="started",phase="preflight",observations=[],native_read_count=0,
        readback_verified=False,observation_verified=False,saved_source_unchanged=False,
        runtime_unchanged=False,inventory_unchanged=False)


class HomeFixture:
    def __init__(self,*,qi_error=None,getter_error=None,raw=(0.1,0.0,0.1),null_owner=False):
        self.qi_error=qi_error;self.getter_error=getter_error;self.raw=raw
        self.owner=None if null_owner else object();self.nc4=object()
        self.calls=[];self.progress=[]
    def read(self,owner,name,*args):
        self.calls.append(("read",name,owner))
        if name=="IGetTurnNCParam":return self.owner
        if name=="GetHomePosition":
            if owner is not self.nc4:raise AssertionError("Wrong getter owner")
            if self.getter_error is not None:raise self.getter_error
            return self.raw
        raise AssertionError("Unexpected getter: "+name)
    def query(self,owner):
        self.calls.append(("query",owner))
        if owner is not self.owner:raise AssertionError("QI must use exact IGetTurnNCParam result")
        if self.qi_error is not None:raise self.qi_error
        return self.nc4
    def run(self,progress=None):
        return m.observe_home("turn",read=self.read,query=self.query,
            progress=progress or (lambda row:self.progress.append(deepcopy(row))))


class ObservationContract(unittest.TestCase):
    def test_exact_owner_one_QI_one_getter_preserves_unknown_semantics(self):
        f=HomeFixture();row=f.run()
        self.assertEqual([x[0] for x in f.calls],["read","query","read"])
        self.assertEqual(row["nc4_qi_attempt_count"],1)
        self.assertTrue(row["complete"]);self.assertTrue(row["home_value_read"])
        self.assertEqual(row["home_raw_xyz"],{"X":0.1,"Y":0.0,"Z":0.1})
        for key in ("home_position_semantics_verified","units_verified","coordinate_frame_verified","editable_home_contract_verified"):
            self.assertIs(row[key],False)
    def test_only_QI_E_NOINTERFACE_becomes_pending_unsupported(self):
        for hr in (-2147467262,0x80004002):
            with self.subTest(hr=hr):
                f=HomeFixture(qi_error=com_error(hr));row=f.run()
                self.assertEqual([x[0] for x in f.calls],["read","query"])
                self.assertEqual(row["capability_outcome"],"unsupported_pending_context_verification")
                self.assertFalse(row["nc4_supported"]);self.assertFalse(row["home_getter_attempted"])
                self.assertEqual(row["nc4_qi_attempt_count"],1);self.assertTrue(row["complete"])
    def test_other_QI_hresult_and_nonCOM_errors_propagate(self):
        class Impostor(RuntimeError):hresult=-2147467262
        for error in (com_error(-2147467259),com_error(-2147352567),Impostor("not COM"),ValueError("invalid return")):
            with self.subTest(error=type(error).__name__):
                f=HomeFixture(qi_error=error)
                with self.assertRaises(type(error)):f.run()
                self.assertEqual(len(f.calls),2)
                self.assertFalse(f.progress[-1]["complete"])
    def test_getter_E_NOINTERFACE_remains_error_not_unsupported(self):
        f=HomeFixture(getter_error=com_error(-2147467262))
        with self.assertRaises(m.COMError):f.run()
        row=f.progress[-1]
        self.assertTrue(row["nc4_supported"]);self.assertTrue(row["home_getter_attempted"])
        self.assertFalse(row["complete"])
        self.assertNotEqual(row["capability_outcome"],"unsupported_pending_context_verification")
    def test_null_owner_stops_before_QI(self):
        f=HomeFixture(null_owner=True)
        with self.assertRaises(ValueError):f.run()
        self.assertEqual(len(f.calls),1)
    def test_home_output_requires_three_finite_nonboolean_numbers(self):
        for raw in ((1,2),(1,2,3,4),(True,0,0),(None,0,0),(float("nan"),0,0),(0,float("inf"),0),{"X":1,"Y":2,"Z":3}):
            with self.subTest(raw=str(raw)):
                f=HomeFixture(raw=raw)
                with self.assertRaises(ValueError):f.run()
                self.assertFalse(f.progress[-1]["complete"])


class GuardClassificationContract(unittest.TestCase):
    def run_flow(self,fixture,failure=None):
        class Backend:
            def __init__(self):self.calls=[];self.captures=0
            def start(self):self.calls.append("start")
            def capture(self):
                self.calls.append("capture");self.captures+=1
                return {"protected":2 if failure=="changed" and self.captures==2 else 1}
            def selected(self,target,progress):return fixture.run(progress)
            def finish(self):
                self.calls.append("finish")
                if failure=="cleanup":raise RuntimeError("disconnect failed")
            def boundary(self):self.calls.append("boundary")
        backend=Backend();r=report()
        m.core.run_read({"targets":[{"operation_native_id":90}]},r,backend,lambda:None)
        return m.classify_after_guards(r),backend
    def test_unsupported_promoted_only_after_second_capture_and_cleanup(self):
        r,b=self.run_flow(HomeFixture(qi_error=com_error(-2147467262)))
        self.assertEqual(r["status"],"observed_unsupported")
        self.assertTrue(r["native_capability_verified"])
        self.assertEqual(b.captures,2);self.assertIn("finish",b.calls);self.assertIn("boundary",b.calls)
    def test_success_classified_as_readable_not_editable(self):
        r,b=self.run_flow(HomeFixture())
        self.assertEqual(r["status"],"review_required")
        self.assertEqual(r["capability_status"],"observed_readable")
        self.assertFalse(r["observations"][0]["editable_home_contract_verified"])
    def test_after_change_or_cleanup_failure_never_promoted(self):
        for failure in ("changed","cleanup"):
            with self.subTest(failure=failure):
                r,b=self.run_flow(HomeFixture(qi_error=com_error(-2147467262)),failure)
                self.assertEqual(r["status"],"error")
                self.assertFalse(r["native_capability_verified"])
                for key in m.core.SUCCESS_FLAGS:self.assertIs(r.get(key,False),False)
    def test_every_success_guard_required_for_classification(self):
        row=HomeFixture(qi_error=com_error(-2147467262)).run()
        for key in m.core.SUCCESS_FLAGS:
            with self.subTest(key=key):
                r={"status":"review_required","observations":[deepcopy(row)],**{k:True for k in m.core.SUCCESS_FLAGS}}
                r[key]=False
                with self.assertRaises(ValueError):m.classify_after_guards(r)
                self.assertFalse(r["native_capability_verified"])


class NativeGateContract(unittest.TestCase):
    def backend(self):
        class NC4:pass
        b=m.NativeHome(None,None,None,{},report(),{m.NC4:NC4},[],lambda:None)
        b.session=type("Session",(),{"summary":lambda s:{"active":True,"subscribed":True}})()
        return b
    def test_no_other_capability_or_scalar_or_mutating_calls(self):
        b=self.backend()
        for name in ("GetTypeInfo","GetPostOptionParamList","GetNumPostParam","GetPostParam","GetCannedCycleStartPoint",
            "GetSpndlSpeed","GetFeedRateIPM","StepInAmt","AxialStockAmt","SetHomePosition","GenerateToolpath","GenerateOpPlan","Save3","DeleteFeature"):
            with self.subTest(name=name),patch.object(m,"_member",side_effect=AssertionError("forbidden native call")),patch.object(m.core,"_member",side_effect=AssertionError("forbidden inherited call")):
                with self.assertRaises(ValueError):b.read(object(),name)
    def test_one_exact_public_QI_target_only(self):
        b=self.backend()
        with patch.object(m,"_member",side_effect=AssertionError("alternate QI")):
            with self.assertRaises(ValueError):b.read(object(),"QueryInterface",object())
            with self.assertRaises(ValueError):b.read(object(),"QueryInterface",b.classes[m.NC4],object())
        for value in (None,object()):
            with self.subTest(value=type(value).__name__),patch.object(m,"_member",return_value=value):
                with self.assertRaises(ValueError):b.query_nc4(object())
    def test_valid_QI_return_is_typed_and_owner_preserved(self):
        b=self.backend();owner=object();value=b.classes[m.NC4]()
        with patch.object(m,"_member",return_value=value) as call:
            self.assertIs(b.query_nc4(owner),value)
            call.assert_called_once_with(owner,"QueryInterface",b.classes[m.NC4])
    def test_event_and_read_limit_stop_before_native(self):
        for mode in ("event","limit"):
            b=self.backend()
            if mode=="event":b.session=type("Session",(),{"summary":lambda s:{"active":True,"subscribed":True,"event_count":1}})()
            else:b.report["native_read_count"]=4096
            with self.subTest(mode=mode),patch.object(m,"_member",side_effect=AssertionError("read beyond guard")):
                with self.assertRaises(ValueError):b.read(object(),"GetHomePosition")


class RequestContract(unittest.TestCase):
    def test_one_explicit_target_and_acknowledgement(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix="offline_home_") as temp:
            root=Path(temp).resolve();source=root/"BASE.SLDPRT";source.write_bytes(b"offline fixture")
            v=dict(process_id=123,expected_process_create_time=100.0,expected_document_path=str(source),
                expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),expected_feature_count=9,
                expected_operation_count=16,expected_operation_setup_count=2,expected_generated_operation_count=1,
                expected_total_record_count=40,targets=[dict(operation_native_id=90,feature_native_id=76,setup_index=0,operation_index=0,operation_type=7)],
                receipt_path=str(root/"fresh.json"),qualification_only=True,message_policy="vendor_default",acknowledge_public_interface_qualification=True)
            m.validate(v)
            for kind in ("two_targets","no_ack","numeric_ack","old_policy","wrong_id"):
                bad=deepcopy(v)
                if kind=="two_targets":bad["targets"]*=2
                if kind=="no_ack":bad["acknowledge_public_interface_qualification"]=False
                if kind=="numeric_ack":bad["acknowledge_public_interface_qualification"]=1
                if kind=="old_policy":bad["post_parameter_index_policy"]="probe_zero_through_count_inclusive"
                if kind=="wrong_id":bad["targets"][0]["operation_native_id"]=True
                with self.subTest(kind=kind),self.assertRaises(ValueError):m.validate(bad)


if __name__=="__main__":unittest.main()
