"""移植的离线回归测试；不连接 CAD 进程。"""
from scripts import sw_cam_straight_cutter_geometry as g
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import pytest
'移植的离线回归测试；只使用合成数据和模拟接口。'
TARGET = dict(EffCutlength=21.0, ShoulderLength=21.0, ShankLength=21.0, NoOfFlutes=4, CutDiameter=8.0, ShoulderDia=8.0, ShankDia=8.0, MillToolShankType=0, Protrusion=25.0, OverallLen=64.0)
ARGS = dict(process_id=23824, target_feature_native_id=244, target_operation_native_id=247, target_operation_setup_native_id=93, expected_candidate_tool_native_id=263, finish_operation_native_id=248, finish_tool_native_id=249)

def line(a, b):
    return dict(read_complete=True, curve_type=0, start_native=[a[0], 0, a[1]], end_native=[b[0], 0, b[1]])

def profile(radius, low, high, split=None):
    lines = [line((0, low), (radius, low)), line((radius, low), (radius, high)), line((radius, high), (0, high))]
    if split is not None:
        lines[1:2] = [line((radius, low), (radius, split)), line((radius, high), (radius, split))]
    return dict(status='observed', declared_chain_count=1, chains=[dict(read_complete=True, declared_curve_count=len(lines), curves=lines)])

@pytest.mark.parametrize('shank', [False, True])
def test_nominal_straight_split_reversed_profile(shank):
    assert g.verify_profile(profile(4, 21 if shank else 0, 64, 40), TARGET, shank_only=shank)['status'] == 'PASS'

@pytest.mark.parametrize('bad', ['chamfer', 'neck', 'gap', 'arc', 'extent', 'radius', 'incomplete', 'nan'])
def test_reject_bad_profiles(bad):
    p = profile(4, 0, 64)
    curves = p['chains'][0]['curves']
    if bad == 'chamfer':
        curves[1]['start_native'] = [3.8, 0, 0.2]
    elif bad == 'neck':
        curves[1]['start_native'][0] = 3
    elif bad == 'gap':
        curves[1]['start_native'][2] = 0.2
    elif bad == 'arc':
        curves[1]['curve_type'] = 1
    elif bad == 'extent':
        curves[1]['end_native'][2] = 65
    elif bad == 'radius':
        curves[1]['end_native'][0] = 4.2
    elif bad == 'incomplete':
        p['chains'][0]['read_complete'] = False
    else:
        curves[1]['end_native'][2] = float('nan')
    with pytest.raises(ValueError):
        g.verify_profile(p, TARGET)

@pytest.mark.parametrize('field,value', [('MillToolShankType', 1), ('MillToolShankType', False), ('NoOfFlutes', True), ('ShankLength', 43), ('CutDiameter', 7), ('Protrusion', 65), ('EffCutlength', 0)])
def test_target_contract(field, value):
    t = dict(TARGET)
    t[field] = value
    with pytest.raises(ValueError):
        g.validate_target(t)
