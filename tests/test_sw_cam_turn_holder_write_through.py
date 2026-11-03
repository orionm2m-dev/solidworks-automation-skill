"""Synthetic copy-only single-put qualification; never loads a native CAM app."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace as NS

import pytest
from test_sw_cam_turn_holder_dimensions import probe, ref
from scripts import sw_cam_turn_holder_dimensions as cam


@pytest.fixture
def length_probe(probe):
    p=probe
    source=p.tmp_path/'copy_source.sldprt';source.write_bytes(p.copy.read_bytes())
    state=dict(mode='live',getter_calls=0,views=[])
    def get_holder():
        state['getter_calls']+=1
        own=state['getter_calls']%2 == 1
        view=p.Holder()
        if state['mode']=='live' or (state['mode']=='stale_crib' and own):
            object.__setattr__(view,'values',p.first.values)
        else:
            object.__setattr__(view,'values',deepcopy(p.first.values))
        if state['mode']=='shared_crib' and not own:
            object.__setattr__(view,'token',p.other.token)
        state['views'].append(view)
        return view
    p.tool.turn.IGetTurnToolHolder=get_holder
    defaults={k:v for k,v in p.defaults.items() if k!='values_native'}
    defaults.update(copy_source_path=str(source),copy_source_sha256=cam._file_hash(source),
        protected_part_pins=p.defaults['protected_part_pins']+[dict(path=str(source),sha256=cam._file_hash(source))],
        expected_shank_length_native=250.,shank_length_native=200.)
    def prepare(**changes):
        return cam.qualify_turn_holder_write_through(p.sw,'clsid','verified.tlb',**(defaults|dict(action='prepare')|changes))
    def run(prepared=None,**changes):
        if prepared is None:prepared=prepare()
        args=dict(action='probe',expected_state_sha256=prepared.get('state_sha256','0'*64),
            allowed_affected_operations=prepared.get('affected_operations',[ref()]),receipt_path=str(p.receipt))
        return cam.qualify_turn_holder_write_through(p.sw,'clsid','verified.tlb',**(defaults|args|changes))
    return NS(p=p,source=source,state=state,defaults=defaults,prepare=prepare,run=run)


def test_distinct_canonical_views_prepare_without_put(length_probe):
    q=length_probe;r=q.prepare()
    assert r['status']=='prepared' and r['apply_eligible'],r
    assert r['snapshot_diagnostics'][0]['holder_identity_observation']['selected_crib_same_canonical_identity'] is False
    assert not q.p.state['writes'] and not q.p.receipt.exists() and not list(q.p.marker_root.iterdir())
    assert not r['owner_write_through_verified']


def test_one_durable_put_with_fresh_and_retained_full_readback(length_probe):
    q=length_probe;r=q.run()
    assert r['status']=='review_required' and r['owner_write_through_verified'] and r['readback_verified'],r
    assert r['write_through_outcome']=='observed_in_fresh_owner_and_crib'
    assert q.p.state['writes']==[('ShankLength',200.)]
    assert r['native_calls_returned_count']==1 and len(r['setters'])==1
    assert r['length_readback_native']==dict(retained_holder=200.,fresh_own_holder=200.,current_crib_holder=200.)
    assert r['retained_holders_after']['crib'][1]==r['retained_holders_before']['crib'][1]
    assert json.loads(q.p.receipt.read_text(encoding='utf-8'))==r
    for field in ['model_saved','persistence_verified','GOP_attempted','GTP_attempted','tool_assignment_attempted',
            'database_save_attempted','automatic_retry','automatic_rollback','physical_tool_qualified',
            'native_units_verified','storage_independence_verified','all_holder_sharing_qualified','production_qualified']:
        assert r[field] is False


def test_detached_returned_copy_stops_without_commit_or_retry(length_probe):
    q=length_probe;q.state['mode']='detached';r=q.run()
    assert r['status']=='uncertain' and not r['readback_verified'],r
    assert r['write_through_outcome']=='not_persisted_to_observed_owner'
    assert r['length_readback_native']==dict(retained_holder=200.,fresh_own_holder=250.,current_crib_holder=250.)
    assert q.p.state['writes']==[('ShankLength',200.)]


def test_fresh_success_with_stale_retained_crib_is_not_success(length_probe):
    q=length_probe;q.state['mode']='stale_crib';r=q.run()
    assert r['status']=='uncertain' and not r['owner_write_through_verified'],r
    assert r['length_readback_native']['fresh_own_holder']==200.
    assert r['retained_holders_after']['crib'][0]['observed_holder']['dimensions_native']['ShankLength']==250.
    assert len(q.p.state['writes'])==1


def test_known_selected_crib_alias_blocks_even_when_own_identity_differs(length_probe):
    q=length_probe;q.state['mode']='shared_crib';r=q.prepare()
    assert r['status']=='error' and not r['mutation_attempted'],r
    assert not q.p.state['writes'] and not list(q.p.marker_root.iterdir())


@pytest.mark.parametrize('field',['GetHolderThickness','BoringBarDiameter','LeadAngle','HolderShape','Protrusion'])
def test_any_unrequested_selected_holder_coupling_stops(length_probe,field):
    q=length_probe;q.p.state['after_write']=lambda key,value:q.p.first.values.__setitem__(field,1 if field=='HolderShape' else 99.)
    r=q.run()
    assert r['status']=='uncertain' and not r['readback_verified'],r
    assert q.p.state['writes']==[('ShankLength',200.)]


def test_other_tool_holder_hidden_storage_coupling_stops(length_probe):
    q=length_probe;q.p.state['after_write']=lambda key,value:q.p.other.values.__setitem__(key,value)
    r=q.run()
    assert r['status']=='uncertain' and not r['readback_verified'],r
    assert len(q.p.state['writes'])==1


@pytest.mark.parametrize('kind',['features','operations','insert','info','assignment'])
def test_non_holder_metadata_drift_stops(length_probe,kind):
    q=length_probe
    def drift(s):
        if not q.p.state['writes']:return
        if kind=='features':s['linked_features'][0]['segments'][0]['start_native'][0]=99.
        if kind=='operations':s['inventory']['operations'][1]['toolpath_generated']=True
        if kind=='insert':s['selected_tool']['dimensions_native']['NoseRadius']=9.
        if kind=='info':s['selected_tool']['info_raw']='changed'
        if kind=='assignment':s['operation_tools'][0]['tool_native_id']=999
    q.p.state['on_snapshot']=drift;r=q.run()
    assert r['status']=='uncertain' and not r['readback_verified'],r
    assert len(q.p.state['writes'])==1


@pytest.mark.parametrize('change',['copy','source','original','digest','refs','pid','lifetime','old','target','holder','dirty'])
def test_stale_binding_prevents_the_only_put(length_probe,change):
    q=length_probe;p=q.prepare();kw={}
    if change=='copy':q.p.copy.write_bytes(b'drift')
    if change=='source':q.source.write_bytes(b'drift')
    if change=='original':q.p.original.write_bytes(b'drift')
    if change=='digest':kw['expected_state_sha256']='0'*64
    if change=='refs':kw['allowed_affected_operations']=[ref(1)]
    if change=='pid':kw['process_id']=124
    if change=='lifetime':kw['expected_process_create_time']=457.
    if change=='old':kw['expected_shank_length_native']=251.
    if change=='target':kw['shank_length_native']=199.
    if change=='holder':kw['expected_holder_id']=5
    if change=='dirty':q.p.document['needs_save']=True
    r=q.run(p,**kw)
    assert r['status']=='error' and not r['mutation_attempted'] and not q.p.state['writes'],r


def test_target_replaced_same_bytes_after_prepare_cannot_reuse_digest(length_probe):
    q=length_probe;p=q.prepare();old=q.p.copy.with_suffix('.old');q.p.copy.rename(old);q.p.copy.write_bytes(old.read_bytes())
    r=q.run(p)
    assert r['status']=='error' and not q.p.state['writes'],r


def test_protected_source_alias_rejected(length_probe):
    q=length_probe
    r=q.prepare(expected_document_path=str(q.source))
    assert r['status']=='error' and not q.p.state['writes']


def test_generated_shared_operation_blocks_probe(length_probe):
    q=length_probe;q.p.state.update(extra_assignment=True,generated=True)
    p=q.prepare();assert p['status']=='prepared' and not p['apply_eligible']
    r=q.run(p);assert r['status']=='error' and not q.p.state['writes']


def test_native_exception_remains_pending_and_never_retries(length_probe):
    q=length_probe
    def fail(*args):raise RuntimeError('synthetic put timeout')
    q.p.state['on_write']=fail;r=q.run()
    assert r['status']=='uncertain' and r['native_dispatch_pending'] and r['native_calls_returned_count']==0
    assert len(q.p.state['writes'])==1 and not r['automatic_retry'] and not r['automatic_rollback']
    another=q.run(receipt_path=str(q.p.tmp_path/'other.json'))
    assert another['status']=='error' and len(q.p.state['writes'])==1


def test_marker_also_blocks_the_ordinary_writer(length_probe):
    q=length_probe;r=q.run();assert r['readback_verified']
    old=q.p.prepare();assert old['status']=='error' and old['failed_phase']=='preflight'
    assert len(q.p.state['writes'])==1


def test_cleanup_events_revoke_success(length_probe):
    q=length_probe;p=q.prepare();q.p.state['on_exit']=lambda session:setattr(session,'error',1)
    r=q.run(p)
    assert r['status']=='uncertain' and not r['owner_write_through_verified'] and not r['readback_verified']


def test_terminal_receipt_failure_revokes_success(length_probe,monkeypatch):
    q=length_probe;write=cam._write_receipt
    def fail(path,report,**kwargs):
        if report.get('status')=='review_required':raise OSError('synthetic terminal failure')
        return write(path,report,**kwargs)
    monkeypatch.setattr(cam,'_write_receipt',fail);r=q.run()
    assert r['status']=='uncertain' and not r['owner_write_through_verified'] and 'receipt_write_error' in r
    assert len(q.p.state['writes'])==1


@pytest.mark.parametrize('field,value',[('shank_length_native',True),('shank_length_native',float('nan')),
    ('shank_length_native',250.),('expected_shank_length_native',0.),('copy_source_sha256','0'*64),
    ('action','apply'),('qualification_only',1),('receipt_path','C:/old.json')])
def test_invalid_recipe_never_bootstraps(length_probe,field,value):
    q=length_probe;r=q.prepare(**{field:value})
    assert r['status']=='error' and q.p.state['snapshots']==0 and not q.p.state['writes'],r

def test_detached_negative_with_retained_coupling_is_uncertain(length_probe):
    q=length_probe;q.state['mode']='detached'
    def coupled(key,value):q.state['views'][-2].values['LeadAngle']=99.
    q.p.state['after_write']=coupled;r=q.run()
    assert r['status']=='uncertain' and r['write_through_outcome']=='uncertain',r
    assert len(q.p.state['writes'])==1
