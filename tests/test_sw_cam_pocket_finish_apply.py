"""Bounded finish adapter regressions using saved parameter shapes."""
import importlib.util
import json
import math
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parent
MODULE=BASE.parent/'scripts/sw_cam_pocket_finish_apply.py'
spec=importlib.util.spec_from_file_location('finish_apply_tested',MODULE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
PARAMETERS=json.loads((BASE/'fixtures/finish_pair_parameters.json').read_text())


def baseline():
    assigned=dict(native_id=145,is_mill_tool=True,native_read_complete=True,units_verified=False,holder_geometry_verified=False,
        tool_type_raw=1,cut_diameter_native=2.,protrusion_native=20.)
    rows=[]
    for i,oid in enumerate(m.ORDER):
        rows.append(dict(native_id=oid,operation_index=i,setup_native_id=93,setup_index=0,toolpath_generated=oid in (267,247,248,271,143),
            toolpath_record_counts=[{267:760,247:191,248:74,271:29,143:31196}.get(oid,1)] if oid in (267,247,248,271,143) else [],
            assigned_tool=deepcopy(assigned),linked_feature_ids=[79] if oid in (143,144) else [oid]))
    state=dict(operation_count=8,operations=rows,features=[{'id':i} for i in range(21)],document={'needs_save':False},saved_file_sha256='a'*64,
        sw_reference={'solids':[{'mass_raw':[float(i+1)/1000 for i in range(12)]}]})
    catalogue=[dict(native_id=i,tool_type_raw=1,CutDiameter=2.,Protrusion=20.) for i in range(300,318)]+[dict(native_id=777,tool_type_raw=1,CutDiameter=2.,Protrusion=26.)]
    return dict(state=state,pocket_parameters=deepcopy(PARAMETERS),pocket_startpoints={'count':1,'raw_xyz':[10.,0.,0.]},
        neck_tool_candidate={'native_id':777},neck_tool_checkpoint={'catalogue':catalogue},source_sha256='a'*64)


def capture(loaded,configured=True,generated=False,saved=False):
    state=deepcopy(loaded['state']);row=state['operations'][-1]
    if configured:row['assigned_tool']=m.wanted_assignment(loaded)
    if generated:row.update(toolpath_generated=True,toolpath_record_counts=[1200])
    state['document']['needs_save']=configured and not saved
    if saved:state['saved_file_sha256']='b'*64
    return dict(state=state,parameters=m.expected_parameters(loaded['pocket_parameters']) if configured else deepcopy(loaded['pocket_parameters']),
        startpoints=deepcopy(loaded['pocket_startpoints']),catalogue=deepcopy(loaded['neck_tool_checkpoint']['catalogue']))


class Journal:
    def __init__(self,report):self.report=report
    def persist(self):pass
    def pending(self,label):
        if label in self.report['actions']:raise ValueError('duplicate')
        self.report['actions'][label]=dict(attempted=True,returned=False,pending=True)
        self.report.update(mutation_attempted=True,phase=label)
    def returned(self,label,value):self.report['actions'][label].update(returned=True,pending=False,native_return_type=type(value).__name__,native_return_value=value)


class Backend:
    def __init__(self,loaded,report,*,fail=None):
        self.loaded=loaded;self.report=report;self.calls=[];self.fail=fail;self.configured=False;self.generated=False;self.saved=False
        self.values={x[0]:[x[5],True] if x[4]=='depth_pair' else deepcopy(x[5]) for x in m.FIELDS}
    def start(self):self.calls.append('start')
    def headers(self,label):return deepcopy(self.loaded['state'])
    def parameters(self,label):return dict(parameters=deepcopy(self.loaded['pocket_parameters']),startpoints=deepcopy(self.loaded['pocket_startpoints']))
    def catalogue(self):return deepcopy(self.loaded['neck_tool_checkpoint']['catalogue'])
    def field(self,spec):return deepcopy(self.values[spec[0]])
    def set_field(self,spec,pending):
        pending();self.calls.append(spec[0]);self.values[spec[0]]=deepcopy(spec[6]);return 1 if self.fail==spec[0] else 0
    def assign(self,pending):pending();self.calls.append('assign');return 0
    def current_tool(self):return m.wanted_assignment(self.loaded)
    def refresh_dirty(self):pass
    def capture_narrow(self,label):
        value=capture(self.loaded,True,self.generated)
        if label=='configured' and self.fail=='unexpected':value['parameters']['144']['finish']['DepthAllow']=.1
        return value
    def generate(self,pending):pending();self.calls.append('generate');self.generated=True;return 1 if self.fail=='generate' else 0
    def boundary(self):pass
    def save(self):self.calls.append('save');self.saved=True;return 0
    def saved_hash(self,report):
        self.report['source_transition']=dict(source_before_sha256='a'*64,source_after_sha256='b'*64,strict_save_return=0);return 'b'*64
    def capture_full(self,label):return capture(self.loaded,True,True,True)
    def finish(self):self.report['messages']=dict(subscribed=True,disconnected=True,active=False)
    def close(self):self.calls.append('close')


def report(loaded):
    return dict(scope=m.SCOPE,status='prepared',phase='prepared',actions={},mutation_attempted=False,readback_verified=False,
        model_saved=False,configuration_readback_verified=False,actual_full_capture_count=0,phase_proofs_verified=True,
        loaded_context_before=deepcopy(loaded),initial_source_sha256='a'*64,**{k:False for k in m.FORBIDDEN})


class Tests(unittest.TestCase):
    def test_recipe_changes_only_approved_parameters(self):
        old=deepcopy(PARAMETERS);new=m.expected_parameters(old);self.assertEqual(old,PARAMETERS)
        self.assertEqual(new['143'],m.projected(old)['143']);self.assertTrue(new['144']['finish']['BottomFinOpt'])
        self.assertEqual(new['144']['levels'],m.projected(old)['144']['levels']);m.verify_parameters(old,new,configured=True)
    def test_compensation_must_not_change(self):
        new=m.expected_parameters(PARAMETERS);new['144']['nc']['feeds_compensation']['GetCNCComp']=0
        with self.assertRaises(ValueError):m.verify_parameters(PARAMETERS,new,configured=True)
    def test_floor_and_stock_are_strict(self):
        for key,val in [('BottomFinOpt',False),('GetPreviousAllowance',.25),('DepthAllow',.1),('SideAllow',.1)]:
            new=m.expected_parameters(PARAMETERS);new['144']['finish'][key]=val
            with self.assertRaises(ValueError):m.verify_parameters(PARAMETERS,new,configured=True)
    def test_only_two_nc_fields_allow_two_ulps(self):
        expected=m.expected_parameters(PARAMETERS);new=deepcopy(expected)
        for oid in ('143','144'):
            for name in ('XYFeed','GetSpndlSpeed'):
                x=new[oid]['nc']['feeds_compensation'][name];new[oid]['nc']['feeds_compensation'][name]=math.nextafter(math.nextafter(x,math.inf),math.inf)
        m.verify_parameters(PARAMETERS,new,configured=True)
        new['144']['nc']['feeds_compensation']['XYFeed']=math.nextafter(new['144']['nc']['feeds_compensation']['XYFeed'],math.inf)
        with self.assertRaises(ValueError):m.verify_parameters(PARAMETERS,new,configured=True)
    def test_nonfinite_nc_and_coerced_types_fail(self):
        for value in (float('nan'),float('inf'),56):
            new=m.expected_parameters(PARAMETERS);new['144']['nc']['feeds_compensation']['XYFeed']=value
            with self.assertRaises(ValueError):m.verify_parameters(PARAMETERS,new,configured=True)
    def test_profile_setting_change_is_not_nc_roundoff(self):
        new=m.expected_parameters(PARAMETERS);new['144']['finish']['FirstDepthCut']=math.nextafter(.3,math.inf)
        with self.assertRaises(ValueError):m.verify_parameters(PARAMETERS,new,configured=True)
    def test_actual_id_not_predicted(self):
        loaded=baseline();self.assertEqual(m.wanted_assignment(loaded)['native_id'],777)
        loaded['neck_tool_candidate']['native_id']=145
        with self.assertRaises((ValueError,StopIteration)):m.wanted_assignment(loaded)
    def test_observed_protrusion_roundoff_preserved_exactly(self):
        loaded=baseline();value=math.nextafter(26.,math.inf)
        loaded['neck_tool_checkpoint']['catalogue'][-1]['Protrusion']=value
        self.assertTrue(m.nominal_protrusion(value));self.assertEqual(m.wanted_assignment(loaded)['protrusion_native'],value)
        c=capture(loaded);m.verify_capture(loaded,c,configured=True,generated=False)
        c['state']['operations'][-1]['assigned_tool']['protrusion_native']=26.
        with self.assertRaises(ValueError):m.verify_capture(loaded,c,configured=True,generated=False)
    def test_protrusion_numeric_limit_is_only_two_ulps(self):
        value=26.
        for _ in range(2):value=math.nextafter(value,math.inf)
        self.assertTrue(m.nominal_protrusion(value))
        self.assertFalse(m.nominal_protrusion(math.nextafter(value,math.inf)))
        for bad in (26,float('inf'),float('nan'),26.000001):self.assertFalse(m.nominal_protrusion(bad))

    def test_five_prior_paths_preserved(self):
        loaded=baseline()
        for oid in (267,247,248,271,143):
            c=capture(loaded);next(x for x in c['state']['operations'] if x['native_id']==oid)['toolpath_record_counts'][0]+=1
            with self.assertRaises(ValueError):m.verify_capture(loaded,c,configured=True,generated=False)
    def test_catalogue_and_rough_point_preserved(self):
        loaded=baseline()
        for key in ('catalogue','startpoints'):
            c=capture(loaded);c[key]=[]
            with self.assertRaises(ValueError):m.verify_capture(loaded,c,configured=True,generated=False)
    def test_generated_target_bounded(self):
        loaded=baseline();c=capture(loaded,generated=True);self.assertEqual(m.verify_capture(loaded,c,configured=True,generated=True),[1200])
        c['state']['operations'][-1]['toolpath_record_counts']=[0]
        with self.assertRaises(ValueError):m.verify_capture(loaded,c,configured=True,generated=True)
    def test_unknown_percent_flag_read_but_absolute_target(self):
        spec=next(x for x in m.FIELDS if x[0]=='first_depth')
        self.assertTrue(m.initial_field_matches(spec,[10.,True]));self.assertTrue(m.initial_field_matches(spec,[10.,False]))
        self.assertFalse(m.initial_field_matches(spec,[10.,0]));self.assertEqual(spec[6],[.3,False])
    def test_complete_single_configure_gtp_save(self):
        loaded=baseline();r=report(loaded);b=Backend(loaded,r);m.run_backend(b,Journal(r),loaded)
        self.assertTrue(r['readback_verified']);self.assertEqual(b.calls.count('generate'),1);self.assertEqual(b.calls.count('save'),1)
        self.assertEqual(set(r['actions']),set(m.ACTIONS));self.assertEqual(r['actual_full_capture_count'],1)
        with patch.object(m.group,'current_projection',lambda c:{'state':c['state'],'source_sha256':c['source_sha256']}):
            ctx=m.validate_terminal(r);self.assertEqual(ctx['generated_pocket_finish']['tool_native_id'],777)
    def test_uncertain_configuration_never_generates(self):
        for fail in ('bottom_finish','unexpected'):
            loaded=baseline();r=report(loaded);b=Backend(loaded,r,fail=fail);m.run_backend(b,Journal(r),loaded)
            self.assertEqual(r['status'],'uncertain');self.assertNotIn('generate',b.calls);self.assertNotIn('save',b.calls)
    def test_nonzero_gtp_never_saves_or_retries(self):
        loaded=baseline();r=report(loaded);b=Backend(loaded,r,fail='generate');m.run_backend(b,Journal(r),loaded)
        self.assertEqual(b.calls.count('generate'),1);self.assertNotIn('save',b.calls);self.assertFalse(r['readback_verified'])
    def test_terminal_rejects_fabricated_hresult(self):
        loaded=baseline();r=report(loaded);b=Backend(loaded,r);m.run_backend(b,Journal(r),loaded)
        r['actions']['SetTool']['native_return_value']=1
        with self.assertRaises(ValueError):m.validate_terminal(r)
    def test_save_projection_preserves_raw_roundoff(self):
        loaded=baseline();a=m.save_projection(capture(loaded,generated=True));b=deepcopy(a)
        b['state']['sw_reference']['solids'][0]['mass_raw'][0]=math.nextafter(b['state']['sw_reference']['solids'][0]['mass_raw'][0],math.inf)
        raw=deepcopy(b);self.assertEqual(m.equivalent_projection(a,b),a);self.assertEqual(raw,b)
    def test_wrong_dispid_rejected(self):
        from types import SimpleNamespace
        from ctypes import HRESULT,c_double
        member=SimpleNamespace(restype=HRESULT,idlflags=[96],argtypes=(c_double,),paramflags=((1,'x'),),name='SetFirstDepthCut')
        with self.assertRaises(ValueError):m.prior.require_abi(member,95,(c_double,),(1,))
    def test_completed_loader_actual_files_and_marker(self):
        import tempfile
        loaded=baseline()
        for key in m.group.CURRENT_KEYS:loaded.setdefault(key,None)
        r=report(loaded);b=Backend(loaded,r);m.run_backend(b,Journal(r),loaded)
        with tempfile.TemporaryDirectory(prefix='finish_authority_') as folder:
            p=Path(folder);source=p/'fixture.SLDPRT';source.write_bytes(b'synthetic fixture')
            sha=m._file_hash(source);r.update(source_path=str(source),process_id=1,module_pin=m.common._pin(m.__file__),
                saved_source_sha256=sha,live_pins=[],offline_proof_pins=[],bootstrap_export_pins=[],
                parent_pin={'path':str(p/'old.json'),'sha256':'c'*64},recipe_pin={'path':'recipe.json','sha256':'d'*64})
            r['source_transition']['source_after_sha256']=sha;r['save_stage']['saved_file_sha256']=sha;r['final']['state']['saved_file_sha256']=sha
            r['checkpoint_digest']=m._digest(m.group.current_projection(m.validate_terminal(r)))
            marker=p/'marker.json';receipt=p/'receipt.json'
            marker.write_text(json.dumps(m.Journal(r,receipt,marker).marker_state()));r['marker_pin']=m.common._pin(marker)
            receipt.write_text(json.dumps(r))
            with patch.object(m,'marker_path',lambda *_:marker):
                ctx=m.load_completed(str(receipt),m._file_hash(receipt),process_id=1,expected_document_path=str(source),expected_source_sha256=sha)
                self.assertEqual(ctx['authority_kind'],m.AUTHORITY)
                marker.write_text('{}')
                with self.assertRaises(ValueError):m.load_completed(str(receipt),m._file_hash(receipt),process_id=1,expected_document_path=str(source),expected_source_sha256=sha)

    def test_cli_reads_utf8_request_and_passes_validate_boolean(self):
        import tempfile,io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory(prefix='finish_cli_') as folder:
            path=Path(folder)/'request with spaces.json';request={'action':'fixture','params':{'label':'проверка'}}
            path.write_text(json.dumps(request,ensure_ascii=False),encoding='utf-8-sig')
            with patch.object(m,'dispatch_request',return_value={'status':'validated_offline','native_called':False}) as dispatch,redirect_stdout(io.StringIO()) as output:
                self.assertEqual(m.main(['--request',str(path),'--validate-only']),0)
            dispatch.assert_called_once_with(request,validate_only=True)
            self.assertIs(json.loads(output.getvalue())['native_called'],False)
    def test_cli_regular_dispatch_passes_false_and_strict_success(self):
        import tempfile,io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory(prefix='finish_cli_') as folder:
            path=Path(folder)/'request.json';path.write_text('{}')
            with patch.object(m,'dispatch_request',return_value={'status':'review_required','readback_verified':True}) as dispatch,redirect_stdout(io.StringIO()):
                self.assertEqual(m.main(['--request',str(path)]),0)
            dispatch.assert_called_once_with({},validate_only=False)
    def test_cli_error_report_returns_nonzero(self):
        import tempfile,io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory(prefix='finish_cli_') as folder:
            path=Path(folder)/'request.json';path.write_text('{}')
            for result in ({'status':'error','issue':{'type':'ValueError'}},{'status':'uncertain','readback_verified':False},{'status':'error','readback_verified':1}):
                with patch.object(m,'dispatch_request',return_value=result),redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(m.main(['--request',str(path)]),1)
                self.assertEqual(json.loads(output.getvalue())['status'],result['status'])
    def test_cli_dispatch_exception_cannot_be_reported_as_success(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix='finish_cli_') as folder:
            path=Path(folder)/'request.json';path.write_text('{}')
            with patch.object(m,'dispatch_request',side_effect=ValueError('preflight rejected')):
                with self.assertRaises(ValueError):m.main(['--request',str(path),'--validate-only'])

    def test_callback_real_native_field_and_raw_setter(self):
        from contextlib import contextmanager
        class Guard:
            def read(self,obj,name,*args):return getattr(obj,name)(*args) if callable(getattr(obj,name)) else getattr(obj,name)
            def dispatch_once(self,call,*,persist_pending):persist_pending();return call()
        class Context:
            @contextmanager
            def guard(self):yield Guard()
        class Owner:
            BottomFinOpt=False
            def set(self,value):self.BottomFinOpt=value;return 0
        owner=Owner();setattr(owner,'_ICWFinishMillOp__com__set_BottomFinOpt',owner.set)
        backend=object.__new__(m.NativeBackend);backend.ctx=Context();backend.owner=lambda g,s:(owner,None,'ICWFinishMillOp')
        spec=next(x for x in m.FIELDS if x[0]=='bottom_finish');calls=[]
        self.assertIs(backend.field(spec),False);self.assertEqual(backend.set_field(spec,lambda:calls.append('pending')),0)
        self.assertIs(backend.field(spec),True);self.assertEqual(calls,['pending'])

if __name__=='__main__':unittest.main()
