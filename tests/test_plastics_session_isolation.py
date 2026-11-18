"""空会话 Plastics 卸载的离线拒绝边界；不启动或调用真实 CAD。"""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'mcp-server'))
import server
from scripts import sw_plastics_session_isolation as core


@pytest.fixture
def c(tmp_path, monkeypatch):
    dll=tmp_path/'SimpoeWorks.dll';dll.write_bytes(b'registered plastics')
    sub=tmp_path/'SimpoeMV';sub.mkdir();module=sub/'SimpoeMoldWorks.DLL';module.write_bytes(b'plastics model')
    markers=tmp_path/'markers';markers.mkdir();monkeypatch.setattr(core,'local_evidence_root',lambda:markers)
    owner=dict(process_id=731,create_time=1000.125,executable='C:/SW/SLDWORKS.exe',alive=True)
    monkeypatch.setattr(core,'_process_identity',lambda pid:copy.deepcopy(owner))
    launch=tmp_path/'launch.json';launch.write_text(json.dumps(dict(status='ok',phase='connected',launch_mode='executable',
        new_process_verified=True,process_id=731,known_process_ids_before=[992],process_identity=owner)))
    state=dict(modules=[str(dll),str(module)],startup={'startup':{'exists':True,'values':[{'value':1}]}},post_check=None)
    reg=dict(clsid=core.CLSID,year=2026,addin_path=str(dll),crash_module_path=str(module),progid='SimpoePlastics.SimpoePlastics.34',registration={'title':'SOLIDWORKS Plastics'})
    def registration(year):return copy.deepcopy(reg)|dict(addin_sha256=core.file_sha(dll),crash_module_sha256=core.file_sha(module))
    monkeypatch.setattr(core,'inspect_registration',registration)
    monkeypatch.setattr(core,'startup_registry',lambda year:copy.deepcopy(state['startup']))
    def modules(pid):
        if state['post_check']:state['post_check']()
        return list(state['modules'])
    monkeypatch.setattr(core,'process_modules',modules)
    sw=SimpleNamespace(ActiveDoc=None,RevisionNumber='34.4.1.1011',GetProcessID=Mock(return_value=731),GetDocuments=Mock(return_value=None))
    def unload(path):state['modules']=[];return 0
    sw.UnloadAddIn=Mock(side_effect=unload)
    args=dict(process_id=731,expected_process_create_time=1000.125,expected_no_documents=True,year=2026,
        addin_path=str(dll),expected_addin_sha256=core.file_sha(dll),crash_module_path=str(module),expected_crash_module_sha256=core.file_sha(module),
        startup_receipt_path=str(launch),startup_receipt_sha256=core.file_sha(launch))
    prep=tmp_path/'prepare.json';out=tmp_path/'apply.json'
    def prepare(**changes):return core.unload_plastics(sw,action='prepare',receipt_path=str(prep),**(args|changes))
    def apply(**changes):return core.unload_plastics(sw,action='apply',receipt_path=str(out),prepare_receipt_path=str(prep),prepare_receipt_sha256=core.file_sha(prep),**(args|changes))
    return SimpleNamespace(**locals())


def test_prepare_reads_without_unload(c):
    r=c.prepare();assert r['status']=='prepared' and r['apply_eligible'] is True
    assert r['unload_calls']==0;c.sw.UnloadAddIn.assert_not_called()
    assert not list(c.markers.iterdir())


def test_success_durable_claim_and_native_return(c):
    c.prepare()
    def unload(path):
        before=json.loads(c.out.read_text());assert before['unload_attempted'] and before['native_dispatch_pending']
        assert len(list(c.markers.iterdir()))==1 and path==str(c.dll)
        c.state['modules']=[];return 0
    c.sw.UnloadAddIn.side_effect=unload
    r=c.apply();assert r['status']=='ok' and r['unloaded_verified'] and r['startup_registry_unchanged']
    assert r['after']['mapped_target_modules']==[] and r['getter_used'] is False
    c.sw.UnloadAddIn.assert_called_once_with(str(c.dll))


def test_new_receipt_cannot_repeat_unload(c):
    c.prepare();c.apply();c.out=c.tmp_path/'not_used.json'
    with pytest.raises(ValueError,match='already claimed'):
        core.unload_plastics(c.sw,action='apply',receipt_path=str(c.tmp_path/'new.json'),prepare_receipt_path=str(c.prep),prepare_receipt_sha256=core.file_sha(c.prep),**c.args)
    with pytest.raises(ValueError,match='already claimed'):
        core.unload_plastics(c.sw,action='prepare',receipt_path=str(c.tmp_path/'new_prepare.json'),**c.args)
    assert c.sw.UnloadAddIn.call_count==1


@pytest.mark.parametrize('kind',['pid','lifetime','hidden','active','year','dll','crash_dll','registration','same_name_elsewhere'])
def test_prepare_mismatch_never_unloads(c,kind):
    if kind=='pid':c.sw.GetProcessID.return_value=732
    if kind=='lifetime':c.owner['create_time']+=1
    if kind=='hidden':c.sw.GetDocuments.return_value=[object()]
    if kind=='active':c.sw.ActiveDoc=object()
    if kind=='year':c.sw.RevisionNumber='33.1.0'
    if kind=='dll':c.dll.write_bytes(b'changed')
    if kind=='crash_dll':c.module.write_bytes(b'changed')
    if kind=='registration':c.reg['addin_path']=str(c.tmp_path/'other.dll')
    if kind=='same_name_elsewhere':c.state['modules']=[str(c.tmp_path/'elsewhere'/'SimpoeWorks.dll')]
    r=c.prepare();assert r['status']=='error' and not r['may_continue'];c.sw.UnloadAddIn.assert_not_called()


def test_already_unmapped_prepare_is_observation_only(c):
    c.state['modules']=[];r=c.prepare()
    assert r['already_unmapped'] and r['module_absence_verified'] and r['may_continue'] and not r['apply_eligible']
    assert r['unloaded_verified'] is False;c.sw.UnloadAddIn.assert_not_called()


def test_orphan_crash_module_is_not_already_unmapped(c):
    c.state['modules']=[str(c.module)];r=c.prepare();assert r['status']=='error';c.sw.UnloadAddIn.assert_not_called()


def test_stale_prepare_state_blocks_apply(c):
    c.prepare();c.state['startup']['startup']['values'][0]['value']=0
    r=c.apply();assert r['status']=='error';c.sw.UnloadAddIn.assert_not_called()


@pytest.mark.parametrize('returned',[-1,False,None,'0'])
def test_nonzero_or_wrong_return_type_is_uncertain(c,returned):
    c.prepare()
    def unload(path):c.state['modules']=[];return returned
    c.sw.UnloadAddIn.side_effect=unload;r=c.apply()
    assert r['status']=='uncertain' and not r['may_continue'] and not r['unloaded_verified']


def test_zero_with_module_still_mapped_is_uncertain(c):
    c.prepare();c.sw.UnloadAddIn.side_effect=lambda path:0;r=c.apply()
    assert r['status']=='uncertain' and not r['unloaded_verified'] and r['unload_result']==0


def test_exception_after_dispatch_keeps_claim(c):
    c.prepare();c.sw.UnloadAddIn.side_effect=RuntimeError('native failed');r=c.apply()
    assert r['status']=='uncertain' and r['native_dispatch_pending'] and not r['may_continue']
    assert len(list(c.markers.iterdir()))==1


def test_return_is_durable_before_readback_failure(c):
    c.prepare()
    def failed_readback():
        saved=json.loads(c.out.read_text());assert saved['phase']=='UnloadAddIn_returned'
        assert saved['unload_result']==0 and not saved['native_dispatch_pending'];raise RuntimeError('readback failed')
    def unload(path):c.state['post_check']=failed_readback;return 0
    c.sw.UnloadAddIn.side_effect=unload;r=c.apply()
    assert r['status']=='uncertain' and r['unload_result']==0 and not r['unloaded_verified']


def test_registry_drift_after_unload_is_not_repaired(c):
    c.prepare()
    def unload(path):c.state['startup']['startup']['values'][0]['value']=0;c.state['modules']=[];return 0
    c.sw.UnloadAddIn.side_effect=unload;r=c.apply()
    assert r['startup_registry_unchanged'] is False and r['status']=='uncertain'
    assert c.state['startup']['startup']['values'][0]['value']==0


def test_receipt_failure_before_native_call_stops(c,monkeypatch):
    c.prepare();original=core._write_receipt
    def write(path,value,**kwargs):
        if value.get('phase')=='UnloadAddIn':raise OSError('disk failure')
        return original(path,value,**kwargs)
    monkeypatch.setattr(core,'_write_receipt',write);r=c.apply();assert not r['may_continue'];c.sw.UnloadAddIn.assert_not_called()


def test_owned_launch_receipt_is_required(c):
    d=json.loads(c.launch.read_text());d['new_process_verified']=False;c.launch.write_text(json.dumps(d))
    with pytest.raises(ValueError):c.prepare(startup_receipt_sha256=core.file_sha(c.launch))
    c.sw.UnloadAddIn.assert_not_called()


@pytest.mark.parametrize('field,value',[('process_id',True),('expected_no_documents',False),('expected_no_documents',1),('expected_process_create_time',float('nan')),('year',True)])
def test_schema_rejects_weak_scope(c,field,value):
    with pytest.raises(ValueError):server.SolidWorksPlasticsUnloadInput(action='prepare',receipt_path=str(c.prep),**(c.args|{field:value}))


def test_wrapper_exact_pid_and_action(c,monkeypatch):
    monkeypatch.setattr(server,'_run_locked',lambda fn,*a,**kw:fn())
    monkeypatch.setattr(server,'_selected_process_id',731)
    connection=Mock(return_value=(c.sw,None));monkeypatch.setattr(server,'connect_solidworks',connection)
    target=Mock(return_value={'status':'prepared'});monkeypatch.setattr(core,'unload_plastics',target)
    p=server.SolidWorksPlasticsUnloadInput(action='prepare',receipt_path=str(c.prep),**c.args)
    assert server.solidworks_unload_plastics_addin(p)=={'status':'prepared'}
    connection.assert_called_once_with(wait_seconds=1,process_id=731)
    assert target.call_args.args==(c.sw,) and target.call_args.kwargs['action']=='prepare'
    monkeypatch.setattr(server,'_selected_process_id',732)
    with pytest.raises(ValueError):server.solidworks_unload_plastics_addin(p)
    assert target.call_count==1


def test_no_getter_loader_registry_write_or_generic_unload_in_source():
    source=Path(core.__file__).read_text(encoding='utf8')
    for forbidden in ('GetAddInObject','LoadAddIn', 'SetValue', 'DeleteKey', 'CreateKey'):
        assert forbidden not in source
    assert "'UnloadAddIn', str(Path(addin_path))" in source

@pytest.mark.parametrize('name',['addin_path','crash_module_path'])
def test_core_rejects_relative_dll_paths(c,name):
    with pytest.raises(ValueError,match='absolute'):
        c.prepare(**{name:'relative.dll'})
    c.sw.UnloadAddIn.assert_not_called()


def test_installation_wrapper_is_read_only_without_automation(c,monkeypatch):
    seen=[]
    def locked(fn,*args,**kwargs):seen.append(kwargs);return fn()
    monkeypatch.setattr(server,'_run_locked',locked)
    target=Mock(return_value={'year':2026});monkeypatch.setattr(core,'inspect_registration',target)
    assert server.solidworks_plastics_installation(server.SolidWorksPlasticsRegistrationInput(year=2026))=={'status':'ok','year':2026}
    assert seen==[{'load_automation':False}];target.assert_called_once_with(2026)


def test_schema_apply_requires_prepare_pin(c):
    with pytest.raises(ValueError):server.SolidWorksPlasticsUnloadInput(action='apply',receipt_path=str(c.out),**c.args)


def test_same_named_crash_module_elsewhere_is_blocked(c):
    c.state['modules'] += [str(c.tmp_path/'old'/'SimpoeMoldWorks.DLL')]
    r=c.prepare();assert r['status']=='error';c.sw.UnloadAddIn.assert_not_called()


@pytest.fixture
def late(c):
    launch=json.loads(c.launch.read_text())
    launch.update(status='uncertain',phase='waiting_for_exact_pid_rot',launch_attempted=True)
    c.launch.write_text(json.dumps(launch));c.args['startup_receipt_sha256']=core.file_sha(c.launch)
    c.sw.UserControl=True
    connection=dict(status='ok',process_id=731,session_target=dict(process_id=731,scope='mcp_server',strict=True),active_document=None)
    inventory=dict(status='ok',process_id=731,active_document=None,documents=[],document_count=0,user_control=True,mutation_attempted=False)
    path=c.tmp_path/'late_attach.json'
    def write():
        rows=[]
        for i,(name,value) in enumerate(zip(('solidworks_connect','solidworks_inspect_open_documents'),(connection,inventory))):
            rows.append(dict(index=i,name=name,outcome=dict(status='success',may_continue=True),
                result=dict(isError=False,content=[dict(type='text',text=json.dumps(value),parsed_json=value)],structuredContent=dict(result=json.dumps(value)))))
        path.write_text(json.dumps(dict(status='success',request_count=2,results=rows)))
        c.args.update(late_attach_receipt_path=str(path),late_attach_receipt_sha256=core.file_sha(path))
    write()
    return SimpleNamespace(c=c,path=path,connection=connection,inventory=inventory,write=write)


def test_late_attach_independent_evidence_qualifies_without_rewriting_startup(late):
    c=late.c;original=c.launch.read_bytes()
    r=c.prepare();assert r['status']=='prepared' and r['config']['startup_qualification']=='separate_late_attach'
    assert c.sw.UnloadAddIn.call_count==0
    r=c.apply();assert r['status']=='ok' and r['unloaded_verified']
    assert c.launch.read_bytes()==original and json.loads(original)['status']=='uncertain'


@pytest.mark.parametrize('fault',['not_fixed','other_pid','open_documents','active','user_control','mutating_inventory','count'])
def test_late_attach_unqualified_history_never_unloads(late,fault):
    if fault=='not_fixed':late.connection['session_target']['strict']=False
    if fault=='other_pid':late.inventory['process_id']=999
    if fault=='open_documents':late.inventory['documents']=[{'path':'part.sldprt'}]
    if fault=='active':late.connection['active_document']='part.sldprt'
    if fault=='user_control':late.inventory['user_control']=False
    if fault=='mutating_inventory':late.inventory['mutation_attempted']=True
    if fault=='count':late.inventory['document_count']=True
    late.write()
    with pytest.raises(ValueError):late.c.prepare()
    late.c.sw.UnloadAddIn.assert_not_called()


def test_uncertain_startup_without_late_attach_is_rejected(late):
    c=late.c;c.args.pop('late_attach_receipt_path');c.args.pop('late_attach_receipt_sha256')
    with pytest.raises(ValueError,match='separately pinned'):c.prepare()
    c.sw.UnloadAddIn.assert_not_called()


def test_late_attach_does_not_qualify_other_failed_startup_phase(late):
    c=late.c;d=json.loads(c.launch.read_text());d['phase']='process_created';c.launch.write_text(json.dumps(d))
    c.args['startup_receipt_sha256']=core.file_sha(c.launch)
    with pytest.raises(ValueError,match='waiting for ROT'):c.prepare()
    c.sw.UnloadAddIn.assert_not_called()


def test_late_attach_does_not_qualify_reused_process(late):
    c=late.c;c.owner['create_time']+=1
    r=c.prepare();assert r['status']=='error';c.sw.UnloadAddIn.assert_not_called()


def test_late_attach_current_user_control_is_rechecked(late):
    c=late.c;c.sw.UserControl=False
    r=c.prepare();assert r['status']=='error';c.sw.UnloadAddIn.assert_not_called()


def test_late_attach_change_after_prepare_blocks_apply(late):
    c=late.c;c.prepare();late.path.write_text('{}')
    with pytest.raises(ValueError,match='hash'):c.apply()
    c.sw.UnloadAddIn.assert_not_called()


def test_late_attach_contradictory_result_copies_are_rejected(late):
    c=late.c;d=json.loads(late.path.read_text());d['results'][0]['result']['content'][0]['parsed_json']['process_id']=732
    late.path.write_text(json.dumps(d));c.args['late_attach_receipt_sha256']=core.file_sha(late.path)
    with pytest.raises(ValueError,match='Contradictory'):c.prepare()
    c.sw.UnloadAddIn.assert_not_called()


@pytest.mark.parametrize('missing',['late_attach_receipt_path','late_attach_receipt_sha256'])
def test_schema_requires_late_attach_pin_pair(late,missing):
    c=late.c;args=c.args.copy();args.pop(missing)
    with pytest.raises(ValueError,match='together'):
        server.SolidWorksPlasticsUnloadInput(action='prepare',receipt_path=str(c.prep),**args)


def test_schema_late_attach_requires_absolute_path(late):
    c=late.c;args=c.args|dict(late_attach_receipt_path='relative.json')
    with pytest.raises(ValueError,match='absolute'):
        server.SolidWorksPlasticsUnloadInput(action='prepare',receipt_path=str(c.prep),**args)
