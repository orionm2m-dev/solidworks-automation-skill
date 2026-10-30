"""PROFILE metadata probe tests; no CAD or COM calls."""
from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import Mock
import json
import pytest
from scripts import sw_cam_mill_profile_headers as m
from scripts import sw_cam_events as events


@pytest.fixture
def feature():
    owner=N(id=69)
    base=N(id=79,GetOwner=lambda:owner,Suppressed=False)
    mill=N(VolumeType=2,Shape=2,IGetIslandCount=lambda:5)
    profile=N(GetSketchCount=lambda:5,
        GetSketchNameList=lambda:tuple('Sketch'+str(i) for i in range(5)),
        GetEndCondition1=lambda:(2.,1,'Top',False),
        GetEndCondition2=lambda:(-1.,2,'Bottom',True))
    doc=N(GetCWObjectFromID=lambda kind,oid:(base,True),GetCWObjectID=lambda obj:(obj.id,True))
    selected=dict(feature_native_id=79,owner_setup_native_id=69,
                  volume_type=2,shape=2,island_count=5,include_contours=False)
    calls=[]
    def read(obj,name,*args):
        calls.append((obj,name,args))
        value=getattr(obj,name)
        return value(*args) if callable(value) else value
    def typed(raw,name):
        calls.append((raw,'QI '+name,()))
        if name=='ICWMillFeature':return mill
        if name=='ICWProfileFeature':return profile
        return raw
    diagnostic={}
    progress=Mock()
    def run():return m.read_profile_feature_headers(doc,selected=selected,read=read,
        typed=typed,diagnostic=diagnostic,progress=progress)
    return N(**locals())


def test_exact_profile_headers_preserve_list_and_four_end_condition_outputs(feature):
    result=feature.run()
    assert result['read_complete'] and result['profile_headers_read_complete']
    assert result['profile_geometry_complete'] is False and result['indexed_methods_called'] is False
    assert result['sketch_names']['observed_representation']=='python_tuple'
    assert result['sketch_names']['native_vartype'] is None
    assert result['sketch_names']['matches_sketch_count']
    assert result['sketch_names']['count_relation_verified'] is False
    assert result['end_conditions']['GetEndCondition2']==dict(
        depth_native=-1.,type_raw=2,name='Bottom',name_observed_representation='python_str',is_reversed=True,units_verified=False)
    assert feature.progress.call_count==3
    assert (feature.doc,'GetCWObjectFromID',(1,79)) in feature.calls
    assert not any('SegmentChain' in name or 'NameListAt' in name or 'Faces' in name
        or name.startswith('Set') or 'ICWVolumeFeature' in name for _,name,_ in feature.calls)


@pytest.mark.parametrize('mode',[
 'lookup_status','lookup_shape','identity','owner','suppressed','volume_type','shape',
 'island_count','unsupported_profile','sketch_count_bound','sketch_count_bool',
 'names_nested','names_nonstring','names_unsupported','name_bound',
 'condition_shape','condition_type_bool','condition_label','condition_reversed','condition_nan',
 'changed_sketch_count','changed_island_count'])
def test_invalid_identity_or_profile_metadata_stops_without_fallback(feature,mode):
    if mode=='lookup_status':feature.doc.GetCWObjectFromID=lambda *_:(feature.base,False)
    if mode=='lookup_shape':feature.doc.GetCWObjectFromID=lambda *_:feature.base
    if mode=='identity':feature.base.id=80
    if mode=='owner':feature.owner.id=70
    if mode=='suppressed':feature.base.Suppressed=0
    if mode=='volume_type':feature.mill.VolumeType=3
    if mode=='shape':feature.mill.Shape=3
    if mode=='island_count':feature.mill.IGetIslandCount=lambda:4
    if mode=='unsupported_profile':
        typed=feature.typed
        def broken(raw,name):
            if name=='ICWProfileFeature':raise ValueError('E_NOINTERFACE')
            return typed(raw,name)
        feature.run=lambda:m.read_profile_feature_headers(feature.doc,selected=feature.selected,
            read=feature.read,typed=broken,diagnostic=feature.diagnostic,progress=feature.progress)
    if mode=='sketch_count_bound':feature.profile.GetSketchCount=lambda:65
    if mode=='sketch_count_bool':feature.profile.GetSketchCount=lambda:True
    if mode=='names_count':feature.profile.GetSketchNameList=lambda:('one',)
    if mode=='names_nested':feature.profile.GetSketchNameList=lambda:(('one',),)*5
    if mode=='names_nonstring':feature.profile.GetSketchNameList=lambda:tuple(range(5))
    if mode=='names_unsupported':feature.profile.GetSketchNameList=lambda:object()
    if mode=='name_bound':feature.profile.GetSketchNameList=lambda:('x'*1025,)*5
    if mode=='condition_shape':feature.profile.GetEndCondition1=lambda:(2.,1)
    if mode=='condition_type_bool':feature.profile.GetEndCondition1=lambda:(2.,True,'Top',False)
    if mode=='condition_label':feature.profile.GetEndCondition1=lambda:(2.,1,3,False)
    if mode=='condition_reversed':feature.profile.GetEndCondition1=lambda:(2.,1,'Top',1)
    if mode=='condition_nan':feature.profile.GetEndCondition1=lambda:(float('nan'),1,'Top',False)
    if mode=='changed_sketch_count':feature.profile.GetSketchCount=Mock(side_effect=[5,4])
    if mode=='changed_island_count':feature.mill.IGetIslandCount=Mock(side_effect=[5,4])
    with pytest.raises(ValueError):feature.run()
    assert feature.diagnostic['state']['read_complete'] is False
    if mode=='names_unsupported':assert feature.diagnostic['state']['sketch_names_return_python_type']=='object'
    assert not any('ICWVolumeFeature' in name or 'Faces' in name for _,name,_ in feature.calls)


@pytest.mark.parametrize('value,count,representation,verified',[
 (None,0,'python_none',True),(None,5,'python_none',False),
 ('Sketch A',1,'python_str',True),('A,B,C',3,'python_str',False),
 (['A','B'],2,'python_list',True),(('A','B'),2,'python_tuple',True)])
def test_preserve_python_variant_representation_without_native_type_claim(value,count,representation,verified):
    result=m._sketch_names(value,count)
    assert result['observed_representation']==representation
    assert result['native_vartype'] is None and result['count_relation_verified'] is False
    if type(value) in (tuple,list):assert result['matches_sketch_count'] is True
    else:assert result['matches_sketch_count'] is None
    if type(value) is str:assert result['value']==value


@pytest.fixture
def wrapper(tmp_path,monkeypatch):
    part=tmp_path/'part.sldprt';part.write_bytes(b'immutable selected feature')
    receipt=tmp_path/'probe.json';source=m._file_hash(part)
    doc=dict(path=str(part),title=part.name,type=1,needs_save=False)
    state=dict(native_id=79,read_complete=True,items=[dict(index=0)],profile_geometry_complete=False)
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
    monkeypatch.setattr(m,'capture_profile_feature_headers',capture)
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    kwargs=dict(process_id=731,expected_document_path=str(part),expected_source_sha256=source,
        expected_feature_native_id=79,expected_owner_setup_native_id=69,expected_volume_type=2,
        expected_shape=2,expected_island_count=5,qualification_only=True,
        acknowledge_disposable_copy=True,receipt_path=str(receipt))
    def run(**override):return m.inspect_mill_profile_headers(sw,'clsid','tlb',**(kwargs|override))
    return N(**locals())


def test_two_snapshots_cleanup_unique_receipt_and_no_manufacturing_claim(wrapper):
    result=wrapper.run()
    assert result['status']=='review_required' and result['readback_verified']
    assert result['profile_read_complete'] and len(wrapper.calls)==2
    for key in ('full_inventory_verified','mutation_attempted','AFR_attempted','GOP_attempted',
                'GTP_attempted','model_saved','production_qualified','apply_eligible',
                'may_continue','post_cleanup_CAM_getters'):
        assert result[key] is False
    assert result['messages']['disconnected']
    assert result['probe_scope']=='profile_headers_only'
    assert result['profile_headers_read_complete'] and result['representation_readback_verified']
    assert result['profile_geometry_complete'] is False
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
    assert result['status']=='error' and not result['profile_read_complete']
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
    result=m.capture_profile_feature_headers(sw,app,'tlb',process_id=731,
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
        m.capture_profile_feature_headers(sw,app,'tlb',process_id=731,
            expected_document_path=str(part),expected_source_sha256=m._file_hash(part),
            baseline=baseline,selected=feature.selected,check=lambda:None,
            diagnostic=diagnostic,progress=Mock())
    assert diagnostic['native_read_count']==2





def test_contours_request_is_explicitly_rejected_before_native(wrapper):
    result=wrapper.run(include_contours=True)
    assert result['status']=='error'
    assert result['contour_limitation']=='CONTOUR_INDEX_CONTRACT_NOT_YET_QUALIFIED'
    assert result['contour_index_contract_verified'] is False
    assert result['issue']['type']=='ValueError'
    wrapper.bootstrap.assert_not_called()
    assert not wrapper.calls



def test_name_count_mismatch_and_null_end_name_are_raw_observations(feature):
    feature.profile.GetSketchNameList=lambda:('Only one observed name',)
    feature.profile.GetEndCondition1=lambda:(0.,0,None,False)
    result=feature.run()
    assert result['read_complete']
    assert result['sketch_count']==5 and result['sketch_names']['observed_name_count']==1
    assert result['sketch_names']['matches_sketch_count'] is False
    assert result['sketch_names']['count_relation_verified'] is False
    condition=result['end_conditions']['GetEndCondition1']
    assert condition['name'] is None and condition['name_observed_representation']=='python_none'
    assert result['profile_geometry_complete'] is False
