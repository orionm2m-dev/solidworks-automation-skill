import ast,importlib.util,json,os,sys
from copy import deepcopy
from pathlib import Path
import pytest
root=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).resolve().parents[1])))
sys.path.insert(0,str(root))
spec=importlib.util.spec_from_file_location('owned_exit',root/'scripts/sw_owned_empty_exit.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.fixture
def evidence(tmp_path):
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'saved current CAM')
    doc=dict(path=str(source),title=source.name,type=1,needs_save=False)
    state=dict(document=doc,inventory=dict(machine_type=3,operation_count=1,operations=[]),saved_file_sha256=m.digest(source))
    before=deepcopy(state);before['document']['needs_save']=True;before['saved_file_sha256']='1'*64
    common=dict(status='review_required',phase='finished',mutation_attempted=True,native_call_attempted=True,native_call_returned=True,generation_attempted=False,messages=dict(subscribed=True,disconnected=True,active=False,event_count=0,events=[],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[]))
    saved=dict(common,action='save',native_save_call_returned=True,save_readback_verified=True,native_close_call_returned=False,native_outcome='save_returned_readback_verified',before=before,after=state,final_state=state,state_sha256=m._digest(state))
    closed=dict(common,action='close',native_close_call_returned=True,close_verified=True,native_save_call_returned=False,native_outcome='target_absent_from_open_documents',before=state,state_sha256=m._digest(state),user_control_before_close=True,open_documents_after=[],open_documents_after_cleanup=[])
    exe=str(tmp_path/'SLDWORKS.exe');ticks=m._EPOCH+1700000000*10000000
    owned=dict(status='ok',phase='connected',launch_mode='executable',launch_attempted=True,new_process_verified=True,process_id=123,known_process_ids_before=[122],executable=exe,launch_intent_time=1699999999.0,process_identity=dict(process_id=123,create_time=1700000000.0,executable=exe,alive=True))
    params=dict(process_id=123,expected_creation_filetime=ticks,expected_executable_path=exe,expected_document_path=str(source),expected_source_sha256=m.digest(source),receipt_path=str(tmp_path/'exit.json'),wait_milliseconds=10,acknowledge_exit_owned_empty_session=True)
    for name,data in [('ownership',owned),('save',saved),('close',closed)]:
        path=tmp_path/(name+'.json');path.write_text(json.dumps(data));params[name+'_receipt_path']=str(path);params[name+'_receipt_sha256']=m.digest(path)
    return params

class Fake:
    def __init__(self,p):self.p=p;self.calls=0;self.started=0;self.closed=False;self.waited=False;self.signalled=True;self.docs=[];self.log=[];self.fail_exit=False;self.owner_change=False
    def start(self):self.started+=1;self.log.append('start')
    def owner(self):
        self.log.append('owner');return dict(process_id=self.p['process_id'],creation_filetime=self.p['expected_creation_filetime']+(1 if self.owner_change else 0),executable=self.p['expected_executable_path'],alive=not(self.waited and self.signalled))
    def empty(self):self.log.append('empty');assert self.calls==0;m.require(self.docs==[],'Open documents');return []
    def exit_once(self):
        self.calls+=1;self.log.append('ExitApp')
        if self.fail_exit:raise RuntimeError('RPC disconnect')
    def wait_exit(self,ms):self.waited=True;self.log.append('OSwait');assert ms==self.p['wait_milliseconds'];return self.signalled
    def close(self):self.closed=True;self.log.append('OSclose')

def rewrite(p,name,update):
    f=Path(p[name+'_receipt_path']);v=json.loads(f.read_text());update(v);f.write_text(json.dumps(v));p[name+'_receipt_sha256']=m.digest(f)

def test_existing_lifecycle_structure_one_exit_and_only_os_reads_after(evidence):
    p=evidence;b=Fake(p);r=m.run_exit(p,backend=b)
    assert r['status']=='exited' and r['process_exit_verified'] and r['readback_verified'] and r['saved_files_preserved'] and b.calls==1
    assert b.log[b.log.index('ExitApp')+1:]==['OSwait','OSclose']
    assert not any(r[k] for k in ('termination_attempted','terminate_rights_requested','save_attempted','close_document_attempted','launch_attempted'))

@pytest.mark.parametrize('mutation',[
 lambda v:v.update(status='uncertain'),lambda v:v.update(save_readback_verified=False),
 lambda v:v.update(native_save_call_returned=False),lambda v:v.update(issue={'type':'error'}),
 lambda v:v['messages'].update(event_count=1),lambda v:v['final_state']['inventory'].update(machine_type=1),
 lambda v:v.update(state_sha256='0'*64),lambda v:v['final_state']['document'].update(needs_save=True),
])
def test_bad_saved_evidence_never_connects(evidence,mutation):
    p=evidence;rewrite(p,'save',mutation);b=Fake(p)
    with pytest.raises((ValueError,KeyError)):m.run_exit(p,backend=b)
    assert b.started==0 and b.calls==0

@pytest.mark.parametrize('mutation',[
 lambda v:v.update(close_verified=False),lambda v:v.update(user_control_before_close=False),
 lambda v:v.update(open_documents_after_cleanup=[{'path':'other'}]),lambda v:v.update(native_outcome='unknown'),
 lambda v:v.update(state_sha256='0'*64),lambda v:v['before']['inventory'].update(operation_count=2),
])
def test_bad_closed_evidence_never_connects(evidence,mutation):
    p=evidence;rewrite(p,'close',mutation);b=Fake(p)
    with pytest.raises(ValueError):m.run_exit(p,backend=b)
    assert b.started==0 and b.calls==0

@pytest.mark.parametrize('mutation',[
 lambda v:v.update(process_id=124),lambda v:v.update(known_process_ids_before=[123]),
 lambda v:v.update(new_process_verified=False),lambda v:v['process_identity'].update(create_time=1700000001.0),
])
def test_bad_ownership_never_connects(evidence,mutation):
    p=evidence;rewrite(p,'ownership',mutation);b=Fake(p)
    with pytest.raises(ValueError):m.run_exit(p,backend=b)
    assert b.started==0

@pytest.mark.parametrize('field,value',[
 ('process_id',True),('expected_creation_filetime',True),('wait_milliseconds',30001),('wait_milliseconds',0),
 ('acknowledge_exit_owned_empty_session',False),('expected_executable_path','relative/SLDWORKS.exe'),
])
def test_bad_inputs(evidence,field,value):
    p=evidence;p[field]=value;b=Fake(p)
    with pytest.raises(ValueError):m.run_exit(p,backend=b)
    assert b.started==0

def test_live_other_document_forbids_exit(evidence):
    b=Fake(evidence);b.docs=['user document'];r=m.run_exit(evidence,backend=b);assert r['status']=='error' and b.calls==0 and b.closed

def test_process_lifetime_mismatch_forbids_exit(evidence):
    b=Fake(evidence);b.owner_change=True;r=m.run_exit(evidence,backend=b);assert r['status']=='error' and b.calls==0

def test_user_control_guard_failure_forbids_exit(evidence):
    b=Fake(evidence)
    def empty():raise ValueError('UserControl false')
    b.empty=empty;r=m.run_exit(evidence,backend=b);assert r['status']=='error' and b.calls==0

def test_no_retry_when_exit_is_not_observed(evidence):
    b=Fake(evidence);b.signalled=False;r=m.run_exit(evidence,backend=b);assert r['status']=='exit_not_observed' and not r['process_exit_verified'] and b.calls==1
    p=dict(evidence,receipt_path=str(Path(evidence['receipt_path']).with_name('different.json')))
    with pytest.raises(ValueError):m.run_exit(p,backend=b)
    assert b.calls==1

def test_rpc_error_kept_even_if_exact_process_exit_is_observed(evidence):
    b=Fake(evidence);b.fail_exit=True;r=m.run_exit(evidence,backend=b)
    assert r['status']=='exited' and r['process_exit_verified'] and 'exit_error' in r and not r['exit_returned'] and b.calls==1

def test_source_change_after_exit_not_reported_preserved(evidence):
    b=Fake(evidence);base=b.wait_exit
    def wait(ms):Path(evidence['expected_document_path']).write_bytes(b'changed');return base(ms)
    b.wait_exit=wait;r=m.run_exit(evidence,backend=b);assert r['status']=='uncertain' and r['saved_files_preserved'] is None and r['process_exit_verified']

def test_changed_source_before_connect_stops(evidence):
    Path(evidence['expected_document_path']).write_bytes(b'changed');b=Fake(evidence)
    with pytest.raises(ValueError):m.run_exit(evidence,backend=b)
    assert b.started==0


def test_signalled_exit_does_not_requery_terminated_process_identity(evidence):
    b=Fake(evidence);base=b.owner
    def owner():
        assert not b.waited,'Terminated process identity must not be queried'
        return base()
    b.owner=owner;r=m.run_exit(evidence,backend=b)
    assert r['status']=='exited' and r['process_exit_verified'] and b.calls==1


def test_mcp_model_strict_identity_and_explicit_acknowledgement(evidence):
    from pydantic import BaseModel,ConfigDict,Field,model_validator
    from enum import Enum
    class BaseInput(BaseModel):model_config=ConfigDict(extra='forbid')
    class ResponseFormat(str,Enum):JSON='json'
    class Decorator:
        def tool(self,**kwargs):return lambda f:f
    sys.modules['scripts.sw_owned_empty_exit']=m
    ns=dict(BaseInput=BaseInput,Field=Field,model_validator=model_validator,ResponseFormat=ResponseFormat,mcp=Decorator())
    server=root/'mcp-server/server.py'
    tree=ast.parse(server.read_text(encoding='utf-8-sig'),filename=str(server))
    names={'SolidWorksOwnedEmptyExitInput','solidworks_exit_owned_empty_session'}
    nodes=[node for node in tree.body if isinstance(node,(ast.ClassDef,ast.FunctionDef)) and node.name in names]
    assert {node.name for node in nodes}==names,'Installed MCP model/tool must both exist'
    isolated=ast.Module(body=nodes,type_ignores=[])
    exec(compile(isolated,str(server),'exec'),ns)
    cls=ns['SolidWorksOwnedEmptyExitInput'];cls(**evidence)
    for field,value in [('process_id',True),('expected_creation_filetime',True),('acknowledge_exit_owned_empty_session',False),('wait_milliseconds','10')]:
        with pytest.raises(ValueError):cls(**dict(evidence,**{field:value}))
