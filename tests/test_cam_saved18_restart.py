from copy import deepcopy
from pathlib import Path
import os,sys,types,json
import pytest
from cam_public_test_support import add_runtime,required_module
R=add_runtime()
c=required_module('sw_cam_saved18_checkpoint')
m=required_module('sw_cam_saved18_preclose')


@pytest.fixture
def facts():
    tool=dict(native_id=9)
    ids=list(range(1,22));features={str(i):dict(native_id=i)for i in range(31,37)}
    ops=[dict(native_id=i,toolpath_generated=i>3,toolpath_record_counts=[i+1]if i>3 else[],assigned_tool=deepcopy(tool),linked_feature_ids=[31+(j%6)],mill_operation_type=j%2,setup_native_id=40)for j,i in enumerate(ids)]
    params=[dict(operation_native_id=i,feature_native_id=ops[i-1]['linked_feature_ids'][0],read_complete=True,tool=dict(generic=deepcopy(tool)))for i in list(range(4,12))+list(range(18,22))]
    snapshot=dict(binding=dict(features=features,operations=ops,operation_setups=[]),parameters=params)
    doc=dict(path='C:/model.sldprt',title='model.sldprt',type=1,needs_save=False)
    ownership=dict(process_id=50,create_time=1000.,executable='C:/SLDWORKS.exe',alive=True)
    q=dict(status='qualified_saved_input',original_receipt_status='uncertain',original_receipt_modified=False,source_sha256='b'*64,receipt_pin=dict(path='C:/raw.json',sha256='a'*64),generation_receipt_pin=dict(path='C:/raw.json',sha256='a'*64),configuration_receipt_pin=dict(path='C:/config.json',sha256='c'*64),saved_cl=dict(output=dict(path='C:/saved.cl',sha256='d'*64),expected_generated_operations=[dict(operation_native_id=o['native_id'],toolpath_record_counts=o['toolpath_record_counts'])for o in ops if o['toolpath_generated']]),direct_dependency_pins=[])
    conf=dict(names_consistent=True,associated_sw_configuration_matches=True,cam_configuration_name='Metric',configuration_object_name='Metric',sw_configuration_name='Default',associated_sw_configuration_name='Default')
    r=dict(saved_source_sha256='b'*64,source_sha256='c'*64,cleanup_session_active=False,messages=dict(active=False,disconnected=True),saved=deepcopy(snapshot),before=deepcopy(snapshot),configuration_receipt_pin=deepcopy(q['configuration_receipt_pin']),source_transition=dict(document=doc),live_pins=[dict(path='C:/_FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0.py',sha256='e'*64)],ownership=ownership,learned_targets=[dict(operation_native_id=i,feature_native_id=ops[i-1]['linked_feature_ids'][0],operation_type=ops[i-1]['mill_operation_type'],assigned_tool=deepcopy(tool))for i in range(18,22)],tool_dimensions={})
    config=dict(saved_source_sha256='c'*64,saved_checkpoint=dict(snapshot=deepcopy(snapshot),configuration=conf,tool_catalogue=[]))
    serial=dict(checkpoint=dict(state=dict(features=[dict(geometry=dict(native_id=i),setup_native_id=40)for i in range(31,37)]),registration=dict(addin_path='C:/CAM/cwaddinu.dll')),bootstrap_export_pins=[])
    return q,r,config,serial,dict(path='C:/serial.json',sha256='f'*64),dict(path='C:/authority.json',sha256='1'*64)

@pytest.fixture
def loaded(facts):return c.project(*facts)

def transition(loaded):
    handle=dict(process_id=50,executable='C:/SLDWORKS.exe',creation_filetime=m.process._EPOCH+10_000_000_000,alive=True)
    closed=dict(scope=m.SCOPE,status='saved_part_closed',phase='finished',readback_verified=True,close_verified=True,authority_pin=deepcopy(loaded['qualified_authority_pin']),ownership=deepcopy(loaded['ownership']),source_sha256=loaded['source_sha256'],source_path='C:/model.sldprt',cleanup_session_active=False,messages=dict(active=False,disconnected=True),open_documents_after_close=[],before_close_binding=deepcopy(loaded['current_snapshot']['binding']),actions={'CloseActiveDocument':dict(attempted=True,returned=True,status='verified',readback_verified=True,native_dispatch_pending=False,native_return=dict(python_type='int',value_recorded=True,value=0))},owner_handle_before=handle,owner_handle_before_close=handle)
    for k in ('save_attempted','GTP_attempted','exit_attempted','launch_attempted','automatic_retry'):closed[k]=False
    exited=dict(scope='OWNED_VERIFIED_EMPTY_SESSION_EXIT_V1',status='exited',phase='finished',exit_call_count=1,open_documents_before=[],open_documents_final=[],owner_before=handle,request=dict(process_id=50,expected_source_sha256='b'*64,expected_document_path='C:/model.sldprt',expected_creation_filetime=handle['creation_filetime'],expected_executable_path='C:/SLDWORKS.exe'))
    for k in ('readback_verified','process_exit_verified','empty_session_verified','saved_files_preserved','exit_attempted','exit_returned'):exited[k]=True
    for k in ('terminate_rights_requested','termination_attempted','save_attempted','close_document_attempted','launch_attempted','automatic_retry','native_dispatch_pending'):exited[k]=False
    startup=dict(status='ok',phase='connected',launch_mode='executable',launch_attempted=True,new_process_verified=True,process_id=60,known_process_ids_before=[99],process_identity=dict(process_id=60,create_time=1100.,executable='C:/SLDWORKS.exe',alive=True),executable='C:/SLDWORKS.exe',launch_intent_time=1099.)
    return closed,exited,startup

def test_projection_keeps_native_baseline_and_current_separate(loaded):
    assert len(loaded['guide_parameters']['expected_parameters']['parameters'])==8
    assert len(loaded['current_snapshot']['parameters'])==12
    assert len(loaded['guide_parameters']['expected_parameters']['binding']['operations'])==17
    assert len(loaded['current_snapshot']['binding']['operations'])==21

@pytest.mark.parametrize('index,path,value',[(0,('original_receipt_modified',),True),(0,('source_sha256',),'x'),(1,('cleanup_session_active',),True),(1,('messages','disconnected'),False),(1,('saved','binding','operations',4,'toolpath_generated'),False),(1,('before','parameters',0,'read_complete'),False),(3,('checkpoint','state','features',0,'setup_native_id'),False)])
def test_projection_rejects_bad_provenance(facts,index,path,value):
    a=deepcopy(facts);obj=a[index]
    for k in path[:-1]:obj=obj[k]
    obj[path[-1]]=value
    with pytest.raises(ValueError):c.project(*a)

def test_transition_retains_history_and_changes_only_verified_owner(loaded):
    before=deepcopy(loaded);closed,exited,startup=transition(loaded)
    out=c.verify_transition(loaded,closed,exited,startup)
    assert loaded==before and out['ownership']['process_id']==60 and out['historical_ownership']==before['ownership']
    assert out['current_snapshot']==before['current_snapshot']

@pytest.mark.parametrize('which,path,value',[(0,('status',),'uncertain'),(0,('open_documents_after_close',),[{}]),(0,('messages','active'),True),(0,('cleanup_session_active',),True),(0,('actions','CloseActiveDocument','native_return','value'),True),(0,('save_attempted',),True),(0,('before_close_binding','operations',0,'native_id'),999),(1,('process_exit_verified',),False),(1,('termination_attempted',),True),(1,('exit_call_count',),2),(1,('owner_before','creation_filetime'),123),(1,('request','expected_source_sha256'),'c'*64),(1,('open_documents_final',),[{}]),(2,('process_id',),50),(2,('known_process_ids_before',),[50,60]),(2,('process_identity','create_time'),999.),(2,('executable',),'C:/OTHER.exe'),(2,('new_process_verified',),False)])
def test_transition_rejects_partial_or_foreign_history(loaded,which,path,value):
    histories=deepcopy(transition(loaded));obj=histories[which]
    for k in path[:-1]:obj=obj[k]
    obj[path[-1]]=value
    with pytest.raises(ValueError):c.verify_transition(loaded,*histories)

class FakeBackend:
    def __init__(self,loaded,report,*,drift=False,dirty=False,ret=0):self.loaded,self.report,self.drift,self.dirty,self.ret=loaded,report,drift,dirty,ret;self.calls=[]
    def start(self):self.calls.append('start')
    def capture_binding(self):
        self.calls.append('binding');v=deepcopy(self.loaded['current_snapshot']['binding'])
        if self.drift:v['operations'][0]['native_id']=999
        return v
    def check_clean(self):
        if self.dirty:raise ValueError('dirty')
    def close_target(self,pending):pending();self.calls.append('close');return self.ret
    def verify_closed(self):return []
    def disconnect_closed(self):self.calls.append('disconnect');self.report['messages']=dict(active=False,disconnected=True)
    def close(self):self.report['cleanup_session_active']=False

def journal(tmp_path,loaded):
    return m.Journal(dict(scope=m.SCOPE,source_path='C:/model.sldprt',source_sha256='b'*64),tmp_path/'receipt.json',tmp_path/'marker.json')

def test_one_close_no_save_gtp_and_replay_changes_nothing(tmp_path,loaded):
    j=journal(tmp_path,loaded);b=FakeBackend(loaded,j.report);r=m.run_backend(b,j,loaded)
    assert r['status']=='saved_part_closed'and b.calls==['start','binding','close','disconnect']
    before=(j.receipt.read_bytes(),j.marker.read_bytes())
    with pytest.raises(ValueError):m.run_backend(b,j,loaded)
    assert before==(j.receipt.read_bytes(),j.marker.read_bytes())
    assert set(r['actions'])=={'CloseActiveDocument'}

@pytest.mark.parametrize('kwargs,closed',[(dict(drift=True),False),(dict(dirty=True),False),(dict(ret=True),True),(dict(ret=1),True)])
def test_failures_do_not_retry(tmp_path,loaded,kwargs,closed):
    j=journal(tmp_path,loaded);b=FakeBackend(loaded,j.report,**kwargs);r=m.run_backend(b,j,loaded)
    assert r['readback_verified']is False and b.calls.count('close')==int(closed)
    assert r['status']==('uncertain'if closed else'error')

def test_actual_constructor_and_inherited_binding_call_are_callable(monkeypatch,loaded):
    args=dict(process_id=50,expected_document_path='C:/model.sldprt',expected_source_sha256='b'*64)
    obj=m.ReadOnlyParameters(loaded,args,object(),'clsid','tlb',{},lambda:None)
    assert isinstance(obj.capture,types.ModuleType)
    for name in ('start','boundary','capture_binding','capture_snapshot','finish','close'):assert callable(getattr(obj,name))
    called=[]
    monkeypatch.setattr(m.native.NativeBackend,'capture_snapshot',lambda self,label,**kw:called.append((label,kw))or{'binding':{'ok':True}})
    assert obj.capture_binding('x')=={'ok':True}and called==[('x',{'full':False})]
    with pytest.raises(ValueError):obj.capture_snapshot('x',full=True)
    for name in ('insert','assign','set_field','set_nc','generate','save'):
        with pytest.raises(ValueError):getattr(obj,name)()

def test_actual_close_requires_one_clean_document(monkeypatch,loaded):
    monkeypatch.setattr(m.reuse.NativeBackend,'check_clean',lambda self:None)
    class SW:
        def GetDocuments(self):return [object(),object()]
    b=m.NativeBackend(loaded,dict(process_id=50),SW(),'clsid','tlb',{},lambda:None)
    b._owner_handle=lambda:dict(process_id=50)
    with pytest.raises(ValueError,match='Exactly one'):b.check_clean()
