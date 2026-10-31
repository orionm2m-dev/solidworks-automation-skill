"""Contract regression using sanitized actual pocket parameter shapes."""
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
from contextlib import contextmanager
import importlib.util,json,tempfile,unittest

MODULE=Path(__file__).resolve().parents[1]/'scripts'/'sw_cam_pocket_rough_apply.py'
spec=importlib.util.spec_from_file_location('rough_apply_under_test',MODULE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
FIXTURE=json.loads((Path(__file__).parent/'pocket_rough_shapes.json').read_text(encoding='utf-8'))


def changed_state(order,generated=False):
    state=deepcopy(FIXTURE['state']);byid={r['native_id']:r for r in state['operations']}
    state['operations']=[byid[oid] for oid in order]
    for i,row in enumerate(state['operations']):row['operation_index']=i
    state['document']['needs_save']=True
    if generated:byid[143].update(toolpath_generated=True,toolpath_record_counts=[500])
    return state


def point(configured):
    return dict(read_complete=True,collection_interface_verified=True,list_is_null=False,hole_center_entry=True,
      entry_type=4 if configured else 0,count=1 if configured else 0,
      rows=[dict(type_raw=1,position_is_null=False,position_native=deepcopy(m.POINT))] if configured else [])


class ProjectionTests(unittest.TestCase):
    def test_actual_raw_parameter_shape(self):
        actual=m.expected_parameters(FIXTURE['parameters'])
        self.assertEqual(actual['143']['levels']['levels']['toolpath_parameters']['start_Z_native'],-.0134)
        self.assertEqual(actual['143']['rough']['depth']['GetStartDepth'],[False,.3])
        m.verify_parameters(FIXTURE['parameters'],actual,configured=True)
    def test_finish144_is_protected(self):
        actual=m.expected_parameters(FIXTURE['parameters']);actual['144']['finish']['SideAllow']=.2
        with self.assertRaisesRegex(ValueError,'outside'):m.verify_parameters(FIXTURE['parameters'],actual,configured=True)
    def test_extra_rough_change_rejected(self):
        actual=m.expected_parameters(FIXTURE['parameters']);actual['143']['rough']['boundary']['SideAllow']=0.
        with self.assertRaisesRegex(ValueError,'outside'):m.verify_parameters(FIXTURE['parameters'],actual,configured=True)
    def test_scalar_and_aggregate_both_required(self):
        actual=m.expected_parameters(FIXTURE['parameters']);actual['143']['rough']['depth']['FirstDepthAmt']=10.
        with self.assertRaises(ValueError):m.verify_parameters(FIXTURE['parameters'],actual,configured=True)
    def test_only_derived_entry_projection_exempted(self):
        actual=m.expected_parameters(FIXTURE['parameters']);actual['143']['rough']['entry']['GetHoleCentreEntry']=False
        actual['143']['rough']['entry']['GetEntryStartPtX']=[10.,0.,0.]
        m.verify_parameters(FIXTURE['parameters'],actual,configured=True)
    def test_all_three_real_orders(self):
        m.verify_route(FIXTURE['state'],FIXTURE['state'],order=m.OLD_ORDER)
        for order in (m.MID_ORDER,m.NEW_ORDER):m.verify_route(FIXTURE['state'],changed_state(order),order=order)
    def test_protected_four_paths(self):
        for oid in (267,247,248,271):
            state=changed_state(m.NEW_ORDER,True);next(r for r in state['operations'] if r['native_id']==oid)['toolpath_record_counts']=[1]
            with self.assertRaises(ValueError):m.verify_route(FIXTURE['state'],state,order=m.NEW_ORDER,generated=True)
    def test_extra_operation_not_accepted(self):
        state=changed_state(m.NEW_ORDER);state['operations'].append(deepcopy(state['operations'][0]))
        with self.assertRaises(ValueError):m.verify_route(FIXTURE['state'],state,order=m.NEW_ORDER)
    def test_wrong_ordinal_rejected(self):
        state=changed_state(m.NEW_ORDER);state['operations'][0]['operation_index']=7
        with self.assertRaisesRegex(ValueError,'ordinal'):m.verify_route(FIXTURE['state'],state,order=m.NEW_ORDER)
    def test_saved_hash_and_clean_state(self):
        state=changed_state(m.NEW_ORDER,True);state['saved_file_sha256']='b'*64;state['document']['needs_save']=False
        self.assertEqual(m.verify_route(FIXTURE['state'],state,order=m.NEW_ORDER,generated=True,saved_sha='b'*64),[500])
    def test_mass_roundoff_scoped(self):
        state=changed_state(m.NEW_ORDER);state['sw_reference']['solids'][0]['mass_raw'][0]+=1e-13
        m.verify_route(FIXTURE['state'],state,order=m.NEW_ORDER)
        state['features'][0]['geometry']['fixture']=False
        with self.assertRaises(ValueError):m.verify_route(FIXTURE['state'],state,order=m.NEW_ORDER)
    def test_start_point_type_and_coordinates(self):
        m.verify_points(point(False),configured=False);m.verify_points(point(True),configured=True)
        for key,bad in [('type_raw',3),('position_native',[-10.,0.,0.]),('position_is_null',True)]:
            value=point(True);value['rows'][0][key]=bad
            with self.assertRaises(ValueError):m.verify_points(value,configured=True)
    def test_save_projection_preserves_changes_and_raw(self):
        before=dict(state=changed_state(m.NEW_ORDER,True),parameters=m.expected_parameters(FIXTURE['parameters']),startpoints=point(True))
        after=deepcopy(before);after['state']['document']['needs_save']=False;after['state']['saved_file_sha256']='b'*64
        after['state']['sw_reference']['solids'][0]['mass_raw'][0]+=1e-13
        normalized=m.equivalent_projection(m.save_projection(before),m.save_projection(after))
        self.assertEqual(normalized,m.save_projection(before));self.assertNotEqual(after['state']['sw_reference'],before['state']['sw_reference'])
        after['parameters']['143']['levels']['levels']['toolpath_parameters']['start_Z_native']=0.
        with self.assertRaises(ValueError):m.equivalent_projection(m.save_projection(before),m.save_projection(after))


class FakePointer:pass
class FakeBackend:
    def __init__(self,report):self.r=report;self.order=m.OLD_ORDER;self.configured=False;self.generated=False;self.closed=False;self.trace=[]
    def start(self):pass
    def headers(self,label):return deepcopy(FIXTURE['state'])
    def parameters(self,label):return dict(parameters=deepcopy(FIXTURE['parameters']),startpoints=point(False))
    def field(self,spec):return deepcopy(spec[6] if spec[0] in self.trace else spec[5])
    def set_field(self,spec,pending):pending();self.trace.append(spec[0]);return 0
    def create_point(self,pending):pending();self.trace.append('factory');self.point=FakePointer();return 0
    def created_type(self):return 1
    def create_position(self,pending):pending();self.position=FakePointer();return 0
    def position_state(self):return deepcopy(m.POINT)
    def set_point_coordinates(self,pending):pending();return 0
    def set_point_position(self,pending):pending();return 0
    def point_state(self):return deepcopy(m.POINT)
    def attach_point(self,member,pending):pending();self.trace.append(member);return 0
    def collection_state(self):return dict(count=1,type_raw=1,position_native=deepcopy(m.POINT))
    def move_after(self,oid,anchor,pending):pending();self.order=m.MID_ORDER if oid==143 else m.NEW_ORDER;return 0
    def route(self,label):return changed_state(self.order,self.generated)
    def capture_narrow(self,label):return dict(state=self.route(label),parameters=m.expected_parameters(FIXTURE['parameters']),startpoints=point(True))
    def generate(self,pending):pending();self.generated=True;return 0
    def capture_full(self,label):
        value=self.capture_narrow(label);value['state']['document']['needs_save']=False;value['state']['saved_file_sha256']='b'*64;value['catalogue']=['tool']*18;return value
    def refresh_dirty(self):pass
    def boundary(self):pass
    def save(self):return 0
    def saved_hash(self,report):self.r['source_transition']=dict(strict_save_return=0,source_before_sha256='a'*64,source_after_sha256='b'*64);return 'b'*64
    def finish(self):pass
    def close(self):self.closed=True


class WorkflowTests(unittest.TestCase):
    def setup_run(self,tmp):
        loaded=dict(state=deepcopy(FIXTURE['state']),pocket_parameters=deepcopy(FIXTURE['parameters']),operation_checkpoint={'final_observation':{'tools':['tool']*18}})
        report=dict(scope=m.SCOPE,phase='prepared',source_path='fixture.SLDPRT',initial_source_sha256='a'*64,recipe_pin={'sha256':'c'*64},actions={},
          mutation_attempted=False,readback_verified=False,model_saved=False,actual_full_capture_count=0)
        journal=m.Journal(report,Path(tmp)/'receipt.json',Path(tmp)/'once.json');backend=FakeBackend(report)
        return loaded,report,journal,backend
    def test_complete_flow_and_exact_action_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded,r,j,b=self.setup_run(tmp)
            with patch.object(m,'_is_comtypes_pointer',lambda v:isinstance(v,FakePointer)):result=m.run_backend(b,j,loaded)
            self.assertTrue(result['readback_verified'],result.get('issue'));self.assertTrue(result['model_saved'])
            self.assertEqual(set(result['actions']),set(m.ACTIONS));self.assertTrue(b.closed)
            self.assertTrue(j.marker.exists());self.assertEqual(b.trace.count('factory'),1)
    def test_no_retry_after_factory_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded,r,j,b=self.setup_run(tmp)
            def bad(pending):pending();b.point=None;return 0
            b.create_point=bad
            with patch.object(m,'_is_comtypes_pointer',lambda v:isinstance(v,FakePointer)):result=m.run_backend(b,j,loaded)
            self.assertFalse(result['readback_verified']);self.assertTrue(j.marker.exists())
            self.assertNotIn('AddStartPoint',r['actions']);self.assertNotIn('GenerateToolpath',r['actions'])
            self.assertTrue(r['actions']['CreateStartPointInstance']['returned'])
    def test_bool_is_not_hresult(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded,r,j,b=self.setup_run(tmp)
            def bad(spec,pending):pending();return True
            b.set_field=bad;result=m.run_backend(b,j,loaded)
            self.assertFalse(result['readback_verified']);self.assertEqual(len(r['actions']),1)
            self.assertNotIn('GenerateToolpath',r['actions'])
    def test_factory_s_false_with_pointer_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded,r,j,b=self.setup_run(tmp)
            def bad(pending):pending();b.point=FakePointer();return 1
            b.create_point=bad
            with patch.object(m,'_is_comtypes_pointer',lambda v:isinstance(v,FakePointer)):result=m.run_backend(b,j,loaded)
            self.assertFalse(result['readback_verified']);self.assertNotIn('CreatePosition',r['actions'])
            self.assertEqual(r['actions']['CreateStartPointInstance']['native_return_value'],1)
    def test_terminal_rejects_factory_s_false_even_with_pointer_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded,r,j,b=self.setup_run(tmp)
            with patch.object(m,'_is_comtypes_pointer',lambda v:isinstance(v,FakePointer)):m.run_backend(b,j,loaded)
            r.update(loaded_context_before=loaded,phase_proofs_verified=True,**{k:False for k in m.FORBIDDEN})
            r['actions']['CreateStartPointInstance']['native_return_value']=1
            with self.assertRaisesRegex(ValueError,'HRESULT0'):m.validate_terminal(r)
    def test_marker_precedes_add_and_rejects_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded,r,j,b=self.setup_run(tmp);j.pending('CreateStartPointInstance')
            self.assertTrue(j.marker.exists())
            with self.assertRaises(ValueError):j.pending('CreateStartPointInstance')
            j.pending('AddStartPoint');self.assertTrue(json.loads(j.marker.read_text())['actions']['AddStartPoint']['pending'])

class ContinuationTests(unittest.TestCase):
    setup_run=WorkflowTests.setup_run
    def prepare_continuation_fake(self,tmp):
        loaded,r,j,b=self.setup_run(tmp)
        actual=m.expected_parameters(FIXTURE['parameters'])
        actual['143']['rough']['entry']['GetEntryStartPtX']=[.01,0.,0.]
        configured=dict(state=changed_state(m.NEW_ORDER),parameters=actual,startpoints=point(True))
        failed_path=Path(tmp)/'configured.json';failed_path.write_text(json.dumps({'configured':configured}))
        r.update(loaded_context_before=loaded,continuation=True,configured_receipt_pin={'path':str(failed_path),'sha256':m._file_hash(failed_path)},new_action_count=0)
        b.order=m.NEW_ORDER;b.headers=lambda label:deepcopy(configured['state'])
        b.parameters=lambda label:dict(parameters=deepcopy(actual),startpoints=point(True))
        b.field=lambda spec:-13.4
        def narrow(label):return dict(state=changed_state(m.NEW_ORDER,b.generated),parameters=deepcopy(actual),startpoints=point(True))
        b.capture_narrow=narrow
        def forbidden(*a,**kw):raise AssertionError('No configured mutation may be replayed')
        for name in ('set_field','create_point','create_position','set_point_coordinates','set_point_position','attach_point','move_after'):setattr(b,name,forbidden)
        return loaded,r,j,b
    def test_continuation_dispatches_only_gtp_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded,r,j,b=self.prepare_continuation_fake(tmp);m.run_continuation(b,j,loaded)
            self.assertTrue(r['readback_verified'],r.get('issue'));self.assertTrue(r['model_saved'])
            self.assertEqual(set(r['actions']),{'GenerateToolpath','SaveActiveDocument'});self.assertEqual(r['new_action_count'],2)
    def test_stale_aggregate_blocks_before_gtp(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded,r,j,b=self.prepare_continuation_fake(tmp);original=b.parameters
            def changed(label):
                value=original(label);value['parameters']['143']['levels']['levels']['toolpath_parameters']['start_Z_native']=-13.4;return value
            b.parameters=changed;m.run_continuation(b,j,loaded)
            self.assertFalse(r['readback_verified']);self.assertEqual(r['actions'],{})
    def test_direct_startz_mismatch_blocks_before_gtp(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded,r,j,b=self.prepare_continuation_fake(tmp);b.field=lambda spec:-.0134;m.run_continuation(b,j,loaded)
            self.assertFalse(r['readback_verified']);self.assertEqual(r['actions'],{})


class AbiTests(unittest.TestCase):
    def test_wrong_dispid_and_flags_rejected(self):
        from ctypes import HRESULT,c_double
        from types import SimpleNamespace
        member=SimpleNamespace(name='SetStartZ',restype=HRESULT,idlflags=[17],argtypes=(c_double,),paramflags=((0,'dSpeed'),))
        m.require_abi(member,17,(c_double,),(0,))
        member.idlflags=[16]
        with self.assertRaises(ValueError):m.require_abi(member,17,(c_double,),(0,))
        member.idlflags=[17];member.paramflags=((1,'dSpeed'),)
        with self.assertRaises(ValueError):m.require_abi(member,17,(c_double,),(0,))

if __name__=='__main__':unittest.main()
