"""Independent post-option contract tests; no application or COM activation."""
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
if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))
SPEC=importlib.util.spec_from_file_location("independent_turn_post_option_module",ROOT/"scripts/sw_cam_turn_post_option_context.py")
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)


def initial_report():
    return dict(status="started",phase="preflight",observations=[],native_read_count=0,
        readback_verified=False,observation_verified=False,saved_source_unchanged=False,
        runtime_unchanged=False,inventory_unchanged=False)


class OptionsFixture:
    def __init__(self,count=2,*,null=False,guid=None,fail_member=None,changed_count=False,wrong_item=False):
        self.count=count;self.null=null;self.guid=guid or m.IIDS[m.COLLECTION]
        self.fail_member=fail_member;self.changed_count=changed_count;self.wrong_item=wrong_item
        self.calls=[];self.progress=[];self.count_reads=0;self.raw=object()
        self.items=[{"PostParamName":"native_"+str(i),"PostParamValue":"value_"+str(i),"ParamsCount":2,"PostParamValueList":("choiceA","choiceB")} for i in range(count if type(count)is int and 0<=count<=32 else 0)]
    def read(self,obj,name,*args):
        self.calls.append(("read",name,args))
        if name==self.fail_member:raise RuntimeError("controlled native getter failure")
        if name=="GetPostOptionParamList":return None if self.null else self.raw
        if name=="Count":
            self.count_reads+=1
            return self.count+1 if self.changed_count and self.count_reads==2 else self.count
        if name=="Item":return self.items[args[0]]
        return obj[name]
    def metadata(self,obj):
        self.calls.append(("metadata",))
        return {"guid":self.guid,"typekind":4,"member_count":2,"name":"ICWDispatchCollection"}
    def typed(self,obj,name):
        self.calls.append(("typed",name))
        if self.wrong_item and name==m.PARAMETER:raise ValueError("wrong public item interface")
        return obj
    def run(self):
        return m.read_options("operation",read=self.read,typed=self.typed,metadata=self.metadata,progress=lambda r:self.progress.append(deepcopy(r)))


class OptionCollectionContract(unittest.TestCase):
    def test_null_stops_without_metadata_QI_or_any_old_scalar(self):
        f=OptionsFixture(null=True);row=f.run()
        self.assertEqual(f.calls,[("read","GetPostOptionParamList",())])
        self.assertTrue(row["complete"]);self.assertTrue(row["list_is_null"])
        self.assertFalse(row["home_point_verified"]);self.assertFalse(row["catalog_complete"])
    def test_metadata_precedes_exact_collection_QI_then_zero_based_items(self):
        f=OptionsFixture();row=f.run()
        self.assertEqual(f.calls[:4],[("read","GetPostOptionParamList",()),("metadata",),("typed",m.COLLECTION),("read","Count",())])
        self.assertEqual([x[2] for x in f.calls if x[:2]==("read","Item")],[(0,),(1,)])
        self.assertEqual(f.calls[-1],("read","Count",()))
        self.assertTrue(row["complete"])
        self.assertEqual([x["name_raw"] for x in row["rows"]],["native_0","native_1"])
        for key in ("scalar_post_parameters_reread","face_or_NC_scalars_reread","home_point_verified","catalog_complete","units_verified","option_value_semantics_verified"):
            self.assertIs(row[key],False)
    def test_wrong_metadata_GUID_fails_before_any_QI_or_count(self):
        f=OptionsFixture(guid="{00000000-0000-0000-0000-000000000000}")
        with self.assertRaises(ValueError):f.run()
        self.assertEqual([x[0] for x in f.calls],["read","metadata"])
    def test_zero_collection_skips_items_and_rechecks_count(self):
        f=OptionsFixture(0);row=f.run()
        self.assertEqual(row["rows"],[]);self.assertEqual(f.count_reads,2)
        self.assertFalse(any(x[:2]==("read","Item") for x in f.calls))
    def test_count32_has_exactly32_items_not_count_inclusive(self):
        f=OptionsFixture(32);row=f.run()
        self.assertEqual([x[2][0] for x in f.calls if x[:2]==("read","Item")],list(range(32)))
        self.assertEqual(len(row["rows"]),32)
    def test_invalid_count_never_reads_item(self):
        for count in (-1,33,True,2.0,None):
            with self.subTest(count=count):
                f=OptionsFixture(count)
                with self.assertRaises(ValueError):f.run()
                self.assertFalse(any(x[:2]==("read","Item") for x in f.calls))
    def test_count_change_or_item_QI_failure_rejects_complete_result(self):
        for kwargs in ({"changed_count":True},{"wrong_item":True}):
            with self.subTest(kwargs=kwargs):
                f=OptionsFixture(**kwargs)
                with self.assertRaises(ValueError):f.run()
                self.assertFalse(f.progress[-1]["complete"])
    def test_exception_keeps_partial_and_does_not_call_later_getters(self):
        f=OptionsFixture(fail_member="PostParamValue")
        with self.assertRaises(RuntimeError):f.run()
        self.assertEqual(f.calls[-1],("read","PostParamValue",()))
        self.assertEqual(f.progress[-1]["rows"][0]["name_raw"],"native_0")
        self.assertNotIn("complete",f.progress[-1]["rows"][0])
    def test_invalid_names_and_params_count_stop_before_choice_read(self):
        for name,count in [("",2),(None,2),("good",33),("good",True)]:
            with self.subTest(name=name,count=count):
                f=OptionsFixture(1);f.items[0]["PostParamName"]=name;f.items[0]["ParamsCount"]=count
                with self.assertRaises(ValueError):f.run()
                self.assertFalse(any(x[:2]==("read","PostParamValueList") for x in f.calls))


class VariantContract(unittest.TestCase):
    def test_supported_values_preserve_type_and_uncertainty(self):
        value=(None,True,1,-1,1.25,"text",["a","b"])
        result=m.variant_value(value)
        self.assertEqual(result["converted_type"],"tuple")
        self.assertEqual(result["value"],[None,True,1,-1,1.25,"text",["a","b"]])
        self.assertIs(result["native_variant_metadata_preserved"],False)
    def test_no_dynamic_objects_nonfinite_or_unbounded_structures(self):
        cases=[object(),{"x":1},float("nan"),float("inf"),2**64,-2**63-1,"x"*4097,[0]*33,[[[0]]],[[0]*32]*4]
        for raw in cases:
            with self.subTest(kind=type(raw).__name__):
                with self.assertRaises(ValueError):m.variant_value(raw)


class ScopeAndCleanupContract(unittest.TestCase):
    def backend(self):
        b=m.NativePostOptions(None,None,None,{},initial_report(),{m.COLLECTION:object(),m.PARAMETER:object()},[],lambda:None)
        b.session=type("Session",(),{"summary":lambda s:{"active":True,"subscribed":True}})()
        return b
    def test_no_mutators_or_previous_scalar_getters_in_new_scope(self):
        b=self.backend()
        names=("SetPostParam","PostParamValue=","GenerateToolpath","GenerateOpPlan","Save3","DeleteFeature",
            "GetNumPostParam","GetPostParam","GetCannedCycleOutput","GetCannedCycleStartPoint",
            "GetSpndlSpeed","GetFeedRateIPM","StepInAmt","AxialStockAmt","IGetTurnNCParam")
        for name in names:
            with self.subTest(name=name),patch.object(m,"_member",side_effect=AssertionError("forbidden call")),patch.object(m.core,"_member",side_effect=AssertionError("forbidden inherited call")):
                with self.assertRaises(ValueError):b.read(object(),name)
    def test_wrong_QI_target_and_null_owner_rejected(self):
        b=self.backend()
        with patch.object(m,"_member",side_effect=AssertionError("unqualified QI")):
            with self.assertRaises(ValueError):b.read(object(),"QueryInterface",object())
            with self.assertRaises(ValueError):b.typed_option(None,m.PARAMETER)
            with self.assertRaises(ValueError):b.typed_option(object(),"ICWVisiNCParam")
    def test_option_native_failure_uses_inherited_fail_closed_cleanup(self):
        fixture=OptionsFixture(fail_member="ParamsCount")
        class Backend:
            def __init__(self):self.closed=False
            def start(self):pass
            def capture(self):return {"inventory":"unchanged"}
            def selected(self,target,progress):return m.read_options(object(),read=fixture.read,typed=fixture.typed,metadata=fixture.metadata,progress=progress)
            def finish(self):self.closed=True
            def boundary(self):pass
        b=Backend();r=initial_report()
        out=m.core.run_read({"targets":[{"operation_native_id":90}]},r,b,lambda:None)
        self.assertEqual(out["status"],"error");self.assertTrue(b.closed)
        for flag in m.core.SUCCESS_FLAGS:self.assertIs(out.get(flag,False),False)
        self.assertFalse(out["observations"][0]["complete"])
    def test_events_and_read_limit_stop_before_option_getter(self):
        for mode in ("event","limit"):
            with self.subTest(mode=mode):
                b=self.backend()
                if mode=="event":b.session=type("Session",(),{"summary":lambda s:{"active":True,"subscribed":True,"event_count":1}})()
                else:b.report["native_read_count"]=4096
                with patch.object(m,"_member",side_effect=AssertionError("call past bound")):
                    with self.assertRaises(ValueError):b.read(object(),"GetPostOptionParamList")


class RequestContract(unittest.TestCase):
    def test_exact_one_target_and_new_policy(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix="offline_post_options_") as temp:
            root=Path(temp).resolve();source=root/"BASE.SLDPRT";source.write_bytes(b"offline only")
            v=dict(process_id=123,expected_process_create_time=100.0,expected_document_path=str(source),
                expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),expected_feature_count=9,
                expected_operation_count=16,expected_operation_setup_count=2,expected_generated_operation_count=1,
                expected_total_record_count=40,targets=[dict(operation_native_id=90,feature_native_id=76,setup_index=0,operation_index=0,operation_type=7)],
                receipt_path=str(root/"fresh.json"),qualification_only=True,message_policy="vendor_default",collection_index_policy=m.INDEX_POLICY)
            m.validate(v)
            for case in ("two_targets","old_policy","extra_old_field","wrong_id"):
                with self.subTest(case=case):
                    bad=deepcopy(v)
                    if case=="two_targets":bad["targets"].append(deepcopy(v["targets"][0]))
                    if case=="old_policy":bad["collection_index_policy"]="probe_zero_through_count_inclusive"
                    if case=="extra_old_field":bad["post_parameter_index_policy"]="probe_zero_through_count_inclusive"
                    if case=="wrong_id":bad["targets"][0]["operation_native_id"]=True
                    with self.assertRaises(ValueError):m.validate(bad)


if __name__=="__main__":unittest.main()
