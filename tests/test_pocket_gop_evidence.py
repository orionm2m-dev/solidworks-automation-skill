"""Pure receipt/marker verifier; no application/native calls."""
from copy import deepcopy
import hashlib,json
from pathlib import Path
import pytest
from scripts import sw_cam_pocket_gop_evidence as e

def write(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding='utf-8');return hashlib.sha256(path.read_bytes()).hexdigest()
@pytest.fixture
def packet(tmp_path):
    c=dict(scope=e.definition.SCOPE,process_id=123,expected_document_path=str(tmp_path/'part.sldprt'),expected_source_sha256='a'*64,expected_feature_native_id=111,
        evidence=dict(path=str(tmp_path/'recovery.json'),sha256='b'*64),save_pin=dict(path=str(tmp_path/'save.json'),sha256='c'*64),creator=dict(status='uncertain'),
        marker=tmp_path/'once.json',recovered=dict(header=dict(native_id=111,owner_setup_native_id=64,volume_type=2,island_count=4,depth_native=13.2)))
    c['saved_transition']=dict(document=dict(path=c['expected_document_path'],title='part.sldprt',type=1,needs_save=False))
    c['expected_inventory']=dict(capture_complete=True,feature_setups=[dict(native_id=64,feature_ids=[111])],features=[dict(native_id=111,setup_native_id=64)],
        feature_count=1,operation_setups=[dict(index=0,native_id=70,operation_count=0)],operations=[],operation_count=0,generated_operation_count=0,total_record_count=0,
        unique_tool_count=0,sw_reference=dict(feature_tree=[],solids=[]),all_solid_body_count=1)
    b=e.expected_before(c);a=deepcopy(b);a.update(operation_count=2,unique_tool_count=1,operation_counts=[2]);a['operation_setups'][0]['operation_count']=2;a['document']['needs_save']=True
    a['operations']=[dict(setup_index=0,operation_index=i,setup_native_id=70,native_id=201+i,mill_operation_type=3,base_operation_type=1,
        linked_feature_ids=[111],all_linked_features_observed=True,suppressed=False,toolpath_generated=False,toolpath_record_counts=[],
        assigned_tool=dict(native_id=501,is_mill_tool=True,native_read_complete=True,tool_type_raw=2,cut_diameter_native=8.,protrusion_native=30.))for i in range(2)]
    r=dict(feature_authority='autodetected_pocket_definition',action='apply',status='review_required',phase='finished',gop_preference=1,process_id=123,
        native_return_type='int',native_hresult=0,definition_recovery_receipt_path=c['evidence']['path'],definition_recovery_receipt_sha256=c['evidence']['sha256'],
        definition_save_receipt_path=c['save_pin']['path'],definition_save_receipt_sha256=c['save_pin']['sha256'],before=b,after=a,new_operations=deepcopy(a['operations']),
        after_cleanup_SW_file=dict(document=deepcopy(a['document']),saved_file_sha256='a'*64),definition_gop_marker_path=str(c['marker']),
        messages=dict(policy='vendor_default',response='default_unknown',subscribed=True,disconnected=True,active=False,event_count=0,events=[],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[]))
    for key in ('readback_verified','insertion_delta_verified','mutation_attempted','native_call_attempted','native_call_returned','apply_eligible','geometry_unqualified'):r[key]=True
    for key in ('native_dispatch_pending','model_saved','AFR_attempted','GTP_attempted','simulation_attempted','stock_edit_attempted','units_verified','physical_depth_verified','tool_or_material_process_qualified','production_qualified','post_cleanup_CAM_getters','island_geometry_verified','may_continue'):r[key]=False
    r['state_sha256']=e._digest(dict(snapshot=b,process_id=123,expected_feature_native_id=111,scope='MILL_SINGLE_FEATURE_GOP_RETAIN1'))
    r['snapshot_diagnostics']=[dict(phase=label,capture_complete=True,state=deepcopy(state))for label,state in zip(('initial_capture','before_mutation_capture','after_mutation_capture'),(b,b,a))]
    path=tmp_path/'gop.json';marker=dict(scope=e.definition.SCOPE,creator_receipt_sha256='b'*64,feature_native_id=111,receipt_path=str(path),state_sha256=r['state_sha256'],automatic_replay=False)
    write(c['marker'],marker);return c,r,path,marker

def load(packet,ids=None):
    c,r,p,_=packet;sha=write(p,r);return e.read_gop_receipt(str(p),sha,c,[201,202]if ids is None else ids)

def test_completed_gop_returns_ordered_actual_definitions_and_pins(packet):
    c,r,p,mark=packet;original=deepcopy(r);out=load(packet)
    assert out['operation_ids']==[201,202]and out['after']==r['after']and out['gop']==original
    assert out['marker_pin']['sha256']==hashlib.sha256(c['marker'].read_bytes()).hexdigest()

@pytest.mark.parametrize('key,value',[('status','uncertain'),('action','prepare'),('gop_preference',True),('gop_preference',0),('native_hresult',False),('native_hresult',1),
    ('native_return_type','bool'),('native_dispatch_pending',True),('GTP_attempted',True),('model_saved',True),('physical_depth_verified',True),('readback_verified',False),
    ('process_id',124),('state_sha256','d'*64),('definition_recovery_receipt_sha256','d'*64),('issue',dict(type='failure'))])
def test_rejects_failed_wrong_or_promoted_gop(packet,key,value):
    packet[1][key]=value
    with pytest.raises(ValueError):load(packet)

@pytest.mark.parametrize('ids',[[202,201],[201],[],[201,201],[True,202]])
def test_exact_operation_order_and_identity_required(packet,ids):
    with pytest.raises(ValueError):load(packet,ids)

@pytest.mark.parametrize('damage',['source','cleanup','feature','path','event','diagnostic','new_operations'])
def test_rejects_incomplete_or_changed_observation(packet,damage):
    r=packet[1]
    if damage=='source':r['after']['saved_file_sha256']='f'*64
    elif damage=='cleanup':r['after_cleanup_SW_file']['document']['needs_save']=False
    elif damage=='feature':r['after']['selected_feature']['native_id']=112
    elif damage=='path':r['after']['operations'][0]['toolpath_record_counts']=[10]
    elif damage=='event':r['messages']['event_count']=1
    elif damage=='diagnostic':r['snapshot_diagnostics'][1]['capture_complete']=False
    elif damage=='new_operations':r['new_operations'].reverse()
    with pytest.raises(ValueError):load(packet)

@pytest.mark.parametrize('key,value',[('automatic_replay',True),('feature_native_id',112),('state_sha256','e'*64),('receipt_path','wrong.json')])
def test_consumed_marker_must_match_exact_attempt(packet,key,value):
    c,r,p,marker=packet;marker[key]=value;write(c['marker'],marker)
    with pytest.raises(ValueError):load(packet)

def test_actual_receipt_hash_is_verified(packet):
    c,r,p,_=packet;write(p,r)
    with pytest.raises(ValueError):e.read_gop_receipt(str(p),'0'*64,c,[201,202])
