from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from scripts import sw_cam_saved18_wip_binding as m

class BindingTests(unittest.TestCase):
    def setUp(self):
        self.path=str(Path(__file__).resolve())
        self.sha='a'*64;self.pin=dict(path=self.path,sha256='b'*64)
        ids=list(range(1,18))+[344,346,348,350]
        self.targets=[dict(operation_native_id=oid,operation_type=i%2,feature_native_id=339+i//2,assigned_tool=dict(native_id=342))for i,oid in enumerate(ids[-4:])]
        ops=[]
        for i,oid in enumerate(ids):
            t=self.targets[i-17]if i>=17 else None;generated=i<14 or i>=17
            ops.append(dict(native_id=oid,toolpath_generated=generated,toolpath_record_counts=[46]if generated else[],suppressed=False,
                linked_feature_ids=[t['feature_native_id']]if t else[100+i],mill_operation_type=t['operation_type']if t else 0,
                assigned_tool=t['assigned_tool']if t else dict(native_id=273)))
        snapshot=dict(binding=dict(operations=ops),parameters=[dict(operation_native_id=x)for x in ids[-12:]])
        rows=m.generated_streams(snapshot,self.targets)
        self.checkpoint=dict(source_path=self.path,source_sha256=self.sha,document=dict(path=self.path,needs_save=False),configuration={},
            snapshot=snapshot,learned_targets=self.targets,saved_cl=dict(status='export_verified',output_verified=True,readback_verified=True,
            source_sha256=self.sha,expected_generated_operations=rows,output=dict(path=self.path,sha256='c'*64)),
            tool_catalogue=[],tool_dimensions={},current_counts=dict(operations=21,parameters=12,paths=18,tools=21),
            GTP_complete=True,nominal_geometry_accepted=False,production_qualified=False)
        self.proof=dict(verified=True,receipt_sha256=self.pin['sha256'],source_sha256=self.sha,process_id=25208)
    def bind(self,checkpoint=None):
        return m.bind_verified_checkpoint(checkpoint or self.checkpoint,receipt_pin=self.pin,terminal_proof=self.proof,
            expected_source_sha256=self.sha,expected_document_path=self.path,process_id=25208,verify_direct_pin=lambda p:None)
    def test_exact_eighteen_binding(self):
        b=self.bind();self.assertEqual(len(b['expected_generated_operations']),18)
        self.assertFalse(b['cumulative_ancestry_replayed'])
    def test_dirty_document_refused(self):
        self.checkpoint['document']['needs_save']=True
        with self.assertRaises(ValueError):self.bind()
    def test_changed_saved_count_refused(self):
        self.checkpoint['snapshot']['binding']['operations'][-1]['toolpath_record_counts']=[99]
        with self.assertRaises(ValueError):self.bind()
    def test_unverified_terminal_refused(self):
        self.proof['verified']=False
        with self.assertRaises(ValueError):self.bind()
    def test_changed_parameter_after_export_refused(self):
        b=self.bind();s=deepcopy(b['snapshot']);s['parameters'][0]['new_feed']=100
        with self.assertRaises(ValueError):m.validate_capture(b,b['document'],s,verify_direct_pin=lambda p:None)
    def test_inmemory_authority_tamper_refused(self):
        b=self.bind();b['source_sha256']='d'*64
        with self.assertRaises(ValueError):m.validate_capture(b,b['document'],b['snapshot'],verify_direct_pin=lambda p:None)
    def test_same_snapshot_accepts(self):
        b=self.bind();v=m.validate_capture(b,b['document'],b['snapshot'],verify_direct_pin=lambda p:None)
        self.assertEqual(v['snapshot'],b['snapshot'])
    def test_wrapper_preserves_cleanup_gate_and_no_replay(self):
        b=self.bind();report=m.new_report(b,output_dir=Path(self.path).parent/'synthetic_output',implementation_pin={});calls=[]
        def core_run(r,**kw):
            calls.append(1);a,_=kw['capture']('before');z,_=kw['capture']('after');self.assertEqual(a,z)
            r.update(readback_verified=True,export_files_verified=True,native_call_count=1,native_call_attempted=True)
        kwargs=dict(capture_existing=lambda _: (b['document'],b['snapshot'],dict(machine=object())),guard_factory=lambda:None,
            persist=lambda:None,claim=lambda:None,invoke=lambda x:True,collect=lambda:[],verify_direct_pin=lambda p:None)
        m.run_existing_core(SimpleNamespace(run_one_wip_export=core_run),b,report,**kwargs)
        self.assertEqual(len(calls),1);self.assertTrue(report['outer_cleanup_still_required']);self.assertEqual(report['status'],'prepared')
        with self.assertRaises(ValueError):m.run_existing_core(SimpleNamespace(run_one_wip_export=core_run),b,report,**kwargs)

if __name__=='__main__':unittest.main()
