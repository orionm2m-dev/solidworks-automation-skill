"""移植的离线回归测试；不连接 CAD 进程。"""
from pathlib import Path
import json
import pytest
from scripts import sw_cam_generic_cl_reader as m
'移植的离线回归测试；只使用合成数据和模拟接口。'

@pytest.fixture
def full_circle():
    return b'UNITS/MM\nCUTTER/8,0,19,0,0,0,63\nTLAXIS/0,0,1\nOPFEATSTART/a\nFEDRAT/MMPM,74\nGOTO/2,0,0\nCIRCLE/0,0,0,0,0,1,2,COUNTERCLOCKWISE\nGOTO/2,0,0\nOPFEATEND/a\nFINI\n'

@pytest.mark.parametrize('old,new', [(b',1,2,COUNTERCLOCKWISE', b',1,-2,COUNTERCLOCKWISE'), (b',1,2,COUNTERCLOCKWISE', b',0,2,COUNTERCLOCKWISE'), (b'COUNTERCLOCKWISE', b'UNSPECIFIED'), (b'CIRCLE/0,0,0,0,0,1,2', b'CIRCLE/0,0,0,0,0,1'), (b'CIRCLE/0,0,0', b'CIRCLE/1,0,0'), (b'GOTO/2,0,0\nOPFEATEND', b'GOTO/2,0,1\nOPFEATEND'), (b'GOTO/2,0,0\nOPFEATEND', b'GOTO/3,0,0\nOPFEATEND'), (b'GOTO/2,0,0\nOPFEATEND', b'OPFEATEND'), (b'CIRCLE/0,0,0', b'UNKNOWN/0,0,0'), (b'GOTO/2,0,0\nOPFEATEND', b'RAPID/\nGOTO/2,0,0\nOPFEATEND')])
def test_invalid_or_incomplete_circle_fails_closed(full_circle, old, new):
    r = m.parse_generic_cl_bytes(full_circle.replace(old, new))
    assert not r['parse_complete'] and (r['invalid_commands'] or r['structure_issues'] or r['unknown_commands'])
    assert not r['may_simulate']

def test_partial_circle_uses_conservative_locus_without_invented_sweep(full_circle):
    r = m.parse_generic_cl_bytes(full_circle.replace(b'GOTO/2,0,0\nOPFEATEND', b'GOTO/0,2,0\nOPFEATEND'))
    assert r['parse_complete'] and (not r['circle_records'][0]['coincident_endpoints'])
    assert r['raw_path_envelope_bounds'] == [[-2, -2, 0], [2, 2, 0]]
    assert not r['circle_records'][0]['sweep_angle_interpreted']
