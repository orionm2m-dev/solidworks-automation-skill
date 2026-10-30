"""移植的离线回归测试；不连接 CAD 进程。"""
from pathlib import Path
import json, math
import pytest
from scripts import sw_cam_generic_cl_reader as m
'移植的离线回归测试；只使用合成数据和模拟接口。'

def helix(end='-3,0,-1.5', center='0,0,0', normal='0,0,1', axis='0,0,1', direction='COUNTERCLOCKWISE'):
    return f'UNITS/MM\nCUTTER/8,0,19,0,0,0,63\nTLAXIS/{axis}\nOPFEATSTART/a\nFEDRAT/MMPM,37\nGOTO/3,0,0\nCIRCLE/{center},{normal},3,{direction}\nGOTO/{end}\nOPFEATEND/a\nFINI\n'.encode()

@pytest.mark.parametrize('end,expected_angle,expected_pitch', [('-3,0,-1.5', 180, 3), ('0,3,-.75', 90, 3), ('0.623735,2.934443,-.65', 78, 3)])
def test_observed_minor_arcs_and_pitch(end, expected_angle, expected_pitch):
    r = m.parse_generic_cl_bytes(helix(end))
    assert r['parse_complete']
    c = r['circle_records'][0]
    assert math.degrees(c['angle_raw_rad']) == pytest.approx(expected_angle, abs=1e-05)
    assert c['pitch_raw_per_rev'] == pytest.approx(expected_pitch, abs=2e-06)
    assert c['helical_envelope_bounds_raw'] == [[-3, -3, float(end.split(',')[2])], [3, 3, 0]]

@pytest.mark.parametrize('kw', [{'direction': 'CLOCKWISE'}, {'normal': '0,0,-1'}, {'normal': '0,1,0'}, {'axis': '0,1,0'}, {'end': '-3,0,1.5'}, {'end': '3,0,-1.5'}, {'end': '0,-3,-1.5'}, {'end': '-3.01,0,-1.5'}, {'center': '0,0,.5'}, {'end': 'NaN,0,-1.5'}])
def test_unobserved_or_inconsistent_helix_stays_incomplete(kw):
    r = m.parse_generic_cl_bytes(helix(**kw))
    assert not r['parse_complete'] and r['invalid_commands']

def test_tilted_planar_circle_preserves_previous_behavior():
    r = m.parse_generic_cl_bytes(helix(end='0,0,3', normal='0,1,0'))
    assert r['parse_complete'] and r['helix_count'] == 0
    assert r['circle_records'][0]['full_circle_locus_bounds_raw'] == [[-3, 0, -3], [3, 0, 3]]
