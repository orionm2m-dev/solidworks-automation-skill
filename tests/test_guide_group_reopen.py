"""Reopen protocol and real adapter contracts; no CAD or running COM objects."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace, ModuleType
from contextlib import contextmanager
import importlib.util, json, os, sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(ROOT)))
sys.path.insert(0,str(RUNTIME))
spec=importlib.util.spec_from_file_location('guide_reopen_test',ROOT/'scripts/sw_cam_guide_group_reopen.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
F=json.loads((Path(__file__).parent/'guide_configuration_shapes.json').read_text(encoding='utf-8'))
DOC={'path':'synthetic.SLDPRT','title':'synthetic.SLDPRT','type':1,'needs_save':False}
CONFIG={'cam_configuration_name':'Mill','configuration_object_name':'Mill','associated_sw_configuration_name':'Default',
    'sw_configuration_name':'Default','names_consistent':True,'associated_sw_configuration_matches':True}
MESSAGES={'active':False,'subscribed':True,'disconnected':True}


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


def saved_report():
    snapshot=deepcopy(F['initial']);rows=F['recipe']['rows'];wanted=F['wanted']
    for row,oid in zip(snapshot['binding']['operations'],m.ORDER):row['native_id']=oid
    for row,target in zip(snapshot['parameters'],rows):
        row['tool']['generic']=deepcopy(wanted)
        for field in m.configuration.ROUGH_FIELDS if target['operation_type']==0 else m.configuration.FINISH_FIELDS:
            update(row,field,target['fields'][field[0]])
    for row in snapshot['binding']['operations']:
        if row['native_id'] in [v[0] for v in m.TARGETS]:row['assigned_tool']=deepcopy(wanted)
    context={'process_id':52,'ownership':{'process_id':52},'document':deepcopy(DOC),'source_sha256':'b'*64,
        'configuration':deepcopy(CONFIG),'snapshot_key':'saved','snapshot_sha256':m.group._digest(snapshot),
        'prior_source_sha256':'a'*64,'prior_parameter_receipt_pin':{'path':'parameters.json','sha256':'c'*64},
        'persistence_after_reopen_verified':False}
    r=dict(scope=m.configuration.SCOPE,status='saved_configuration_no_toolpath',phase='finished',readback_verified=True,
        configuration_readback_verified=True,model_saved=True,continuation_ready=True,GTP_attempted=False,native_dispatch_pending=False,
        persistence_after_reopen_verified=False,messages=deepcopy(MESSAGES),saved_checkpoint_context=context,request={'process_id':52},
        ownership={'process_id':52},source_path=DOC['path'],source_sha256='a'*64,saved_source_sha256='b'*64,
        source_transition={'document':deepcopy(DOC)},saved=deepcopy(snapshot),configured=deepcopy(snapshot),after_tools=deepcopy(snapshot),
        recipe=deepcopy(F['recipe']),recipe_sha256='d'*64,configured_operation_ids=[v[0] for v in m.TARGETS],
        configuration_pins=[context['prior_parameter_receipt_pin'],{'path':'recipe.json','sha256':'d'*64}],captures=[],actions={})
    for oid,_,_ in m.TARGETS:
        label='after_tool_'+str(oid);capture=dict(label=label,**deepcopy(snapshot));r['captures'].append(capture)
        ref={'capture_index':len(r['captures'])-1,'capture_label':label,'snapshot_sha256':m.group._digest(capture),'operation_native_id':oid}
        r['actions'][str(oid)+':SetTool']={'status':'verified','readback_verified':True,'observed':ref}
    r['actions']['SaveActiveDocument']={'status':'verified','readback_verified':True,'attempted':True,'returned':True,'native_dispatch_pending':False}
    return r


def params():return {'process_id':52,'expected_document_path':DOC['path'],'expected_source_sha256':'b'*64}


def test_complete_saved_authority_accepts_exact_thirteen():
    result=m.completed_checkpoint(saved_report(),params())
    assert [r['native_id'] for r in result['baseline']['operations']]==m.ORDER
    assert [r['operation_native_id'] for r in result['targets']]==[322,324,326,328]


@pytest.mark.parametrize('key,value',[
    ('continuation_ready',False),('model_saved',False),('GTP_attempted',True),('native_dispatch_pending',True),
    ('status','uncertain'),('readback_verified',False),('saved_source_sha256','f'*64)])
def test_incomplete_saved_authority_rejected(key,value):
    r=saved_report();r[key]=value
    with pytest.raises(ValueError):m.completed_checkpoint(r,params())


def test_wrong_pid_dirty_snapshot_and_rebound_capture_rejected():
    for mutate in (
        lambda r:r['saved_checkpoint_context'].update(process_id=53),
        lambda r:r['saved_checkpoint_context']['document'].update(needs_save=True),
        lambda r:r['saved_checkpoint_context'].update(snapshot_sha256='0'*64),
        lambda r:r['captures'][0]['binding']['operations'][0].update(name='changed')):
        r=saved_report();mutate(r)
        with pytest.raises(ValueError):m.completed_checkpoint(r,params())


class Fake:
    def __init__(self,expected,failure=None):self.expected=expected;self.failure=failure;self.trace=[];self.opens=0
    def start(self):self.trace.append('start')
    def capture_parameters(self,label):
        self.trace.append(label)
        value=deepcopy(self.expected)
        if self.failure==label:value['parameters'][0]['unexpected']=True
        return value
    def capture_binding(self):
        self.trace.append('before_close')
        value=deepcopy(self.expected['binding'])
        if self.failure=='before_close':value['changed']=True
        return value
    def check_clean(self):
        self.trace.append('clean')
        if self.failure=='dirty':raise ValueError('unsaved')
    def close_target(self,pending):pending();self.trace.append('native_close');return -1 if self.failure=='close_hresult' else 0
    def verify_closed(self):
        self.trace.append('closed_check')
        if self.failure=='still_open':raise ValueError('target still open')
    def disconnect_closed(self):self.trace.append('disconnect')
    def open_target(self,pending):
        pending();self.trace.append('native_open');self.opens+=1
        if self.failure=='open':raise ValueError('open failed')
        return True
    def finish(self):self.trace.append('finish')
    def close(self):self.trace.append('cleanup')


def setup(tmp_path,failure=None):
    selected=m.completed_checkpoint(saved_report(),params());loaded={'guide_parameters':selected}
    backend=Fake(selected['expected_parameters'],failure)
    report={'scope':m.SCOPE,'source_path':DOC['path'],'source_sha256':'b'*64}
    journal=m.ReopenJournal(report,tmp_path/'receipt.json',tmp_path/'marker.json')
    return backend,journal,loaded


def test_one_clean_close_reopen_and_fresh_second_read(tmp_path):
    b,j,l=setup(tmp_path);r=m.run_backend(b,j,l)
    assert r['status']=='reopen_verified' and r['persistence_after_reopen_verified']
    assert b.trace.count('native_close')==b.trace.count('native_open')==1
    assert b.trace.count('start')==2 and b.trace.index('disconnect')<b.trace.index('native_open')
    assert not r['save_attempted'] and not r['GTP_attempted']
    assert j.report['actions']['OpenDoc6']['native_return']=={'model_returned':True}


@pytest.mark.parametrize('failure',['before_close','dirty','close_hresult','still_open','open','reopened'])
def test_failure_prefix_never_replays_or_credits_persistence(tmp_path,failure):
    b,j,l=setup(tmp_path,failure);r=m.run_backend(b,j,l)
    assert not r['persistence_after_reopen_verified'] and not r['readback_verified']
    assert b.trace.count('native_close')<=1 and b.trace.count('native_open')<=1
    if failure in ('before_close','dirty'):assert not j.marker.exists() and 'native_close' not in b.trace
    if failure in ('close_hresult','still_open'):assert 'native_open' not in b.trace
    if failure in ('open','reopened'):assert r['close_verified']
    before=(j.receipt.read_bytes(),j.marker.read_bytes() if j.marker.exists() else None)
    with pytest.raises(ValueError):m.run_backend(b,j,l)
    assert before==(j.receipt.read_bytes(),j.marker.read_bytes() if j.marker.exists() else None)


def constructed(tmp_path):
    selected=m.completed_checkpoint(saved_report(),params())
    loaded={'guide_parameters':selected,'pins':[],'checkpoint_pins':[],'configuration_pins':[],
        'ownership':{'process_id':52},'generated_pin':{'path':'metadata.py','sha256':'e'*64}}
    args=dict(params(),expected_configuration='Default',receipt_path=str(tmp_path/'receipt.json'),progress_path=str(tmp_path/'progress.json'))
    backend=m.ParameterBackend(loaded,args,object(),'unused','metadata.tlb',{},lambda:None)
    return backend


def test_actual_constructor_has_no_method_shadow_and_uses_existing_capture(tmp_path):
    b=constructed(tmp_path)
    assert isinstance(b.capture,ModuleType)
    assert b.capture_parameters.__self__ is b
    assert b.capture_parameters.__func__ is m.configuration.NativeBackend.capture_parameters
    assert [key for key in vars(b) if callable(getattr(type(b),key,None))]==[]
    top=m.NativeBackend(b.loaded,b.args,b.sw,b.clsid,b.typelib_path,{},lambda:None)
    assert [key for key in vars(top) if callable(getattr(type(top),key,None))]==[]


def test_actual_start_hits_existing_bootstrap_boundary(tmp_path,monkeypatch):
    b=constructed(tmp_path);calls=[]
    b.ctx.files=lambda:calls.append('files');b.ctx.identity=lambda:calls.append('identity')
    class Entered(Exception):pass
    def bootstrap(*args):calls.append('bootstrap');raise Entered()
    monkeypatch.setattr(b.capture.cone,'_bootstrap',bootstrap)
    with pytest.raises(Entered):b.start()
    assert calls==['files','identity','bootstrap'] and not b.session_active


def test_actual_capture_body_reuses_reader_with_complete_constructor_contract(tmp_path,monkeypatch):
    b=constructed(tmp_path);doc=object();app=object();expected=b.loaded['guide_parameters']['expected_parameters'];calls=[]
    b.ctx.app=app;b.boundary=lambda:None;b.configuration=lambda value:deepcopy(CONFIG)
    class Guard:
        def typed(self,value,name):return value
        def read(self,value,name):assert value is app and name=='IGetActiveDoc';return doc
    @contextmanager
    def guard():yield Guard()
    b.ctx.guard=guard
    class Batch:
        read=typed=object()
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def require_complete(self):calls.append('complete')
        def summary(self):return {'complete':True}
    b.batch=lambda *args:Batch()
    class Progress:
        def __init__(self,**kwargs):assert kwargs['progress_path'].endswith('.reopened.json')
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):pass
        def complete(self):pass
    monkeypatch.setattr(m.reader.pocket.journal,'ReadProgressJournal',Progress)
    monkeypatch.setattr(m.configuration.definitions,'read_current_binding',lambda *a,**kw:(deepcopy(expected['binding']),{}))
    def parameters(doc,handles,targets,batch,out,persist):out['parameters']=deepcopy(expected['parameters']);calls.append('parameters')
    monkeypatch.setattr(m.reader,'read_parameters',parameters)
    assert b.capture_parameters('reopened')==expected
    assert calls==['parameters','complete']


def test_actual_parameter_batch_constructor_requires_progress_and_state(tmp_path,monkeypatch):
    b=constructed(tmp_path);source=tmp_path/'part.SLDPRT';source.write_bytes(b'synthetic')
    b.ctx.identity=lambda:dict(DOC,path=str(source))
    b.loaded['pins']=[{'path':str(Path(__file__).resolve()),'sha256':'e'*64}]
    batch=b.batch(object(),lambda:None,{'read_index':0},lambda:None)
    assert type(batch) is m.reader.ParameterReadBatch


def test_actual_close_cleanup_calls_event_session_once(tmp_path):
    b=constructed(tmp_path);called=[]
    b.session=SimpleNamespace(__exit__=lambda *args:called.append('exit'));b.session_active=True
    b.close();b.close()
    assert called==['exit'] and not b.session_active





def test_actual_top_cleanup_refreshes_failed_event_summary(tmp_path):
    b=constructed(tmp_path);top=m.NativeBackend(b.loaded,b.args,b.sw,b.clsid,b.typelib_path,b.report,lambda:None)
    top.parameter_reader=b;called=[]
    b.session=SimpleNamespace(__exit__=lambda *args:called.append('exit'),summary=lambda:dict(MESSAGES,event_count=1))
    b.session_active=True
    with pytest.raises(ValueError,match='CAM event'):top.close()
    assert called==['exit'] and b.report['messages']['event_count']==1 and not b.session_active


def test_actual_close_target_invokes_once_after_clean_check_and_pending(tmp_path,monkeypatch):
    b=constructed(tmp_path);top=m.NativeBackend(b.loaded,b.args,b.sw,b.clsid,b.typelib_path,b.report,lambda:None)
    top.parameter_reader=b;calls=[];app=object();b.ctx.app=app
    b.boundary=lambda:calls.append('boundary');b.ctx.identity=lambda:deepcopy(DOC);b.events=lambda:calls.append('events')
    class Guard:
        def typed(self,value,name):assert value is app and name=='ICWApp';return value
    @contextmanager
    def guard():yield Guard()
    b.ctx.guard=guard
    def member(obj,name):
        if name=='UserControl':assert obj is b.sw;return True
        assert obj is app and name=='CloseActiveDocument';calls.append('close');return 0
    monkeypatch.setattr(m,'_member',member)
    assert top.close_target(lambda:calls.append('pending'))==0
    assert calls.count('close')==1 and calls.index('pending')<calls.index('close')
    assert calls[-1]=='events' and b.doc is None

