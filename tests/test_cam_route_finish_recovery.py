"""移植的离线回归测试；不连接 CAD 进程。"""
from cam_route_test_fixtures import state, payload, IDS
from scripts import sw_cam_finish_recovery
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import pytest
'移植的离线回归测试；只使用合成数据和模拟接口。'

def test_exact_observed_delta_and_inputs_unchanged(recovery, case):
    original = deepcopy(case)
    result = recovery.verify_recovery_delta(*case)
    assert isinstance(result, dict)
    assert case == original
    finish = case[3]['finish']['details']['finish']
    assert finish['GetPreviousAllowance']['raw'] == 0.25
    assert finish['SideCutAmt']['raw'] == 3.2
    assert next((x for x in case[2]['operations'] if x['native_id'] == 248))['toolpath_record_counts'] == [74]

@pytest.mark.parametrize('name,value', [('SideCutAmt', 3.0), ('GetPreviousAllowance', 0.3), ('SideAllow', 0.1), ('OverridePrevAllow', True), ('FinalDepthCut', 0.1)])
def test_other_finish_values_rejected(recovery, case, name, value):
    case[3]['finish']['details']['finish'][name]['raw'] = value
    with pytest.raises(ValueError):
        recovery.verify_recovery_delta(*case)

@pytest.mark.parametrize('section', ['levels', 'leads', 'unit_record', 'full_tool'])
def test_other_finish_sections_rejected(recovery, case, section):
    case[3]['finish'][section] = {'unexpected': True}
    with pytest.raises(ValueError):
        recovery.verify_recovery_delta(*case)

def test_rough_payload_change_rejected(recovery, case):
    case[3]['rough']['unexpected'] = True
    with pytest.raises(ValueError):
        recovery.verify_recovery_delta(*case)

@pytest.mark.parametrize('operation_id', [143, 247])
def test_sibling_generation_change_rejected(recovery, case, operation_id):
    row = next((x for x in case[2]['operations'] if x['native_id'] == operation_id))
    row['toolpath_generated'] = True
    row['toolpath_record_counts'] = [192]
    with pytest.raises(ValueError):
        recovery.verify_recovery_delta(*case)

@pytest.mark.parametrize('counts', [[], [74, 1], [0], [-1]])
def test_bad_finish_container_rejected(recovery, case, counts):
    next((x for x in case[2]['operations'] if x['native_id'] == 248))['toolpath_record_counts'] = counts
    with pytest.raises(ValueError):
        recovery.verify_recovery_delta(*case)

def test_source_change_rejected(recovery, case):
    case[2]['saved_file_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        recovery.verify_recovery_delta(*case)

def test_dirty_start_rejected(recovery, case):
    case[0]['document']['needs_save'] = True
    with pytest.raises(ValueError):
        recovery.verify_recovery_delta(*case)

def test_unobserved_old_value_rejected(recovery, case):
    case[1]['finish']['details']['finish']['SideCutAmt']['raw'] = 4.0
    with pytest.raises(ValueError):
        recovery.verify_recovery_delta(*case)

@pytest.fixture
def recovery():
    return sw_cam_finish_recovery

@pytest.fixture
def case():
    before = state()
    bp = payload()
    after = state(True)
    after['document']['needs_save'] = True
    ap = deepcopy(bp)
    ap['finish']['details']['finish']['GetPreviousAllowance']['raw'] = 0.25
    ap['finish']['details']['finish']['SideCutAmt']['raw'] = 3.2
    return (before, bp, after, ap, dict(IDS))

@pytest.fixture
def failed_context(tmp_path):
    from cam_route_test_fixtures import arguments
    args=arguments();args.update(expected_document_path=str(tmp_path/'part.SLDPRT'),receipt_path=str(tmp_path/'receipt.json'))
    base=state();base['document']['path']=args['expected_document_path'];p=payload()
    pin=lambda name:dict(path=str(tmp_path/name),sha256='b'*64)
    loaded=dict(state=base,payload=p['rough'],finish_payload=p['finish'],source_sha256=args['expected_source_sha256'],
      pin=pin('current.json'),pins=[],lineage_pins=[],recovery_module_pin=sw_cam_finish_recovery._self_pin(),
      failed_pin=pin('failed.json'),failed_marker_pin=pin('original_marker.json'),holder_recipe={},historical_only=False)
    return loaded,args

@pytest.mark.parametrize('action',['export_cl','save'])
def test_recovery_marker_cannot_be_reset_by_readonly_receipt(failed_context,action,tmp_path):
    loaded,args=failed_context;a=deepcopy(loaded);b=deepcopy(loaded)
    b['pin']=dict(path=str(tmp_path/'different.json'),sha256='c'*64)
    x=sw_cam_finish_recovery._report(action,a,'recover_readonly',args)
    y=sw_cam_finish_recovery._report(action,b,'recover_readonly',args)
    assert x['marker_path']==y['marker_path']
    original=loaded['failed_pin'];renamed=dict(original,path=str(tmp_path/'renamed.json'))
    assert sw_cam_finish_recovery._marker(action,original,args)==sw_cam_finish_recovery._marker(action,renamed,args)


def test_recovery_export_preflight_failure_preserves_existing_receipt(failed_context,monkeypatch,tmp_path):
    from scripts import sw_cam_mill_generic_cl
    loaded,args=failed_context;p=Path(args['receipt_path']);p.write_bytes(b'prior evidence')
    monkeypatch.setattr(sw_cam_finish_recovery,'load_completed_recovery',lambda *a,**kw:loaded)
    monkeypatch.setattr(sw_cam_mill_generic_cl,'export_mill_generic_cl',lambda *a,**kw:dict(status='error',phase='preflight',readback_verified=False))
    r=sw_cam_finish_recovery.export_cl(None,None,None,checkpoint_receipt_path=loaded['pin']['path'],checkpoint_receipt_sha256=loaded['pin']['sha256'],project_root=str(tmp_path),output_path=str(tmp_path/'output/result.cl'),acknowledge_machine_scope=True,**args)
    assert r['status']=='error' and p.read_bytes()==b'prior evidence'
