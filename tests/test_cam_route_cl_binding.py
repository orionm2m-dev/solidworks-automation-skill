"""移植的离线回归测试；不连接 CAD 进程。"""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts import sw_cam_generic_cl_reader as reader
from test_cam_route_cl_multi import two_blocks
'移植的离线回归测试；只使用合成数据和模拟接口。'

@pytest.fixture
def multi_args(tmp_path):
    contract = [dict(operation_native_id=247, toolpath_record_counts=[4]), dict(operation_native_id=248, toolpath_record_counts=[4])]
    operations = [dict(native_id=r['operation_native_id'], toolpath_generated=True, toolpath_record_counts=r['toolpath_record_counts'], suppressed=False) for r in contract]
    operations.insert(0, dict(native_id=143, toolpath_generated=False, toolpath_record_counts=[], suppressed=False))
    before = dict(mill_state=dict(operations=operations, saved_file_sha256='a' * 64), selected_operation_native_id=248, expected_toolpath_record_counts=[4], expected_generated_operations=contract, expected_ungenerated_operation_ids=[143])
    raw = two_blocks()
    cl = tmp_path / 'output.cl'
    cl.write_bytes(raw)
    receipt = dict(status='review_required', phase='finished', readback_verified=True, output_verified=True, native_call_attempted=True, native_call_returned=True, native_dispatch_pending=False, native_hresult=0, messages=dict(subscribed=True, disconnected=True, active=False), before=before, after=deepcopy(before), productionNC=False, GTP_attempted=False, output=dict(sha256=reader._file_hash(cl), bytes=len(raw)), export_scope='synthetic test only')
    rp = tmp_path / 'export.json'
    rp.write_text(json.dumps(receipt), encoding='utf-8')
    return dict(export_receipt_path=str(rp), export_receipt_sha256=reader._file_hash(rp), cl_path=str(cl), cl_sha256=reader._file_hash(cl), expected_operation_native_id=248, output_path=str(tmp_path / 'analysis.json'), expected_generated_operations=contract, expected_ungenerated_operation_ids=[143])

def test_multi_export_reader_binding(multi_args):
    r = reader.analyze_exported_generic_cl(**multi_args)
    assert r['parse_complete'] and r['native_calls'] == 0
    report = json.loads(Path(r['report']['path']).read_text())
    assert report['expected_block_operation_ids'] == [247, 248]
    assert not report['operation_block_association_verified'] and (not report['block_order_native_qualified'])

@pytest.mark.parametrize('change', ['reorder', 'count', 'missing_remaining', 'old_default', 'extra_block'])
def test_wrong_reader_contract_rejected(multi_args, change):
    if change == 'reorder':
        multi_args['expected_generated_operations'].reverse()
    elif change == 'count':
        multi_args['expected_generated_operations'][0]['toolpath_record_counts'] = [5]
    elif change == 'missing_remaining':
        multi_args['expected_ungenerated_operation_ids'] = []
    elif change == 'old_default':
        multi_args.pop('expected_generated_operations')
        multi_args.pop('expected_ungenerated_operation_ids')
    elif change == 'extra_block':
        multi_args['expected_generated_operations'].append(dict(operation_native_id=249, toolpath_record_counts=[4]))
    with pytest.raises(ValueError):
        reader.analyze_exported_generic_cl(**multi_args)
    assert not Path(multi_args['output_path']).exists()
