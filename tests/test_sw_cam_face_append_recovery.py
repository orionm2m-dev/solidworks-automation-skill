"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
from copy import deepcopy
from pathlib import Path
import importlib.util,json,sys
import pytest
from scripts import sw_cam_raw_mill_face_operation_append_recovery as m


@pytest.fixture
def before():
    from cam_face_test_fixtures import state
    return state(21)
def after(before):
    s=deepcopy(before);s['operation_count']=7;s['operation_counts'][0]=7;s['operation_setups'][0]['operation_count']=7
    s['operations'].append(dict(setup_index=0,setup_native_id=93,operation_index=6,native_id=267,base_operation_type=0,mill_operation_type=20,
      suppressed=False,toolpath_generated=False,linked_feature_ids=[265],toolpath_record_counts=[],assigned_tool=None))
    return s

def test_actual_false_flag_preserved(before):
    a=after(before);copy=deepcopy(a)
    assert m.verify_recovery_delta(before,a,267,265)['assigned_tool'] is None
    assert a==copy and a['document']['needs_save'] is False and before['document']['needs_save'] is False

@pytest.mark.parametrize('change',[
 lambda a:a['document'].update(needs_save=True),lambda a:a['operations'][6].update(linked_feature_ids=[264]),
 lambda a:a['operations'][6].update(mill_operation_type=0),lambda a:a['operations'][6].update(toolpath_generated=True),
 lambda a:a['operations'][5].update(toolpath_record_counts=[192]),lambda a:a['operations'][5]['assigned_tool'].update(protrusion_native=24),
 lambda a:a['operations'][5].update(operation_index=4),lambda a:a['features'][-1]['geometry'].update(depth_native=3.0),
 lambda a:a.update(saved_file_sha256='0'*64),lambda a:a['operations'][6].update(assigned_tool={}),
])
def test_unrelated_or_unproven_change_rejected(before,change):
    a=after(before);change(a)
    with pytest.raises(ValueError):m.verify_recovery_delta(before,a,267,265)

def test_only_qualified_mass_roundoff(before):
    a=after(before);a['sw_reference']['solids'][0]['mass_raw'][0]*=(1+1e-14)
    m.verify_recovery_delta(before,a,267,265)
    a['sw_reference']['solids'][0]['mass_raw'][0]*=1.01
    with pytest.raises(ValueError):m.verify_recovery_delta(before,a,267,265)

def discovery(a):
    rows=deepcopy(a['operations'])
    for row in rows:
        row.pop('assigned_tool');row.pop('toolpath_record_counts')
    return dict(discovered_rows=rows,discovered_setups=deepcopy(a['operation_setups']))

def test_discovery_selects_only_observed_appended_face(before):assert m.verify_discovery(discovery(after(before)),before,265)==267

@pytest.mark.parametrize('change',[
 lambda d:d['discovered_rows'].__delitem__(6),lambda d:d['discovered_rows'][6].update(native_id=247),
 lambda d:d['discovered_rows'][6].update(linked_feature_ids=[265,264]),lambda d:d['discovered_rows'][6].update(setup_native_id=94),
 lambda d:d['discovered_rows'][0].update(suppressed=True),lambda d:d['discovered_rows'][6].update(toolpath_generated=True),
])
def test_discovery_changes_rejected(before,change):
    d=discovery(after(before));change(d)
    with pytest.raises(ValueError):m.verify_discovery(d,before,265)



def request(tmp_path):
    return dict(action='recover_appended_raw_mill_face_operation',params=dict(failed_receipt_path=str(tmp_path/'failed.json'),failed_receipt_sha256='a'*64,discovery_receipt_path=str(tmp_path/'discovery.json'),discovery_receipt_sha256='c'*64,process_id=23824,expected_document_path=str(tmp_path/'part.sldprt'),expected_source_sha256='b'*64,expected_feature_native_id=265,receipt_path=str(tmp_path/'recovery.json'),addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}',module_sha256=m._self_pin()['sha256']))

def test_exact_readonly_request(tmp_path):assert m.validate_request(request(tmp_path))['process_id']==23824

@pytest.mark.parametrize('change',[lambda r:r.update(action='insert_raw_mill_face_operation'),lambda r:r['params'].update(process_id=True),
 lambda r:r['params'].update(assign_tool=249),lambda r:r['params'].update(module_sha256='a'*64)])
def test_request_no_broadening(tmp_path,change):
    r=request(tmp_path);change(r)
    with pytest.raises(ValueError):m.validate_request(r)







def test_previous_requested_order_is_rejected(before):
    value=after(before);new=value['operations'].pop(6);value['operations'].insert(4,new)
    for i,row in enumerate(value['operations']):row['operation_index']=i
    with pytest.raises(ValueError):m.verify_recovery_delta(before,value,267,265)

def test_observed_readonly_parent_cannot_be_omitted(tmp_path):
    value=request(tmp_path);value['params'].pop('discovery_receipt_sha256')
    with pytest.raises(ValueError):m.validate_request(value)
