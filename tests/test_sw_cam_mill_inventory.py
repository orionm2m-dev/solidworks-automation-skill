from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import Mock
import json
import pytest
from scripts import sw_cam_mill_inventory as cam
from scripts import sw_cam_events as events

@pytest.fixture
def probe(tmp_path,monkeypatch):
    part=tmp_path/'part.sldprt';part.write_bytes(b'saved accepted target')
    receipt=tmp_path/'receipt.json';doc=dict(path=str(part),title=part.name,type=1,needs_save=False)
    flags=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    knobs=dict(on_capture=None,on_exit=None)
    class Session:
        def __enter__(self):flags.update(subscribed=True,active=True);return self
        def __exit__(self,*_):
            flags.update(active=False,disconnected=True)
            if knobs['on_exit']:knobs['on_exit']()
        def summary(self):return deepcopy(flags)
    sw=N(GetProcessID=lambda:731,ActiveDoc=N(GetPathName=lambda:doc['path']))
    state=dict(document=doc,saved_file_sha256=cam._file_hash(part),features=[],material_raw='6061-T6',
        stock=dict(type_raw=4,stock_geometry_verified=False),operation_counts=[0],operation_count=0,
        sw_reference=dict(feature_tree=[],solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[0.,0.,0.,1.])]))
    calls=[]
    def capture(*args,**kw):
        assert flags['active'];kw['check']();calls.append(True)
        kw['diagnostic']['partial_observation']='read reached fixture'
        if knobs['on_capture']:knobs['on_capture']()
        kw['check']();return deepcopy(state)
    monkeypatch.setattr(cam,'raw_part_identity',lambda *_:deepcopy(doc))
    monkeypatch.setattr(cam,'_bootstrap',Mock(return_value=object()))
    monkeypatch.setattr(cam,'capture_mill_inventory',capture)
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    def run(**changes):
        return cam.inspect_mill_feature_inventory(sw,'clsid','tlb',**(dict(process_id=731,
            expected_document_path=str(part),expected_source_sha256=cam._file_hash(part),qualification_only=True,
            acknowledge_disposable_copy=True,receipt_path=str(receipt))|changes))
    return N(**locals())


def test_two_stable_captures_only_and_explicit_unqualified_material(probe):
    result=probe.run()
    assert result['status']=='review_required' and result['readback_verified']
    assert result['before']['material_raw']=='6061-T6' and len(probe.calls)==2
    assert not any(result[k] for k in ['mutation_attempted','AFR_attempted','GOP_attempted','GTP_attempted','model_saved','production_qualified','TechDB_write_attempted'])
    assert result['messages']['disconnected'] and not result['post_cleanup_CAM_getters']
    assert json.loads(probe.receipt.read_text())==result

@pytest.mark.parametrize('mode',['pid','source','dirty','event','geometry','receipt','cleanup'])
def test_invalid_or_changed_state_never_promoted(probe,mode):
    extra={}
    if mode=='pid':extra['process_id']=732
    if mode=='source':extra['expected_source_sha256']='a'*64
    if mode=='dirty':probe.doc['needs_save']=True
    if mode=='event':probe.knobs['on_capture']=lambda:probe.flags.update(event_count=1)
    if mode=='geometry':
        def changed():
            if len(probe.calls)==2:probe.state['sw_reference']['solids'][0]['mass_raw'][3]=2.
        probe.knobs['on_capture']=changed
    if mode=='receipt':probe.receipt.write_text('preserve')
    if mode=='cleanup':probe.knobs['on_exit']=lambda:probe.flags['disconnect_errors'].append('failure')
    result=probe.run(**extra)
    assert result['status']=='error' and not result['readback_verified']
    if mode=='receipt':assert probe.receipt.read_text()=='preserve'
    assert not result['mutation_attempted']


def test_partial_failed_capture_is_durable_without_replay(probe):
    def fail():raise ValueError('unsupported curve after partial read')
    probe.knobs['on_capture']=fail
    result=probe.run()
    assert len(probe.calls)==1 and not result['inventory_read_complete']
    durable=json.loads(probe.receipt.read_text())
    assert durable['snapshot_diagnostics'][0]['partial_observation']=='read reached fixture'


def test_receipt_failure_stops_before_first_capture(probe,monkeypatch):
    original=cam._write_receipt
    def write(path,result,**kw):
        if result['phase']=='before':raise OSError('durability failure')
        return original(path,result,**kw)
    monkeypatch.setattr(cam,'_write_receipt',write)
    result=probe.run();assert not probe.calls and not result['readback_verified']


@pytest.fixture
def native(monkeypatch):
    doc=N(GetEMFFeatTypeOptions=lambda _:True,GetEMFPartPeriTypeOptions=lambda _:False,
        GetEMFTypeOptions=lambda _:True,FeatureCreationStyle=0,EMFHoleMaxDiameter=12.,EMFHoleMinimumIncludedAngle=30.)
    features=[N(id=101),N(id=102)]
    class Collection:
        def __init__(self,items):self.items=items
        @property
        def Count(self):return len(self.items)
        def Item(self,index):return self.items[index]
    setup=N(id=64,IGetEnumFeatures=lambda:Collection(features));op_setup=N(id=65,IGetEnumOperations=lambda:Collection([]))
    machine=N(IGetWorkpiece=lambda:object(),IGetEnumOpSetups=lambda:Collection([op_setup]))
    state=dict(document={},saved_file_sha256='a'*64,current_machine=dict(machine_type=1),mill_catalogue=[],
        feature_setups=[dict(native_id=64,feature_count=2)],operation_counts=[0],material_raw='6061-T6')
    handles=dict(doc=doc,machine=machine,setups=[setup]);sw=N(ActiveDoc=N(GetBodies2=lambda *_:[object()]))
    monkeypatch.setattr(cam,'_mill_snapshot',lambda *a,**k:(deepcopy(state),handles))
    monkeypatch.setattr(cam,'_typed',lambda raw,*_:raw)
    monkeypatch.setattr(cam,'_object_id',lambda doc,raw,read:raw.id)
    monkeypatch.setattr(cam,'_stock',lambda *a:({'type_raw':2,'bounds_native':[0,0,0,1,1,1]},object()))
    monkeypatch.setattr(cam,'_features',lambda *_:([],None))
    monkeypatch.setattr(cam,'_bodies',lambda *_:[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[0.,0.,0.,1.])])
    decoder=Mock(side_effect=lambda raw,**kw:dict(native_id=raw.id))
    monkeypatch.setattr(cam,'read_mill_feature',decoder)
    diagnostic={}
    def run():return cam.capture_mill_inventory(sw,'clsid','tlb','C:/part.sldprt',check=lambda:None,diagnostic=diagnostic)
    return N(**locals())


def test_capture_all_feature_ids_and_exact_defaults_with_no_operations(native):
    result=native.run()
    assert [r['geometry']['native_id'] for r in result['features']]==[101,102]
    assert result['material_raw']=='6061-T6' and result['stock']['type_raw']==2
    assert result['recognition_method']==dict(value=0,name='AFR',status='observed_via_ICWDoc3_FeatureCreationStyle')
    assert len(result['recognition_options']['GetEMFFeatTypeOptions'])==6
    assert result['recognition_options']['EMFHoleMaxDiameter']==12.
    assert native.diagnostic['capture_complete'] and native.decoder.call_count==2

@pytest.mark.parametrize('kind',['operations','duplicate','count','bool_option','nan_scalar','feature_bound'])
def test_capture_fail_closed(native,kind):
    if kind=='operations':native.state['operation_counts']=[1]
    if kind=='duplicate':native.features[1].id=101
    if kind=='count':native.state['feature_setups'][0]['feature_count']=1
    if kind=='bool_option':native.doc.GetEMFTypeOptions=lambda _:1
    if kind=='nan_scalar':native.doc.EMFHoleMaxDiameter=float('nan')
    if kind=='feature_bound':native.state['feature_setups'][0]['feature_count']=65
    with pytest.raises(ValueError):native.run()
    assert native.diagnostic['capture_complete'] is False


def test_full_capture_combines_two_real_decoded_features_and_islands(native,monkeypatch):
    from test_sw_cam_mill_inventory_geometry import Node,feature,chain,curve,island
    from scripts.sw_cam_mill_inventory_geometry import read_mill_feature
    first=feature(chain([curve(0),curve(1)]),chain([curve(2)]),islands=[island(chain([curve(2)]))])
    second=feature(chain([curve(2)]),chain([curve(2)]))
    first.fields['native_id']=101;second.fields['native_id']=102
    native.features[:]=[first,second]
    old_member=cam._member
    def member(obj,name,*args):
        if isinstance(obj,Node):
            value=obj.fields[name]
            return value(*args) if callable(value) else value
        return old_member(obj,name,*args)
    def typed(obj,name,*_):
        if isinstance(obj,Node) and name not in obj.interfaces:raise ValueError('unsupported interface')
        return obj
    monkeypatch.setattr(cam,'_member',member);monkeypatch.setattr(cam,'_typed',typed)
    monkeypatch.setattr(cam,'_object_id',lambda doc,obj,read:obj.fields['native_id'] if isinstance(obj,Node) else obj.id)
    monkeypatch.setattr(cam,'read_mill_feature',read_mill_feature)
    result=native.run()
    assert [r['geometry']['native_id'] for r in result['features']]==[101,102]
    assert result['features'][0]['geometry']['islands']['declared_count']==1
    assert native.diagnostic['geometry_budget']['curves']==6
    assert not result['features'][1]['geometry']['physical_depth_verified']


def test_full_file_hash_count_is_independent_of_inner_guard_count(probe,monkeypatch):
    real_hash=cam._file_hash;hashes=[]
    def counted(path):hashes.append(path);return real_hash(path)
    monkeypatch.setattr(cam,'_file_hash',counted)
    original=cam.capture_mill_inventory
    def many_checks(*args,**kw):
        for _ in range(100):kw['check']()
        return original(*args,**kw)
    monkeypatch.setattr(cam,'capture_mill_inventory',many_checks)
    result=probe.run()
    assert result['readback_verified'],result
    assert len(hashes)<=8
