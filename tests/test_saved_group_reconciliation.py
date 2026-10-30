"""保存后只读恢复的合成前缀及边界测试，不连接原生应用。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from test_checkpoint_exports import m, g, fixture


def make_failed_saved_prefix(f, count=760):
    """使用合成路线重现保存已返回、最终观察未结束的状态。"""
    current=g.current_projection(f.loaded)
    current['source_sha256']='a'*64
    current['state']['saved_file_sha256']='a'*64
    before=next(r for r in current['state']['operations'] if r['native_id']==267)
    before['toolpath_generated']=False;before['toolpath_record_counts']=[]
    before['assigned_tool']=dict(before['assigned_tool'],native_id=252,cut_diameter_native=12.0,protrusion_native=50.0)
    payload=dict(rough=deepcopy(current['payload']),finish=deepcopy(current['finish_payload']))
    def observation(state,configured):
        selected=next(r for r in state['operations'] if r['native_id']==267)
        return dict(state=deepcopy(state),payload=deepcopy(payload),settings=g.expected_settings(configured),
            binding=deepcopy(selected['assigned_tool']),units=deepcopy(f.loaded['finish_payload']['unit_record']),
            cone_observation=deepcopy(current['cone_observation']),face_observation=deepcopy(current['face_observation']))
    baseline=observation(current['state'],False)
    configured=deepcopy(current['state'])
    selected=next(r for r in configured['operations'] if r['native_id']==267)
    selected['assigned_tool']=deepcopy(next(r for r in configured['operations'] if r['native_id']==248)['assigned_tool'])
    configured_observation=observation(configured,True)
    selected['toolpath_generated']=True;selected['toolpath_record_counts']=[count]
    generated=observation(configured,True)
    final_state=deepcopy(configured);final_state['saved_file_sha256']=f.args['expected_source_sha256']
    final=dict(phase='final',capture_complete=True,state=final_state,payload=deepcopy(payload),cone=deepcopy(current['cone_observation']))
    actions={}
    properties={name for name,kind,*_ in g.CHANGES if kind=='property'}
    for name in ['SetTool']+[row[0] for row in g.CHANGES]+['GenerateToolpath','SaveActiveDocument']:
        actions[name]=dict(status='returned' if name=='SaveActiveDocument' else 'verified',
            attempted=True,returned=True,native_dispatch_pending=False,readback_verified=name!='SaveActiveDocument',
            native_return=g.return_observation(None if name in properties else 0))
    data=dict(scope=g.SCOPE,status='error',phase='SaveActiveDocument',current_action='SaveActiveDocument',
        process_id=f.args['process_id'],source_path=f.args['expected_document_path'],source_sha256='a'*64,
        receipt_path=str(f.root/'failed_group.json'),recipe_sha256='c'*64,module_pin=g._self_pin(),
        current_before=current,current_before_sha256=m._digest(current),actions=actions,
        baseline=baseline,configured=configured_observation,generated=generated,before_save=deepcopy(generated),
        automatic_count_observation=dict(before=1,after=1,physical_pass_count_verified=False),
        source_transition=dict(source_before_sha256='a'*64,source_after_sha256=f.args['expected_source_sha256'],
            strict_save_return=0,document=deepcopy(final_state['document'])),
        save_stage=dict(phase='after_capture',native_call_returned=True,save_pending=False,save_attempted=True,
            mutation_attempted=True,native_call_attempted=True,native_return_type='int',native_return_value=0,
            saved_file_sha256=f.args['expected_source_sha256'],before=g.NativeBackend.save_projection(None,generated)),
        full_diagnostics=[dict(phase='baseline',state=deepcopy(current['state'])),final],full_capture_count=1,
        messages=dict(subscribed=True,active=True,event_count=0,overflow=False,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[]),
        model_saved=False,readback_verified=False,native_dispatch_pending=False,mutation_attempted=True,
        native_call_attempted=True,native_call_returned=True,automatic_retry=False,automatic_replay=False,
        automatic_rollback=False,physical_geometry_verified=False,cutting_conditions_qualified=False,production_qualified=False)
    marker=g.GroupJournal(data,data['receipt_path'],g.group_marker(f.args['expected_document_path'],'a'*64))._marker_state()
    return data,marker,final_state


@pytest.fixture
def failed_prefix(fixture,monkeypatch):
    f=fixture
    data,marker,final=make_failed_saved_prefix(f,count=83)
    monkeypatch.setattr(m,'_group',lambda:g)
    return f,data,marker,final


def verify_prefix(case):
    f,data,marker,final=case
    return m.verify_failed_saved_group(data,marker,**{k:f.args[k] for k in ('process_id','expected_document_path','expected_source_sha256')})


def test_saved_prefix_is_expected_state_not_completed_group(failed_prefix):
    f,data,marker,final=failed_prefix
    original=deepcopy((data,marker))
    loaded=verify_prefix(failed_prefix)
    assert loaded['state']==final and loaded['toolpath_record_counts']==[83]
    assert loaded['settings']==g.expected_settings(True)
    assert loaded['payload']==data['current_before']['payload']
    assert (data,marker)==original
    assert data['model_saved'] is False and data['readback_verified'] is False
    assert loaded['current_context_sha256']==m._digest(g.current_projection(loaded))


@pytest.mark.parametrize('kind',['prefix_phase','pending_setter','save_boolean','save_unreturned','header_incomplete',
    'header_count','payload','cone','baseline_geometry','configured_settings','automatic_count','event','marker','source'])
def test_saved_prefix_rejects_unproved_or_changed_facts(failed_prefix,kind):
    f,data,marker,final=failed_prefix
    if kind=='prefix_phase':data['phase']='GenerateToolpath'
    elif kind=='pending_setter':data['actions']['SetTool']['native_dispatch_pending']=True
    elif kind=='save_boolean':data['save_stage']['native_return_value']=False
    elif kind=='save_unreturned':data['save_stage']['native_call_returned']=False
    elif kind=='header_incomplete':data['full_diagnostics'][-1]['capture_complete']=False
    elif kind=='header_count':next(r for r in final['operations'] if r['native_id']==267)['toolpath_record_counts']=[84]
    elif kind=='payload':data['full_diagnostics'][-1]['payload']['rough']['changed']=True
    elif kind=='cone':data['full_diagnostics'][-1]['cone']['changed']=True
    elif kind=='baseline_geometry':data['baseline']['state']['features'][0]['unexpected']='changed'
    elif kind=='configured_settings':data['configured']['settings']['face']['GetFirstCutAmount']=[1.0,False]
    elif kind=='automatic_count':data['automatic_count_observation']['after']=True
    elif kind=='event':data['messages']['event_count']=1
    elif kind=='source':f.args['expected_source_sha256']='b'*64
    if kind=='marker':marker['source_sha256']='d'*64
    else:
        marker.clear();marker.update(g.GroupJournal(data,data['receipt_path'],g.group_marker(data['source_path'],data['source_sha256']))._marker_state())
    with pytest.raises((ValueError,KeyError)):verify_prefix(failed_prefix)


@pytest.fixture
def recovery_case(fixture,monkeypatch):
    f=fixture;monkeypatch.setenv('LOCALAPPDATA',str(f.root))
    f.loaded.update(failed_group_pin=deepcopy(f.loaded['parent_pin']),recovery_retired_pins=[])
    f.args['receipt_path']=str(f.root/'reconciled.json')
    def no_mutation(*a,**kw):pytest.fail('Readonly recovery attempted a native mutation')
    for name in ('assign_tool','write_field','generate','save'):
        monkeypatch.setattr(f.group.NativeBackend,name,no_mutation)
    return f


def run_recovery(f):
    return m._run_reconciliation(object(),'synthetic','synthetic.tlb',loaded=f.loaded,args=f.args)


def test_one_readonly_capture_preserves_original_evidence_and_builds_checkpoint(recovery_case):
    f=recovery_case
    old={p['path']:Path(p['path']).read_bytes() for p in [f.loaded['failed_group_pin'],f.loaded['group_marker_pin']]}
    report=run_recovery(f)
    assert report['status']=='observed' and report['readback_verified'] is True,report
    assert report['original_group_completion_claimed'] is False
    assert report['native_mutation_calls']==0 and f.control.calls==0
    assert f.control.labels==['readonly_saved_group'] and report['full_capture_count']==1
    assert report['checkpoint']['current']['state']==f.loaded['state']
    assert all(Path(path).read_bytes()==value for path,value in old.items())
    marker=m.export_marker('reconcile_saved_group',f.source,f.args['expected_source_sha256'])
    assert marker.parent==m.local_evidence_root() and marker.parent!=f.source.parent
    assert json.loads(marker.read_text())['readback_verified'] is True


@pytest.mark.parametrize('kind',['state','settings','payload','face','rough_count','finish_count'])
def test_fresh_drift_is_retained_before_reconciliation_assertions(recovery_case,kind):
    f=recovery_case
    def drift(label,observation):
        if kind=='state':observation['state']['features'][0]['unexpected']='changed'
        elif kind=='settings':observation['settings']['nc']['XYFeed']=1.0
        elif kind=='payload':observation['payload']['rough']['unexpected']='changed'
        elif kind=='face':observation['face_observation']['unexpected']='changed'
        else:
            oid=247 if kind=='rough_count' else 248
            next(r for r in observation['state']['operations'] if r['native_id']==oid)['toolpath_record_counts']=[9]
    f.control.drift=drift
    report=run_recovery(f)
    assert report['readback_verified'] is False and report['status']=='error'
    saved=json.loads(Path(f.args['receipt_path']).read_text())
    assert saved['observed']==report['observed'] and saved['full_capture_count']==1
    assert f.control.calls==0 and f.control.labels==['readonly_saved_group']
    assert 'checkpoint' not in saved


def test_local_marker_is_stable_across_receipt_names_and_blocks_second_read(recovery_case):
    f=recovery_case
    report=run_recovery(f);assert report['readback_verified'] is True
    marker=m.export_marker('reconcile_saved_group',f.source,f.args['expected_source_sha256'])
    original=marker.read_bytes()
    assert marker==m.export_marker('reconcile_saved_group',f.source.parent/'.'/f.source.name,f.args['expected_source_sha256'])
    f.args['receipt_path']=str(f.root/'different.json')
    with pytest.raises(ValueError):run_recovery(f)
    assert marker.read_bytes()==original and f.control.labels==['readonly_saved_group']
    assert not Path(f.args['receipt_path']).exists() and f.control.calls==0


@pytest.mark.parametrize('kind',['source','pin'])
def test_current_drift_stops_before_fresh_capture(recovery_case,kind):
    f=recovery_case
    if kind=='source':f.source.write_bytes(b'changed current source')
    else:Path(f.loaded['pins'][0]['path']).write_bytes(b'changed current dependency')
    report=run_recovery(f)
    assert report['readback_verified'] is False and report['status']=='error'
    assert f.control.labels==[] and f.control.calls==0


@pytest.fixture
def completed_case(recovery_case,monkeypatch):
    f=recovery_case
    runtime=f.root/'synthetic_runtime';runtime.mkdir()
    monkeypatch.setattr(f.group,'__file__',str(runtime/'group.py'))
    for name in ('sw_cam_mill_stock_export_evidence.py','sw_cam_installation.py','sw_cam_shared_holder_geometry.py'):
        path=runtime/name;path.write_text('# synthetic dependency')
        f.loaded['pins'].append(m._pin(path))
    recipe=f.root/'holder.json';recipe.write_text('{}')
    holder=f.root/'holder.mh';holder.write_text('synthetic non-native holder')
    f.loaded['holder_recipe']['pins']=[m._pin(recipe),m._pin(holder)]
    f.loaded['pins']+=deepcopy(f.loaded['holder_recipe']['pins'])
    import scripts.sw_cam_sandvik_phase1 as phase1
    f.loaded['pins']+=[m._pin(m.__file__),m._pin(phase1.__file__)]
    for index in range(64-len(f.loaded['pins'])):
        path=f.root/f'input_{index}.txt';path.write_text('synthetic dependency')
        f.loaded['pins'].append(m._pin(path))
    f.loaded['current_context_sha256']=m._digest(g.current_projection(f.loaded))
    trusted=deepcopy(f.loaded)
    monkeypatch.setattr(m,'load_failed_saved_group',lambda *a,**kw:deepcopy(trusted))
    monkeypatch.setattr(f.group,'load_completed_group',lambda *a,**kw:pytest.fail('Incomplete grouped loader replayed'),raising=False)
    report=run_recovery(f);assert report['readback_verified'] is True
    return f,report


def load_recovered(f):
    path=Path(f.args['receipt_path'])
    return m.load_completed_reconciliation(str(path),m._file_hash(path),
        **{k:f.args[k] for k in ('process_id','expected_document_path','expected_source_sha256')})


def test_completed_loader_and_both_export_partitions_reuse_readonly_checkpoint(completed_case):
    f,report=completed_case
    loaded=load_recovered(f)
    assert loaded['authority_kind']=='reconciled_saved_group' and len(loaded['pins'])==64
    assert loaded['toolpath_record_counts']==[83]
    assert not any(m._key(p['path'])==m._key(f.loaded['failed_group_pin']['path']) for p in loaded['pins'])
    for action in ('export_cl','export_wip'):
        path=Path(f.args['receipt_path'])
        exported=m.load_export_checkpoint(str(path),m._file_hash(path),action=action,
            **{k:f.args[k] for k in ('process_id','expected_document_path','expected_source_sha256')})
        assert len(exported['pins'])==64 and len(exported['bootstrap_export_pins'])==1
        assert exported['current_context_sha256']==loaded['current_context_sha256']
    assert f.control.calls==0 and f.control.labels==['readonly_saved_group']


def test_completed_loader_rejects_rehashed_changed_checkpoint(completed_case):
    f,report=completed_case
    changed=deepcopy(report)
    next(r for r in changed['checkpoint']['current']['state']['operations'] if r['native_id']==267)['toolpath_record_counts']=[84]
    changed['checkpoint_sha256']=m._digest(changed['checkpoint'])
    m._write_receipt(f.args['receipt_path'],changed)
    with pytest.raises(ValueError):load_recovered(f)
    assert f.control.calls==0 and f.control.labels==['readonly_saved_group']


def test_completed_loader_rejects_local_marker_tampering_and_false_readonly_flag(completed_case):
    f,report=completed_case
    marker=Path(report['recovery_marker_pin']['path']);original=marker.read_bytes()
    marker.write_text('{}')
    with pytest.raises(ValueError):load_recovered(f)
    marker.write_bytes(original)
    for name,value in [('native_mutation_calls',1),('GTP_attempted',True),('model_saved',True),
                       ('setter_attempted',True),('automatic_replay',True)]:
        changed=deepcopy(report);changed[name]=value
        m._write_receipt(f.args['receipt_path'],changed)
        with pytest.raises(ValueError):load_recovered(f)
    assert f.control.calls==0
