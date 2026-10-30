"""Exact-feature probe tests; native interfaces are simulated."""
from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import Mock
import json
import pytest
from scripts import sw_cam_mill_volume_islands as m
from scripts import sw_cam_events as events


@pytest.fixture
def feature():
    start=N(GetCoordinates=lambda:(0.,0.,0.))
    end=N(GetCoordinates=lambda:(1.,0.,0.))
    curve=N(GetTypeOfCurve=lambda:0,GetStart=lambda:start,GetEnd=lambda:end)
    chain=N(IGetNumChains=lambda:1,GetNumOfCurves=lambda:1,
            GetCurveAtIndex=lambda index:curve,IGetNextChain=lambda:None)
    islands=[N(GetStartPosition=lambda:start,GetDepth=lambda:2.,
        IGetTopSegChain=lambda:chain,IGetBottomSegChain=lambda:chain,
        IGetWallSegChain=lambda:chain) for _ in range(5)]
    collection=N(Count=5,Item=lambda index:islands[index])
    owner=N(id=69)
    base=N(id=79,GetOwner=lambda:owner,Suppressed=False)
    mill=N(VolumeType=2,Shape=2,IGetIslandCount=lambda:5)
    volume=N(IGetIslands=lambda:collection)
    doc=N(GetCWObjectFromID=lambda kind,oid:(base,True),
          GetCWObjectID=lambda obj:(obj.id,True))
    selected=dict(feature_native_id=79,owner_setup_native_id=69,
                  volume_type=2,shape=2,island_count=5,include_contours=True)
    calls=[]
    def read(obj,name,*args):
        calls.append((obj,name,args))
        value=getattr(obj,name)
        return value(*args) if callable(value) else value
    def typed(raw,name):
        calls.append((raw,'QI '+name,()))
        if name=='ICWMillFeature':return mill
        if name=='ICWVolumeFeature':return volume
        return raw
    diagnostic={}
    progress=Mock()
    def run():return m.read_volume_feature_islands(doc,selected=selected,read=read,
        typed=typed,diagnostic=diagnostic,progress=progress)
    return N(**locals())


def test_exact_volume_path_reads_all_five_islands_and_contours(feature):
    result=feature.run()
    assert result['read_complete'] and result['declared_count']==5
    assert len(result['items'])==5 and result['all_contours_available']
    assert feature.diagnostic['geometry_budget']==dict(curves=15,chains=15,islands=5)
    assert all(i['read_complete'] and set(i['contours'])=={'top','bottom','wall'}
               for i in result['items'])
    island_calls=[obj for obj,name,args in feature.calls if name=='IGetIslands']
    assert island_calls==[feature.volume]
    assert (feature.doc,'GetCWObjectFromID',(1,79)) in feature.calls
    assert not any('Faces' in name or name.startswith('Set') for _,name,_ in feature.calls)
    assert feature.progress.call_count==25


@pytest.mark.parametrize('mode',[
 'lookup_status','lookup_shape','identity','owner','suppressed','volume_type','shape',
 'count','null_collection','collection_count','unsupported_volume','unsupported_island',
 'changed_collection','changed_feature_count','bad_curve','negative_depth_nan'])
def test_bad_identity_or_representation_stops_without_fallback(feature,mode):
    if mode=='lookup_status':feature.doc.GetCWObjectFromID=lambda *_:(feature.base,False)
    if mode=='lookup_shape':feature.doc.GetCWObjectFromID=lambda *_:feature.base
    if mode=='identity':feature.base.id=80
    if mode=='owner':feature.owner.id=70
    if mode=='suppressed':feature.base.Suppressed=0
    if mode=='volume_type':feature.mill.VolumeType=3
    if mode=='shape':feature.mill.Shape=3
    if mode=='count':feature.mill.IGetIslandCount=lambda:4
    if mode=='null_collection':feature.volume.IGetIslands=lambda:None
    if mode=='collection_count':feature.collection.Count=4
    if mode in ('unsupported_volume','unsupported_island'):
        target='ICWVolumeFeature' if mode=='unsupported_volume' else 'ICWIslandInfo'
        typed=feature.typed
        def broken(raw,name):
            if name==target:raise ValueError('E_NOINTERFACE '+target)
            return typed(raw,name)
        # Rebind the run callback explicitly; no alternate interface route.
        feature.run=lambda:m.read_volume_feature_islands(feature.doc,selected=feature.selected,
            read=feature.read,typed=broken,diagnostic=feature.diagnostic,progress=feature.progress)
    if mode=='changed_collection':
        item=feature.collection.Item
        def last(index):
            if index==4:feature.collection.Count=4
            return item(index)
        feature.collection.Item=last
    if mode=='changed_feature_count':
        feature.mill.IGetIslandCount=Mock(side_effect=[5,4])
    if mode=='bad_curve':feature.curve.GetTypeOfCurve=lambda:99
    if mode=='negative_depth_nan':feature.islands[0].GetDepth=lambda:float('nan')
    with pytest.raises(ValueError):feature.run()
    assert feature.diagnostic['state']['read_complete'] is False
    assert not any('ProfileSketchParam' in name or 'Faces' in name for _,name,_ in feature.calls)


def test_null_contours_are_unavailable_not_fabricated(feature):
    feature.islands[0].IGetWallSegChain=lambda:None
    result=feature.run()
    assert result['read_complete'] and result['all_contours_available'] is False
    assert result['items'][0]['contours']['wall']['status']=='observed_not_available'


@pytest.fixture
def wrapper(tmp_path,monkeypatch):
    part=tmp_path/'part.sldprt';part.write_bytes(b'immutable selected feature')
    receipt=tmp_path/'probe.json';source=m._file_hash(part)
    doc=dict(path=str(part),title=part.name,type=1,needs_save=False)
    state=dict(native_id=79,read_complete=True,items=[dict(index=0)],islands_geometry_complete=False)
    flags=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,
        callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    knobs=dict(capture=None,exit=None)
    class Session:
        def __enter__(self):flags.update(subscribed=True,active=True);return self
        def __exit__(self,*_):
            flags.update(active=False,disconnected=True)
            if knobs['exit']:knobs['exit']()
        def summary(self):return deepcopy(flags)
    calls=[]
    def capture(*args,**kwargs):
        kwargs['check']();calls.append(True)
        kwargs['diagnostic']['entered']=True;kwargs['progress']()
        if knobs['capture']:knobs['capture']()
        kwargs['check']()
        return deepcopy(state)
    sw=N(GetProcessID=lambda:731)
    monkeypatch.setattr(m,'raw_part_identity',lambda *_:deepcopy(doc))
    bootstrap=Mock(return_value=object());monkeypatch.setattr(m,'_bootstrap',bootstrap)
    monkeypatch.setattr(m,'capture_volume_feature_islands',capture)
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    kwargs=dict(process_id=731,expected_document_path=str(part),expected_source_sha256=source,
        expected_feature_native_id=79,expected_owner_setup_native_id=69,expected_volume_type=2,
        expected_shape=2,expected_island_count=5,qualification_only=True,
        acknowledge_disposable_copy=True,receipt_path=str(receipt))
    def run(**override):return m.inspect_mill_volume_islands(sw,'clsid','tlb',**(kwargs|override))
    return N(**locals())


def test_two_snapshots_cleanup_unique_receipt_and_no_manufacturing_claim(wrapper):
    result=wrapper.run()
    assert result['status']=='review_required' and result['readback_verified']
    assert result['islands_read_complete'] and len(wrapper.calls)==2
    for key in ('full_inventory_verified','mutation_attempted','AFR_attempted','GOP_attempted',
                'GTP_attempted','model_saved','production_qualified','apply_eligible',
                'may_continue','post_cleanup_CAM_getters'):
        assert result[key] is False
    assert result['messages']['disconnected']
    assert result['probe_scope']=='island_headers_only'
    assert result['island_headers_read_complete'] and result['representation_readback_verified']
    assert result['islands_geometry_complete'] is False
    assert json.loads(wrapper.receipt.read_text())==result


@pytest.mark.parametrize('mode',['pid','source','dirty','bool_id','same_ids','count_bound',
 'receipt','event','changed_read','capture_error','cleanup','changed_source','persist'])
def test_wrapper_failure_keeps_partial_and_never_reports_complete(wrapper,mode,monkeypatch):
    override={}
    if mode=='pid':override['process_id']=732
    if mode=='source':override['expected_source_sha256']='b'*64
    if mode=='dirty':wrapper.doc['needs_save']=True
    if mode=='bool_id':override['expected_feature_native_id']=True
    if mode=='same_ids':override['expected_owner_setup_native_id']=79
    if mode=='count_bound':override['expected_island_count']=65
    if mode=='receipt':wrapper.receipt.write_text('keep')
    if mode=='event':wrapper.knobs['capture']=lambda:wrapper.flags.update(event_count=1)
    if mode=='changed_read':
        def changed():
            if len(wrapper.calls)==2:wrapper.state['items'][0]['index']=1
        wrapper.knobs['capture']=changed
    if mode=='capture_error':
        def failed():raise ValueError('QI unsupported')
        wrapper.knobs['capture']=failed
    if mode=='cleanup':wrapper.knobs['exit']=lambda:wrapper.flags.update(disconnect_errors=['bad'])
    if mode=='changed_source':wrapper.knobs['capture']=lambda:wrapper.part.write_bytes(b'changed')
    if mode=='persist':
        write=m._write_receipt
        def failed(path,report,**kw):
            if report.get('readback_verified'):raise OSError('receipt failed')
            return write(path,report,**kw)
        monkeypatch.setattr(m,'_write_receipt',failed)
    result=wrapper.run(**override)
    assert result['status']=='error' and not result['islands_read_complete']
    assert not result['readback_verified']
    if mode=='receipt':assert wrapper.receipt.read_text()=='keep'
    if mode in ('pid','source','dirty','bool_id','same_ids','count_bound','receipt'):
        wrapper.bootstrap.assert_not_called()
    if mode=='capture_error':
        assert len(wrapper.calls)==1
        assert result['snapshots_diagnostics'][0]['entered']


def test_actual_capture_enforces_per_getter_guard_and_source_file_scope(feature,tmp_path,monkeypatch):
    part=tmp_path/'part.sldprt';part.write_bytes(b'stable')
    baseline=dict(path=str(part),title=part.name,type=1,needs_save=False)
    sw=N(ActiveDoc=N(GetSaveFlag=lambda:False))
    app=N(IGetActiveDoc=lambda:feature.doc)
    guarded=Mock()
    monkeypatch.setattr(m,'_check_capture_document',guarded)
    monkeypatch.setattr(m,'raw_part_identity',lambda *_:deepcopy(baseline))
    monkeypatch.setattr(m,'_typed',lambda raw,name,path:feature.typed(raw,name))
    check=Mock();diagnostic={}
    result=m.capture_volume_feature_islands(sw,app,'tlb',process_id=731,
        expected_document_path=str(part),expected_source_sha256=m._file_hash(part),
        baseline=baseline,selected=feature.selected,check=check,diagnostic=diagnostic,progress=Mock())
    assert result['read_complete']
    assert guarded.call_count==2*diagnostic['native_read_count']+1
    assert check.call_count==2*guarded.call_count


def test_actual_capture_stops_on_native_budget_before_getter(feature,tmp_path,monkeypatch):
    part=tmp_path/'part.sldprt';part.write_bytes(b'stable')
    baseline=dict(path=str(part),title=part.name,type=1,needs_save=False)
    sw=N(ActiveDoc=N(GetSaveFlag=lambda:False))
    app=N(IGetActiveDoc=lambda:feature.doc)
    monkeypatch.setattr(m,'_check_capture_document',lambda *_:None)
    monkeypatch.setattr(m,'raw_part_identity',lambda *_:deepcopy(baseline))
    monkeypatch.setattr(m,'_typed',lambda raw,name,path:feature.typed(raw,name))
    monkeypatch.setattr(m,'MAX_READS',2)
    diagnostic={}
    with pytest.raises(ValueError,match='budget'):
        m.capture_volume_feature_islands(sw,app,'tlb',process_id=731,
            expected_document_path=str(part),expected_source_sha256=m._file_hash(part),
            baseline=baseline,selected=feature.selected,check=lambda:None,
            diagnostic=diagnostic,progress=Mock())
    assert diagnostic['native_read_count']==2



def test_headers_only_never_reads_contours(feature):
    feature.selected['include_contours']=False
    result=feature.run()
    assert result['island_headers_read_complete']
    assert result['islands_geometry_complete'] is False
    assert result['all_contours_available'] is False
    assert result['contour_status']=='not_requested'
    assert feature.diagnostic['geometry_budget']==dict(curves=0,chains=0,islands=5)
    assert all(not item['contours'] and 'depth_native' in item for item in result['items'])
    assert not any('SegChain' in name or 'Curve' in name for _,name,_ in feature.calls)
