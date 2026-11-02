from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json,os,sys
import pytest
from cam_public_test_support import add_runtime,required_module
R=add_runtime()
m=required_module('sw_cam_saved18_dirty_fast_capture')

class Guard:
    def __init__(self,b):self.b=b
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,obj,name):self.b.calls.append(name);return 'native-doc'
    def typed(self,obj,name):self.b.calls.append(name);return obj

class Backend:
    def __init__(self,dirty=False):
        self.report={};self.args=dict(process_id=60);self.typelib_path='C:/cam.tlb';self.calls=[];self.persisted=[];self.doc=None;self.save_app=None
        doc=dict(path='C:/part.sldprt',title='part.sldprt',type=1,needs_save=dirty)
        self.ctx=SimpleNamespace(expected_document=doc,args=dict(expected_source_sha256='a'*64),app='native-app')
        self.ctx.identity=lambda:deepcopy(self.ctx.expected_document);self.ctx.guard=lambda:Guard(self)
    def boundary(self):self.calls.append('boundary')
    def persist(self):self.persisted.append(deepcopy(self.report))
    def verify_catalogue(self,label):self.calls.append('catalogue:'+label)

class Call:
    def __init__(self,b,*,bad_mvid=False,dirty=None,change_source=False,error=False):self.b=b;self.bad=bad_mvid;self.dirty=dirty;self.change_source=change_source;self.error=error;self.count=0
    def read(self,artifact,request):
        self.count+=1;self.b.calls.append('host')
        if self.error:raise ValueError('read failed')
        doc=deepcopy(self.b.ctx.expected_document);doc['configuration']='Default'
        if self.dirty is not None:doc['needs_save']=self.dirty
        if self.change_source:self.b.ctx.args['expected_source_sha256']='c'*64
        return json.dumps(dict(host_module_version_id='wrong'if self.bad else artifact['mvid'],host_assembly_location=artifact['dll']['path'],document_before=doc,document_after=doc,actual_value=100+self.count))

@pytest.fixture
def cap(monkeypatch):
    monkeypatch.setattr(m.common,'check_files',lambda pins:None)
    monkeypatch.setattr(m.projection,'project_packet',lambda packet,request:dict(snapshot=dict(binding={'actual':packet['actual_value']},parameters=[{'actual':packet['actual_value']}]),diagnostic={'semantic_projection_complete':True}))
    return dict(scope=m.SCOPE,request=dict(expected_process_id=60,expected_document_path='C:/part.sldprt'),artifact=dict(mvid='new',dll=dict(path='C:/new.dll')),ownership=dict(process_id=60),pins=[],reopen_pin=dict(path='C:/reopen.json',sha256='b'*64),cam_typelib_pin=dict(path='C:/cam.tlb'))

@pytest.mark.parametrize('dirty',[False,True])
def test_observes_actual_values_and_expected_dirty_without_old_value_comparison(cap,dirty):
    b=Backend(dirty);call=Call(b);out=m.capture_snapshot(b,m.LABELS[0],cap,host_call=call)
    assert out['parameters'][0]['actual']==101 and call.count==1 and b.doc=='native-doc'and b.save_app=='native-app'
    assert b.calls.index('ICWApp')<b.calls.index('catalogue:'+m.LABELS[0]+'_before_fast')<b.calls.index('host')<b.calls.index('catalogue:'+m.LABELS[0]+'_after_fast')
    assert b.report['captures'][0]['capture_mode']=='qualified_inprocess'and 'read_batch'not in b.report['captures'][0]
    assert b.report['fast_captures'][0]['readback_verified']is True
    assert any('raw_host_response'in row.get('fast_captures',[{}])[0]and 'host_response'not in row['fast_captures'][0]for row in b.persisted)

@pytest.mark.parametrize('kwargs',[dict(bad_mvid=True),dict(dirty=True),dict(change_source=True),dict(error=True)])
def test_unknown_or_inconsistent_packet_stops_no_retry(cap,kwargs):
    b=Backend();call=Call(b,**kwargs)
    with pytest.raises(ValueError):m.capture_snapshot(b,m.LABELS[0],cap,host_call=call)
    assert call.count==1 and b.report['fast_captures'][0]['status']=='error'and not b.report.get('captures')
    with pytest.raises(ValueError):m.capture_snapshot(b,m.LABELS[0],cap,host_call=call)
    with pytest.raises(ValueError):m.capture_snapshot(b,m.LABELS[1],cap,host_call=call)
    assert call.count==1

def test_four_fixed_stages_allow_expected_source_transition_only_between_calls(cap):
    b=Backend();call=Call(b)
    for i,label in enumerate(m.LABELS):
        b.ctx.expected_document['needs_save']=i in (1,2)
        if i==3:b.ctx.args['expected_source_sha256']='d'*64
        m.capture_snapshot(b,label,cap,host_call=call)
    assert call.count==4 and len(b.report['captures'])==4
    with pytest.raises(ValueError):m.capture_snapshot(b,m.LABELS[3],cap,host_call=call)
    assert call.count==4

@pytest.mark.parametrize('change',['pid','path','tlb','label','scope'])
def test_scope_drift_rejected_before_native(cap,change):
    b=Backend();call=Call(b);label=m.LABELS[0]
    if change=='pid':b.args['process_id']=99
    if change=='path':b.ctx.expected_document['path']='C:/foreign.sldprt'
    if change=='tlb':b.typelib_path='C:/other.tlb'
    if change=='label':label=m.LABELS[1]
    if change=='scope':cap['scope']='other'
    with pytest.raises(ValueError):m.capture_snapshot(b,label,cap,host_call=call)
    assert call.count==0

def test_catalogue_change_stops_before_host(cap):
    b=Backend();call=Call(b)
    b.verify_catalogue=lambda label:(_ for _ in ()).throw(ValueError('catalogue changed'))
    with pytest.raises(ValueError):m.capture_snapshot(b,m.LABELS[0],cap,host_call=call)
    assert call.count==0

def test_hostcall_fixed_interface_and_exact_request(monkeypatch):
    b=Backend();b.sw=object();calls=[]
    monkeypatch.setattr(m.lifecycle.NativeBackend,'_read',lambda self,artifact,**kwargs:calls.append((self.application(),artifact,kwargs))or'raw')
    request={'fixed':'request'};artifact={'pinned':'artifact'}
    assert m.HostCall(b).read(artifact,request)=='raw'
    assert calls[0][0]is b.sw and calls[0][1]==artifact and calls[0][2]['mill']is True and json.loads(calls[0][2]['text'])==request

def test_hostcall_has_no_activation_or_cam_mutator():
    value=m.HostCall(Backend())
    for name in ('load_once','unload_once','register_once','generate','save','assign','insert'):assert not hasattr(value,name)


@pytest.fixture
def qualified(tmp_path):
    dll=tmp_path/'host.dll';dll.write_bytes(b'synthetic artifact')
    tlb=tmp_path/'host.tlb';tlb.write_bytes(b'synthetic metadata')
    owner=dict(process_id=60,create_time=1000.,executable='C:/SLDWORKS.exe',alive=True)
    request=dict(expected_operation_ids=list(range(1,22)),parameter_targets=[dict(operation_native_id=i)for i in range(1,13)],feature_ids=list(range(31,37)))
    snapshot=dict(binding={},parameters=[])
    ref=dict(ownership=owner,counts=dict(operations=21,parameters=12,features=6,paths=18),mill_request=request,expected_snapshot=snapshot,cam_typelib_pin=m.lifecycle.pin(tlb))
    artifact=dict(mvid='new',dll=m.lifecycle.pin(dll),tlb=m.lifecycle.pin(tlb),dependencies=[])
    r=dict(scope=m.authority.SCOPE,status='saved_eighteen_observed_dirty_verified',phase='finished',readback_verified=True,persistence_after_reopen_verified=True,loaded_mvid_verified=True,host_native_compatibility_qualified=True,ownership=owner,module_pin=m.lifecycle.pin(m.authority.__file__),identity=dict(loaded_artifact='new',module_version_id='new',assembly_location=str(dll)),host_response=dict(validated_request=request),projection=dict(snapshot=snapshot))
    file=tmp_path/'synthetic_verified_protocol.json';file.write_text(json.dumps(r),encoding='utf-8')
    loaded=dict(reopened_checkpoint_pin=m.lifecycle.pin(file),host_reference=deepcopy(ref),host_artifact=deepcopy(artifact),ownership=deepcopy(owner),pins=[m.lifecycle.pin(tlb)])
    return loaded,r,file

def test_prepare_capture_binds_exact_qualified_request_and_all_code_artifacts(qualified):
    loaded,_,_=qualified;cap=m.prepare_capture(loaded)
    assert cap['request']==loaded['host_reference']['mill_request']and cap['scope']==m.SCOPE
    assert loaded['pins'][0]in cap['pins']and loaded['host_artifact']['dll']in cap['pins']
    assert m.lifecycle.pin(m.lifecycle.__file__)in cap['pins']and m.lifecycle.pin(m.projection.__file__)in cap['pins']

@pytest.mark.parametrize('kind',['unqualified','pid','request','snapshot','mvid','producer','missing'])
def test_prepare_capture_rejects_unverified_or_changed_capability(qualified,kind):
    loaded,r,file=qualified
    if kind=='pid':loaded['ownership']['process_id']=99
    elif kind=='request':loaded['host_reference']['mill_request']['feature_ids'][0]=999
    elif kind=='snapshot':loaded['host_reference']['expected_snapshot']['binding']['changed']=True
    elif kind=='mvid':loaded['host_artifact']['mvid']='old'
    elif kind=='missing':del loaded['reopened_checkpoint_pin']
    else:
        if kind=='unqualified':r['host_native_compatibility_qualified']=False
        if kind=='producer':r['module_pin']['sha256']='0'*64
        file.write_text(json.dumps(r),encoding='utf-8');loaded['reopened_checkpoint_pin']=m.lifecycle.pin(file)
    with pytest.raises(ValueError):m.prepare_capture(loaded)
