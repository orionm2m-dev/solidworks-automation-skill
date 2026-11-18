from copy import deepcopy
from pathlib import Path
import sys,os,json,hashlib
import pytest
RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path.home()/'.codex'/'skills'/'solidworks-automation'))
STAGE=Path(__file__).resolve().parents[1]
WRITER_STAGE=STAGE.parent/'circular_reconfigure_20261110'
sys.path[:0]=[str(RUNTIME),str(RUNTIME/'tests'),str(WRITER_STAGE/'tests'),str(STAGE/'tests')]
import scripts
scripts.__path__[:0]=[str(STAGE/'scripts'),str(WRITER_STAGE/'scripts')]
from scripts import sw_cam_reconfigured_circular_wip_binding as m
from scripts import sw_cam_completed_gtp_wip as core
from wip_fixture_support import state_recipe,independently_configured
from test_current_circular_wip_binding import cl_bytes,pin,write


def fixture(tmp_path,count=731):
    b,recipe=state_recipe();source=tmp_path/'part.sldprt';source.write_bytes(b'saved replacement')
    sha=pin(source)['sha256'];b['document']['path']=str(source)
    configured=independently_configured(b,recipe);generated=deepcopy(configured)
    generated['operations'][-1]['toolpath_record_counts']=[count]
    saved=deepcopy(generated);saved['document']['needs_save']=False
    saved['sketch_state'].update(needs_save=False,saved_file_sha256=sha)
    old=m.common.delta.inventory(b)['generated'];new=m.common.delta.inventory(saved)['generated']
    pre=tmp_path/'old.cl';pre.write_bytes(cl_bytes(old));post=tmp_path/'new.cl';post.write_bytes(cl_bytes(new))
    recipepin=write(tmp_path/'recipe.json',recipe);nc=write(tmp_path/'nc.json',dict(synthetic=True));wp=pin(Path(m.writer.__file__))
    rp=tmp_path/'receipt.json';mp=tmp_path/'marker.json'
    req=dict(process_id=123,expected_process_create_time=1.25,expected_document_path=str(source),expected_source_sha256='a'*64,
        nc_receipt_path=nc['path'],nc_receipt_sha256=nc['sha256'],recipe_path=recipepin['path'],recipe_sha256=recipepin['sha256'],
        receipt_path=str(rp),saved_cl_path=str(post),qualification_only=True,message_policy='vendor_default')
    r=dict(scope=m.writer.SCOPE,status='review_required',phase='finished',
        reason='ONE_SELECTED_RECONFIGURATION_GTP_SAVE_AND_PROTECTED_CL_VERIFIED',request=req,
        source_before_sha256='a'*64,source_after_sha256=sha,saved_file_sha256=sha,
        receipt_path=str(rp),dispatch_marker_path=str(mp),recipe=recipe,recipe_pin=recipepin,operation_native_id=361,
        evidence_pins=[nc,recipepin,wp],historical_CL_pin=pin(pre),messages=dict(subscribed=True,active=False,disconnected=True,event_count=0))
    for key in ('continuation_verified','readback_verified','runtime_unchanged','model_saved','save_readback_verified','source_update_verified',
        'GTP_attempted','save_attempted','CL_export_attempted','parameter_setter_attempted','receipt_created','marker_created',
        'mutation_attempted','native_call_attempted','native_call_returned'):r[key]=True
    for key in ('native_dispatch_pending','GOP_attempted','AFR_attempted','operation_creation_attempted',
        'tool_assignment_attempted','automatic_replay','automatic_rollback','selected_cached_path_is_stale'):r[key]=False
    states=dict(before=b,configured=configured,generated=generated,saved=saved,confirm_saved=saved)
    r.update(deepcopy(states));r['captures']=[dict(label=k,capture_complete=True,state=deepcopy(v))for k,v in states.items()]
    r['configuration_proof']=m.writer.verify_configuration(b,configured,recipe)
    r['generation_proof']=m.writer.verify_generation(configured,generated,361)
    returned=dict(attempted=True,returned=True,native_dispatch_pending=False,native_return_type='int',native_return_value=0)
    r['actions']={}
    for kind in ('nc','rough'):
        for change in recipe[kind]:r['actions'][kind+':'+change['field']]=dict(**returned,immediate_readback=deepcopy(change['new']))
    for name in ('GTP:361','SaveActiveDocument','postCL'):r['actions'][name]=deepcopy(returned)
    r['save_stage']=dict(native_call_returned=True,save_pending=False,native_return_type='int',native_return_value=0)
    r['postCL']=dict(output_verified=True,readback_verified=True,source_sha256=sha,expected_generated_operations=new,
        before=deepcopy(saved),after=deepcopy(saved),output=pin(post))
    parsed=[m.common.parse_generic_cl_bytes(p.read_bytes(),expected_block_record_counts=[x['toolpath_record_counts'][0]for x in rows])
        for p,rows in ((pre,old),(post,new))]
    r['CL_preservation']=m.writer.compare_replacement_cl(*parsed,old,new,361)
    receiptpin=write(rp,r)
    mark=dict(scope=m.writer.SCOPE,receipt_path=str(rp),receipt_sha256=receiptpin['sha256'],source_before_sha256='a'*64,
        recipe_pin=recipepin,status='review_required',phase='finished',automatic_replay=False)
    markerpin=write(mp,mark)
    kw=dict(process_id=123,process_create_time=1.25,source_path=str(source),source_sha256=sha,
        selected_operation_ids=[361],protected_operation_ids=[x['operation_native_id']for x in old if x['operation_native_id']!=361],
        expected_generated_operations=new,marker_pin=markerpin,writer_pin=wp)
    return r,receiptpin,kw


def repin(r,rp,kw):
    rp=write(Path(rp['path']),r);mp=kw['marker_pin'];mark=json.loads(Path(mp['path']).read_bytes())
    mark['receipt_sha256']=rp['sha256'];kw['marker_pin']=write(Path(mp['path']),mark);return rp


@pytest.mark.parametrize('count',[42,731,1001])
def test_existing_19_to_19_variable_target_with_actual_writer_delta_and_parser(tmp_path,count):
    r,rp,kw=fixture(tmp_path,count);old=deepcopy(r);b=m.bind_completed_revision(rp,**kw)
    assert len(b['expected_generated_operations'])==19 and len(b['protected_operation_ids'])==18
    assert b['expected_generated_operations'][-1]['toolpath_record_counts']==[count]
    assert b['protected_complete_streams']['protected_complete_streams_verified'] and r==old
    assert b['producer_scope']==m.writer.SCOPE
    canonical=m.common.validate_capture(b,r['saved']['document'],r['saved'])
    assert canonical['source_sha256']==kw['source_sha256']


@pytest.mark.parametrize('defect',['uncertain','selfclaim','pending','setter_bool','setter_readback','dirty','source',
    'capture','protected_count','configured_feed','count','bool_count','owner','lifetime','protected_mapping',
    'marker','cleanup','event','extra_action','writer_pin','postCL_readback'])
def test_rejects_incomplete_untrusted_dirty_stale_and_mapping(tmp_path,defect):
    r,rp,kw=fixture(tmp_path)
    if defect=='uncertain':r['status']='uncertain'
    elif defect=='selfclaim':r.update(status='prepared',verified=True)
    elif defect=='pending':r['native_dispatch_pending']=True
    elif defect=='setter_bool':r['actions']['nc:XYFeed']['native_return_value']=True
    elif defect=='setter_readback':r['actions']['nc:XYFeed']['immediate_readback']=999.
    elif defect=='dirty':r['saved']['document']['needs_save']=True
    elif defect=='source':r['postCL']['source_sha256']='0'*64
    elif defect=='capture':r['captures'][-1]['capture_complete']=False
    elif defect=='protected_count':r['generated']['operations'][0]['toolpath_record_counts']=[999]
    elif defect=='configured_feed':r['configured']['cutting_context']['nc']['XYFeed']=999.
    elif defect=='count':kw['expected_generated_operations'][-1]['toolpath_record_counts']=[777]
    elif defect=='bool_count':kw['expected_generated_operations'][-1]['toolpath_record_counts']=[True]
    elif defect=='owner':kw['process_id']=124
    elif defect=='lifetime':kw['process_create_time']=1.5
    elif defect=='protected_mapping':kw['protected_operation_ids']=[]
    elif defect=='marker':r['dispatch_marker_path']=str(tmp_path/'other.json')
    elif defect=='cleanup':r['cleanup_error']={'reason':'event disconnect'}
    elif defect=='event':r['messages']['event_count']=1
    elif defect=='extra_action':r['actions']['GTP:100']=deepcopy(r['actions']['GTP:361'])
    elif defect=='writer_pin':kw['writer_pin']['sha256']='0'*64
    elif defect=='postCL_readback':r['postCL']['readback_verified']=False
    rp=repin(r,rp,kw)
    with pytest.raises(ValueError):m.bind_completed_revision(rp,**kw)


def test_actual_protected_stream_changed_with_updated_hash_is_rejected(tmp_path):
    r,rp,kw=fixture(tmp_path);p=Path(r['postCL']['output']['path'])
    p.write_bytes(p.read_bytes().replace(b'GOTO/100,0,10',b'GOTO/999,0,10'));r['postCL']['output']=pin(p)
    rp=repin(r,rp,kw)
    with pytest.raises(ValueError,match='Protected complete CL'):m.bind_completed_revision(rp,**kw)


def test_source_changed_on_disk_rejected(tmp_path):
    r,rp,kw=fixture(tmp_path);Path(kw['source_path']).write_bytes(b'later change')
    with pytest.raises(ValueError,match='Pinned evidence changed'):m.bind_completed_revision(rp,**kw)


def test_wrong_marker_digest_rejected(tmp_path):
    r,rp,kw=fixture(tmp_path);mp=kw['marker_pin'];mark=json.loads(Path(mp['path']).read_bytes());mark['receipt_sha256']='0'*64
    kw['marker_pin']=write(Path(mp['path']),mark)
    with pytest.raises(ValueError,match='revision marker differs'):m.bind_completed_revision(rp,**kw)


def test_new_target_validator_not_relaxed_for_existing_writer(tmp_path):
    r,rp,kw=fixture(tmp_path);kw.pop('writer_pin')
    with pytest.raises(ValueError,match='circular generation receipt'):m.common.bind_completed_receipt(rp,**kw)


def test_reconfigured_binding_uses_existing_one_call_wip_core_without_whole_model_claim(tmp_path):
    from test_current_circular_wip_binding import Guard
    r,rp,kw=fixture(tmp_path);b=m.bind_completed_revision(rp,**kw)
    report=m.common.new_report(b,output_dir=tmp_path/'wip',implementation_pin=pin(Path(m.__file__)));calls=[]
    def capture(label):
        calls.append('capture:'+label)
        return deepcopy(b['document']),deepcopy(b['snapshot']),dict(machine=object())
    def invoke(machine):calls.append('WIP');return True
    files=[dict(stl_extension=True,bytes=12,sha256='a'*64,path='synthetic.stl')]
    m.common.run_existing_core(core,b,report,capture_existing=capture,guard_factory=Guard,persist=lambda:None,
        claim=lambda:calls.append('claim'),invoke=invoke,collect=lambda:deepcopy(files))
    assert calls==['capture:before','claim','WIP','capture:after']
    assert report['binding_readback_verified'] and report['outer_cleanup_still_required']
    assert not report['whole_R25_geometry_verified'] and not report['production_qualified']
    with pytest.raises(ValueError,match='Fresh bound'):
        m.common.run_existing_core(core,b,report,capture_existing=capture,guard_factory=Guard,persist=lambda:None,
            claim=lambda:None,invoke=invoke,collect=lambda:files)


def test_verified_revision_path_alias_and_clean_capture_guard(tmp_path):
    r,rp,kw=fixture(tmp_path);(tmp_path/'alias').mkdir();rp=deepcopy(rp)
    rp['path']=str(tmp_path/'alias'/'..'/'receipt.json');b=m.bind_completed_revision(rp,**kw)
    bad=deepcopy(b['snapshot']);bad['sketch_state']['needs_save']=True
    with pytest.raises(ValueError):m.common.validate_capture(b,b['document'],bad)
