"""Offline native-graph and typed-buffer fault injection; no COM server."""
from copy import deepcopy
from ctypes import POINTER, c_double, c_long, c_short, cast, HRESULT
from ctypes.wintypes import VARIANT_BOOL
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import scripts
scripts.__path__.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scripts import sw_cam_finish_floor_read as m
from scripts import sw_cam_dispatch_guard as guard


def pin(path, value):
    path.write_bytes(value)
    return dict(path=str(path), sha256=hashlib.sha256(value).hexdigest())


class Obj:
    def __init__(self, role, state): self.role, self.state = role, state
    def QueryInterface(self, cls):
        self.state['qi'].append((self.role, cls.__name__))
        return cls(self.role, self.state)


def pointer_call(self, percent, amount):
    self.state['pointer_calls'] += 1
    assert cast(percent, POINTER(c_short)).contents.value == m.BOOL_SENTINEL
    assert cast(amount, POINTER(c_double)).contents.value != cast(amount, POINTER(c_double)).contents.value
    if self.state.get('pointer_exception'): raise ValueError('pointer failed')
    if not self.state.get('omit_bool'):
        cast(percent, POINTER(c_short)).contents.value = self.state.get('raw_bool', -1 if self.state['values']['stepover'][0] else 0)
    if not self.state.get('omit_double'):
        cast(amount, POINTER(c_double)).contents.value = self.state.get('raw_double', self.state['values']['stepover'][1])
    return self.state.get('hresult', 0)


@pytest.fixture
def env(tmp_path, monkeypatch):
    source=pin(tmp_path/'part.SLDPRT', b'saved source')
    proof=pin(tmp_path/'proof.json', b'proof')
    own=dict(path=m.__file__,sha256=m.finish._file_hash(m.__file__))
    doc=dict(path=source['path'],title='part.SLDPRT',type=1,needs_save=False)
    state=dict(pid=123,document=deepcopy(doc),events=True,owned=True,evidence=True,
               op_id=144,feature_id=79,suppressed=False,op_type=1,found=True,
               calls=[],qi=[],pointer_calls=0,persists=0)
    values={v[0]:{'bool':False,'long':1,'double':30.,'double_bool':[.5,False],
                      'owned_bool_double':[False,.25]}[v[3]] for v in m.FIELDS}
    state['values']=values
    classes={n:type(n,(Obj,),{'_iid_':'{test-'+n+'}'}) for n in m.INTERFACES}
    setattr(classes['ICWFinishMillOp'],m.RAW_STEPOVER,pointer_call)
    for owner,cls in classes.items():
        members=[]
        for _,interface,name,kind,dispid in m.FIELDS:
            if interface != owner: continue
            if kind=='owned_bool_double': args,flags=(POINTER(VARIANT_BOOL),POINTER(c_double)),(0,0)
            elif kind=='double_bool': args,flags=(POINTER(c_double),POINTER(VARIANT_BOOL)),(2,2)
            else: args,flags=(POINTER({'bool':VARIANT_BOOL,'long':c_long,'double':c_double}[kind]),),(10,)
            prop=not name.startswith('Get')
            members.append(SimpleNamespace(name='_get_'+name if prop else name,
                restype=HRESULT,argtypes=args,paramflags=tuple((f,'value') for f in flags),
                idlflags=[dispid]+(['propget'] if prop else [])))
        cls._methods_=members
    objects={n:Obj(n,state) for n in ('doc','operation','feature','collection','sw')}
    mapping={v[2]:v[0] for v in m.FIELDS}
    def native(obj,name,*args):
        state['calls'].append((obj.role,name))
        if obj is objects['sw']: assert name=='GetProcessID'; return state['pid']
        if name=='GetCWObjectFromID':return objects['operation' if args[0]==3 else 'feature'],state['found']
        if name=='GetCWObjectID':return (state['op_id'] if args[0].role=='operation' else state['feature_id']),True
        if name=='Suppressed':return state['suppressed']
        if name=='OpernType':return state['op_type']
        if name=='IGetAllFeatures':return objects['collection']
        if name=='Count':return 1
        if name=='Item':return objects['feature']
        key=mapping[name]
        value=deepcopy(values[key])
        if key=='retract_ramp_height' and state.get('on_last'):state['on_last']()
        return tuple(value) if type(value) is list else value
    monkeypatch.setattr(guard,'_member',native)
    monkeypatch.setattr(guard,'_typed',lambda obj,name,path:obj.QueryInterface(classes[name]))
    monkeypatch.setattr(guard,'raw_part_identity',lambda sw:deepcopy(state['document']))
    monkeypatch.setattr(m,'_member',native)
    monkeypatch.setattr(m.finish,'interface_class',lambda name,*args:classes[name])
    def check(key):
        if not state[key]:raise ValueError(key+' changed')
    kwargs=dict(process_id=123,expected_document=doc,source_sha256=source['sha256'],
        evidence_pins=[proof,own],verify_evidence=lambda:check('evidence'),
        verify_owned_process=lambda:check('owned'),check_events=lambda:check('events'))
    ctx=SimpleNamespace(guard=lambda:guard.ScopedCamDispatchGuard(objects['sw'],'fake.tlb',**kwargs),
        identity=lambda:deepcopy(state['document']),args={'expected_source_sha256':source['sha256']},
        files=lambda:check('evidence'),owned=lambda:check('owned'))
    backend=SimpleNamespace(ctx=ctx,sw=objects['sw'],typelib_path='fake.tlb',
        native={'doc':objects['doc'],'operations':{}},report={},
        args=dict(process_id=123,expected_document_path=source['path'],expected_source_sha256=source['sha256'],
                  progress_path=str(tmp_path/'progress.json'),receipt_path=str(tmp_path/'receipt.json')),
        loaded=dict(pins=[proof,own],generated_pin={}),events=lambda:check('events'))
    backend.persist=lambda:state.update(persists=state['persists']+1)
    backend.target=lambda g,oid:m.finish.prior.NativeBackend.target(backend,g,oid)
    return SimpleNamespace(state=state,values=values,classes=classes,objects=objects,
         kwargs=kwargs,backend=backend,source=source,proof=proof,tmp=tmp_path)


def test_exact_eighteen_with_owned_stepover_and_both_boundaries(env):
    result=m.read_fields(env.backend,'inspect')
    assert result==env.values and len(result)==18
    d=env.backend.report['floor_field_batches'][0]
    assert d['complete'] and d['batch']['read_scope_complete']
    assert d['batch']['complete_boundary_checks']==2 and d['batch']['content_hash_reads']==6
    assert d['batch']['timer_counts']['identity']==6 and d['batch']['timer_counts']['binding']==2
    assert d['batch']['getter_calls']==40 and d['batch']['query_interface_calls']==8
    assert env.state['pointer_calls']==1
    assert d['pointer_fields']['stepover']['boolean_short']==0
    assert d['pointer_fields']['stepover']['hresult']['value']==0
    assert d['batch']['retained_reference_count']==0 and not d['batch']['dispatch_available']
    for owner in ('ICWFinishMillOp','ICWFinishMillOp3'):
        assert env.state['qi'].count(('operation',owner))==1


@pytest.mark.parametrize('change',['pid','document','dirty','source','proof','events','owned',
                                   'operation','feature','suppressed','optype','found'])
def test_exit_fault_never_releases_values(env,change):
    def mutate():
        if change=='pid':env.state['pid']=999
        elif change=='document':env.state['document']['title']='other'
        elif change=='dirty':env.state['document']['needs_save']=True
        elif change=='source':Path(env.source['path']).write_bytes(b'changed')
        elif change=='proof':Path(env.proof['path']).write_bytes(b'changed')
        elif change=='events':env.state['events']=False
        elif change=='owned':env.state['owned']=False
        elif change=='operation':env.state['op_id']=145
        elif change=='feature':env.state['feature_id']=80
        elif change=='suppressed':env.state['suppressed']=True
        elif change=='optype':env.state['op_type']=0
        elif change=='found':env.state['found']=False
    env.state['on_last']=mutate
    with pytest.raises(ValueError):m.read_fields(env.backend,'inspect')
    d=env.backend.report['floor_field_batches'][0]
    assert not d['complete'] and d['batch']['invalid']


@pytest.mark.parametrize('fault,value',[('omit_bool',True),('omit_double',True),
    ('raw_bool',1),('raw_bool',-2),('raw_double',float('inf')),('hresult',1),
    ('hresult',-2147467259),('hresult',True),('pointer_exception',True)])
def test_pointer_fault_retains_diagnostic_and_never_retries(env,fault,value):
    env.state[fault]=value
    with pytest.raises(ValueError):m.read_fields(env.backend,'inspect')
    d=env.backend.report['floor_field_batches'][0]
    assert not d['complete'] and env.state['pointer_calls']==1 and env.state['persists']>0
    p=d['pointer_fields']['stepover']
    assert p['attempted'] and not p['outputs_validated'] and not p['automatic_retry']
    if fault=='raw_bool':assert p['boolean_short']==value
    if fault=='hresult':assert p['hresult']['value']==value
    if fault=='omit_double':assert p['double']['nonfinite']=='nan'


def test_percent_true_uses_canonical_minus_one_and_keeps_order(env):
    env.values['stepover']=[True,12.5]
    r=m.read_fields(env.backend,'inspect')
    assert r['stepover']==[True,12.5]
    assert env.backend.report['floor_field_batches'][0]['pointer_fields']['stepover']['boolean_short']==-1


@pytest.mark.parametrize('key,bad',[('bottom_finish',1),('bottom_method',True),('perimeter_pass_type',2**31),
     ('side_allowance',[False,.5]),('entry_angle',float('nan')),('entry_length',[.5,1])])
def test_scalar_shapes_preserve_raw_before_failure(env,key,bad):
    env.values[key]=bad
    with pytest.raises(ValueError,match='scalar shape'):m.read_fields(env.backend,'inspect')
    d=env.backend.report['floor_field_batches'][0]
    assert key in d['raw_fields'] and not d['complete']


@pytest.mark.parametrize('fault',['flags','order','hresult','dispid','property','missing_wrapper'])
def test_metadata_fault_prevents_all_native_calls(env,fault):
    cls=env.classes['ICWFinishMillOp']
    spec=next(x for x in cls._methods_ if x.name=='GetStepOver')
    if fault=='flags':spec.paramflags=((2,'a'),(2,'b'))
    elif fault=='order':spec.argtypes=tuple(reversed(spec.argtypes))
    elif fault=='hresult':spec.restype=c_long
    elif fault=='dispid':spec.idlflags[0]=26
    elif fault=='property':spec.idlflags.append('propget')
    elif fault=='missing_wrapper':delattr(cls,m.RAW_STEPOVER)
    with pytest.raises(ValueError):m.read_fields(env.backend,'inspect')
    assert env.state['calls']==[] and env.state['pointer_calls']==0


def make_batch(env):
    return m.FloorReadBatch(env.objects['sw'],'fake.tlb',**env.kwargs,generated_pin={},
        retained_objects=(env.objects['operation'],),verify_retained_binding=lambda:None,
        max_native_calls=128,progress=lambda:None,progress_state={})


@pytest.mark.parametrize('name',['SetStepOver','GetStepOver','BottomFinOpt_set','Save','GTP','ActiveDoc'])
def test_no_pointer_or_mutation_via_generic_read(env,name):
    b=make_batch(env)
    with pytest.raises(ValueError):
        with b:b.read(env.objects['operation'],name)
    assert b.summary()['invalid']


def test_dispatch_cannot_invoke_callback(env):
    b=make_batch(env);called=[]
    with pytest.raises(ValueError):
        with b:b.dispatch_once(lambda:called.append(True),persist_pending=lambda:None)
    assert not called


def test_foreign_typed_pointer_owner_rejected_before_raw_call(env):
    b=make_batch(env)
    foreign=env.classes['ICWFinishMillOp']('foreign',env.state)
    with pytest.raises(ValueError):
        with b:b.step_over(foreign,{})
    assert env.state['pointer_calls']==0


@pytest.mark.parametrize('method',['sw_typed','plane','feature_dispatch'])
def test_unrelated_inherited_helpers_rejected(env,method):
    b=make_batch(env)
    with pytest.raises(ValueError):
        with b:getattr(b,method)(env.objects['operation'],'anything')


@pytest.mark.parametrize('bad',[False,True])
def test_wrapper_saves_actual_observation_or_partial_pointer_failure(env,monkeypatch,bad):
    env.state['omit_bool']=bad
    env.backend.loaded.update(state={'document':deepcopy(env.state['document'])},
        offline_export_proof_pins=[],bootstrap_export_pins=[])
    env.backend.start=lambda:None;env.backend.close=lambda:None;env.backend.boundary=lambda:None
    env.backend.current_tool=lambda:{'assigned':273}
    def ctor(loaded,params,sw,clsid,typelib,report,persist):
        env.backend.report=report;env.backend.persist=persist;return env.backend
    monkeypatch.setattr(m.finish,'NativeBackend',ctor)
    monkeypatch.setattr(m.finish,'wanted_assignment',lambda loaded:{'assigned':273})
    result=m.run_inspection(None,'','',params=env.backend.args,loaded=env.backend.loaded,
                            observed_pin=env.proof,plan_pin=env.proof)
    saved=json.loads(Path(env.backend.args['receipt_path']).read_text(encoding='utf-8-sig'))
    assert saved==result and saved['readback_verified'] is not bad
    assert saved['floor_field_batches'][0]['pointer_fields']['stepover']['attempted']
    assert not any(saved[k] for k in ('setter_attempted','GTP_attempted','model_saved','automatic_replay','mutation_authority','floor_recipe_qualified'))
    if bad:assert saved['status']=='error' and 'fields' not in saved
    else:assert len(saved['fields'])==18 and saved['fields']['bottom_finish'] is False


def test_raised_hresult_preserves_owned_outputs_without_invented_return(env):
    class NativeFailure(OSError):
        winerror = -2147467259
    def failed(self, percent, amount):
        self.state['pointer_calls'] += 1
        cast(percent, POINTER(c_short)).contents.value = -1
        cast(amount, POINTER(c_double)).contents.value = .8
        raise NativeFailure('native HRESULT failed')
    setattr(env.classes['ICWFinishMillOp'], m.RAW_STEPOVER, failed)
    with pytest.raises(NativeFailure):m.read_fields(env.backend,'inspect')
    p=env.backend.report['floor_field_batches'][0]['pointer_fields']['stepover']
    assert not p['returned'] and 'hresult' not in p
    assert p['boolean_short']==-1 and p['double']['value']==.8
    assert p['exception_winerror']==-2147467259 and p['exception_type']=='NativeFailure'
    assert env.state['pointer_calls']==1


def test_unwritten_outputs_on_exception_remain_standard_json(env):
    env.state['pointer_exception']=True
    with pytest.raises(ValueError):m.read_fields(env.backend,'inspect')
    d=env.backend.report['floor_field_batches'][0]
    p=d['pointer_fields']['stepover']
    assert p['boolean_short']==32767 and p['double']['nonfinite']=='nan'
    json.dumps(d, allow_nan=False)
