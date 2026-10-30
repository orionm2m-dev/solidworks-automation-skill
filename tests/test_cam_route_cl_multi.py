"""移植的离线回归测试；不连接 CAD 进程。"""
from copy import deepcopy
import ast, json
from pathlib import Path
import pytest
from scripts import sw_cam_cl_inventory as inv
from scripts import sw_cam_generic_cl_reader as reader
from scripts import sw_cam_mill_generic_cl as core
from test_sw_cam_mill_generic_cl import probe
'移植的离线回归测试；只使用合成数据和模拟接口。'
CONTRACT = [dict(operation_native_id=214, toolpath_record_counts=[68]), dict(operation_native_id=215, toolpath_record_counts=[11])]

def two_blocks(second_header=True):
    second = 'CUTTER/6,0,20,0,0,0,60\nTLAXIS/0,1,0\n' if second_header else ''
    return ('UNITS/MM\nCUTTER/8,0,21,0,0,0,64\nTLAXIS/0,0,1\nOPFEATSTART/одинаковая подпись\nROTABL/0,AAXIS,TABLE,CCLW\nFEDRAT/MMPM,20\nMOVE_ATTRIB/LEADIN,END_ATTRIB\nGOTO/0,0,0\nOPFEATEND/одинаковая подпись\n' + second + 'OPFEATSTART/одинаковая подпись\nRAPID/\nGOTO/1,0,0\nFEDRAT/MMPM,30\nGOTO/2,0,0\nOPFEATEND/одинаковая подпись\nFINI\n').encode('cp1251')

def test_two_blocks_explicit_counts_reset_every_state():
    r = reader.parse_generic_cl_bytes(two_blocks(), expected_block_record_counts=[4, 4])
    assert r['parse_complete'] and r['block_command_counts'] == [4, 4]
    assert not r['operation_native_ids_inferred_from_labels'] and (not r['block_order_native_qualified'])
    (one, two, three) = r['motions']
    assert one['feed_raw']['value'] == 20 and two['feed_raw'] is None and (three['feed_raw']['value'] == 30)
    assert two['axis_raw'] == [0.0, 1.0, 0.0] and two['cutter_raw'][0] == 6
    assert two['move_attrib_tokens'] == [] and two['rotabl_records_before_motion'] == []
    assert not r['production_qualified'] and (not r['physical_poses_verified'])

@pytest.mark.parametrize('counts', [None, [4], [4, 3], [4, 4, 4]])
def test_default_extra_missing_wrong_blocks_fail(counts):
    kw = {} if counts is None else {'expected_block_record_counts': counts}
    assert not reader.parse_generic_cl_bytes(two_blocks(), **kw)['parse_complete']

@pytest.mark.parametrize('counts', [[], [True, 4], (4, 4), [4, 0], [100001, 4], [4] * 33, [60000, 60000]])
def test_invalid_explicit_block_contract_rejected(counts):
    with pytest.raises(ValueError):
        reader.parse_generic_cl_bytes(two_blocks(), expected_block_record_counts=counts)

def test_both_count_interfaces_rejected():
    with pytest.raises(ValueError):
        reader.parse_generic_cl_bytes(two_blocks(), expected_record_counts=[4], expected_block_record_counts=[4, 4])

@pytest.mark.parametrize('remove', [b'CUTTER/6,0,20,0,0,0,60\n', b'TLAXIS/0,1,0\n', b'RAPID/\n', b'FEDRAT/MMPM,30\n'])
def test_second_block_cannot_inherit_tool_axis_mode_or_feed(remove):
    raw = two_blocks().replace(remove, b'')
    r = reader.parse_generic_cl_bytes(raw, expected_block_record_counts=[4, 4])
    assert not r['parse_complete']
    if remove != b'FEDRAT/MMPM,30\n':
        assert r['invalid_commands']

def test_second_circle_cannot_take_prior_block_start():
    raw = two_blocks().replace(b'RAPID/\nGOTO/1,0,0\n', b'FEDRAT/MMPM,30\nCIRCLE/0,0,0,0,0,1,2,COUNTERCLOCKWISE\n')
    r = reader.parse_generic_cl_bytes(raw, expected_block_record_counts=[4, 4])
    assert not r['parse_complete'] and r['invalid_commands']

def test_second_unknown_or_invalid_command_refused():
    for needle in (b'UNKNOWN/1', b'GOTO/NaN,0,0', b'TLAXIS/0,0,0'):
        r = reader.parse_generic_cl_bytes(two_blocks().replace(b'GOTO/2,0,0', needle), expected_block_record_counts=[4, 4])
        assert not r['parse_complete']

def test_every_block_needs_motion():
    raw = two_blocks().replace(b'RAPID/\nGOTO/1,0,0\nFEDRAT/MMPM,30\nGOTO/2,0,0', b'RAPID/\nRAPID/\nRAPID/\nRAPID/')
    assert not reader.parse_generic_cl_bytes(raw, expected_block_record_counts=[4, 4])['parse_complete']

@pytest.mark.parametrize('change', ['duplicate', 'overlap', 'selected_counts', 'bool_id', 'float_count', 'multi_path', 'extra_field', 'bound'])
def test_strict_inventory_contract(change):
    rows = deepcopy(CONTRACT)
    siblings = []
    if change == 'duplicate':
        rows[1]['operation_native_id'] = 214
    elif change == 'overlap':
        siblings = [215]
    elif change == 'selected_counts':
        rows[0]['toolpath_record_counts'] = [67]
    elif change == 'bool_id':
        rows[1]['operation_native_id'] = True
    elif change == 'float_count':
        rows[1]['toolpath_record_counts'] = [11.0]
    elif change == 'multi_path':
        rows[1]['toolpath_record_counts'] = [10, 1]
    elif change == 'extra_field':
        rows[1]['label'] = 'not identity'
    elif change == 'bound':
        siblings = list(range(1000, 1031))
    with pytest.raises(ValueError):
        inv.generated_operation_contract(214, [68], siblings, rows)

def test_max32_inventory_preserves_existing_bound():
    rows = [dict(operation_native_id=i, toolpath_record_counts=[1]) for i in range(1, 33)]
    assert len(inv.generated_operation_contract(1, [1], [], rows)) == 32
    with pytest.raises(ValueError):
        inv.generated_operation_contract(1, [1], [33], rows)

def enable(probe):
    probe.current['operations'][1].update(toolpath_generated=True, toolpath_record_counts=[11])
    return dict(expected_generated_operations=deepcopy(CONTRACT), expected_ungenerated_operation_ids=[])

def test_two_generated_operations_single_unchanged_native_export(probe):
    kw = enable(probe)
    prepared = probe.call('prepare', **kw)
    assert prepared['status'] == 'ok', prepared
    r = probe.call('apply', **kw, expected_state_sha256=prepared['state_sha256'], receipt_path=str(probe.receipt))
    assert r['status'] == 'review_required' and r['readback_verified'] and (r['before'] == r['after'])
    assert r['before']['expected_generated_operations'] == CONTRACT and (not r['CL_block_order_native_qualified'])
    assert not r['GTP_attempted'] and (not r['model_saved']) and (not r['production_qualified'])
    probe.machine.SaveCLFile.assert_called_once()

@pytest.mark.parametrize('change', ['order', 'count', 'suppressed', 'ungenerated', 'extra', 'missing'])
def test_wrong_generated_inventory_stops_before_export(probe, change):
    kw = enable(probe)
    if change == 'order':
        probe.current['operations'].reverse()
    elif change == 'count':
        probe.current['operations'][1]['toolpath_record_counts'] = [12]
    elif change == 'suppressed':
        probe.current['operations'][1]['suppressed'] = True
    elif change == 'ungenerated':
        probe.current['operations'][1]['toolpath_generated'] = False
    elif change == 'extra':
        probe.current['operations'].append(dict(probe.current['operations'][1], native_id=216))
    elif change == 'missing':
        probe.current['operations'].pop()
    r = probe.call('prepare', **kw)
    assert r['status'] == 'error', r
    probe.machine.SaveCLFile.assert_not_called()

def test_legacy_default_still_refuses_second_generated(probe):
    enable(probe)
    assert probe.call('prepare')['status'] == 'error'
    probe.machine.SaveCLFile.assert_not_called()

def test_protected_generated_count_drift_after_export_is_uncertain(probe):
    kw = enable(probe)
    p = probe.call('prepare', **kw)

    def post():
        probe.output.write_bytes(b'CL')
        probe.current['operations'][1]['toolpath_record_counts'] = [12]
        return 0
    probe.control['on_post'] = post
    r = probe.call('apply', **kw, expected_state_sha256=p['state_sha256'], receipt_path=str(probe.receipt))
    assert r['status'] == 'uncertain' and (not r['readback_verified']) and (not r['automatic_retry_permitted'])
    probe.machine.SaveCLFile.assert_called_once()
