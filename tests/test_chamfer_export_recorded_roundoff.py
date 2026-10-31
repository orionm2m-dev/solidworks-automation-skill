"""Actual recorded body-mass roundoff through unchanged CL/WIP export cores."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import pytest

STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE))
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from scripts import sw_cam_chamfer_exports as exports

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

cl_tests=module('recorded_mass_cl_fixtures',ROOT/'tests/test_chamfer_exports.py')
wip_tests=module('recorded_mass_wip_fixtures',ROOT/'tests/test_chamfer_wip.py')
RECORDED=json.loads((ROOT/'tests/testdata/chamfer_mass_roundoff_v2.json').read_text(encoding='utf-8'))

def actual_observation():
    # Full actual prior observation plus the newly captured actual route.
    observed=deepcopy(RECORDED['before'])
    observed.update(deepcopy(RECORDED['reconciled']))
    return observed

def test_actual_recorded_projection_normalizes_only_mass_and_preserves_raw():
    loaded=deepcopy(RECORDED['loaded']);observed=actual_observation()
    raw=deepcopy(observed)
    normalized,diagnostic=exports.verify_observed(loaded,observed)
    assert normalized==loaded['state'] and observed==raw
    assert diagnostic['relative_tolerance']==1e-12 and diagnostic['absolute_tolerance']==0.
    # Saved R114 versus V2 has ten deltas; prior fresh-before versus V2 has eight.
    assert len(diagnostic['accepted_numeric_deltas'])==10
    assert max(v['relative_delta'] for v in diagnostic['accepted_numeric_deltas'])<1e-12

@pytest.mark.parametrize('kind',['outside_mass','beyond_bound','nonfinite','wrong_shape','protected_count'])
def test_actual_recorded_projection_rejects_non_roundoff_changes(kind):
    loaded=deepcopy(RECORDED['loaded']);observed=actual_observation()
    body=observed['state']['sw_reference']['solids'][0]
    if kind=='outside_mass':body['box_m'][0]+=1e-5
    elif kind=='beyond_bound':body['mass_raw'][0]*=1.+1e-11
    elif kind=='nonfinite':body['mass_raw'][0]=float('nan')
    elif kind=='wrong_shape':body['mass_raw'].append(0.)
    elif kind=='protected_count':observed['state']['operations'][4]['toolpath_record_counts'][0]+=1
    with pytest.raises(ValueError):exports.verify_observed(loaded,observed)

def inject_recorded_pair(f):
    reference=deepcopy(RECORDED['before']['state']['sw_reference'])
    actual=deepcopy(RECORDED['reconciled']['state']['sw_reference'])
    f.loaded['state']['sw_reference']=reference
    f.loaded['current_context_sha256']=exports._digest(exports.group.current_projection(f.loaded))
    def drift(label,observed):
        # Both native-read values are from the failed real V2 receipt.
        observed['state']['sw_reference']=deepcopy(actual if len(f.control.labels)%2 else reference)
    f.control.drift=drift
    return reference,actual

def check_evidence(f,result,reference,actual):
    assert result['readback_verified'] is True,result
    assert result['before']==result['after']
    assert f.control.calls==1
    raw=json.loads(Path(f.args['receipt_path']).with_suffix('.observations.json').read_text())
    assert raw['observations'][0]['state']['sw_reference']==actual
    for i,row in enumerate(raw['observations']):
        assert row['state']['sw_reference']==(actual if i%2==0 else reference)
    assert actual!=reference
    assert all(result[k] is False for k in ('GTP_attempted','GOP_attempted','model_saved','setter_attempted'))

def test_real_cl_core_accepts_recorded_pair_without_dropping_raw(tmp_path,monkeypatch):
    f=cl_tests.case.__wrapped__(tmp_path,monkeypatch)
    reference,actual=inject_recorded_pair(f)
    result=cl_tests.run(f)
    check_evidence(f,result,reference,actual)
    assert len(f.control.labels)==3 and result['before']['mill_state']['sw_reference']==reference

def test_real_wip_core_accepts_recorded_pair_without_dropping_raw(tmp_path,monkeypatch):
    f=wip_tests.case.__wrapped__(tmp_path,monkeypatch)
    reference,actual=inject_recorded_pair(f)
    result=wip_tests.run(f)
    check_evidence(f,result,reference,actual)
    assert f.control.labels==['before','after'] and result['before']['sw_reference']==reference
