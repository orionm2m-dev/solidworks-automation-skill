"""Portable saved-plan authority tests; application access is never used."""
from copy import deepcopy
import hashlib,json
from pathlib import Path
import pytest
from scripts import sw_cam_pocket_definition_context as d
from scripts import sw_cam_pocket_gop_evidence as e
from test_pocket_gop_evidence import packet,write

@pytest.fixture
def saved_packet(packet):
    c,g,path,marker=packet
    c['current_sketch_baseline']=dict(path=c['expected_document_path'],pid=123,saved_file_sha256='a'*64,needs_save=False,features=[],planes=[],spec={'circle':8.},solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[1.,2.,3.])])
    gp=dict(path=str(path),sha256='d'*64);mp=dict(path=str(c['marker']),sha256='e'*64)
    plan=dict(operation_ids=[201,202],after=deepcopy(g['after']),gop_pin=gp,marker_pin=mp)
    metadata=dict(machine_kind='mill_single_feature_qualification',process_id=123,expected_feature_native_id=111,expected_operation_native_ids=[201,202])
    before=deepcopy(g['after']);before.update(metadata)
    after=deepcopy(before);after['saved_file_sha256']='f'*64;after['document']['needs_save']=False
    saved=dict(status='review_required',phase='finished',action='save',feature_kind='autodetected_pocket',message_policy='vendor_default',
        native_return_type='int',native_return_value=0,native_hresult=0,native_outcome='save_returned_readback_verified',
        definition_gop_receipt_pin=gp,definition_gop_marker_pin=mp,before=before,after=after,final_state=deepcopy(after),
        saved_file_sha256_after_native_return='f'*64,state_sha256=d._digest(after),after_cleanup_sw_file=dict(document=deepcopy(after['document']),saved_file_sha256='f'*64),messages=deepcopy(g['messages']),**metadata)
    for k in ('mutation_attempted','native_call_attempted','native_call_returned','native_save_call_returned','save_readback_verified','saved_file_changed','geometry_unqualified'):saved[k]=True
    for k in ('native_dispatch_pending','native_close_call_returned','close_verified','persistence_verified','generation_attempted','AFR_attempted','GOP_attempted','GTP_attempted','post_cleanup_CAM_getters','physical_depth_verified','production_qualified','may_continue'):saved[k]=False
    saved['snapshot_diagnostics']=[]
    for label,state in zip(('initial_capture','before_native_action','after_native_save'),(before,before,after)):
        raw=deepcopy(state)
        for k in metadata:raw.pop(k)
        sketch=deepcopy(c['current_sketch_baseline']);sketch.update(saved_file_sha256=state['saved_file_sha256'],needs_save=state['document']['needs_save'])
        saved['snapshot_diagnostics'].append(dict(phase=label,capture_complete=True,state=raw,actual_sketch_snapshot=sketch))
    return c,plan,saved,packet

def verify(p):return d._verify_saved_plan_transition(p[0],p[1],p[2],'f'*64)

def test_save_transition_is_exact_and_does_not_promote(saved_packet):
    c,plan,saved,_=saved_packet;original=deepcopy(saved);out=verify(saved_packet)
    assert out['after_sha256']=='f'*64 and out['before_sha256']=='a'*64 and not out['persistence_verified']
    assert out['saved_plan_inventory']['operations']==plan['after']['operations'] and saved==original

@pytest.mark.parametrize('key,value',[('status','uncertain'),('phase','after'),('action','prepare'),('feature_kind','circular_pocket'),('process_id',True),('expected_feature_native_id',112),('expected_operation_native_ids',[202,201]),('message_policy','other'),('save_readback_verified',False),('geometry_unqualified',False),('native_return_value',True),('native_return_value',1),('native_hresult',False),('native_outcome','unknown'),('persistence_verified',True),('GTP_attempted',True),('production_qualified',True),('state_sha256','0'*64),('saved_file_sha256_after_native_return','a'*64),('issue',{'type':'uncertain'})])
def test_failed_mismatched_or_promoted_save_is_rejected(saved_packet,key,value):
    saved_packet[2][key]=value
    with pytest.raises(ValueError):verify(saved_packet)

@pytest.mark.parametrize('damage',['operation','tool','owner','feature','cleanup','event','marker','diagnostic','plane','sketch','body','source','final'])
def test_saved_plan_geometry_inventory_and_provenance_are_protected(saved_packet,damage):
    s=saved_packet[2]
    if damage=='operation':s['after']['operations'][0]['native_id']+=1
    elif damage=='tool':s['after']['operations'][0]['assigned_tool']['native_id']+=1
    elif damage=='owner':s['after']['operation_setups'][0]['native_id']+=1
    elif damage=='feature':s['after']['selected_feature']['island_count']-=1
    elif damage=='cleanup':s['after_cleanup_sw_file']['saved_file_sha256']='a'*64
    elif damage=='event':s['messages']['event_count']=1
    elif damage=='marker':s['definition_gop_marker_pin']=dict(path=s['definition_gop_marker_pin']['path'],sha256='0'*64)
    elif damage=='diagnostic':s['snapshot_diagnostics'][1]['capture_complete']=False
    elif damage=='plane':s['snapshot_diagnostics'][2]['actual_sketch_snapshot']['planes']=[{'different':True}]
    elif damage=='sketch':s['snapshot_diagnostics'][2]['actual_sketch_snapshot']['spec']['circle']+=1
    elif damage=='body':s['snapshot_diagnostics'][2]['actual_sketch_snapshot']['solids'][0]['mass_raw'][0]+=1e-8
    elif damage=='source':s['snapshot_diagnostics'][2]['state']['saved_file_sha256']='a'*64
    elif damage=='final':s['final_state']['document']['title']='other.sldprt'
    with pytest.raises(ValueError):verify(saved_packet)

def test_existing_body_tolerance_is_reused_without_widening(saved_packet):
    saved_packet[2]['snapshot_diagnostics'][2]['actual_sketch_snapshot']['solids'][0]['mass_raw'][0]+=1e-11
    assert verify(saved_packet)['native_return_value']==0

def test_false_to_false_CAD_flag_does_not_invalidate_proved_Save(saved_packet):
    c,plan,s,_=saved_packet;plan['after']['document']['needs_save']=False;s['before']['document']['needs_save']=False
    for row in s['snapshot_diagnostics'][:2]:
        row['state']['document']['needs_save']=False;row['actual_sketch_snapshot']['needs_save']=False
    assert verify(saved_packet)['saved_plan_inventory']['document']['needs_save']is False

@pytest.fixture
def file_chain(saved_packet,tmp_path,monkeypatch):
    c,plan,s,packet=saved_packet;g=packet[1];target=Path(c['expected_document_path']);target.write_bytes(b'current saved draft plan');new_sha=hashlib.sha256(target.read_bytes()).hexdigest()
    pins={}
    for label in ('recovery','creator','creator_marker','zero_save'):
        p=tmp_path/(label+'.json');pins[label]=dict(path=str(p),sha256=write(p,{'label':label}))
    c['evidence']=pins['recovery'];c['save_pin']=pins['zero_save'];c['creator']=dict(status='uncertain',request=dict(process_id=123,expected_process_create_time=12.,expected_document_path=str(target),expected_source_sha256='c'*64))
    c['marker']=target.parent/('feature_gop_'+d._digest(dict(scope=d.SCOPE,target=d.creator.canonical(str(target)),creator_sha256=pins['creator']['sha256'],feature_id=111))+'.json')
    g['definition_recovery_receipt_path']=pins['recovery']['path'];g['definition_recovery_receipt_sha256']=pins['recovery']['sha256'];g['definition_save_receipt_path']=pins['zero_save']['path'];g['definition_save_receipt_sha256']=pins['zero_save']['sha256']
    authority=dict(scope=d.SCOPE,recovery_receipt_sha256=pins['recovery']['sha256'],save_receipt_sha256=pins['zero_save']['sha256'],raw_creator_status='uncertain',saved_definition_binding_verified=True,persistence_verified=False,analytic_sketch_and_body_invariants_verified=True,island_geometry_verified=False,physical_depth_verified=False)
    for state in (g['before'],g['after'],s['before'],s['after'],s['final_state']):state['definition_authority']=deepcopy(authority)
    g['state_sha256']=e._digest(dict(snapshot=g['before'],process_id=123,expected_feature_native_id=111,scope='MILL_SINGLE_FEATURE_GOP_RETAIN1'));g['definition_gop_marker_path']=str(c['marker'])
    for row,state in zip(g['snapshot_diagnostics'],(g['before'],g['before'],g['after'])):row['state']=deepcopy(state)
    marker=dict(scope=d.SCOPE,creator_receipt_sha256=pins['recovery']['sha256'],feature_native_id=111,receipt_path=str(packet[2]),state_sha256=g['state_sha256'],automatic_replay=False)
    mp=dict(path=str(c['marker']),sha256=write(c['marker'],marker));gp=dict(path=str(packet[2]),sha256=write(packet[2],g));s['definition_gop_receipt_pin']=gp;s['definition_gop_marker_pin']=mp
    for state in (s['after'],s['final_state']):state['saved_file_sha256']=new_sha
    s['saved_file_sha256_after_native_return']=new_sha;s['after_cleanup_sw_file']['saved_file_sha256']=new_sha;s['state_sha256']=d._digest(s['after'])
    for row in s['snapshot_diagnostics']:
        row['state']['definition_authority']=deepcopy(authority)
        if row['phase']=='after_native_save':row['state']['saved_file_sha256']=new_sha;row['actual_sketch_snapshot']['saved_file_sha256']=new_sha
    post=tmp_path/'post_save.json';post_sha=write(post,s)
    rec=dict(old=c['creator'],header=c['recovered']['header'],pins=[dict(path=str(target),sha256='c'*64)],creator_pin=pins['creator'],marker_pin=pins['creator_marker'],receipt_pin=pins['recovery'],expected_inventory=c['expected_inventory'],sketch={'after':c['current_sketch_baseline']},spec=c['current_sketch_baseline']['spec'])
    zero={'after':{'saved_file_sha256':'a'*64}};pins['zero_save']['sha256']=write(Path(pins['zero_save']['path']),zero)
    # Preserve this newly pinned zero-Save in every GOP/Save authority observation.
    old_sha=authority['save_receipt_sha256'];new_zero=pins['zero_save']['sha256']
    def replace(value):
        if isinstance(value,dict):return {k:replace(v) for k,v in value.items()}
        if isinstance(value,list):return [replace(v) for v in value]
        return new_zero if value==old_sha else value
    g=replace(g);s=replace(s);g['state_sha256']=e._digest(dict(snapshot=g['before'],process_id=123,expected_feature_native_id=111,scope='MILL_SINGLE_FEATURE_GOP_RETAIN1'));marker['state_sha256']=g['state_sha256'];mp['sha256']=write(c['marker'],marker);gp['sha256']=write(packet[2],g);s['definition_gop_receipt_pin']=gp;s['definition_gop_marker_pin']=mp;s['state_sha256']=d._digest(s['after']);post_sha=write(post,s)
    monkeypatch.setattr(d,'_read_recovery',lambda p,h:deepcopy(rec))
    monkeypatch.setattr(d,'verify_saved_transition',lambda *args,**kw:deepcopy(c['saved_transition']))
    v=dict(process_id=123,expected_process_create_time=12.,expected_document_path=str(target),expected_source_sha256=new_sha,expected_feature_native_id=111,expected_operation_native_ids=[201,202])
    for prefix,pin in [('definition_recovery_receipt',pins['recovery']),('definition_save_receipt',pins['zero_save']),('definition_gop_receipt',gp),('definition_gop_save_receipt',dict(path=str(post),sha256=post_sha))]:v.update({prefix+'_path':pin['path'],prefix+'_sha256':pin['sha256']})
    return v,rec,pins,target

def test_loader_checks_new_target_only_and_retains_immutable_history(file_chain):
    v,rec,pins,target=file_chain;original=deepcopy(rec);out=d.load_saved_plan(v)
    assert out['expected_source_sha256']==v['expected_source_sha256'] and out['expected_operation_native_ids']==[201,202]
    assert out['creator']['status']=='uncertain' and rec==original and not out['verified_saved_plan_transition']['persistence_verified']
    assert [p['sha256'] for p in out['pins'] if d.creator.same_path(p['path'],str(target))]==[v['expected_source_sha256']]
    assert {p['sha256'] for p in out['historical_target_pins']}=={'c'*64,'a'*64}

@pytest.mark.parametrize('damage',['target','immutable','lifetime','operation_order','post_pin'])
def test_loader_rejects_changed_current_or_provenance(file_chain,damage):
    v,rec,pins,target=file_chain
    if damage=='target':target.write_bytes(b'other')
    elif damage=='immutable':Path(pins['creator']['path']).write_text('{}',encoding='utf-8')
    elif damage=='lifetime':v['expected_process_create_time']=13.
    elif damage=='operation_order':v['expected_operation_native_ids'].reverse()
    elif damage=='post_pin':v['definition_gop_save_receipt_sha256']='0'*64
    with pytest.raises(ValueError):d.load_saved_plan(v)
