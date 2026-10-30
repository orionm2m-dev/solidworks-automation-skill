"""Pinned index/name and linked-chain diagnostics; synthetic interfaces only."""
from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import Mock
import hashlib
import json
import pytest
from profile_probe_fixtures import feature
from scripts import sw_cam_mill_profile_indexed as m
from scripts import sw_cam_events as events


@pytest.fixture
def route(feature,tmp_path):
    names=['Face'+str(i) for i in range(6)]
    feature.profile.GetSketchCount=lambda:6
    feature.profile.GetSketchNameList=lambda:tuple(names)
    start=N(GetCoordinates=lambda:(0.,0.,0.));end=N(GetCoordinates=lambda:(1.,0.,0.))
    curve=N(GetTypeOfCurve=lambda:0,GetStart=lambda:start,GetEnd=lambda:end)
    chain=N(IGetNumChains=lambda:1,GetNumOfCurves=lambda:1,
            GetCurveAtIndex=lambda index:curve,IGetNextChain=lambda:None)
    feature.profile.GetSketchNameListAt=lambda index:names[index]
    feature.profile.GetSegmentChain=lambda index:chain
    mapping=[dict(native_index=i,expected_sketch_name=name) for i,name in enumerate(names)]
    state=feature.run()
    part=tmp_path/'part.sldprt';part.write_bytes(b'unchanged source')
    source=m._file_hash(part)
    doc=dict(path=str(part),title=part.name,type=1,needs_save=False)
    messages=dict(subscribed=True,disconnected=True,active=False,event_count=0,overflow=0,
        callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    data=dict(status='review_required',phase='finished',process_id=731,read_only=True,
        profile_read_complete=True,readback_verified=True,profile_headers_read_complete=True,
        representation_readback_verified=True,saved_file_sha256=source,document=doc,
        selected=feature.selected,messages=messages,before=state,after=deepcopy(state),state_sha256=m._digest(state))
    for key in ('mutation_attempted','AFR_attempted','GOP_attempted','GTP_attempted','model_saved',
                'TechDB_write_attempted','post_cleanup_CAM_getters','include_contours','profile_geometry_complete'):
        data[key]=False
    receipt=tmp_path/'headers.json'
    def write():
        receipt.write_text(json.dumps(data),encoding='utf-8')
        return hashlib.sha256(receipt.read_bytes()).hexdigest()
    sha=write()
    def load():
        return m.load_profile_headers_anchor(str(receipt),write(),process_id=731,
            expected_document_path=str(part),expected_source_sha256=source,
            selected=feature.selected,index_mapping=mapping)
    anchor=load()
    boundary=Mock();progress=Mock();diagnostic={}
    def run():
        return m.read_profile_indexed_chains(feature.doc,selected=feature.selected,
            index_mapping=mapping,anchor=anchor,read=feature.read,typed=feature.typed,
            boundary=boundary,diagnostic=diagnostic,progress=progress)
    feature.calls.clear()
    return N(**locals())


def test_explicit_mapping_names_before_chain_and_no_outer_role_assumption(route):
    out=route.run()
    assert out['read_complete'] and len(out['indexed_chains'])==6
    assert all(x['name_matches'] and x['read_complete'] and x['geometric_role']=='unknown'
               for x in out['indexed_chains'])
    calls=[(name,args) for _,name,args in route.feature.calls]
    for i in range(6):
        assert calls.index(('GetSketchNameListAt',(i,)))<calls.index(('GetSegmentChain',(i,)))
        assert calls.count(('GetSegmentChain',(i,)))==1
    assert route.diagnostic['geometry_budget']['curves']==6
    assert not out['geometric_role_mapping_verified'] and not out['universal_index_base_verified']
    assert not any(name=='QI ICWDispatchCollection' for name,args in calls)


def test_an_explicit_one_based_mapping_does_not_trigger_automatic_alternatives(route):
    for row in route.mapping:row['native_index']+=1
    route.feature.profile.GetSketchNameListAt=lambda index:route.names[index-1]
    out=route.run()
    assert [x['native_index'] for x in out['indexed_chains']]==[1,2,3,4,5,6]
    assert not any(name=='GetSketchNameListAt' and args==(0,) for _,name,args in route.feature.calls)


@pytest.mark.parametrize('mode',['name_mismatch','name_error','null_chain','chain_error',
 'unsupported_chain','changed_headers','malformed_curve','changed_owner'])
def test_stop_without_fallback_and_keep_partial(route,mode):
    if mode=='name_mismatch':route.feature.profile.GetSketchNameListAt=lambda _:route.names[1]
    if mode=='name_error':
        def fail(_):raise ValueError('E_INVALIDARG')
        route.feature.profile.GetSketchNameListAt=fail
    if mode=='null_chain':route.feature.profile.GetSegmentChain=lambda _:None
    if mode=='chain_error':
        def fail(_):raise ValueError('E_INVALIDARG')
        route.feature.profile.GetSegmentChain=fail
    if mode=='unsupported_chain':
        typed=route.feature.typed
        def fail(raw,name):
            if name=='ICWSegChain':raise ValueError('E_NOINTERFACE')
            return typed(raw,name)
        route.feature.typed=fail
    if mode=='changed_headers':route.feature.profile.GetSketchCount=lambda:5
    if mode=='malformed_curve':route.curve.GetTypeOfCurve=lambda:99
    if mode=='changed_owner':route.feature.owner.id=70
    with pytest.raises(ValueError):route.run()
    assert not route.diagnostic['state']['read_complete']
    calls=[(name,args) for _,name,args in route.feature.calls]
    assert not any(name=='GetSketchNameListAt' and args==(1,) for name,args in calls)
    if mode in ('name_mismatch','name_error','changed_headers','changed_owner'):
        assert not any(name=='GetSegmentChain' for name,args in calls)


def test_linked_list_boundaries_cover_each_chain_not_just_each_index(route):
    following=N(IGetNumChains=lambda:2,GetNumOfCurves=lambda:1,
                GetCurveAtIndex=lambda _:route.curve,IGetNextChain=lambda:None)
    route.chain.IGetNumChains=lambda:2
    route.chain.IGetNextChain=lambda:following
    route.mapping[:]=route.mapping[:1]
    out=route.run()
    assert len(out['indexed_chains'][0]['contour']['chains'])==2
    labels=[c.args[0] for c in route.boundary.call_args_list]
    assert labels.count('linked_chain_before:0')==2
    assert labels.count('linked_chain_after:0')==2


def test_pinned_completed_headers_load_and_remain_pinned(route):
    anchor=route.load()
    assert anchor['names']==route.names
    route.receipt.write_bytes(route.receipt.read_bytes()+b' ')
    with pytest.raises(ValueError):m.check_anchor_files(anchor)


@pytest.mark.parametrize('mode',['pid','source','partial','mutation','cleanup','unequal',
 'digest','name_absent','index_beyond_count','unstructured_names','selected','dirty'])
def test_anchor_rejects_stale_or_incomplete_context(route,mode):
    d=route.data
    if mode=='pid':d['process_id']=732
    if mode=='source':d['saved_file_sha256']='a'*64
    if mode=='partial':d['profile_headers_read_complete']=False
    if mode=='mutation':d['GOP_attempted']=True
    if mode=='cleanup':d['messages']['disconnected']=False
    if mode=='unequal':d['after']['island_count']=4
    if mode=='digest':d['state_sha256']='a'*64
    if mode=='name_absent':route.mapping[0]['expected_sketch_name']='Not pinned'
    if mode=='index_beyond_count':route.mapping[0]['native_index']=7
    if mode=='unstructured_names':
        d['before']['sketch_names']['value']='CSV not parsed'
        d['after']=deepcopy(d['before']);d['state_sha256']=m._digest(d['before'])
    if mode=='selected':d['selected']=dict(d['selected'],feature_native_id=80)
    if mode=='dirty':d['document']['needs_save']=True
    with pytest.raises(ValueError):route.load()


@pytest.fixture
def wrapper(route,monkeypatch):
    receipt=route.tmp_path/'indexed.json'
    flags=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,
        callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    knobs=dict(capture=None,exit=None)
    class Session:
        def __enter__(self):flags.update(subscribed=True,active=True);return self
        def __exit__(self,*_):
            flags.update(active=False,disconnected=True)
            if knobs['exit']:knobs['exit']()
        def summary(self):return deepcopy(flags)
    state=dict(read_complete=True,indexed_chains=[dict(native_index=0)],headers=route.state)
    calls=[]
    def capture(*args,**kwargs):
        kwargs['check']();calls.append(True)
        kwargs['diagnostic']['entered']=True;kwargs['progress']()
        if knobs['capture']:knobs['capture']()
        kwargs['check']()
        return deepcopy(state)
    sw=N(GetProcessID=lambda:731)
    monkeypatch.setattr(m,'raw_part_identity',lambda *_:deepcopy(route.doc))
    bootstrap=Mock(return_value=object());monkeypatch.setattr(m,'_bootstrap',bootstrap)
    monkeypatch.setattr(m,'capture_profile_indexed_chains',capture)
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    kwargs=dict(process_id=731,expected_document_path=str(route.part),expected_source_sha256=route.source,
        expected_feature_native_id=79,expected_owner_setup_native_id=69,expected_volume_type=2,
        expected_shape=2,expected_island_count=5,qualification_only=True,
        acknowledge_disposable_copy=True,receipt_path=str(receipt),
        profile_headers_receipt_path=str(route.receipt),profile_headers_receipt_sha256=route.sha,
        index_mapping=route.mapping)
    def run(**override):return m.inspect_mill_profile_indexed(sw,'clsid','tlb',**(kwargs|override))
    return N(**locals())


def test_wrapper_two_equal_snapshots_clean_cleanup_no_manufacturing_claim(wrapper):
    out=wrapper.run()
    assert out['status']=='review_required' and out['readback_verified']
    assert out['selected_chains_read_complete'] and len(wrapper.calls)==2
    assert out['selected_index_name_mapping_verified']
    for key in ('universal_index_base_verified','geometric_role_mapping_verified',
                'physical_geometry_verified','production_qualified','full_inventory_verified',
                'mutation_attempted','model_saved','post_cleanup_CAM_getters','GTP_attempted','GOP_attempted'):
        assert out[key] is False
    assert json.loads(wrapper.receipt.read_text())==out


@pytest.mark.parametrize('mode',['pid','receipt_sha','bool_index','duplicate_index','name_absent',
 'event','different_capture','capture_error','cleanup','source_change','persist'])
def test_wrapper_failure_never_authorizes_success(wrapper,mode,monkeypatch):
    extra={}
    if mode=='pid':extra['process_id']=732
    if mode=='receipt_sha':extra['profile_headers_receipt_sha256']='a'*64
    if mode=='bool_index':extra['index_mapping']=[dict(native_index=True,expected_sketch_name='Face0')]
    if mode=='duplicate_index':extra['index_mapping']=[wrapper.route.mapping[0]]*2
    if mode=='name_absent':extra['index_mapping']=[dict(native_index=0,expected_sketch_name='Unknown')]
    if mode=='event':wrapper.knobs['capture']=lambda:wrapper.flags.update(event_count=1)
    if mode=='different_capture':
        def change():
            if len(wrapper.calls)==2:wrapper.state['indexed_chains'][0]['native_index']=1
        wrapper.knobs['capture']=change
    if mode=='capture_error':
        def fail():raise ValueError('E_INVALIDARG')
        wrapper.knobs['capture']=fail
    if mode=='cleanup':wrapper.knobs['exit']=lambda:wrapper.flags.update(disconnect_errors=['error'])
    if mode=='source_change':wrapper.knobs['capture']=lambda:wrapper.route.part.write_bytes(b'changed')
    if mode=='persist':
        write=m._write_receipt
        def fail(path,result,**kw):
            if result.get('readback_verified'):raise OSError('persist failure')
            return write(path,result,**kw)
        monkeypatch.setattr(m,'_write_receipt',fail)
    out=wrapper.run(**extra)
    assert out['status']=='error' and not out['readback_verified']
    assert not out['selected_chains_read_complete'] and not out['selected_index_name_mapping_verified']
    if mode in ('pid','receipt_sha','bool_index','duplicate_index','name_absent'):
        wrapper.bootstrap.assert_not_called()


def test_batched_capture_checks_identity_at_all_linked_chain_boundaries(route,monkeypatch):
    sw=N(GetProcessID=lambda:731)
    app=N(IGetActiveDoc=lambda:route.feature.doc)
    identity=Mock(side_effect=lambda *_:deepcopy(route.doc))
    monkeypatch.setattr(m,'raw_part_identity',identity)
    monkeypatch.setattr(m,'_typed',lambda raw,name,path:route.feature.typed(raw,name))
    diagnostic={};check=Mock()
    out=m.capture_profile_indexed_chains(sw,app,'tlb',process_id=731,
        expected_document_path=str(route.part),expected_source_sha256=route.source,
        baseline=route.doc,selected=route.feature.selected,index_mapping=route.mapping,anchor=route.anchor,
        check=check,diagnostic=diagnostic,progress=Mock())
    assert out['read_complete']
    assert identity.call_count==diagnostic['identity_boundary_count']==30
    assert diagnostic['native_read_count']>identity.call_count
    assert diagnostic['guard_policy']==m.GUARD_POLICY


def test_mid_chain_document_change_is_rejected_before_chain_completion(route,monkeypatch):
    sw=N(GetProcessID=lambda:731);app=N(IGetActiveDoc=lambda:route.feature.doc)
    baseline=deepcopy(route.doc)
    monkeypatch.setattr(m,'raw_part_identity',lambda *_:deepcopy(route.doc))
    monkeypatch.setattr(m,'_typed',lambda raw,name,path:route.feature.typed(raw,name))
    def altered():
        route.doc['needs_save']=True
        return 1
    route.chain.GetNumOfCurves=altered
    diagnostic={}
    with pytest.raises(ValueError):
        m.capture_profile_indexed_chains(sw,app,'tlb',process_id=731,
            expected_document_path=str(route.part),expected_source_sha256=route.source,
            baseline=baseline,selected=route.feature.selected,index_mapping=route.mapping,anchor=route.anchor,
            check=lambda:None,diagnostic=diagnostic,progress=Mock())
    assert not diagnostic['state']['indexed_chains'][0]['read_complete']
