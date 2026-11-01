"""Selected guide GTP protocol and actual native adapter boundary tests."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json,os,sys,types
import pytest
ROOT=Path(__file__).resolve().parents[1];RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME));import scripts;scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_guide_group_generation as m
F=json.loads((RUNTIME/'tests/guide_configuration_shapes.json').read_text())


def fixture():
    state=deepcopy(F['initial']);old={267,247,248,271,143,320}
    for index,row in enumerate(state['binding']['operations']):
        row['native_id']=m.reopen.ORDER[index]
        if index<9:row['toolpath_generated']=row['native_id']in old;row['toolpath_record_counts']=[index+11]if row['native_id']in old else[]
        else:row['assigned_tool']=deepcopy(F['wanted'])
    for row in state['parameters']:row['tool']['generic']=deepcopy(F['wanted'])
    targets=[dict(row,assigned_tool=deepcopy(F['wanted']))for row in F['recipe']['rows']]
    return state,targets


class Fake:
    def __init__(self,state,report,failure=None):self.state=deepcopy(state);self.report=report;self.trace=[];self.failure=failure
    def start(self):self.trace.append('start')
    def capture_parameters(self,label):
        self.trace.append('capture:'+label)
        if self.failure==label:raise ValueError('read failed')
        result=deepcopy(self.state)
        if self.failure=='saved_delta'and label=='saved':result['parameters'][0]['nc']['extra']=1
        self.report.setdefault('captures',[]).append(dict(label=label,**result));return result
    def capture_binding(self,label):self.trace.append('binding:'+label);return deepcopy(self.state['binding'])
    def generate(self,target,pending):
        oid=target['operation_native_id'];pending();self.trace.append(('GTP',oid))
        if self.failure=='exception':raise RuntimeError('native uncertain')
        if self.failure=='return':return -1
        row=next(v for v in self.state['binding']['operations']if v['native_id']==oid)
        row['toolpath_generated']=True;row['toolpath_record_counts']=[10+oid]
        if self.failure=='old_path':self.state['binding']['operations'][2]['toolpath_record_counts']=[999]
        if self.failure=='parameters':self.state['parameters'][0]['nc']['extra']=1
        return 0
    def outcome(self,target):
        row=next(v for v in self.state['binding']['operations']if v['native_id']==target['operation_native_id'])
        return dict(operation_native_id=row['native_id'],feature_native_id=target['feature_native_id'],
            generated=row['toolpath_generated'],generated_for_feature=row['toolpath_generated'],record_counts=row['toolpath_record_counts'],
            background_over_before=True,background_over_after=self.failure!='background')
    def refresh_dirty(self):self.trace.append('refresh')
    def export_cl(self,label,binding):
        self.trace.append('cl:'+label)
        if self.failure=='export_'+label:raise ValueError('export failed')
        return dict(label=label,old_signatures=list(range(6)),new_signatures=[]if label=='before'else list(range(4)))
    def boundary(self):self.trace.append('boundary')
    def save(self):self.trace.append('save');return -1 if self.failure=='save_return'else 0
    def saved_hash(self,r):
        self.report['source_transition']={'document':{'path':'synthetic.SLDPRT','type':1,'title':'synthetic.SLDPRT','needs_save':False}}
        return'b'*64
    def finish(self):self.trace.append('finish')
    def close(self):self.trace.append('close')


def setup(tmp_path,monkeypatch,failure=None):
    state,targets=fixture();loaded=dict(guide_parameters={'expected_parameters':deepcopy(state),'targets':targets,'configuration':{'synthetic':True}},
        reopen_pin={'path':'reopen.json','sha256':'e'*64})
    report=dict(source_path='synthetic.SLDPRT',source_sha256='a'*64,reopen_receipt_pin=loaded['reopen_pin'],request={'process_id':52},ownership={'process_id':52})
    journal=m.Journal(report,tmp_path/'receipt.json',tmp_path/'marker.json')
    def protected(a,b):assert a['old_signatures']==b['old_signatures'];return True
    def all_equal(a,b):assert a['new_signatures']==b['new_signatures'];return True
    monkeypatch.setattr(m.cl,'verify_protected',protected);monkeypatch.setattr(m.cl,'verify_all',all_equal)
    return Fake(state,report,failure),journal,loaded


def test_exact_four_gtp_then_verified_cl_then_one_save(tmp_path,monkeypatch):
    b,j,l=setup(tmp_path,monkeypatch);r=m.run_backend(b,j,l)
    assert r['status']=='saved_generated_review_required',r.get('issue')
    assert [x[1]for x in b.trace if isinstance(x,tuple)]==[322,324,326,328]
    assert b.trace.count('save')==1 and b.trace.index('cl:generated')<b.trace.index('save')<b.trace.index('cl:saved')
    assert r['generated_operation_ids']==[322,324,326,328]and r['GTP_attempted']
    assert r['protected_cl_verified']and r['readback_verified']and r['model_saved']and r['continuation_ready']
    assert not r['SetTool_attempted']and not r['setter_attempted']and not r['operation_creation_attempted']
    assert not r['production_qualified']and not r['physical_cutting_conditions_qualified']and not r['geometry_acceptance_complete']
    assert r['saved_checkpoint_context']['source_sha256']=='b'*64


@pytest.mark.parametrize('failure',['before','export_before','exception','return','background','old_path','parameters','export_generated','save_return','saved_delta','export_saved'])
def test_prefix_failure_never_replays_or_claims_unsaved_success(tmp_path,monkeypatch,failure):
    b,j,l=setup(tmp_path,monkeypatch,failure);r=m.run_backend(b,j,l)
    assert not r['readback_verified']and not r['continuation_ready']
    assert r['model_saved']is(failure in ('saved_delta','export_saved'))
    gtps=[x for x in b.trace if isinstance(x,tuple)]
    assert len(gtps)<=4
    if failure in ('exception','return','background','old_path'):assert len(gtps)==1
    if failure in ('before','export_before'):assert gtps==[]and not r['GTP_attempted']
    else:assert r['GTP_attempted']
    if failure not in ('save_return','saved_delta','export_saved'):assert 'save'not in b.trace
    before=(j.receipt.read_bytes(),j.marker.read_bytes()if j.marker.exists()else None)
    with pytest.raises(ValueError):m.run_backend(b,j,l)
    assert before==(j.receipt.read_bytes(),j.marker.read_bytes()if j.marker.exists()else None)


def test_empty_or_changed_old_paths_block(tmp_path):
    before,targets=fixture();after=deepcopy(before)
    after['binding']['operations'][-1]['toolpath_generated']=True;after['binding']['operations'][-1]['toolpath_record_counts']=[0]
    with pytest.raises(ValueError):m.verify_snapshot(before,after,{328:[0]})
    after=deepcopy(before);after['binding']['operations'][2]['assigned_tool']['native_id']=9999
    with pytest.raises(ValueError):m.verify_snapshot(before,after,{})


def constructed(tmp_path):
    part=tmp_path/'synthetic.SLDPRT';part.write_bytes(b'part');dep=tmp_path/'generated.py';dep.write_bytes(b'pass')
    doc=dict(path=str(part),title=part.name,type=1,needs_save=False);state,targets=fixture()
    loaded=dict(pins=[m.common._pin(dep)],checkpoint_pins=[m.common._pin(dep)],configuration_pins=[],generated_pin=m.common._pin(dep),
        guide_parameters={'document':doc,'configuration':{'synthetic':True},'targets':targets,'expected_parameters':state})
    args=dict(process_id=52,expected_document_path=str(part),expected_source_sha256=m._file_hash(part),expected_configuration='synthetic')
    class Trap:
        def __getattr__(self,name):raise AssertionError('Native access: '+name)
    return m.NativeBackend(loaded,args,Trap(),'synthetic-clsid',str(tmp_path/'vendor.tlb'),{},lambda:None)


def test_real_constructor_no_shadow_and_actual_start(tmp_path,monkeypatch):
    b=constructed(tmp_path);assert isinstance(b.capture,types.ModuleType)
    assert not [k for k in vars(b)if callable(getattr(type(b),k,None))]
    assert b.capture_parameters.__func__ is m.configuration.NativeBackend.capture_parameters
    trace=[];b.ctx.files=lambda:trace.append('files');b.ctx.identity=lambda:trace.append('identity')
    class Entered(Exception):pass
    def bootstrap(*a):trace.append('bootstrap');raise Entered()
    monkeypatch.setattr(b.capture.cone,'_bootstrap',bootstrap)
    with pytest.raises(Entered):b.start()
    assert trace==['files','identity','bootstrap']


def test_real_capture_binding_calls_actual_batch_constructor(tmp_path,monkeypatch):
    b=constructed(tmp_path);state,_=fixture();b.doc=object();b.boundary=lambda:None;b.ctx.identity=lambda:b.loaded['guide_parameters']['document']
    b.ctx.files=lambda:None;b.ctx.owned=lambda:None;b.events=lambda:None
    monkeypatch.setattr(m.fast,'make_configuration_check',lambda *a:lambda:None)
    Base=m.reader.ParameterReadBatch
    class Transport(Base):
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def require_complete(self):pass
    monkeypatch.setattr(m.reader,'ParameterReadBatch',Transport)
    monkeypatch.setattr(m.configuration.definitions,'read_current_binding',lambda *a,**k:(deepcopy(state['binding']),{}))
    assert b.capture_binding('test')==state['binding']
    assert len(b.report['configuration_checks'])==1 and b.report['bindings'][0]['label']=='test'


def test_real_generation_target_native_scope_and_once_pending(tmp_path,monkeypatch):
    from contextlib import contextmanager
    b=constructed(tmp_path);doc=object();op=object();feature=object();app=object();b.doc=doc;b.ctx.app=app;trace=[];target=b.loaded['guide_parameters']['targets'][0]
    class Mill:
        def GenerateToolpath(self):trace.append('GenerateToolpath');return 0
    mill=Mill()
    class Guard:
        def typed(self,value,name):return mill if name=='ICWMillOperation'else value
        def read(self,value,name,*args):
            trace.append(name)
            if value is doc and name=='GetCWObjectFromID':return(op if args[0]==3 else feature,True)
            if value is op and name=='Suppressed':return False
            if value is mill and name=='OpernType':return 0
            if value is op and name=='IGetAllFeatures':return[feature]
            if value is app and name=='IsBackgroundProcessForGTPOver':return True
            raise AssertionError((name,args))
        def dispatch_once(self,call,*,persist_pending):persist_pending();return call()
    @contextmanager
    def guarded():yield Guard()
    b.ctx.guard=guarded
    monkeypatch.setattr(m.configuration,'_object_id',lambda d,v,read:322 if v is op else 82)
    monkeypatch.setattr(m.configuration,'_items',lambda value,*a:value)
    monkeypatch.setattr(m,'read_generic_tool',lambda *a:(deepcopy(target['assigned_tool']),None))
    b.outcome=lambda t:dict(operation_native_id=322,feature_native_id=82,generated=False,generated_for_feature=False,record_counts=[],background_over_before=True,background_over_after=True)
    assert b.generate(target,lambda:trace.append('pending'))==0
    assert trace.count('GenerateToolpath')==1 and trace.index('pending')<trace.index('GenerateToolpath')
    assert 'SetTool'not in trace and 'IGetMachine'not in trace


def test_exact_supported_generation_abi_offline():
    generated=RUNTIME/'.venv/Lib/site-packages/comtypes/gen/_FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0.py'
    tlb=Path('D:/Program Files/SOLIDWORKS Corp/SOLIDWORKS CAM/camworks.tlb')
    if not generated.is_file()or not tlb.is_file():pytest.skip('Vendor metadata unavailable')
    result=m.audit(str(tlb),m.common._pin(generated))
    assert [v['member']for v in result['members']]==['GenerateToolpath','GetIsToolpathGeneratedForFeature','_get_IsBackgroundProcessForGTPOver','SaveCLFile']


@pytest.mark.parametrize('bad',[None,'not_reopened','source','owner','module','pending','snapshot','settings_side_effect'])
def test_current_reopened_checkpoint_outer_contract(tmp_path,monkeypatch,bad):
    state,targets=fixture();document=str(tmp_path/'synthetic.SLDPRT')
    p=dict(process_id=52,expected_document_path=document,expected_source_sha256='a'*64)
    selected=dict(expected_parameters=deepcopy(state),baseline=deepcopy(state['binding']),targets=targets)
    owner=dict(process_id=52,create_time=123.,executable='synthetic.exe',alive=True)
    action=dict(status='verified',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False)
    r=dict(scope=m.reopen.SCOPE,status='reopen_verified',phase='finished',module_pin=m.common._pin(m.reopen.__file__),
        close_verified=True,reopen_verified=True,persistence_after_reopen_verified=True,readback_verified=True,
        native_dispatch_pending=False,save_attempted=False,GTP_attempted=False,automatic_retry=False,
        source_path=document,source_sha256='a'*64,ownership=owner,request=dict(process_id=52,configuration_receipt_path='prior.json',configuration_receipt_sha256='b'*64),
        actions={'CloseActiveDocument':deepcopy(action),'OpenDoc6':deepcopy(action)},reopened=deepcopy(state),before_close_binding=deepcopy(state['binding']))
    monkeypatch.setattr(m,'clean_events',lambda value:None)
    monkeypatch.setattr(m,'read_pin',lambda *args:({'ownership':deepcopy(owner)},{'path':'prior.json','sha256':'b'*64}))
    monkeypatch.setattr(m.reopen,'completed_checkpoint',lambda *args:deepcopy(selected))
    if bad=='not_reopened':r['persistence_after_reopen_verified']=False
    if bad=='source':r['source_sha256']='c'*64
    if bad=='owner':r['request']['process_id']=53
    if bad=='module':r['module_pin']['sha256']='d'*64
    if bad=='pending':r['actions']['OpenDoc6']['native_dispatch_pending']=True
    if bad=='snapshot':r['reopened']['parameters'][0]['nc']['extra']=1
    if bad=='settings_side_effect':r['save_attempted']=True
    if bad:
        with pytest.raises(ValueError):m.completed_reopen(r,p)
    else:assert m.completed_reopen(r,p)[2]==selected
