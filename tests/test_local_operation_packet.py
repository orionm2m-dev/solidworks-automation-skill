from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from cam_public_test_support import add_runtime, required_module, required_test_module
ROOT=add_runtime()
m=required_module('sw_cam_local_operation_packet')
f=required_test_module('test_local_operation_group')
c=required_test_module('test_local_operation_context_entry')


def test_real_journal_reentry_preserves_all_evidence(tmp_path,monkeypatch):
    report=dict(source_path=str(tmp_path/'part.sldprt'),source_sha256='a'*64,status='uncertain',phase='GTP:1000',actions={})
    j=m.assembly.Journal(report,tmp_path/'receipt.json',tmp_path/'marker.json');j.create();j.entry('GTP:1000');j.pending('GTP:1000')
    before=deepcopy(report);rb=j.receipt.read_bytes();mb=j.marker.read_bytes();calls=[]
    monkeypatch.setattr(m.engine,'run_backend',lambda *a,**k:calls.append(True))
    with pytest.raises(ValueError,match='re-entered'):m.run_once(object(),j,{})
    assert report==before and j.receipt.read_bytes()==rb and j.marker.read_bytes()==mb and calls==[]


def test_created_unclaimed_journal_reentry_does_not_persist(tmp_path,monkeypatch):
    report=dict(source_path='part',source_sha256='a'*64,status='error',phase='preflight',actions={})
    j=m.assembly.Journal(report,tmp_path/'receipt.json',tmp_path/'marker.json');j.create()
    before=j.receipt.read_bytes()
    with pytest.raises(ValueError):m.run_once(object(),j,{})
    assert j.receipt.read_bytes()==before and not j.marker.exists()


def test_new_journal_cannot_evade_existing_source_marker(tmp_path,monkeypatch):
    marker=tmp_path/'marker.json';marker.write_text('prior')
    j=m.assembly.Journal({'keep':True},tmp_path/'new.json',marker)
    with pytest.raises(ValueError):m.run_once(object(),j,{})
    assert j.report=={'keep':True}and not j.receipt.exists()and marker.read_text()=='prior'


def test_marker_independent_of_pid_recipe_and_outputs(tmp_path,monkeypatch):
    monkeypatch.setattr(m.common,'local_evidence_root',lambda:tmp_path)
    p=dict(expected_document_path=str(tmp_path/'part'),expected_source_sha256='a'*64,process_id=1,receipt_path='x')
    q=dict(p,process_id=2,receipt_path='y',recipe_sha256='b'*64)
    assert m.marker_path(p)==m.marker_path(q)
    q['expected_source_sha256']='c'*64;assert m.marker_path(p)!=m.marker_path(q)


def test_fixed_source_audit_covers_insert_native_reader_and_guard():
    pins=[m.common._pin(__import__('importlib').import_module('scripts.'+n).__file__)for n in m.LIVE_MODULES]
    result=m.native_source_audit(pins)
    assert result['status']=='actual_callable_sources_covered'
    assert 'sw_cam_guide_group_definitions'in m.LIVE_MODULES
    assert any(v['member']=='identity_native_call'and Path(v['path']).name=='sw_cam_feature_sketch.py'for v in result['methods'])
    for name in ('sw_cam_feature_sketch.py','sw_cam_mill_units_qualification.py'):
        with pytest.raises(ValueError):m.native_source_audit([v for v in pins if Path(v['path']).name!=name])
    assert len(pins)+3<=64
    bad=[v for v in pins if Path(v['path']).name!='sw_cam_pocket_rough_apply.py']
    with pytest.raises(ValueError):m.native_source_audit(bad)


def _prepared(tmp_path,monkeypatch):
    outer,recipe,observed,choices,feed,tool=c.context_fixture()
    source=tmp_path/'part.sldprt';backup=tmp_path/'backup.sldprt';source.write_bytes(b'current');backup.write_bytes(b'current');sha=m._file_hash(source)
    document=dict(path=str(source),title='part.sldprt',type=1,needs_save=False)
    outer.update(source_sha256=sha,state=dict(document=document,saved_file_sha256=sha),ownership=dict(process_id=42,create_time=123,executable='sldworks.exe'))
    outer['deep_loaded']['guide_parameters'].update(document=document,configuration=dict(sw_configuration_name='Default'))
    outer['deep_loaded']['source_sha256']='0'*64;outer['deep_loaded']['tool_catalogue_ids']=[999]
    receipt=tmp_path/'authority.json';receipt.write_text('{}');recipepath=tmp_path/'recipe.json';recipepath.write_text(__import__('json').dumps(recipe))
    generated=tmp_path/'generated_metadata.py';generated.write_text('# immutable metadata')
    tlb=tmp_path/'camworks.tlb';tlb.write_bytes(b'metadata')
    outer['deep_loaded']['generated_pin']=m.common._pin(generated)
    outer['deep_loaded']['ownership']=outer['ownership']
    outer['deep_loaded']['generated']=dict(saved_cl=dict(authority14=True))
    outer['pins']=[m.common._pin(tlb),m.common._pin(source)]
    proof=tmp_path/'proof.json';proof.write_text('{}');outer['offline_export_proof_pins']=[m.common._pin(proof)]
    outer['registration']=dict(clsid='{test}',addin_path=str(tmp_path/'cam.dll'))
    outer['parent_pin']=m.common._pin(receipt)
    monkeypatch.setattr(m.projection,'tool_dimensions',lambda *a:dict(generic=deepcopy(tool)))
    monkeypatch.setattr(m.mixed,'verify_pocket',lambda *a,**k:dict(actual_profile_verified=True))
    monkeypatch.setattr(m.common,'discover_export_registration',lambda *a:deepcopy(outer['registration']))
    monkeypatch.setattr(m.native.generation,'audit',lambda *a:dict(native_called=False))
    monkeypatch.setattr(m.micro,'audit',lambda *a:dict(native_called=False))
    monkeypatch.setattr(m.common,'_local_receipt',lambda p:Path(p))
    monkeypatch.setattr(m.common,'local_evidence_root',lambda:tmp_path)
    monkeypatch.setattr(m.cl.prior,'_fresh_path',lambda p:Path(p))
    p=dict(process_id=42,expected_document_path=str(source),expected_source_sha256=sha,
      tool_receipt_path=str(receipt),tool_receipt_sha256=m._file_hash(receipt),source_backup_path=str(backup),source_backup_sha256=sha,
      recipe_path=str(recipepath),recipe_sha256=m._file_hash(recipepath),choices=choices,feed_policy=feed,
      module_sha256=m._file_hash(m.__file__),receipt_path=str(tmp_path/'result.json'),progress_path=str(tmp_path/'progress.json'),saved_cl_path=str(tmp_path/'route.cl'),acknowledgement=m.ACK)
    calls=[]
    def loader(*a,**k):calls.append((a,k));return deepcopy(outer)
    return dict(action=m.ACTION,params=p),outer,loader,calls,observed


def test_real_guard_prepare_and_actual_context_constructor(tmp_path,monkeypatch):
    request,outer,loader,calls,_=_prepared(tmp_path,monkeypatch);original=deepcopy(request)
    p,loaded,returned,reg,tlb,abi,receipt,marker,*_=m.prepare_request(request,creation_loader=loader)
    assert request==original and len(calls)==1
    assert loaded['source_sha256']==outer['source_sha256']and loaded['tool_catalogue_ids']==list(range(680,701))
    assert loaded['native_guard_preflight']['constructor_verified']and loaded['native_guard_preflight']['source_and_unique_files']<=64
    assert loaded['initial_source_pins']==[m.common._pin(p['expected_document_path'])]
    assert all(m.common._key(v['path'])!=m.common._key(p['expected_document_path'])for v in loaded['phase_proof_pins'])
    assert loaded['checkpoint_pins']==[]and not receipt.exists()and not marker.exists()
    b=m.NativeBackend(loaded,p,None,reg['clsid'],tlb,{},lambda:None,before_generate=m.nc.before_generate,exporter=m.cl.export_saved)
    assert len(b.protected_targets)==8 and b.ctx.expected_document==outer['state']['document']
    assert b.loaded['configuration_tool']['native_id']==700 and b.capture is not None


@pytest.mark.parametrize('problem',['pidbool','backuphash','backupsame','outputalias','claimed','wrongtoolsource','foreignkeys','badfeed','baddefault'])
def test_prepare_fails_closed(tmp_path,monkeypatch,problem):
    request,outer,loader,calls,_=_prepared(tmp_path,monkeypatch);p=request['params']
    if problem=='pidbool':p['process_id']=True
    elif problem=='backuphash':p['source_backup_sha256']='0'*64
    elif problem=='backupsame':p['source_backup_path']=p['expected_document_path']
    elif problem=='outputalias':p['receipt_path']=p['tool_receipt_path']
    elif problem=='claimed':m.marker_path(p).write_text('{}')
    elif problem=='wrongtoolsource':outer['source_sha256']='0'*64
    elif problem=='foreignkeys':p['native_script']='arbitrary'
    elif problem=='badfeed':p['feed_policy']['left_rough']=[[35.,float('inf')]]
    elif problem=='baddefault':p['choices']['left_rough']={'name':'x','default_operation_id':True}
    with pytest.raises(ValueError):m.prepare_request(request,creation_loader=loader)
    assert not (tmp_path/'route.cl').exists()


def test_changed_phase_proof_stops_before_any_native_save(tmp_path,monkeypatch):
    request,outer,loader,_,_=_prepared(tmp_path,monkeypatch)
    p,loaded,*_=m.prepare_request(request,creation_loader=loader)
    report={};calls=[]
    b=object.__new__(m.NativeBackend);b.loaded=loaded;b.report=report;b.persist=lambda:None
    monkeypatch.setattr(m.native.NativeBackend,'save',lambda self:calls.append('save'))
    proof=Path(outer['offline_export_proof_pins'][0]['path']);proof.write_text('changed')
    with pytest.raises(ValueError):b.save()
    assert calls==[]


def test_preflight_does_not_add_auto_native_selection(monkeypatch,tmp_path):
    request,outer,loader,_,_=_prepared(tmp_path,monkeypatch)
    p,loaded,*_=m.prepare_request(request,creation_loader=loader)
    assert 'local_plan'not in loaded and loaded['dispatch_ready']
    assert 'serial_flat_tool'not in m.LIVE_MODULES and 'sw_cam_serial_flat_tool'not in m.LIVE_MODULES
    assert any(Path(v['path']).name=='sw_cam_serial_flat_tool.py'for v in loaded['phase_proof_pins'])


def _run_real(tmp_path,monkeypatch,*,feed=False,fail_at=None):
    baseline,plan,param,old=f.fixture();r=dict(source_path=str(tmp_path/'part.sldprt'),source_sha256='a'*64)
    j=m.assembly.Journal(r,tmp_path/'receipt.json',tmp_path/'marker.json')
    backend=f.Backend(baseline,plan,param,old,j,feed_delta=feed,fail_at=fail_at)
    backend.outcome=lambda target:dict(operation_native_id=target['operation_native_id'],feature_native_id=target['feature_native_id'],background_over_before=False,background_over_after=False,generated=True,generated_for_feature=True,record_counts=[100])
    monkeypatch.setattr(m.assembly,'hooks',f.hooks)
    monkeypatch.setattr(m.engine.config,'verify_automatic_target',lambda *a:None)
    monkeypatch.setattr(m.engine.generation,'close_checked',lambda b,r:b.close())
    def save(stage,*,capture,verify,guard,claim,persist,save,saved_hash):
        verify(capture('before'));guard();claim();assert save()==0;saved_hash();verify(capture('after'))
    monkeypatch.setattr(m.engine.config.save_core,'run_one_existing_save',save)
    loaded=dict(guide_parameters=dict(expected_parameters=baseline),local_plan=plan,generated=dict(saved_cl={}))
    result=m.run_once(backend,j,loaded)
    return backend,j,result


def test_actual_journal_complete_once_and_reentry(tmp_path,monkeypatch):
    b,j,r=_run_real(tmp_path,monkeypatch)
    assert r['readback_verified']and b.calls.count('save')==1 and b.calls.count('generate')==4
    before=j.receipt.read_bytes();marker=j.marker.read_bytes();calls=deepcopy(b.calls)
    with pytest.raises(ValueError):m.run_once(b,j,{})
    assert j.receipt.read_bytes()==before and j.marker.read_bytes()==marker and b.calls==calls


@pytest.mark.parametrize('step',[1,2,3,4])
def test_actual_journal_uncertain_gtp_stops_without_save_or_replay(tmp_path,monkeypatch,step):
    b,j,r=_run_real(tmp_path,monkeypatch,fail_at=step)
    assert r['status']=='uncertain'and b.calls.count('generate')==step and 'save'not in b.calls
    rb=j.receipt.read_bytes();mb=j.marker.read_bytes()
    with pytest.raises(ValueError):m.run_once(b,j,{})
    assert j.receipt.read_bytes()==rb and j.marker.read_bytes()==mb


def test_actual_journal_unknown_feed_keeps_all_four_completed_without_save(tmp_path,monkeypatch):
    b,j,r=_run_real(tmp_path,monkeypatch,feed=True)
    assert r['status']=='uncertain'and len(r['completed_gtp_counts'])==4
    assert all(r['actions']['GTP:'+str(i)]['readback_verified']for i in r['actual_new_ids'])
    assert 'save'not in b.calls and 'export'not in b.calls


@pytest.mark.parametrize('text',['{"a":1,"a":2}','{"a":NaN}','[]'])
def test_sealed_recipe_rejects_ambiguous_or_nonfinite_json(tmp_path,text):
    p=tmp_path/'recipe.json';p.write_text(text)
    with pytest.raises(ValueError):m.read_json_pin(str(p),m._file_hash(p))


def _terminal(tmp_path,monkeypatch):
    backend,j,r=_run_real(tmp_path,monkeypatch)
    baseline=r['before'];plan=r['plan'];targets=r['learned_targets']
    loaded=dict(guide_parameters=dict(expected_parameters=baseline),configuration_tool=plan['tool'],
        generated=dict(saved_cl={'old14':True}),local_verified_context={},local_recipe={})
    r['request']=dict(choices={k:{'selection':'unique_native_default'}for k in m.engine.KEYS},feed_policy=plan['feed_policy'])
    r['actual_default_catalogues']=[{'actual':True}]
    r['messages']=dict(subscribed=True,disconnected=True,active=False,event_count=0)
    r['source_transition']=dict(source_before_sha256='a'*64,source_after_sha256='b'*64,strict_save_return=0,document=dict(needs_save=False))
    r['phase_proof_checks']=[dict(phase=x,verified=True)for x in ('before_native_start','before_save','after_export_and_cleanup')]
    r['saved_cl']['source_sha256']='b'*64
    def skipped():return dict(status='verified',attempted=False,returned=False,readback_verified=True,observed=dict(already_satisfied=True))
    def executed():return dict(status='verified',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,observed={'typed_readback':True})
    for target in targets:
        oid=str(target['operation_native_id']);rough=target['operation_type']==0
        for spec in (m.engine.config.ROUGH_FIELDS if rough else m.engine.config.FINISH_FIELDS):r['actions'][oid+':'+spec[0]]=skipped()
        for key in ('GetSpndlSpeed','XYFeed'):r['actions'][oid+':NC:'+key]=skipped()
        if rough:
            for key in ('CreateStartPointInstance','CreatePosition','SetPointCoordinates','SetPointPosition','AddStartPoint','SetStartPointList'):r['actions'][oid+':entry:'+key]=executed()
    monkeypatch.setattr(m.projection,'project_context',lambda *a,**k:dict(local_plan=deepcopy(plan)))
    monkeypatch.setattr(m.recipe_hooks,'verify_configured',lambda *a:None)
    monkeypatch.setattr(m.cl,'verify_saved',lambda *a:dict(protected_count=14))
    return r,loaded


def test_completed_validator_uses_actual_save_field_names(tmp_path,monkeypatch):
    r,loaded=_terminal(tmp_path,monkeypatch)
    result=m.validate_completed(r,loaded)
    assert result['saved_operations']==21 and result['saved_parameters']==12 and result['saved_cl_streams']==18
    assert result['source_sha256']=='b'*64 and not result['nominal_geometry_accepted']


@pytest.mark.parametrize('problem',['extra_action','empty_targets','unverified','pending','claimed_without_return','old_source','dirty','production','bad_protected','different_choices','wrong_clsource','missing_phaseproof'])
def test_completed_validator_rejects_incomplete_or_unrelated_authority(tmp_path,monkeypatch,problem):
    r,loaded=_terminal(tmp_path,monkeypatch)
    if problem=='extra_action':r['actions']['GOP']={**r['actions']['SaveActiveDocument']}
    elif problem=='empty_targets':r['learned_targets']=[]
    elif problem=='unverified':r['actions']['GTP:1000']['readback_verified']=False
    elif problem=='pending':r['actions']['GTP:1000']['native_dispatch_pending']=True
    elif problem=='claimed_without_return':r['actions']['SetTool:1000']['returned']=False
    elif problem=='old_source':r['saved_source_sha256']='a'*64
    elif problem=='dirty':r['source_transition']['document']['needs_save']=True
    elif problem=='production':r['production_qualified']=True
    elif problem=='bad_protected':r['saved']['parameters'][0]['nc']['feeds_compensation']['XYFeed']=71.
    elif problem=='different_choices':r['plan']['rows'][0]['default_operation_name']='unknown'
    elif problem=='wrong_clsource':r['saved_cl']['source_sha256']='a'*64
    elif problem=='missing_phaseproof':r['phase_proof_checks'].pop()
    with pytest.raises(ValueError):m.validate_completed(r,loaded)


def test_evidence_decoded_bytes_must_match_even_if_later_file_hash_matches(tmp_path,monkeypatch):
    path=tmp_path/'recipe.json';path.write_bytes(b'{"old":true}')
    promised=__import__('hashlib').sha256(b'{"new":true}').hexdigest()
    monkeypatch.setattr(m,'_file_hash',lambda _:promised)
    with pytest.raises(ValueError,match='Evidence bytes'):m.read_json_pin(str(path),promised)


@pytest.mark.parametrize('kind',['runtime','fixture'])
def test_missing_public_runtime_or_committed_fixture_fails(tmp_path,monkeypatch,kind):
    with pytest.raises(RuntimeError):
        if kind=='runtime':
            monkeypatch.setenv('SOLIDWORKS_SKILL_ROOT',str(tmp_path/'missing'))
            add_runtime()
        else:required_test_module('test_missing_committed_cam_fixture')


@pytest.mark.parametrize('action',['insert','SetTool','GTP'])
def test_terminal_action_readback_must_match_its_actual_selected_result(tmp_path,monkeypatch,action):
    r,loaded=_terminal(tmp_path,monkeypatch)
    if action=='insert':r['actions']['insert:left_rough']['actual_native_id']=2222
    elif action=='SetTool':r['actions']['SetTool:1000']['observed']['feature_native_id']=2222
    else:r['actions']['GTP:1000']['observed']['record_counts']=[99]
    with pytest.raises(ValueError):m.validate_completed(r,loaded)
