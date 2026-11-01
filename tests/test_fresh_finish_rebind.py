from copy import deepcopy
from pathlib import Path
import json
import pytest
from scripts import sw_cam_fresh_finish_rebind as r


@pytest.fixture
def context():
    state=json.loads((Path(__file__).parent/'fixtures/guide_group_R122.json').read_text(encoding='utf-8'))
    c={k:None for k in r.group.CURRENT_KEYS}
    c.update(state=state,ownership=dict(process_id=47168,create_time=100.0,executable='C:/SW/SLDWORKS.exe',alive=True))
    c['current_context_sha256']=r._digest(r.group.current_projection(c))
    return c


def startup():return dict(process_id=50000,create_time=200.0,executable='C:/SW/SLDWORKS.exe',alive=True)


def test_bind_preserves_old_evidence_and_only_provisional(context):
    before=deepcopy(context)
    out=r.bind_new_owner(context,startup(),previous_process_id=47168,process_id=50000)
    assert context==before
    assert out['ownership']==startup() and out['state']==context['state']
    assert out['current_context_sha256']!=context['current_context_sha256']
    assert out['rebind_provisional_read_context'] is True
    assert 'session_rebind_verified' not in out

@pytest.mark.parametrize('change',[{'process_id':47168},{'create_time':100.0},{'executable':'C:/other/SLDWORKS.exe'},{'alive':False}])
def test_bind_rejects_wrong_startup(context,change):
    with pytest.raises(ValueError):r.bind_new_owner(context,dict(startup(),**change),previous_process_id=47168,process_id=50000)

def test_bind_rejects_changed_historical_context(context):
    context['state']['operations'].reverse()
    with pytest.raises(ValueError):r.bind_new_owner(context,startup(),previous_process_id=47168,process_id=50000)


def params(tmp_path):
    return dict(process_id=50000,previous_process_id=47168,expected_document_path=str(tmp_path/'source.bin'),
        expected_source_sha256='a'*64,expected_configuration='Default',addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}',
        checkpoint_receipt_path=str(tmp_path/'checkpoint.json'),checkpoint_receipt_sha256='b'*64,
        owned_startup_receipt_path=str(tmp_path/'startup.json'),owned_startup_receipt_sha256='c'*64,
        module_sha256=r._file_hash(r.__file__),receipt_path=str(tmp_path/'new.json'),progress_path=str(tmp_path/'progress.json'))

@pytest.mark.parametrize('change',[{'previous_process_id':True},{'previous_process_id':50000},{'process_id':True},
    {'owned_startup_receipt_sha256':'short'},{'module_sha256':'a'*64},{'owned_startup_receipt_path':'relative'}])
def test_request_rejects_identity_errors(tmp_path,change):
    with pytest.raises(ValueError):r.validate_request(dict(action='rebind_fresh_finish_session',params=dict(params(tmp_path),**change)))


def observation(context,tmp_path):
    p=params(tmp_path);Path(p['expected_document_path']).write_bytes(b'offline-fixture-only')
    p['expected_source_sha256']=r._file_hash(p['expected_document_path'])
    c=deepcopy(context);c['state']['document']['path']=p['expected_document_path']
    expected=r.guide.expected(c)
    config=dict(cam_configuration_name='CAM1',configuration_object_name='CAM1',associated_sw_configuration_name='Default',
        sw_configuration_name='Default',names_consistent=True,associated_sw_configuration_matches=True)
    report=dict(scope=r.SCOPE,status='observed',phase='finished',readback_verified=True,group_baseline_read_complete=True,
        mutation_attempted=False,save_attempted=False,GTP_attempted=False,production_qualified=False,
        messages=dict(subscribed=True,active=False,disconnected=True,event_count=0),request=p,
        before=deepcopy(expected),after=deepcopy(expected),before_document=deepcopy(c['state']['document']),after_document=deepcopy(c['state']['document']),
        configuration_before=config,configuration_after=deepcopy(config))
    return report,c


def test_completed_read_passes_without_cam(context,tmp_path):
    report,c=observation(context,tmp_path);r.verify_readback(report,c)

@pytest.mark.parametrize('change',['read_error','unverified','event','count','reorder','tool','header','config','source','dirty','mutation'])
def test_failed_read_cannot_rebind(context,tmp_path,change):
    report,c=observation(context,tmp_path)
    if change=='read_error':report['issue']={'error':'failure'}
    elif change=='unverified':report['readback_verified']=False
    elif change=='event':report['messages']['event_count']=1
    elif change=='count':report['after']['operations'][-1]['toolpath_record_counts']=[1]
    elif change=='reorder':report['after']['operations'].reverse()
    elif change=='tool':report['after']['operations'][-1]['assigned_tool']['native_id']=999
    elif change=='header':report['after']['features']['82']['depth_native']=2.0
    elif change=='config':report['configuration_after']['sw_configuration_name']='Wrong'
    elif change=='source':Path(report['request']['expected_document_path']).write_bytes(b'changed fixture')
    elif change=='dirty':report['after_document']['needs_save']=True
    else:report['mutation_attempted']=True
    with pytest.raises(ValueError):r.verify_readback(report,c)


def test_guide_legacy_request_unchanged(tmp_path):
    p={k:v for k,v in params(tmp_path).items() if k in r.guide.PARAMS};p['module_sha256']=r._file_hash(r.guide.__file__)
    assert r.guide.validate_request(dict(action='read_shallow_guide_group',params=p))==p


def test_guide_accepts_only_complete_rebind_pair(tmp_path):
    p={k:v for k,v in params(tmp_path).items() if k in r.guide.PARAMS};p['module_sha256']=r._file_hash(r.guide.__file__)
    p['session_rebind_receipt_path']=str(tmp_path/'rebound.json')
    with pytest.raises(ValueError):r.guide.validate_request(dict(action='read_shallow_guide_group',params=p))
    p['session_rebind_receipt_sha256']='d'*64
    assert r.guide.validate_request(dict(action='read_shallow_guide_group',params=p))==p


def test_load_guide_uses_verified_association_not_raw_pid_override(monkeypatch,tmp_path):
    seen=[];wanted={'proof':'verified only'}
    monkeypatch.setattr(r,'load_verified_rebind',lambda path,sha,current:(seen.append((path,sha,current['process_id'])) or wanted))
    monkeypatch.setattr(r.guide,'prepare_loaded',lambda value:value)
    p=params(tmp_path);p.update(session_rebind_receipt_path=str(tmp_path/'rebound.json'),session_rebind_receipt_sha256='d'*64)
    assert r.guide.load_inputs(p)==wanted
    assert seen==[(p['session_rebind_receipt_path'],'d'*64,50000)]


def association(context,tmp_path):
    report,c=observation(context,tmp_path)
    c['ownership']=startup();c['current_context_sha256']=r._digest(r.group.current_projection(c))
    c.update(parent_pin=dict(path=report['request']['checkpoint_receipt_path'],sha256='b'*64),
        rebind_startup_pin=dict(path=report['request']['owned_startup_receipt_path'],sha256='c'*64),
        rebind_historical_context_sha256='f'*64,pins=[])
    report.update(session_rebind_verified=True,historical_receipt_modified=False,module_pin=r.common._pin(r.__file__),
        guide_module_pin=r.common._pin(r.guide.__file__),historical_checkpoint_pin=c['parent_pin'],startup_pin=c['rebind_startup_pin'],
        new_ownership=deepcopy(c['ownership']),historical_context_sha256=c['rebind_historical_context_sha256'],new_context_sha256=c['current_context_sha256'])
    return report,c


def test_verified_receipt_loader_keeps_old_and_new_linked(context,tmp_path,monkeypatch):
    report,c=association(context,tmp_path);pin=dict(path=str(tmp_path/'association.json'),sha256='e'*64)
    monkeypatch.setattr(r,'read_pin',lambda path,sha:(deepcopy(report),pin))
    monkeypatch.setattr(r,'load_inputs',lambda p:deepcopy(c))
    out=r.load_verified_rebind(pin['path'],pin['sha256'],report['request'])
    assert out['session_rebind_receipt_pin']==pin
    assert out['rebind_provisional_read_context'] is False
    assert out['parent_pin']==c['parent_pin'] and out['ownership']==startup()

@pytest.mark.parametrize('change',['verified_flag','module_pin','historical_pin','startup_pin','new_owner','new_digest','current_pid'])
def test_association_rejects_tampering(context,tmp_path,monkeypatch,change):
    report,c=association(context,tmp_path);current=deepcopy(report['request'])
    if change=='verified_flag':report['session_rebind_verified']=False
    elif change=='module_pin':report['module_pin']['sha256']='a'*64
    elif change=='historical_pin':report['historical_checkpoint_pin']=dict(c['parent_pin'],sha256='a'*64)
    elif change=='startup_pin':report['startup_pin']=dict(c['rebind_startup_pin'],sha256='a'*64)
    elif change=='new_owner':report['new_ownership']['process_id']=50001
    elif change=='new_digest':report['new_context_sha256']='a'*64
    else:current['process_id']=50001
    monkeypatch.setattr(r,'read_pin',lambda path,sha:(deepcopy(report),dict(path=path,sha256=sha)))
    monkeypatch.setattr(r,'load_inputs',lambda p:deepcopy(c))
    with pytest.raises(ValueError):r.load_verified_rebind(str(tmp_path/'association.json'),'e'*64,current)


def test_rebind_mcp_schema_and_selected_process_guard(tmp_path,monkeypatch):
    import ast
    from enum import Enum
    from pydantic import BaseModel,ConfigDict,Field,model_validator
    class Format(str,Enum):JSON='json'
    class FakeMcp:
        def tool(self,**kwargs):return lambda f:f
    env=dict(BaseInput=BaseModel,ConfigDict=ConfigDict,Field=Field,model_validator=model_validator,
        ResponseFormat=Format,mcp=FakeMcp(),_selected_process_id=50000,_run_locked=lambda op,*a,**k:op())
    server=Path(r.__file__).parents[1]/'mcp-server/server.py'
    wanted={'SolidWorksCamFreshFinishRebindInput','solidworks_cam_rebind_fresh_finish_session'}
    nodes=[node for node in ast.parse(server.read_text(encoding='utf-8-sig')).body if isinstance(node,(ast.ClassDef,ast.FunctionDef)) and node.name in wanted]
    assert len(nodes)==2
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(server),'exec'),env)
    model=env['SolidWorksCamFreshFinishRebindInput'];tool=env['solidworks_cam_rebind_fresh_finish_session']
    p=params(tmp_path);observed=[]
    monkeypatch.setattr(r,'dispatch_request',lambda value:observed.append(value) or {'status':'fake'})
    assert tool(model(**p))=={'status':'fake'}
    assert observed==[dict(action='rebind_fresh_finish_session',params=p)]
    env['_selected_process_id']=50001
    with pytest.raises(ValueError):tool(model(**p))
    with pytest.raises(ValueError):model(**dict(p,process_id=True))
    with pytest.raises(ValueError):model(**dict(p,unknown=True))
