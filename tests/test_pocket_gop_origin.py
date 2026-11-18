"""Pure GOP origin parity with the current definition capture."""
from copy import deepcopy
import pytest
from scripts import sw_cam_pocket_gop_evidence as e
from test_pocket_gop_evidence import packet,load,write


def set_origin(packet,variant,kind):
    c,r,p,marker=packet;c['request']={'source_variant':variant};c['origin_kind']=kind
    for state in (r['before'],r['after']):state['definition_authority']['origin_kind']=kind
    r['state_sha256']=e._digest(dict(snapshot=r['before'],process_id=c['process_id'],expected_feature_native_id=c['expected_feature_native_id'],scope='MILL_SINGLE_FEATURE_GOP_RETAIN1'))
    marker['state_sha256']=r['state_sha256'];write(c['marker'],marker)
    for row,state in zip(r['snapshot_diagnostics'],(r['before'],r['before'],r['after'])):row['state']=deepcopy(state)


@pytest.mark.parametrize('variant,kind',[('saved_cam_caps','recovery'),('saved_cam_caps','creator'),('legacy','creator')])
def test_current_capture_origin_is_exact_expected_and_consumed(packet,variant,kind):
    set_origin(packet,variant,kind);c,r,p,marker=packet;original=deepcopy(r)
    assert e.expected_before(c)==r['before']
    assert load(packet)['gop']==original and r==original


@pytest.mark.parametrize('observed',[None,'creator','unknown'])
def test_missing_or_wrong_saved_caps_origin_is_rejected(packet,observed):
    set_origin(packet,'saved_cam_caps','recovery');r=packet[1]
    if observed is None:r['before']['definition_authority'].pop('origin_kind')
    else:r['before']['definition_authority']['origin_kind']=observed
    with pytest.raises(ValueError,match='exact recovered/saved definition'):load(packet)


def test_legacy_recovery_keeps_previous_authority_shape(packet):
    c,r,p,marker=packet;c['request']={};c['origin_kind']='recovery'
    assert 'origin_kind' not in e.expected_before(c)['definition_authority']
    assert load(packet)['gop']==r


def test_saved_caps_missing_context_origin_does_not_fallback(packet):
    packet[0]['request']={'source_variant':'saved_cam_caps'}
    with pytest.raises(KeyError):e.expected_before(packet[0])
