from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import patch
import importlib.util
import sys
import unittest

from scripts import sw_cam_saved_prior_lengths as m

class Guard:
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,obj,name,*args):
        if name in ("GetDocType","MachType"):return 1
        return object()
    def typed(self,obj,name):return obj

class ObservationTests(unittest.TestCase):
    def scenario(self,mode):
        calls=[];binding_calls=[];groups=[]
        document={"path":"current.SLDPRT","needs_save":False}
        ident_count=[0]
        def identity():
            ident_count[0]+=1
            d=deepcopy(document)
            if mode=="dirty" or (mode=="doc_change"and ident_count[0]>=3):d["needs_save"]=True
            return d
        ctx=N(app=object(),guard=lambda:Guard(),identity=identity,files=lambda:None,owned=lambda:None)
        backend=N(ctx=ctx,sw=object(),typelib_path="fake.tlb",loaded={"generated_pin":{},"pins":[]},
                  args={"process_id":25208,"expected_source_sha256":"source"},events=lambda *a:None)
        p={"operation_native_id":322,"feature_native_id":82,"expected_document_path":"current.SLDPRT","expected_source_sha256":"source"}
        expected={"toolpath_record_counts":[4500]}
        plan={"bound":{"document":document,"snapshot":{"binding":{"operations":[]}}},"expected_operation":expected}
        class Batch:
            def __init__(self,*args,**kwargs):self.n=0
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def require_complete(self):pass
            def summary(self):return {"read_count":self.n,"complete":True}
            def typed(self,obj,name):return obj
            def read(self,obj,name,*args):
                calls.append(name);self.n+=1
                return {"ToolpathFeedLength":.35794284,"ToolpathRapidLength":.1004500015,
                        "ToolpathTotalLength":.4583928415}[name]
        def binding(doc,ref,oid,fid,**kwargs):
            binding_calls.append((oid,fid))
            count=4499 if mode=="count" else 4500
            row={"native_id":oid,"feature_ids":[fid],"record_counts":[count],"tool_id":273}
            if mode=="binding"and len(binding_calls)==2:row["tool_id"]=999
            return row,object(),object()
        def direct(value):
            if mode=="source":raise ValueError("Direct source changed")
            return value
        actual=m.wip.capture_lengths
        def capture(*args,**kwargs):
            groups.append(1)
            result=actual(*args,**kwargs)
            if mode=="scalar_order":
                args[2]["native_length_readbacks"][0]["rows"][0]["scalar_observations"].reverse()
            return result
        report={}
        with patch.object(m.wip.lengths,"ReadBatch",Batch),patch.object(m.wip.lengths.protected,"binding",binding),patch.object(m.wip,"direct",direct),patch.object(m.wip,"capture_lengths",capture):
            m.observe_existing_three(backend,p,plan,report,lambda:None)
        return calls,binding_calls,groups,report

    def test_exact_one_group_three_ordered_getters(self):
        calls,bindings,groups,report=self.scenario("ok")
        self.assertEqual(groups,[1])
        self.assertEqual(calls,["ToolpathFeedLength","ToolpathRapidLength","ToolpathTotalLength"])
        self.assertEqual(bindings,[(322,82),(322,82)])
        self.assertEqual(report["length_property_read_count"],3)

    def test_wrong_count_fails(self):
        with self.assertRaises(ValueError):self.scenario("count")

    def test_binding_drift_fails(self):
        with self.assertRaises(ValueError):self.scenario("binding")

    def test_dirty_initial_document_fails(self):
        with self.assertRaises(ValueError):self.scenario("dirty")

    def test_document_changed_after_read_fails(self):
        with self.assertRaises(ValueError):self.scenario("doc_change")

    def test_source_hash_change_fails(self):
        with self.assertRaises(ValueError):self.scenario("source")

    def test_scalar_reordering_fails(self):
        with self.assertRaises(ValueError):self.scenario("scalar_order")

if __name__=="__main__":unittest.main(verbosity=2)
