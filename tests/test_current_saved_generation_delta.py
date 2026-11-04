from copy import deepcopy
import pytest
from scripts import sw_cam_current_saved_generation_delta as d

def state():
    tool=dict(native_id=44,is_mill_tool=True,cut_diameter_native=8.0)
    rows=[]
    for oid,kind,generated,suppressed,feature in [(11,0,True,False,101),(12,2,False,True,102),(13,0,False,False,102),(14,1,False,False,102)]:
        rows.append(dict(native_id=oid,mill_operation_type=kind,toolpath_generated=generated,suppressed=suppressed,toolpath_record_counts=[17]if generated else[],linked_feature_ids=[feature],setup_native_id=9,assigned_tool=deepcopy(tool)))
    return dict(capture_complete=True,operation_count=4,operation_counts=[4],operations=rows,document=dict(path='part.sldprt',type=1,needs_save=False),parameter_capture_complete=True,operation_parameters=[dict(operation_native_id=oid,operation_type=kind,feature_native_id=102,read_complete=True,tool=dict(generic=deepcopy(tool),holder=dict(length=50.0)),nc=dict(feed=100.0),rough=dict(depth=1.0))for oid,kind in[(13,0),(14,1)]],parameter_batch=dict(read_complete=True,candidate_tool=dict(diameter=8.0),catalogue=[44],consumer_nc={'11':100.0}),profile=dict(steps=[1,2,3]))

def after():
    x=state();r=x['operations'][2];r['toolpath_generated']=True;r['toolpath_record_counts']=[31];x['document']['needs_save']=True;return x

def test_one_selected_generated_exact_delta():
    p=d.verify_generation(state(),after(),[13],[13]);assert p['selected_generated_counts']=={'13':[31]};assert p['suppressed_rows_preserved']

@pytest.mark.parametrize('change',[lambda x:x['operations'][1].update(suppressed=False),lambda x:x['operations'][0].update(toolpath_record_counts=[18]),lambda x:x['operation_parameters'][1]['nc'].update(feed=101.0),lambda x:x['operation_parameters'][0]['nc'].update(feed=101.0),lambda x:x['operations'][2]['assigned_tool'].update(native_id=45),lambda x:x['profile']['steps'].append(4),lambda x:x['parameter_batch']['candidate_tool'].update(diameter=9.0),lambda x:x['operations'].reverse()])
def test_protected_delta_rejected(change):
    x=after();change(x)
    with pytest.raises(ValueError):d.verify_generation(state(),x,[13],[13])

@pytest.mark.parametrize('ids',[[12],[14],[False],[13,13],[999],[]])
def test_invalid_selected_rejected(ids):
    with pytest.raises(ValueError):d.select(state(),ids)

@pytest.mark.parametrize('counts',[[0],[False],[-1],[100001],[1,2],[]])
def test_bad_generated_counts_rejected(counts):
    x=after();x['operations'][2]['toolpath_record_counts']=counts
    with pytest.raises(ValueError):d.verify_generation(state(),x,[13],[13])

def test_total_capacity_rejected_without_truncation():
    x=after();x['operations'][0]['toolpath_record_counts']=[99980]
    with pytest.raises(ValueError,match='capacity'):d.inventory(x)

def test_only_pinned_suppressed_empty_allowed():
    a=state();b=after();assert len(d.cl_rows(a,b,[13],completed_ids=[13]))==2
    b['operations'][1].update(toolpath_generated=True,toolpath_record_counts=[1])
    with pytest.raises(ValueError,match='Suppressed'):d.cl_rows(a,b,[13],completed_ids=[13])

def test_no_silent_unsuppression_projection():
    a=state();b=deepcopy(a);b['operations'][1]['suppressed']=False
    with pytest.raises(ValueError):d.cl_rows(a,b,[13])

def test_save_only_clean_flag_allowed():
    a=after();b=deepcopy(a);b['document']['needs_save']=False
    assert d.verify_saved(a,b)['clean_document']
    b['operation_parameters'][0]['nc']['feed']=200.0
    with pytest.raises(ValueError):d.verify_saved(a,b)

def test_boolean_dirty_exact():
    a=after();a['document']['needs_save']=1
    with pytest.raises(ValueError,match='Boolean|bool|Strict'):d.verify_generation(state(),a,[13],[13])
