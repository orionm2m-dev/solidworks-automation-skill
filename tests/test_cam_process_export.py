from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ast, hashlib, json, math
import pytest
from scripts import sw_cam_process_export as m
from scripts import sw_cam_dispatch_guard as gd


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def env(tmp_path, monkeypatch):
    source = tmp_path/'source.sldprt'; source.write_bytes(b'unchanged model and saved CAM')
    registry = tmp_path/'attempts'; registry.mkdir()
    p = dict(process_id=123, expected_process_create_time=42.5,
        expected_document_path=str(source), expected_source_sha256=sha(source),
        expected_feature_native_id=10, expected_feature_setup_native_id=20,
        expected_operation_setup_native_id=30, expected_operation_native_ids=[40,41],
        expected_generated_operation_count=1, expected_total_record_count=7,
        output_path=str(tmp_path/'new_export'/'saved.prtcam'),
        receipt_path=str(tmp_path/'receipt.json'), attempt_registry_path=str(registry),
        provenance_pins=[], qualification_only=True, message_policy='vendor_default')
    e = dict(p=p, source=source, calls=[], current=dict(path=str(source), title=source.name,
        type=1, needs_save=False), mode='success', guard=None, runtime_calls=0)
    e['state'] = dict(capture_complete=True, features=[dict(native_id=10)],
        operations=[dict(native_id=40, generated=True, records=[7]),
                    dict(native_id=41, generated=False, records=[])])
    sw = SimpleNamespace(GetProcessID=lambda:123)
    e['sw'] = sw
    monkeypatch.setattr(gd, '_member', lambda obj,name,*args:getattr(obj,name)(*args))
    monkeypatch.setattr(gd, 'raw_part_identity', lambda sw:deepcopy(e['current']))
    monkeypatch.setattr(gd, '_typed', lambda raw,name,tlb:raw)
    def member(target,name,path):
        assert name == 'ExportCAMData'
        r = json.loads(Path(p['receipt_path']).read_text(encoding='utf-8'))
        assert r['native_call_attempted'] and r['native_dispatch_pending']
        assert list(registry.glob('process_export_*.json'))
        e['calls'].append(name)
        if e['mode'] == 'native_error':raise RuntimeError('native output uncertain')
        if e['mode'] != 'missing_output':Path(path).write_bytes(b'opaque native prtcam archive')
        if e['mode'] == 'extra_output':Path(path).with_name('extra.bin').write_bytes(b'extra')
        if e['mode'] == 'empty_output':Path(path).write_bytes(b'')
        if e['mode'] == 'source_changed':source.write_bytes(b'changed')
        if e['mode'] == 'state_changed':e['state']['operations'][1]['records']=[999]
        if e['mode'] == 'event_after':e['event']=True
        if e['mode'] == 'bool_return':return True
        if e['mode'] == 'false_return':return False
        if e['mode'] == 'nonzero_return':return 1
        return 0
    monkeypatch.setattr(m, '_member', member)
    class Fake(m.CurrentExportContext):
        def start(self):
            self.app=object();self.initial=deepcopy(e['current']);self.check()
        def identity(self):
            assert sha(source)==p['expected_source_sha256'], 'source changed'
            return deepcopy(e['current'])
        def check(self):
            if e.get('event'):raise ValueError('CAM event requires stop')
        def capture(self,label):
            self.boundary()
            s=deepcopy(e['state']);s['document']=deepcopy(e['current'])
            self.report[label]=s;self.persist();return s
        def guard(self):
            g=super().guard();e['guard']=g
            if e['mode']=='drift_after_pending':
                original=g.dispatch_once
                def dispatch(invoke,*,persist_pending):
                    def pending():
                        persist_pending();source.write_bytes(b'drift before native call')
                    return original(invoke,persist_pending=pending)
                g.dispatch_once=dispatch
            return g
        def close(self):
            e['closed']=True
            if e['mode']=='cleanup_error':raise RuntimeError('event disconnect failed')
            self.identity()
    e['factory']=Fake
    def runtime():
        e['runtime_calls']+=1
        if e['mode']=='final_runtime_drift' and e['runtime_calls']>=2:
            raise RuntimeError('runtime changed')
    e['runtime']=runtime
    return e


def run(e):
    return m.run_export(e['sw'],'clsid','tlb',runtime_check=e['runtime'],
        _context_factory=e['factory'],_preflight=lambda tlb:dict(method='ExportCAMData',dispid=59),**e['p'])


def test_export_uses_real_guard_callback_contract_and_preserves_model(env):
    r=run(env)
    assert r['status']=='review_required' and r['export_verified'] and r['readback_verified']
    assert r['source_unchanged'] and r['runtime_unchanged'] and r['before']==r['after']
    assert env['calls']==['ExportCAMData'] and env['closed']
    assert env['guard'].summary()['native_call_attempted']
    assert env['guard'].summary()['native_call_returned']
    assert env['guard'].summary()['complete_boundary_checks']>=3
    assert r['output']['sha256']==sha(env['p']['output_path'])
    for k in ('model_saved','mutation_attempted','GTP_attempted','GOP_attempted','AFR_attempted',
              'import_attempted','rebuild_attempted','TechDB_setter_attempted','stock_included',
              'archive_contents_verified','archive_restore_verified','CAM_migration_verified','production_qualified'):
        assert r[k] is False


@pytest.mark.parametrize('mode',['native_error','missing_output','empty_output','extra_output',
    'source_changed','state_changed','event_after','bool_return','false_return','nonzero_return',
    'cleanup_error','final_runtime_drift'])
def test_post_attempt_failures_are_uncertain_and_never_replayed(env,mode):
    env['mode']=mode;r=run(env)
    assert r['status']=='uncertain' and not r['export_verified'] and not r['readback_verified']
    assert env['calls']==['ExportCAMData'] and env['closed']
    assert len(list(Path(env['p']['attempt_registry_path']).glob('*.json')))==1
    assert not r['automatic_replay']


def test_actual_guard_rechecks_source_after_pending_before_export(env):
    env['mode']='drift_after_pending';r=run(env)
    assert r['dispatch_claimed'] and not r['native_call_attempted']
    assert r['status']=='uncertain' and env['calls']==[]
    assert env['guard'].summary()['native_call_attempted'] is False


def test_fresh_output_name_cannot_bypass_prior_source_attempt(env):
    assert run(env)['export_verified']
    env['p']['receipt_path']=str(env['source'].parent/'another.json')
    env['p']['output_path']=str(env['source'].parent/'another_dir'/'again.prtcam')
    with pytest.raises(ValueError,match='Prior process export attempt'):run(env)
    assert env['calls']==['ExportCAMData']


def test_preexport_event_stops_without_claim_or_native_call(env):
    env['event']=True;r=run(env)
    assert r['status']=='error' and not r['dispatch_claimed'] and env['calls']==[]
    assert not list(Path(env['p']['attempt_registry_path']).glob('*.json'))


@pytest.mark.parametrize('field,value',[
    ('process_id',True),('expected_process_create_time',float('nan')),
    ('expected_operation_native_ids',[40,40]),('expected_total_record_count',100001),
    ('qualification_only',False),('message_policy','accept_all')])
def test_invalid_scope_rejected_before_context(env,field,value):
    env['p'][field]=value
    with pytest.raises(ValueError):run(env)
    assert env['calls']==[] and not Path(env['p']['receipt_path']).exists()


def test_stale_source_rejected_before_context(env):
    env['source'].write_bytes(b'changed')
    with pytest.raises(ValueError,match='saved source'):run(env)
    assert env['calls']==[]


def test_provenance_is_pinned_without_reinterpreting_old_history(env):
    history=env['source'].parent/'previous.json';raw=b'{"historical_source":"older", "status":"review_required"}';history.write_bytes(raw)
    env['p']['provenance_pins']=[dict(path=str(history),sha256=sha(history))]
    r=run(env)
    assert r['export_verified'] and r['provenance_is_history_only']
    assert history.read_bytes()==raw


def test_changed_provenance_rejected(env):
    history=env['source'].parent/'previous.json';history.write_text('{}')
    env['p']['provenance_pins']=[dict(path=str(history),sha256=sha(history))]
    history.write_text('{"changed":true}')
    with pytest.raises(ValueError):run(env)
    assert env['calls']==[]


def test_output_requires_new_local_directory_and_prtcam(env):
    output=Path(env['p']['output_path']);output.parent.mkdir()
    with pytest.raises(ValueError,match='Fresh local'):run(env)
    assert env['calls']==[]


def test_return_is_durable_before_postread_failure(env):
    env['mode']='event_after';r=run(env)
    assert r['native_call_returned'] and r['native_return_type']=='int' and r['native_return_value']==0
    assert r['native_dispatch_pending'] is False
    assert json.loads(Path(env['p']['receipt_path']).read_text(encoding='utf-8'))['native_return_value']==0


def test_revoke_runtime_durably_withdraws_success(env):
    r=run(env);m.revoke_runtime(r,RuntimeError('changed after return'))
    saved=json.loads(Path(env['p']['receipt_path']).read_text(encoding='utf-8'))
    assert saved['status']=='uncertain' and saved['native_call_returned'] and not saved['export_verified']


def test_exact_export_abi_admission(monkeypatch):
    from ctypes import HRESULT
    from comtypes import BSTR
    method=SimpleNamespace(name='ExportCAMData',restype=HRESULT,idlflags=[59],argtypes=(BSTR,),paramflags=((1,'path'),))
    iface=SimpleNamespace(_iid_=m._INTERFACES['ICWApp4'],_methods_=[method])
    monkeypatch.setattr(m.current,'_abi',lambda tlb:None)
    monkeypatch.setattr(m,'_interface_class',lambda name,tlb:iface)
    assert m.preflight('tlb')['dispid']==59
    method.idlflags=[58]
    with pytest.raises(ValueError,match='DISP59'):m.preflight('tlb')


def test_no_mutation_api_allowed_by_export_module():
    tree=ast.parse(Path(m.__file__).read_text(encoding='utf-8-sig'))
    names=[x.value for x in ast.walk(tree) if isinstance(x,ast.Constant) and type(x.value) is str]
    for forbidden in ('ImportCAMData','RebuildActiveDocForCAMData2','GenerateToolpath','SaveActiveDocument','Save3','ExtractMachinableFeatures'):
        assert forbidden not in names


def test_current_capture_uses_existing_full_inventory_reader(env,monkeypatch):
    loaded=m.validate(env['p']);r=dict(native_read_count=0);ctx=m.CurrentExportContext(None,'clsid','tlb',env['p'],loaded,r,lambda:None,lambda:None)
    ctx.app=object();ctx.initial=env['current'];ctx.boundary=lambda:None
    def capture(app,tlb,read,typed,state,values,boundary):
        assert values['expected_operation_native_ids']==[40,41]
        assert values['expected_total_record_count']==7
        assert values['observation']=='three_step_profile'
        assert values['parameters_authority_receipt_path'] is None
        state.update(capture_complete=True,operations=deepcopy(env['state']['operations']))
        return dict(doc=object())
    monkeypatch.setattr(m.current,'_capture',capture)
    assert ctx.capture('before')['capture_complete'] and r['before']['document']==env['current']


def test_native_identity_rejects_wrong_process_lifetime(env,monkeypatch):
    loaded=m.validate(env['p']);ctx=m.CurrentExportContext(None,'clsid','tlb',env['p'],loaded,{},lambda:None,lambda:None)
    monkeypatch.setattr(m,'_process_identity',lambda pid:dict(alive=True,process_id=123,create_time=43.5,executable='C:/SLDWORKS.exe'))
    with pytest.raises(ValueError,match='lifetime'):ctx.identity()


def schema_namespace():
    import os
    from enum import Enum
    from typing import Optional, Literal, Annotated
    from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
    from scripts.sw_operation_guard import absolute_document_path
    runtime_root = Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', Path.home()/'.codex/skills/solidworks-automation'))
    source = Path(os.environ.get('CAM_PROCESS_EXPORT_SERVER_PATH', runtime_root/'mcp-server/server.py'))
    wanted = {'ResponseFormat', 'BaseInput', 'ActiveDocumentInput', 'SolidWorksCamTargetInput',
              'SolidWorksCamProcessExportInput', 'solidworks_cam_export_process_data'}
    nodes = [node for node in ast.parse(source.read_text(encoding='utf-8-sig')).body
             if getattr(node, 'name', '') in wanted]
    assert {node.name for node in nodes} == wanted
    for node in nodes:
        if isinstance(node, ast.FunctionDef): node.decorator_list = []
    ns = dict(Enum=Enum, Optional=Optional, Literal=Literal, Annotated=Annotated,
              BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field,
              field_validator=field_validator, model_validator=model_validator,
              Path=Path, absolute_document_path=absolute_document_path)
    exec(compile(ast.Module(body=nodes,type_ignores=[]), str(source), 'exec'), ns)
    return ns


@pytest.mark.parametrize('ids',[[40,'41'],[40,True],[40,40]])
def test_new_schema_rejects_coerced_or_duplicate_ids(env,ids):
    ns=schema_namespace();v=dict(env['p'],addin_clsid='{00000000-0000-0000-0000-000000000001}',expected_operation_native_ids=ids)
    with pytest.raises(ValueError):ns['SolidWorksCamProcessExportInput'](**v)


def test_new_wrapper_checks_selected_pid_before_target(env,monkeypatch):
    ns=schema_namespace();params=ns['SolidWorksCamProcessExportInput'](**env['p'],addin_clsid='{00000000-0000-0000-0000-000000000001}')
    calls=[];ns.update(_selected_process_id=999,_runtime_identity=SimpleNamespace(assert_current=lambda:calls.append('runtime')),
        _run_locked=lambda fn,fmt:fn(),_cam_target=lambda p:calls.append('target'))
    with pytest.raises(ValueError,match='connected process'):ns['solidworks_cam_export_process_data'](params)
    assert calls==['runtime']


def test_new_wrapper_passes_current_scope_without_history_loader(env,monkeypatch):
    ns=schema_namespace();params=ns['SolidWorksCamProcessExportInput'](**env['p'],addin_clsid='{00000000-0000-0000-0000-000000000001}')
    ns.update(_selected_process_id=123,_runtime_identity=SimpleNamespace(assert_current=lambda:None),
        _run_locked=lambda fn,fmt:fn(),_cam_target=lambda p:('sw',dict(clsid='clsid',addin_path='C:/CAM/cam.dll')))
    got={}
    def exported(sw,clsid,tlb,**values):
        got.update(values);return dict(status='review_required')
    monkeypatch.setattr(m,'run_export',exported)
    assert ns['solidworks_cam_export_process_data'](params)['status']=='review_required'
    assert got['expected_generated_operation_count']==1 and got['provenance_pins']==[]
    assert 'configuration_receipt_path' not in got and callable(got['runtime_check'])


def test_context_factory_failure_finishes_own_receipt(env):
    def broken(*args):raise RuntimeError('context construction failed')
    r=m.run_export(env['sw'],'clsid','tlb',runtime_check=lambda:None,
        _context_factory=broken,_preflight=lambda tlb:{},**env['p'])
    assert r['status']=='error' and r['phase']=='finished' and env['calls']==[]


def test_guard_is_closed_in_success_and_failure_receipts(env):
    r=run(env)
    assert r['dispatch_guard']['active'] is False
    assert r['dispatch_guard']['native_call_returned'] is True
