from copy import deepcopy
from pathlib import Path
import json,types
import pytest
from cam_public_test_support import add_runtime,required_module,required_test_module
R=add_runtime()
shared=required_test_module('test_cam_saved18_restart')
facts,loaded,transition=shared.facts,shared.loaded,shared.transition
m=required_module('sw_cam_saved18_restarted_verify')


def events(closed=False):return dict(subscribed=True,active=not closed,event_count=0,overflow=0,callback_error_count=0,callback_errors=[],subscription_error=None,disconnect_errors=[],disconnected=closed)

def prepared(tmp_path,loaded):
    closed,exited,startup=transition(loaded);loaded=m.checkpoint.verify_transition(loaded,closed,exited,startup)
    doc=deepcopy(loaded['guide_parameters']['document']);doc['configuration']='Default'
    p=dict(late_exit_observation_pin=dict(path='C:/late.json',sha256='e'*64),process_id=60,expected_process_creation_time=1100.,expected_document_path='C:/model.sldprt',expected_source_sha256='b'*64,expected_dirty=False,expected_configuration='Default',saved_cl_path=str(tmp_path/'export/saved.cl'))
    old=dict(mvid='11111111-1111-1111-1111-111111111111',dll=dict(path='C:/old.dll'))
    new=dict(mvid='22222222-2222-2222-2222-222222222222',dll=dict(path='C:/new.dll'))
    ref=dict(document=doc,expected_snapshot=deepcopy(loaded['current_snapshot']),mill_request=dict(expected_process_id=60),cam_typelib_pin=dict(path='C:/cam.tlb'))
    want=dict(path='C:/before.cl',sha256='c'*64,bytes=123)
    q=dict(source_sha256='b'*64,saved_cl=dict(output=want,expected_generated_operations=[dict(operation_native_id=i,toolpath_record_counts=[2])for i in range(4,22)]))
    return p,loaded,q,old,new,ref,[],tmp_path/'result.json',tmp_path/'marker.json'

class Fake:
    def __init__(self,plan,*,old=False,dirty=False,owner=False,mismatch=False,cl=False,event=False,exception=None):
        self.plan=plan;self.calls=[];self.old=old;self.dirty=dirty;self.wrongowner=owner;self.mismatch=mismatch;self.badcl=cl;self.badevent=event;self.exception=exception;self.active=False
    def owner(self):
        result=deepcopy(self.plan[1]['ownership'])
        if self.wrongowner:result['process_id']=99
        return result
    def document(self):
        doc=deepcopy(self.plan[5]['document'])
        if self.dirty:doc['needs_save']=True
        return doc
    def identity_once(self):
        self.calls.append('identity');a=self.plan[3 if self.old else 4]
        return json.dumps(dict(schema_version=1,scope='TURN_INPROCESS_READ_V1',engine_version='turn-reader-1',stage='request',status='error',message='REQUEST_FIELDS',read_only=True,mutation_attempted=False,readback_verified=False,process_id=60,elapsed_ms=1,host_module_version_id=a['mvid'],host_assembly_location=a['dll']['path']))
    def start_events(self):self.calls.append('start_events');self.active=True;return events()
    def read_once(self):
        self.calls.append('mill')
        if self.exception=='mill':raise ValueError('native read failed')
        return json.dumps(dict(host_module_version_id=self.plan[4]['mvid'],host_assembly_location=self.plan[4]['dll']['path'],mismatch=self.mismatch))
    def export_once(self,diagnostic):
        self.calls.append('export')
        if self.exception=='export':raise ValueError('export failed')
        out=deepcopy(self.plan[2]['saved_cl']['output']);out['path']=self.plan[0]['saved_cl_path']
        if self.badcl:out['sha256']='d'*64
        diagnostic['output']=out;return out
    def close_events(self):
        if not self.active:return None
        self.calls.append('close_events');self.active=False;v=events(True)
        if self.badevent:v['event_count']=1
        return v

@pytest.fixture
def setup(tmp_path,loaded,monkeypatch):
    plan=prepared(tmp_path,loaded)
    monkeypatch.setattr(m.common,'check_files',lambda pins:None)
    def project(packet,request):
        snap=deepcopy(plan[5]['expected_snapshot'])
        if packet.get('mismatch'):snap['binding']['operations'][0]['native_id']=999
        return dict(snapshot=snap,diagnostic=dict(read_only=True))
    monkeypatch.setattr(m.projection,'project_packet',project)
    return plan

def test_identity_then_one_host_read_then_one_export(setup):
    b=Fake(setup);r=m.run_prepared(setup,backend=b)
    assert r['status']=='saved_eighteen_reopen_verified'
    assert b.calls==['identity','start_events','mill','export','close_events']
    assert r['readback_verified']is True and r['persistence_after_reopen_verified']is True
    assert r['cl_verification']['all18_complete_streams_bit_identical']is True
    assert r['GTP_attempted']is False and r['model_saved']is False and r['host_load_attempted']is False

def test_old_mvid_stops_before_any_cam(setup):
    b=Fake(setup,old=True);r=m.run_prepared(setup,backend=b)
    assert r['status']=='error'and b.calls==['identity']and 'raw_identity'in r and not r['persistence_after_reopen_verified']

@pytest.mark.parametrize('kwargs,expected',[(dict(dirty=True),[]),(dict(owner=True),[]),(dict(mismatch=True),['identity','start_events','mill','close_events']),(dict(cl=True),['identity','start_events','mill','export','close_events']),(dict(event=True),['identity','start_events','mill','export','close_events']),(dict(exception='mill'),['identity','start_events','mill','close_events']),(dict(exception='export'),['identity','start_events','mill','export','close_events'])])
def test_failure_no_replay_or_side_effect(setup,kwargs,expected):
    b=Fake(setup,**kwargs);r=m.run_prepared(setup,backend=b)
    assert r['status']=='error'and r['readback_verified']is False and r['persistence_after_reopen_verified']is False and b.calls==expected

def test_completed_attempt_cannot_replay_or_overwrite(setup):
    b=Fake(setup);m.run_prepared(setup,backend=b);before=(setup[-2].read_bytes(),setup[-1].read_bytes())
    with pytest.raises(ValueError):m.run_prepared(setup,backend=b)
    assert before==(setup[-2].read_bytes(),setup[-1].read_bytes())and b.calls.count('mill')==1

def test_actual_composed_constructor_exposes_no_mutator(setup):
    p,loaded,q,old,new,ref,*_=setup;b=m.NativeBackend(p,loaded,old,new,ref,{},lambda:None)
    for name in ('identity_once','start_events','read_once','export_once','close_events','owner','document','application'):assert callable(getattr(b,name))
    for name in ('load_once','unload_once','register_once','generate','save','insert','assign'):assert not hasattr(b,name)

def test_fixed_identity_payload_and_real_method_dispatch(monkeypatch,setup):
    p,loaded,q,old,new,ref,*_=setup;b=m.NativeBackend(p,loaded,old,new,ref,{},lambda:None);calls=[]
    monkeypatch.setattr(m.lifecycle.NativeBackend,'_read',lambda self,artifact,**kw:calls.append((artifact,kw))or'raw')
    assert b.identity_once()=='raw'and calls==[(old,dict(mill=False,text='{}'))]
    with pytest.raises(ValueError):b.identity_once()
    assert len(calls)==1

def test_host_read_uses_exact_sealed_request_once(monkeypatch,setup):
    p,loaded,q,old,new,ref,*_=setup;b=m.NativeBackend(p,loaded,old,new,ref,{},lambda:None);calls=[]
    monkeypatch.setattr(m.lifecycle.NativeBackend,'_read',lambda self,artifact,**kw:calls.append((artifact,kw))or'raw')
    assert b.read_once()=='raw';assert calls[0][0]==new and calls[0][1]['mill']is True and json.loads(calls[0][1]['text'])==ref['mill_request']
    with pytest.raises(ValueError):b.read_once()

def test_historical_loader_is_not_silently_allowed():
    with pytest.raises(ValueError,match='current unchanged'):m.load_completed_rebind('unused','0'*64,check_current=False)


def test_actual_cl_export_prebinds_before_real_guard_claim(tmp_path,monkeypatch,setup):
    from scripts import sw_cam_dispatch_guard as gm
    from types import SimpleNamespace
    source=tmp_path/'part.sldprt';source.write_bytes(b'source');proof=tmp_path/'proof.txt';proof.write_bytes(b'proof')
    p,loaded,q,old,new,ref,*_=setup;b=m.NativeBackend(p,loaded,old,new,ref,{},lambda:None)
    order=[];guards=[];raw=object();diag={}
    monkeypatch.setattr(gm.ScopedCamDispatchGuard,'_identity',lambda self:None)
    monkeypatch.setattr(gm,'_typed',lambda obj,name,path:order.append('QI')or raw)
    monkeypatch.setattr(m.cl.post,'_controller',lambda value:dict(name='fixed'))
    def member(obj,name,*args):
        if name=='SaveCLFile':order.append('SaveCLFile');Path(args[0]).write_bytes(b'fixedCL');return 0
        if name=='MachType':return 1
        return raw
    monkeypatch.setattr(gm,'_member',member);monkeypatch.setattr(m,'_member',member)
    def guard():
        g=gm.ScopedCamDispatchGuard(None,'metadata',process_id=60,expected_document=dict(path=str(source),title=source.name,type=1,needs_save=False),source_sha256=m.common.digest(source),evidence_pins=[m.lifecycle.pin(proof)],verify_evidence=lambda:None,verify_owned_process=lambda:None,check_events=lambda:None)
        guards.append(g);return g
    def persist():
        if diag.get('native_dispatch_pending')and 'pending'not in order:order.append('pending')
    b.persist=persist;b.parameters=SimpleNamespace(boundary=lambda:None,ctx=SimpleNamespace(guard=guard,app=raw),doc=None)
    pin=b.export_once(diag)
    assert order[order.index('pending')+1]=='SaveCLFile'
    assert guards[0]._claimed and guards[0]._attempted and guards[0]._returned
    assert len(guards)==2 and order.count('SaveCLFile')==1 and pin['bytes']==7
    with pytest.raises(ValueError):b.export_once({})
    assert order.count('SaveCLFile')==1


def completed_fixture(setup,monkeypatch):
    b=Fake(setup);r=m.run_prepared(setup,backend=b)
    p,loaded,q,old,new,ref,pins,out,marker=setup
    # Synthetic protocol fixture: it proves the validator, never native machining.
    r['request']={k:None for k in m.PARAMS};r['request'].update(p)
    r['cleanup_session_active']=False
    r['cl_export'].update(native_call_returned=True,native_dispatch_pending=False,native_return=dict(python_type='int',value_recorded=True,value=0))
    monkeypatch.setattr(m,'prepare',lambda request,completed=False:setup)
    monkeypatch.setattr(m.checkpoint.authority,'check',lambda pin:None)
    def persist(value):
        out.write_text(json.dumps(value),encoding='utf-8');marker.write_text(json.dumps(dict(scope=m.SCOPE,status=value['status'],receipt_pin=m.lifecycle.pin(out),automatic_replay=False)),encoding='utf-8')
        return str(out),m.common.digest(out)
    return r,persist


def test_completed_loader_preserves_verified_new_ownership(setup,monkeypatch):
    r,persist=completed_fixture(setup,monkeypatch);path,digest=persist(r)
    loaded,q,verified,pins=m.load_completed_rebind(path,digest)
    assert loaded['ownership']['process_id']==60 and loaded['historical_ownership']['process_id']==50
    assert loaded['current_snapshot']==setup[1]['current_snapshot']and loaded['reopened_checkpoint_pin']['sha256']==digest

@pytest.mark.parametrize('path,value',[(('persistence_after_reopen_verified',),False),(('host_load_attempted',),True),(('cleanup_session_active',),True),(('identity','loaded_artifact'),'old'),(('host_response','host_module_version_id'),'11111111-1111-1111-1111-111111111111'),(('cl_export','native_return','value'),True),(('cl_export','output','sha256'),'f'*64),(('ownership','process_id'),99),(('events_after','active'),True)])
def test_completed_loader_rejects_partial_proof(setup,monkeypatch,path,value):
    r,persist=completed_fixture(setup,monkeypatch);obj=r
    for key in path[:-1]:obj=obj[key]
    obj[path[-1]]=value
    name,digest=persist(r)
    with pytest.raises(ValueError):m.load_completed_rebind(name,digest)


def test_prepare_uses_old_turn_and_new_mill_abi_only():
    import ast,inspect
    tree=ast.parse(inspect.getsource(m.prepare))
    calls=[n for n in ast.walk(tree)if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and n.func.attr=='type_library']
    assert len(calls)==2
    assert [('old'if isinstance(v.args[0],ast.Subscript)and 'old'in ast.unparse(v.args[0])else'new',next(k.value.value for k in v.keywords if k.arg=='mill'))for v in calls]==[('old',False),('new',True)]
