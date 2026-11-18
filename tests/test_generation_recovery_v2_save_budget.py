"""V2 recovery retains the complete authority through the existing Save helper."""
from copy import deepcopy
from pathlib import Path
import pytest
from test_generation_recovery_v2_flow import flow,c

def pins(tmp_path,n):
    return [dict(path=str(tmp_path/('evidence_%03d.json'%i)),sha256=('%064x'%i))for i in range(n)]

@pytest.mark.parametrize('count',[71,76,125])
def test_full_root_union_survives_one_save_and_export(flow,tmp_path,count):
    backend,journal,data,report=flow
    authority=pins(tmp_path,count)
    data['bundle']['root_pins']=deepcopy(authority);data['bundle']['context']['pins']=deepcopy(authority)
    data['save_bundle']=c.current.save_bundle_for_context(data['bundle'])
    assert data['save_bundle']['root_pins']==[]
    result=c.run_backend(backend,journal,data)
    assert result['status']=='review_required'and all(result[k]is True for k in c.FLAGS)
    assert result['current_context']['root_pins']==authority
    assert backend.calls.count('Save')==backend.calls.count('CL')==1
    assert result['GTP_attempted']is False
    assert data['bundle']['root_pins']==authority and data['bundle']['context']['pins']==authority

def test_exact128_union_accepted_and129_rejected(tmp_path):
    p=pins(tmp_path,128)
    assert c.current.pin_union(p,p)==p
    with pytest.raises(ValueError,match='Bounded'):c.current.pin_union(p,pins(tmp_path,129))

def test_conflicting_same_path_hash_cannot_be_deduplicated(tmp_path):
    a=pins(tmp_path,71);b=deepcopy(a[0]);b['sha256']='f'*64
    with pytest.raises(ValueError,match='Conflicting'):c.current.pin_union(a,[b])

def test_saved_union_cannot_omit_prior_root(flow,tmp_path):
    _,_,data,_=flow
    data['bundle']['root_pins']=pins(tmp_path,71);data['bundle']['context']['pins']=pins(tmp_path,70)
    with pytest.raises(ValueError,match='omitted'):c.current.save_bundle_for_context(data['bundle'])

def test_save_reserves_all_future_current_loader_pins(flow,tmp_path):
    _,_,data,_=flow
    p=pins(tmp_path,126);data['bundle']['root_pins']=deepcopy(p);data['bundle']['context']['pins']=deepcopy(p)
    with pytest.raises(ValueError,match='Reserve'):c.current.save_bundle_for_context(data['bundle'])
