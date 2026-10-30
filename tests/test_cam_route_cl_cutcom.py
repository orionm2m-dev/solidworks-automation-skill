"""移植的离线回归测试；不连接 CAD 进程。"""
from pathlib import Path
import pytest
from scripts import sw_cam_generic_cl_reader as m
'移植的离线回归测试；只使用合成数据和模拟接口。'

def program(middle):
    return ('UNITS/MM\nCUTTER/8,0,4,0,0,0,64\nTLAXIS/0,0,1\nOPFEATSTART/a\nFEDRAT/MMPM,10\nGOTO/2,0,0\n' + middle + 'OPFEATEND/a\nFINI\n').encode()

@pytest.mark.parametrize('side', ['LEFT', 'RIGHT'])
def test_state_is_attached_to_each_motion_but_no_coordinate_offset(side):
    result = m.parse_generic_cl_bytes(program('CUTCOM/ON\nCUTCOM/' + side + '\nGOTO/0,2,0\nCUTCOM/OFF\nGOTO/2,0,0\n'))
    assert result['parse_complete']
    assert result['motions'][1]['xyz'] == [0.0, 2.0, 0.0]
    assert result['motions'][1]['cutcom_state']['side'] == side
    assert result['motions'][2]['cutcom_state']['enabled'] is False
    assert not result['motions'][1]['cutcom_state']['coordinate_offset_applied']

@pytest.mark.parametrize('body', ['CUTCOM/LEFT\n', 'CUTCOM/OFF\n', 'CUTCOM/ON\nCUTCOM/ON\n', 'CUTCOM/ON\nGOTO/0,2,0\n', 'CUTCOM/ON\nCUTCOM/LEFT\n', 'CUTCOM/ON\nCUTCOM/LEFT\nCUTCOM/RIGHT\nCUTCOM/OFF\n', 'CUTCOM/ON,LEFT\n', 'CUTCOM/ON\nCUTCOM/LEFT,4\n', 'CUTCOM/ON\nCUTCOM/WEAR\n', 'CUTCOM/ON\n'])
def test_unknown_or_incomplete_cutcom_fails_closed(body):
    result = m.parse_generic_cl_bytes(program(body))
    assert not result['parse_complete'] and (result['invalid_commands'] or result['structure_issues'])
    assert not result['may_simulate']

def test_cutcom_outside_operation_is_rejected():
    result = m.parse_generic_cl_bytes(b'CUTCOM/ON\n' + program(''))
    assert not result['parse_complete']

def test_coincident_circle_has_no_implicit_one_turn():
    result = m.parse_generic_cl_bytes(program('CIRCLE/0,0,0,0,0,1,2,COUNTERCLOCKWISE\nGOTO/2,0,0\n'))
    assert result['parse_complete']
    c = result['circle_records'][0]
    assert c['sweep_classification'] == 'coincident_planar_circle_unqualified'
    assert c['turn_count'] is None and (not c['sweep_angle_interpreted'])
    assert not c['preceding_same_circle_geometry'] and (not c['full_circle_qualified'])
