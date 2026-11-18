"""Read-only execution lifecycle/late-failure contracts; no native applications."""
from copy import deepcopy
from pathlib import Path
import ast,hashlib,os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1];RT=Path(os.environ['SWMCP_RUNTIME_ROOT'])
sys.path.insert(0,str(RT))
import scripts
STAGING=ROOT.parent
for folder in (ROOT/'scripts',STAGING/'cam_current_pocket_generation_recovery_v2_20261111/recovered_context_candidate/scripts',STAGING/'cam_current_pair_read_acceleration_20261111/fast_definition_candidate/scripts',STAGING/'cam_current_pair_read_acceleration_20261111/prebound_inventory_candidate/scripts',STAGING/'cam_current_pair_read_acceleration_20261111/scripts'):
    if folder.is_dir():scripts.__path__.insert(0,str(folder))
from scripts import sw_cam_qualify_recovered_pocket_read as c

def pin(p):return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())

def summary(active):
    return dict(subscribed=True,active=active,disconnected=not active,event_count=0,events=[],overflow=False,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])

@pytest.fixture
def env(tmp_path,monkeypatch):
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'current saved part')
    proof=tmp_path/'terminal.json';proof.write_bytes(b'file authority fixture')
    cl=tmp_path/'path.cl';cl.write_bytes(b'protected CL fixture')
    tlb=tmp_path/'camworks.tlb';tlb.write_bytes(b'ABI fixture')
    generated=tmp_path/'generated.py';generated.write_bytes(b'generated type fixture')
    document=dict(path=str(source),title=source.name,type=1,needs_save=False)
    rows=[dict(native_id=i,setup_native_id=51,mill_operation_type=k,suppressed=False,toolpath_generated=k==0,toolpath_record_counts=[17]if k==0 else [],linked_feature_ids=[22])for k,i in enumerate((31,32))]
    state=dict(document=document,saved_file_sha256=pin(source)['sha256'],operations=rows,operation_setups=[dict(native_id=51)])
    parameters=[dict(operation_native_id=i,read_complete=True,raw_parameter=3.5)for i in(31,32)]
    v=dict(process_id=123,expected_process_create_time=1234.5,expected_document_path=str(source),expected_source_sha256=pin(source)['sha256'],expected_feature_native_id=22,expected_operation_native_ids=[31,32],recovered_receipt_path=str(proof),recovered_receipt_sha256=pin(proof)['sha256'],receipt_path=str(tmp_path/'read.json'))
    context=dict(request=deepcopy(v),expected_document_path=str(source),expected_source_sha256=v['expected_source_sha256'],saved_plan_inventory=deepcopy(state),pins=[pin(source),pin(proof),pin(cl)])
    bundle=dict(context=context,state=state,parameters=parameters,pins=context['pins'],receipt_pin=pin(proof),protected_generated={31:[17]},protected_cl=dict(pin=pin(cl)))
    control=dict(fault=None,captures=0,native_calls=[],closed=False)
    def files(value):
        d=value['context']if 'context'in value else value
        for p in d['pins']:
            assert pin(Path(p['path']))['sha256']==p['sha256'],'immutable pin changed'
        if control['fault']=='late_authority'and control['closed']:raise ValueError('late authority changed')
    def load(request):
        assert set(request)==c.admission.KEYS
        if control['fault']=='admission':raise ValueError('terminal authority rejected')
        return deepcopy(bundle)
    monkeypatch.setattr(c.admission,'load',load);monkeypatch.setattr(c.admission,'verify_files',files)
    monkeypatch.setattr(c.reader.definition,'verify_files',files)
    def identity(sw,d):
        value=deepcopy(document)
        if control['fault']=='cleanup_identity'and control['closed']:value['needs_save']=True
        return dict(document=value,saved_file_sha256=v['expected_source_sha256'])
    monkeypatch.setattr(c.reader.definition,'identity',identity)
    monkeypatch.setattr(c.reader,'preflight',lambda tlb:dict(generated_pin=pin(generated)))
    sw,addin,app,doc,machine,feature=(object()for _ in range(6))
    def bootstrap(obj,name,*args):
        control['native_calls'].append(name)
        if obj is sw and name=='GetAddInObject':return addin
        if obj is addin and name=='GetCWApp':return app
        raise AssertionError(name)
    monkeypatch.setattr(c.reader,'_member',bootstrap);monkeypatch.setattr(c.reader,'_typed',lambda obj,*args:obj)
    class Session:
        def __init__(self,*args):self.active=False
        def __enter__(self):self.active=True;return self
        def summary(self):
            value=summary(self.active)
            if control['fault']=='event'and control['captures']>0:value.update(event_count=1,events=[{'message':'unexpected'}])
            return value
        def __exit__(self,*args):
            self.active=False;control['closed']=True
            if control['fault']=='cleanup':raise ValueError('unsubscribe failed')
    monkeypatch.setattr(c.reader,'CamMessageSession',Session)
    def capture(sw,clsid,tlb,context,check,diag):
        check();control['captures']+=1;value=deepcopy(state)
        if control['fault']=='late_inventory'and control['captures']==2:value['operations'][1]['setup_native_id']=99
        if control['fault']=='body'and control['captures']==2:raise ValueError('CAD body changed')
        if control['fault']=='source'and control['captures']==2:source.write_bytes(b'changed source')
        diag.update(capture_complete=True,timing_seconds={'before_cad':.1,'bootstrap':.1,'inventory_and_header':.1,'after_cad':.1})
        return value,dict(doc=doc,machine=machine,selected_feature=feature)
    monkeypatch.setattr(c.fast,'capture',capture)
    def binding(obj,name,*args):
        assert name in('GetDocType','MachType','GetCWObjectID')
        return (22,True)if name=='GetCWObjectID'else 1
    monkeypatch.setattr(c,'_member',binding)
    class Batch:
        def __init__(self,*args,**kw):
            assert kw['evidence_pin_limit']==128 and len(kw['evidence_pins'])<=128
            self.kw=kw;self.complete=False
        def __enter__(self):
            self.kw['verify_evidence']();self.kw['verify_owned_process']();self.kw['check_events']();self.kw['verify_retained_binding']();return self
        def __exit__(self,*args):
            self.kw['check_events']();self.kw['verify_evidence']();self.kw['verify_owned_process']();self.complete=args[0]is None
        def require_complete(self):assert self.complete
        def summary(self):return dict(read_scope_complete=self.complete,native_call_attempted=False)
    monkeypatch.setattr(c.retained,'RetainedPairReadBatch',Batch)
    def read_pair(state,native,targets,batch,report,persist,observations):
        assert observations=={31:[17]}and [x['native_id']for x in targets]==[31,32]
        report['parameters']=deepcopy(parameters)
        if control['fault']=='retained_source':source.write_bytes(b'source changed during retained phase')
        control['retained_phase_done']=True
        if control['fault']=='parameters':report['parameters'][1]['raw_parameter']=99.
        persist()
    monkeypatch.setattr(c.retained.generation,'read_pair',read_pair)
    def runtime():
        if control['fault']=='runtime'and control['closed']or control['fault']=='retained_runtime'and control.get('retained_phase_done'):raise ValueError('runtime changed')
    def run(prepared=None):return c.run_read(sw,'fixed',str(tlb),v,prepared=prepared,runtime_check=runtime)
    return dict(v=v,bundle=bundle,control=control,run=run,source=source,proof=proof,cl=cl)


def test_complete_saved_snapshot_and_clean_lifecycle(env):
    r=env['run']()
    assert r['status']=='observed'and all(r[k]is True for k in c.FLAGS)
    assert r['before_definition']==r['after_definition']==env['bundle']['state']
    assert r['parameters']==env['bundle']['parameters']and env['control']['closed']
    assert set(r['timing_seconds'])=={'before_definition','retained_parameters','after_definition'}
    assert set(env['control']['native_calls'])=={'GetAddInObject','GetCWApp'}
    for flag in ('mutation_attempted','Save_attempted','GOP_attempted','GTP_attempted','CL_export_attempted','tool_creation_attempted','tool_assignment_attempted','production_qualified','reusable_for_mutation','performance_improvement_verified'):assert r[flag]is False

@pytest.mark.parametrize('fault',['late_inventory','body','source','parameters','event','cleanup','cleanup_identity','late_authority','runtime','retained_source','retained_runtime'])
def test_late_failure_revokes_all_acceptance_flags(env,fault):
    env['control']['fault']=fault;r=env['run']()
    assert r['status']=='error'and all(r[k]is False for k in c.FLAGS)
    assert env['control']['closed']and r['mutation_attempted']is False


def test_failed_genuine_admission_never_connects(env):
    env['control']['fault']='admission'
    with pytest.raises(ValueError,match='authority'):env['run']()
    assert env['control']['native_calls']==[]and not Path(env['v']['receipt_path']).exists()


def test_output_alias_and_existing_receipt_rejected_before_connection(env):
    env['v']['receipt_path']=str(env['proof'])
    with pytest.raises(ValueError,match='Fresh'):env['run']()
    assert env['control']['native_calls']==[]


def test_prepared_invocation_cannot_be_replayed(env):
    prepared=c.prepare(env['v']);env['run'](prepared)
    with pytest.raises(ValueError,match='unused'):env['run'](prepared)
    assert env['control']['captures']==2


def test_only_readonly_lifecycle_is_inherited():
    assert c.Context.start is c.reader.Context.start and c.Context.close is c.reader.Context.close and c.Context.identity is c.reader.Context.identity
    tree=ast.parse(Path(c.__file__).read_text(encoding='utf-8'))
    forbidden={'dispatch_once','GenerateToolpath','SaveActiveDocument','SetTool','SetSaveFlag','LoadAddIn','ActivateDoc3'}
    assert not any(isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and n.func.attr in forbidden for n in ast.walk(tree))


@pytest.fixture
def mcp_env(env,monkeypatch):
    from enum import Enum
    from typing import Optional,Literal
    from types import SimpleNamespace
    from pydantic import BaseModel,Field,ConfigDict,field_validator,model_validator
    from scripts.sw_operation_guard import absolute_document_path
    server=ROOT/'mcp-server/server.py'
    if not server.is_file():server=RT/'mcp-server/server.py'
    names={'ResponseFormat','BaseInput','ActiveDocumentInput','SolidWorksCamTargetInput','SolidWorksCamRecoveredPocketReadQualificationInput','solidworks_cam_qualify_recovered_pocket_read'}
    nodes=[n for n in ast.parse(server.read_text(encoding='utf-8')).body if isinstance(n,(ast.ClassDef,ast.FunctionDef))and n.name in names]
    assert {n.name for n in nodes}==names
    trace=[]
    def run(sw,clsid,tlb,v,*,prepared,runtime_check):
        trace.append('read');assert set(v)==c.KEYS and prepared['consumed']is False
        return dict(status='observed',mutation_attempted=False)
    monkeypatch.setattr(c,'run_read',run)
    def target(params):trace.append('target');return object(),dict(clsid=params.addin_clsid,addin_path=str(Path(env['v']['receipt_path']).parent/'addin.dll'))
    ns=dict(BaseModel=BaseModel,Field=Field,ConfigDict=ConfigDict,field_validator=field_validator,model_validator=model_validator,Optional=Optional,Literal=Literal,Enum=Enum,Path=Path,absolute_document_path=absolute_document_path,mcp=SimpleNamespace(tool=lambda **kw:lambda f:f),_runtime_identity=SimpleNamespace(assert_current=lambda:trace.append('runtime')),_selected_process_id=123,_cam_target=target,_run_locked=lambda op,fmt:op())
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(server),'exec'),ns)
    params=dict(env['v'],addin_clsid='{11111111-2222-3333-4444-555555555555}',response_format='json')
    return ns,params,trace


def test_actual_mcp_schema_and_dispatch_are_fixed_readonly(mcp_env):
    ns,v,trace=mcp_env
    model=ns['SolidWorksCamRecoveredPocketReadQualificationInput'].model_validate(v)
    r=ns['solidworks_cam_qualify_recovered_pocket_read'](model)
    assert r==dict(status='observed',mutation_attempted=False)
    assert trace==['runtime','target','read','runtime']

@pytest.mark.parametrize('key,value',[('process_id',True),('expected_operation_native_ids',[31,True]),('expected_operation_native_ids',[31,31]),('expected_document_title','part'),('receipt_path','relative.json'),('expected_source_sha256','wrong'),('recovered_receipt_sha256','wrong'),('Save_attempted',True)])
def test_invalid_mcp_input_never_resolves_target(mcp_env,key,value):
    ns,v,trace=mcp_env;v[key]=value
    with pytest.raises(ValueError):ns['SolidWorksCamRecoveredPocketReadQualificationInput'].model_validate(v)
    assert not trace


def test_wrong_selected_process_stops_before_file_preparation(mcp_env,monkeypatch):
    ns,v,trace=mcp_env;ns['_selected_process_id']=124
    model=ns['SolidWorksCamRecoveredPocketReadQualificationInput'].model_validate(v)
    monkeypatch.setattr(c,'prepare',lambda v:(_ for _ in()).throw(AssertionError('must not prepare')))
    with pytest.raises(ValueError,match='process'):ns['solidworks_cam_qualify_recovered_pocket_read'](model)
    assert trace==['runtime']


@pytest.mark.parametrize('observations',[{}, {32:[17]}, {31:[18]}, {31:[True]}])
def test_wrong_generated_mapping_rejected_before_connection(env,observations):
    env['bundle']['protected_generated']=observations
    with pytest.raises(ValueError):env['run']()
    assert env['control']['native_calls']==[]and not Path(env['v']['receipt_path']).exists()


def test_mcp_outer_runtime_failure_calls_exact_revoke(mcp_env,monkeypatch):
    from types import SimpleNamespace
    ns,v,trace=mcp_env
    def current():
        trace.append('runtime')
        if trace.count('runtime')==2:raise ValueError('outer runtime changed')
    ns['_runtime_identity']=SimpleNamespace(assert_current=current)
    def revoke(result,error):
        assert result==dict(status='observed',mutation_attempted=False)and str(error)=='outer runtime changed'
        trace.append('revoke');return dict(result,status='error',runtime_error=str(error))
    monkeypatch.setattr(c,'revoke',revoke)
    result=ns['solidworks_cam_qualify_recovered_pocket_read'](ns['SolidWorksCamRecoveredPocketReadQualificationInput'].model_validate(v))
    assert result['status']=='error'and trace==['runtime','target','read','runtime','revoke']


def test_revoke_durably_clears_all_acceptance_flags(env):
    import json
    result=env['run']();assert all(result[k]is True for k in c.FLAGS)
    c.revoke(result,ValueError('late outer runtime change'))
    actual=json.loads(Path(env['v']['receipt_path']).read_text(encoding='utf-8'))
    assert actual['status']=='error'and all(actual[k]is False for k in c.FLAGS)
    assert actual['runtime_error']['type']=='ValueError'and actual['mutation_attempted']is False
