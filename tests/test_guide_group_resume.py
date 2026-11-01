"""Synthetic interrupted-prefix continuation tests; no CAD calls."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json,os,sys,types
import pytest
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_guide_group_resume as m
F=json.loads((Path(__file__).parent/'guide_configuration_shapes.json').read_text())


def update(row,spec,value):
    key=spec[0]
    if 'rough' in row:
        area={'entry_type':'entry','spiral_radius':'entry','spiral_pitch':'entry','first_depth':'depth','subsequent_depth':'depth'}.get(key,'boundary')
        row['rough'][area][spec[2]]['raw']=deepcopy(value)
        if key=='entry_type':row['startpoints']['entry_type']=value
    elif key in row['finish_fields']:row['finish_fields'][key]=deepcopy(value)
    elif key=='gouge_check':row['protected_finish']['gouge_check']=value
    elif key in ('lead_in_type','lead_out_type'):row['protected_finish']['lead_types'][0 if key=='lead_in_type' else 1]=value
    else:row['finish']['BottomFinOpt']['raw']=value


def history():
    p=dict(scope=m.config.SCOPE,module_pin=m.common._pin(m.config.__file__),source_path='synthetic.SLDPRT',source_sha256='a'*64,
        phase='328:previous_allowance',mutation_attempted=True,native_dispatch_pending=False,save_attempted=False,model_saved=False,GTP_attempted=False,
        recipe=deepcopy(F['recipe']),before=deepcopy(F['initial']),actions={},captures=[],current_document={'path':'synthetic.SLDPRT','title':'synthetic.SLDPRT','type':1,'needs_save':False})
    state=deepcopy(F['initial'])
    for target in p['recipe']['rows']:
        oid=target['operation_native_id'];name=str(oid)+':SetTool'
        next(o for o in state['binding']['operations']if o['native_id']==oid)['assigned_tool']=deepcopy(F['wanted'])
        next(o for o in state['parameters']if o['operation_native_id']==oid)['tool']['generic']=deepcopy(F['wanted'])
        p['captures'].append(dict(label='after_tool_'+str(oid),**deepcopy(state)))
        p['actions'][name]=dict(status='verified',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,
            native_return=m.group.return_observation(0),observed=m.config.capture_reference(p,'after_tool_'+str(oid),state,oid))
    p['after_tools']=deepcopy(state)
    for target,row in zip(p['recipe']['rows'],state['parameters']):
        for spec in m.specs(target):
            name=str(target['operation_native_id'])+':'+spec[0];value=target['fields'][spec[0]]
            update(row,spec,value)
            p['actions'][name]=dict(status='verified',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,
                native_return=m.group.return_observation(0),observed=deepcopy(value))
            if name==p['phase']:break
        if target['operation_native_id']==328:break
    pin={'path':'partial.json','sha256':'d'*64}
    e=dict(client_present=False,no_new_candidate_server_at_or_after_client_start=True,client_result_status='timeout',client_exit_code=1,
        native_receipt_sha256=pin['sha256'],native_phase=p['phase'],native_dispatch_pending=False,save_attempted=False,
        source=p['source_path'],source_sha256=p['source_sha256'])
    return p,e,pin,state


def test_exact_verified_prefix_and_remaining_values():
    p,e,pin,state=history()
    assert len(m.validate_partial(p,e,pin))==16
    rows=m.reconcile(p,state,F['wanted'])
    assert len(rows)==16 and rows[0]['action']=='328:override_previous' and rows[-1]['action']=='328:bottom_finish'
    assert all(r['action']not in p['actions']for r in rows)


@pytest.mark.parametrize('bad',['writer_present','new_writer','pending','save','unknown','prefix','capture','exit_source','module','event'])
def test_reject_unproved_writer_exit_or_uncertain_prefix(bad):
    p,e,pin,state=history()
    if bad=='writer_present':e['client_present']=True
    if bad=='new_writer':e['no_new_candidate_server_at_or_after_client_start']=False
    if bad=='pending':p['native_dispatch_pending']=True
    if bad=='save':p['save_attempted']=True
    if bad=='unknown':p['actions'][p['phase']]['readback_verified']=False
    if bad=='prefix':p['actions'].pop('322:entry_type')
    if bad=='capture':p['captures'][-1]['parameters'][0]['nc']['extra']=1
    if bad=='exit_source':e['source_sha256']='f'*64
    if bad=='module':p['module_pin']['sha256']='f'*64
    if bad=='event':p['messages']={'event_count':1}
    with pytest.raises(ValueError):m.validate_partial(p,e,pin)


@pytest.mark.parametrize('bad',['confirmed','untouched','nc','protected','route','foreign_id'])
def test_reconcile_protects_confirmed_and_unselected_state(bad):
    p,e,pin,state=history()
    if bad=='confirmed':state['parameters'][0]['rough']['entry']['GetSpiralRadius']['raw']=9.
    if bad=='untouched':state['parameters'][3]['finish_fields']['perimeter']=99
    if bad=='nc':state['parameters'][3]['nc']['extra']=1
    if bad=='protected':state['parameters'][0]['rough']['depth']['FinCutAmt']['raw']=.9
    if bad=='route':state['binding']['operations'][0]['name']='foreign'
    if bad=='foreign_id':state['parameters'][3]['operation_native_id']=999
    with pytest.raises(ValueError):m.reconcile(p,state,F['wanted'])


class Fake:
    def __init__(self,state,report,failure=None):
        self.state=deepcopy(state);self.report=report;self.trace=[];self.failure=failure
        self.ctx=SimpleNamespace(expected_document={'path':'synthetic.SLDPRT','title':'synthetic.SLDPRT','type':1,'needs_save':False})
    def start(self):self.trace.append('start')
    def check_prepared(self,prepared):
        self.trace.append('check_prepared')
        if self.failure=='stale':raise ValueError('prepared changed')
        assert self.state==prepared
    def capture_parameters(self,label):
        self.trace.append('capture:'+label)
        if self.failure==label:raise ValueError('read failed')
        out=deepcopy(self.state)
        if self.failure=='saved_delta'and label=='saved':out['binding']['operations'][0]['name']='foreign'
        self.report.setdefault('captures',[]).append(dict(label=label,**deepcopy(out)))
        return out
    def set_field(self,target,spec,value,pending):
        pending();self.trace.append(('field',target['operation_native_id'],spec[0]))
        if self.failure=='field_return':return -1
        row=next(v for v in self.state['parameters']if v['operation_native_id']==target['operation_native_id'])
        update(row,spec,value)
        if self.failure=='alias_later' and spec[0]=='apply_all':row['finish_fields']['out_independent']=True
        if self.failure=='foreign_delta':self.state['parameters'][0]['nc']['extra']=1
        return 0
    def refresh_dirty(self):self.trace.append('refresh')
    def read_fields(self,target,names):
        self.trace.append(('read',target['operation_native_id'],tuple(names)))
        row=next(v for v in self.state['parameters']if v['operation_native_id']==target['operation_native_id'])
        return{s[0]:m.config.field_value(row,s)for s in m.specs(target)if s[0]in names}
    def boundary(self):self.trace.append('boundary')
    def save(self):self.trace.append('save');return -1 if self.failure=='save_return'else 0
    def saved_hash(self,r):
        self.report['source_transition']={'document':deepcopy(self.ctx.expected_document)}
        return'b'*64
    def finish(self):self.trace.append('finish')
    def close(self):self.trace.append('close')


def setup(tmp_path,failure=None):
    p,e,pin,state=history();remaining=m.reconcile(p,state,F['wanted'])
    prepared={'actual':deepcopy(state),'remaining':deepcopy(remaining)}
    loaded=dict(partial=p,prepared=prepared,configuration_tool=F['wanted'],guide_parameters={'configuration':{'synthetic':True}},prepared_pin={'path':'prepared.json','sha256':'e'*64})
    report=dict(source_path=p['source_path'],source_sha256=p['source_sha256'],recipe_sha256='c'*64,
        request={'process_id':52},ownership={'process_id':52},source_partial_receipt_pin=pin)
    journal=m.ResumeJournal(report,tmp_path/'receipt.json',tmp_path/'marker.json')
    return Fake(state,report,failure),journal,loaded


def test_resume_only_untouched_fields_and_one_save(tmp_path):
    b,j,l=setup(tmp_path);r=m.run_resume(b,j,l)
    assert r['status']=='saved_configuration_no_toolpath',r.get('issue')
    assert r['model_saved']and r['readback_verified']and r['continuation_ready']
    assert not r['SetTool_attempted']and not r['GTP_attempted']
    assert b.trace.count('save')==1
    writes=[str(x[1])+':'+x[2]for x in b.trace if isinstance(x,tuple)and x[0]=='field']
    assert writes and all(x not in l['partial']['actions']for x in writes)
    assert set(r['actions'])=={x['action']for x in l['prepared']['remaining']}|{'SaveActiveDocument'}
    assert r['saved_checkpoint_context']['source_sha256']=='b'*64
    assert r['saved_checkpoint_context']['snapshot_sha256']==m.group._digest(r['saved'])
    assert not r['persistence_after_reopen_verified']


@pytest.mark.parametrize('failure',['stale','field_return','foreign_delta','configured','save_return','saved_delta'])
def test_failure_stops_and_retains_save_fact(tmp_path,failure):
    b,j,l=setup(tmp_path,failure);r=m.run_resume(b,j,l)
    assert not r['readback_verified']and not r['continuation_ready']
    assert r['model_saved']is(failure=='saved_delta')
    assert b.trace.count('save')<=1 and b.trace[-1]=='close'
    if failure not in ('save_return','saved_delta'):assert 'save'not in b.trace
    if failure=='stale':assert not r['mutation_attempted']and r['actions']=={}
    before=(j.receipt.read_bytes(),j.marker.read_bytes()if j.marker.exists()else None)
    with pytest.raises(ValueError):m.run_resume(b,j,l)
    assert before==(j.receipt.read_bytes(),j.marker.read_bytes()if j.marker.exists()else None)


def test_prepare_is_read_only_and_records_remainder(tmp_path):
    b,j,l=setup(tmp_path);r=m.run_prepare(b,j.report,lambda:None,l)
    assert r['status']=='observed'and len(r['remaining'])==16 and r['read_only']
    assert not r['mutation_attempted']and not r['save_attempted']and not r['GTP_attempted']
    assert b.trace==['start','capture:reconcile','finish','close']


def native(tmp_path):
    document={'path':str(tmp_path/'synthetic.SLDPRT'),'title':'synthetic.SLDPRT','type':1,'needs_save':False}
    loaded={'state':{'document':document,'operations':[{'native_id':248,'assigned_tool':{'native_id':249}}]},
        'ids':{},'guide_parameters':{'document':document},'partial':{'current_document':document}}
    args={'process_id':52,'expected_document_path':document['path'],'expected_source_sha256':'a'*64}
    class Trap:
        def __getattr__(self,name):raise AssertionError('Unexpected native access: '+name)
    return m.NativeBackend(loaded,args,Trap(),'synthetic-clsid',str(tmp_path/'vendor.tlb'),{},lambda:None)


def test_real_constructor_methods_and_start_boundary(tmp_path,monkeypatch):
    b=native(tmp_path);assert isinstance(b.capture,types.ModuleType)
    assert not [k for k in vars(b)if callable(getattr(type(b),k,None))]
    assert b.capture_parameters.__func__ is m.config.NativeBackend.capture_parameters
    trace=[];b.ctx.files=lambda:trace.append('files');b.ctx.identity=lambda:trace.append('identity')
    class Entered(Exception):pass
    def bootstrap(*args):trace.append('bootstrap');raise Entered()
    monkeypatch.setattr(b.capture.cone,'_bootstrap',bootstrap)
    with pytest.raises(Entered):b.start()
    assert trace==['files','identity','bootstrap']


def test_actual_resume_binding_batch_constructor_and_scalar_invocations(tmp_path,monkeypatch):
    from contextlib import contextmanager
    b=native(tmp_path);p,e,pin,state=history();trace=[];doc=object();app=object()
    (tmp_path/'synthetic.SLDPRT').write_bytes(b'part');(tmp_path/'generated.py').write_bytes(b'pass')
    pin=m.common._pin(tmp_path/'generated.py');b.loaded.update(generated_pin=pin,pins=[pin],partial=p)
    b.ctx.app=app;b.ctx.files=lambda:None;b.ctx.owned=lambda:None;b.ctx.identity=lambda:b.ctx.expected_document;b.events=lambda:None
    b.boundary=lambda:trace.append('boundary')
    class Guard:
        def typed(self,value,name):return value
        def read(self,value,name):assert value is app and name=='IGetActiveDoc';return doc
    @contextmanager
    def guard():yield Guard()
    b.ctx.guard=guard
    Real=m.reader.ParameterReadBatch
    class Transport(Real):
        def __enter__(self):trace.append('enter');return self
        def __exit__(self,*args):trace.append('exit')
        def require_complete(self):trace.append('complete')
    monkeypatch.setattr(m.reader,'ParameterReadBatch',Transport)
    monkeypatch.setattr(m.fields,'make_configuration_check',lambda *a:lambda:None)
    monkeypatch.setattr(m.config.definitions,'read_current_binding',lambda *a,**k:(deepcopy(state['binding']),{}))
    def read(backend,target,*,field_names,diagnostic):
        assert backend is b and b.doc is doc and diagnostic in b.report['field_readbacks']
        trace.append(('fields',target['operation_native_id']));row=next(v for v in state['parameters']if v['operation_native_id']==target['operation_native_id'])
        diagnostic.update(field_values={s[0]:m.config.field_value(row,s)for s in m.specs(target)},read_complete=True)
        return diagnostic
    monkeypatch.setattr(m.fields,'read_field_values',read)
    b.check_prepared(state)
    assert trace[:4]==['boundary','enter','exit','complete']
    assert [x[1]for x in trace if isinstance(x,tuple)]==[322,324,326,328]
    assert len(b.report['field_readbacks'])==4


def test_failed_read_prefix_persisted(tmp_path,monkeypatch):
    b=native(tmp_path);persist=[];b.persist=lambda:persist.append(deepcopy(b.report))
    def read(*a,diagnostic,**kw):diagnostic.update(read_complete=False,stage='getter');raise ValueError('transport')
    monkeypatch.setattr(m.fields,'read_field_values',read)
    with pytest.raises(ValueError):b.read_fields(F['targets'][0],['entry_type'])
    assert persist[0]['field_readbacks']==[{}]
    assert persist[-1]['field_readbacks'][0]['stage']=='getter'


def test_current_alias_overrides_prepared_skip_decision(tmp_path):
    b,j,l=setup(tmp_path,'alias_later')
    b.state['parameters'][3]['finish_fields']['out_independent']=False
    l['prepared']['actual']=deepcopy(b.state)
    l['prepared']['remaining']=m.reconcile(l['partial'],b.state,F['wanted'])
    old=next(v for v in l['prepared']['remaining']if v['field']=='out_independent')
    assert old['write_required']is False
    r=m.run_resume(b,j,l)
    assert r['status']=='saved_configuration_no_toolpath',r.get('issue')
    assert r['fields_before']['328:out_independent']is True
    assert r['actions']['328:out_independent']['attempted']is True
    assert ('field',328,'out_independent')in b.trace
