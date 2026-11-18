"""Portable file-only finalizer regression; fake Save writes only temporary bytes."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,os.environ.get('SWMCP_RUNTIME_ROOT',str(ROOT)))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_current_pocket_saved_context as f
c=f.current


def pin(path,data):
    path.write_bytes(data);return dict(path=str(path),sha256=hashlib.sha256(data).hexdigest())


def make_case(tmp_path,root_count=2):
    target=tmp_path/'part.sldprt';tp=pin(target,b'prior');source=tp['sha256']
    roots=[pin(tmp_path/('root_'+str(i)+'.json'),str(i).encode())for i in range(root_count)]
    predecessor=pin(tmp_path/'predecessor.json',b'completed predecessor')
    doc=dict(path=str(target),title=target.name,type=1,needs_save=False);header=dict(native_id=13,island_count=4)
    state=dict(capture_complete=True,document=deepcopy(doc),saved_file_sha256=source,operations=[dict(native_id=31,toolpath_generated=True,toolpath_record_counts=[17]),dict(native_id=48,toolpath_generated=False,toolpath_record_counts=[])],selected_feature=header,feature_setups=[dict(origin=[0,0,0])],operation_setups=[dict(origin=[0,0,26])])
    params=[dict(operation_native_id=i,read_complete=True,tool={'native_id':i+100},nc={'feed':120.})for i in (31,48)]
    d=dict(scope=c.definition.SCOPE,process_id=1234,expected_document_path=str(target),expected_source_sha256=source,expected_feature_native_id=13,evidence=roots[0],save_pin=roots[0],saved_transition={'document':deepcopy(doc)},expected_inventory={'features':[header]},current_sketch_baseline={'saved_file_sha256':source,'needs_save':False,'features':[],'solids':[]},spec={'radius':8},request=dict(process_id=1234,expected_process_create_time=12.5,expected_document_path=str(target),expected_sw_configuration='Default',expected_cam_configuration='Mill',owner_setup_native_id=7),creator=dict(status='uncertain',feature_header=header),sketch={'sketch_readback':{'radius':8}},pins=roots+[predecessor,tp])
    bundle=dict(context=d,state=deepcopy(state),parameters=deepcopy(params),receipt_pin=predecessor,root_pins=roots+[predecessor],pins=d['pins'],lineage_pins=[predecessor])
    expected=dict(inventory=deepcopy(state),parameters=deepcopy(params));observed=deepcopy(expected);report={};calls=[]
    def capture(label):calls.append('capture:'+label);return deepcopy(observed)
    def save():calls.append('Save');target.write_bytes(b'already saved');return 0
    def adopt(new):calls.append('adopt');observed['inventory']['saved_file_sha256']=new['expected_source_sha256'];observed['inventory']['document']['needs_save']=False
    kwargs=dict(capture=capture,save=save,guard=lambda:calls.append('guard'),claim=lambda:calls.append('claim'),persist=lambda:None,adopt_context=adopt)
    return dict(target=target,bundle=bundle,expected=expected,report=report,calls=calls,kwargs=kwargs)


def saved_case(tmp_path,count=2):
    p=make_case(tmp_path,count)
    try:c.save_current_baseline(p['report'],p['bundle'],p['expected'],**p['kwargs'])
    except ValueError:
        assert count==53 and p['report']['model_saved']is True and p['report']['save_readback_verified']is True
    return p


def test_actual_shape_55pins_late_failure_finalizes_without_save_replay(tmp_path):
    p=saved_case(tmp_path,53);assert len(p['bundle']['context']['pins'])==55
    assert 'current_context'not in p['report'];old=deepcopy((p['report'],p['bundle'],p['expected']));calls=list(p['calls']);raw=p['target'].read_bytes()
    out=f.finalize_saved_context(p['report'],p['bundle'],p['expected'])
    assert p['calls']==calls and p['calls'].count('Save')==1 and p['target'].read_bytes()==raw
    assert (p['report'],p['bundle'],p['expected'])==old
    assert len(out['payload']['root_pins'])==54 and len(out['context']['pins'])==55
    assert out['payload']['scope']==f.GENERATED_SCOPE and out['payload']['limitations']==c.LIMITS
    assert out['state']==p['report']['save_snapshots']['after']['inventory']
    assert out['payload']['source_transition']['before_sha256']!=out['payload']['source_transition']['after_sha256']
    assert out['context']['creator']['status']=='uncertain'


@pytest.mark.parametrize('where,value',[
 ('native_return_value',True),('native_return_value',False),('native_return_value',0.0),('native_return_value',1),
 ('native_return_type','bool'),('save_pending',True),('native_call_returned',False),('save_readback_verified',False),('phase','SaveActiveDocument')])
def test_native_save_record_must_be_completed_and_strict(tmp_path,where,value):
    p=saved_case(tmp_path);p['report']['native_save'][where]=value
    with pytest.raises(ValueError):f.finalize_saved_context(p['report'],p['bundle'],p['expected'])
    assert p['calls'].count('Save')==1


@pytest.mark.parametrize('damage',['source','dirty','second_parameter','feature_setup','operation_setup','native_before','predecessor','complete','top_save_flag'])
def test_actual_saved_observations_cannot_be_reconstructed_from_changed_data(tmp_path,damage):
    p=saved_case(tmp_path);r=p['report'];after=r['save_snapshots']['after']
    if damage=='source':r['saved_file_sha256_after_native_return']='b'*64
    elif damage=='dirty':after['inventory']['document']['needs_save']=True
    elif damage=='second_parameter':after['parameters'][1]['nc']['feed']=121.
    elif damage=='feature_setup':after['inventory']['feature_setups'][0]['origin'][2]=26
    elif damage=='operation_setup':after['inventory']['operation_setups'][0]['origin'][2]=0
    elif damage=='native_before':r['native_save']['before']['parameters'][0]['nc']['feed']=121.
    elif damage=='predecessor':r['current_baseline_receipt_pin']['sha256']='b'*64
    elif damage=='complete':after['inventory']['capture_complete']=False
    else:r['model_saved']=False
    with pytest.raises(ValueError):f.finalize_saved_context(r,p['bundle'],p['expected'])


@pytest.mark.parametrize('damage',['target','root'])
def test_current_files_must_match_new_source_and_immutable_roots(tmp_path,damage):
    p=saved_case(tmp_path)
    target=p['target']if damage=='target'else Path(p['bundle']['root_pins'][0]['path']);target.write_bytes(b'tampered')
    with pytest.raises(ValueError):f.finalize_saved_context(p['report'],p['bundle'],p['expected'])


def test_bounded_union_deduplicates_then_caps_unique_and_rejects_conflicts(tmp_path):
    rows=[dict(path=str(tmp_path/(str(i)+'.json')),sha256='a'*64)for i in range(64)]
    assert len(f.merge_pins(rows,deepcopy(rows)))==64
    bad=deepcopy(rows);bad[-1]['sha256']='b'*64
    with pytest.raises(ValueError,match='Conflicting'):f.merge_pins(rows,bad)
    with pytest.raises(ValueError,match='Unique'):f.merge_pins(rows,[dict(path=str(tmp_path/'extra.json'),sha256='a'*64)])
    with pytest.raises(ValueError):f.merge_pins(rows+rows,[])
    bad=deepcopy(rows);bad[-1]['sha256']='invalid'
    with pytest.raises(ValueError):f.merge_pins(rows,bad)
