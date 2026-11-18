"""Portable orchestration tests exercise the inherited real CL exporter/parser."""
import ast,copy,json,os,sys
from pathlib import Path
from enum import Enum
from typing import Literal
import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
ROOT=Path(__file__).resolve().parents[1];RT=Path(os.environ.get('SWMCP_RUNTIME_ROOT',ROOT));sys.path.insert(0,str(RT))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
if os.environ.get('SWMCP_SAVED_CONTEXT_ROOT'):scripts.__path__.insert(0,str(Path(os.environ['SWMCP_SAVED_CONTEXT_ROOT'])/'scripts'))
from scripts import sw_cam_current_pocket_cl_recovery as c


def request(tmp_path):
    return dict(process_id=51,expected_process_create_time=123.5,expected_document_path=str(tmp_path/'part.sldprt'),expected_source_sha256='a'*64,expected_feature_native_id=77,expected_operation_native_ids=[501,502],selected_operation_native_id=501,saved_attempt_receipt_path=str(tmp_path/'saved.json'),saved_attempt_receipt_sha256='b'*64,receipt_path=str(tmp_path/'receipt.json'),saved_cl_path=str(tmp_path/'fresh'/'one.cl'),qualification_only=True,acknowledge_export_only=True,message_policy='vendor_default')


def schema():
    p=ROOT/'server.fragment.py'
    if not p.exists():p=RT/'mcp-server/server.py'
    node=next(n for n in ast.parse(p.read_text('utf-8-sig')).body if isinstance(n,ast.ClassDef)and n.name=='SolidWorksCamCurrentPocketCLRecoveryInput')
    class Target(BaseModel):
        model_config=ConfigDict(extra='forbid')
        addin_clsid:str
        expected_document_title:str|None=None
    class ResponseFormat(str,Enum):JSON='json'
    env=dict(SolidWorksCamTargetInput=Target,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,Literal=Literal,ResponseFormat=ResponseFormat)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),env);return env[node.name]


@pytest.mark.parametrize('patch',[dict(selected_operation_native_id=502),dict(expected_operation_native_ids=[501.,502]),dict(process_id=True),dict(expected_process_create_time=float('nan')),dict(acknowledge_export_only=False),dict(unrequested_Save=True)])
def test_schema_rejects_outside_scope(tmp_path,patch):
    v=request(tmp_path);v.update(patch)
    with pytest.raises(ValueError):schema()(**dict(v,addin_clsid='x'))


def test_schema_noapplication_and_native_save_forbidden(tmp_path):
    v=request(tmp_path);schema()(**dict(v,addin_clsid='x'))
    class NoApp:
        def __getattr__(self,name):raise AssertionError(name)
    b=c.Backend(NoApp(),'x','tlb',v,dict(bundle=dict(context=dict(pins=[]))),{},lambda:None,lambda:None,dict(generated_pin={}))
    assert b.attempted==[501]
    for name in ('save','generate','set_field','read_field','create','field','property','assign_selected','attach_holder'):
        with pytest.raises(ValueError):getattr(b,name)()
    assert c.Backend.export_cl is c.generation.generation.NativeGenerationContext.export_cl


@pytest.fixture
def flow(tmp_path,monkeypatch):
    v=request(tmp_path);state=dict(document=dict(path=v['expected_document_path'],title='part.sldprt',type=1,needs_save=False),saved_file_sha256='a'*64,operations=[dict(native_id=501,toolpath_generated=True,toolpath_record_counts=[6]),dict(native_id=502,toolpath_generated=False,toolpath_record_counts=[])])
    expected=dict(inventory=state,parameters=[{'operation_native_id':501},{'operation_native_id':502}]);pin={'path':str(tmp_path/'saved.json'),'sha256':'b'*64}
    data=dict(request=v,expected_state=expected,receipt=Path(v['receipt_path']),marker=tmp_path/'once.json')
    r=dict(scope=c.SCOPE,status='prepared',phase='prepared',configuration_receipt_pin=pin,selected_operation_native_ids=[501],actions={},mutation_attempted=False,CL_export_attempted=False,Save_attempted=False,GTP_attempted=False,historical_model_saved=True,historical_save_readback_verified=True,**{k:False for k in c.FLAGS})
    j=c.Journal(data['receipt'],data['marker'],r)
    monkeypatch.setattr(c.delta,'flatten',lambda s:dict(copy.deepcopy(s['inventory']),operation_parameters=copy.deepcopy(s['parameters'])))
    monkeypatch.setattr(c.reader.shared,'event_health',lambda *a,**k:0)
    raw=b'UNITS/MM\nOPFEATSTART/test\nCUTTER/8,0,4,0,0,0,64\nTLAXIS/0,0,1\nRAPID/\nGOTO/0,0,-12\nFEDRAT/MMPM,100\nGOTO/0,0,-13.3\nOPFEATEND/test\nFINI\n'
    class Machine:
        def SaveCLFile(self,path):
            b.calls.append('nativeCL')
            if b.fail=='CL':raise ValueError('native CL failure')
            Path(path).write_bytes(raw);return True if b.fail=='bool'else 0
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def typed(self,obj,name):return obj
        def read(self,obj,name):
            b.calls.append(name)
            if name=='IGetMachine':return b.native['machine']
            if name=='MachType':return 1
            if name=='GetController2':assert obj is b.native['machine'];return False,'test',True
            pytest.fail('Unrequested native getter '+name)
        def dispatch_once(self,callback,persist_pending):persist_pending();return callback()
    class B:
        export_cl=c.Backend.export_cl
        parse_cl=c.Backend.parse_cl
        fail=None
        def __init__(self):self.args=v;self.source='a'*64;self.calls=[];self.expected_document=state['document'];self.native={};self.persist=j.persist
        def start(self):self.calls.append('start')
        def boundary(self):return copy.deepcopy(self.expected_document)
        def capture(self,label,partial):
            self.calls.append(label);self.native={'doc':object(),'machine':Machine()}
            partial.update(c.delta.flatten(expected))
            if self.fail==label:partial['operation_parameters'][1]['changed']=True
            return partial
        def guard(self):return Guard()
        def close(self):
            self.calls.append('close');r['messages']={}
            if self.fail=='cleanup':raise ValueError('cleanup failed')
        def runtime_check(self):
            if self.fail=='runtime':raise ValueError('runtime changed')
        def identity(self):return self.expected_document
        def files(self):pass
    b=B();return b,j,data,r


def test_real_export_only_two_captures_native_once_and_parser(flow):
    b,j,d,r=flow;out=c.run_backend(b,j,d)
    assert out['status']=='review_required'and all(out[k]is True for k in c.FLAGS)
    assert [x for x in b.calls if x.startswith('postCL_')]==['postCL_before','postCL_after']
    assert b.calls.count('nativeCL')==1 and set(r['actions'])=={'postCL'}
    assert out['first_CL_proof']['expected_record_count']==6
    assert out['Save_attempted']is out['GTP_attempted']is False and out['historical_model_saved']is True
    assert Path(d['request']['saved_cl_path']).is_file()


@pytest.mark.parametrize('failure',['postCL_before','CL','bool','postCL_after','cleanup','runtime'])
def test_failure_never_replays_save_or_gtp_and_retains_actual_export(flow,failure):
    b,j,d,r=flow;b.fail=failure;out=c.run_backend(b,j,d)
    assert all(out[k]is False for k in c.FLAGS) and out['Save_attempted']is out['GTP_attempted']is False
    assert b.calls.count('nativeCL')<=1 and out['historical_save_readback_verified']is True
    if failure=='postCL_before':assert 'nativeCL'not in b.calls
    if failure in ('postCL_after','cleanup','runtime'):assert out['actions']['postCL']['native_return_value']==0
    with pytest.raises(ValueError):c.Journal(j.receipt,j.marker,out).create()


@pytest.mark.parametrize('name',['SaveActiveDocument','GTP:501','field:entry_type'])
def test_journal_has_no_save_or_generation_action(tmp_path,name):
    j=c.Journal(tmp_path/'r',tmp_path/'m',{'actions':{}})
    with pytest.raises(ValueError):j.action(name)


def test_actual_or_generic_request_envelope(tmp_path):
    path=os.environ.get('SWMCP_REQUEST_ENVELOPE_PATH')
    r=json.loads(Path(path).read_text('utf-8'))if path else {'requests':[{'name':'solidworks_connect','arguments':{'params':{'process_id':51}}},{'name':'solidworks_cam_export_saved_current_pocket','arguments':{'params':dict(request(tmp_path),addin_clsid='x')}}]}
    connect,call=r['requests'];assert connect['name']=='solidworks_connect'and set(connect['arguments'])=={'params'}
    assert call['name']=='solidworks_cam_export_saved_current_pocket';v=schema()(**call['arguments']['params'])
    assert connect['arguments']['params']=={'process_id':v.process_id}
