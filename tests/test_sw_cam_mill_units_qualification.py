"""MILL 真实轮廓资格流程的模拟原生测试；不调用 CAD。"""
from copy import deepcopy
from ctypes import POINTER, c_int, cast
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest

STAGE=Path(__file__).resolve().parent
for short in ('sw_cam_mill_units_geometry','sw_cam_mill_units_qualification'):
    name='scripts.'+short
    source=STAGE/(short+'.py')
    if not source.is_file():source=STAGE.parent/'scripts'/(short+'.py')
    spec=importlib.util.spec_from_file_location(name,source)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
cam=sys.modules['scripts.sw_cam_mill_units_qualification']
from scripts import sw_cam_events as events


class CallableCOM(N):
    def __init__(self,**kwargs):super().__init__(**kwargs);self._oleobj_=object()
    def __call__(self,*args):raise AssertionError('Do not invoke a returned COM property default member')


@pytest.fixture
def case(tmp_path,monkeypatch):
    part=tmp_path/'copy.sldprt';part.write_bytes(b'saved disposable copy')
    receipt=tmp_path/'create.json'
    document=dict(path=str(part),title=part.name,type=1,needs_save=False)
    points=[[0.,0.,0.],[17.,0.,0.],[17.,29.,0.],[0.,29.,0.]]
    sketch_spec=dict(plane_axis='Z',plane_offset_mm=0.,sketch_name='UnitRectangle',plane_name='UnitPlane',
        profile=dict(kind='closed_polyline',points_model_mm=deepcopy(points)))
    sketch=dict(entities=[dict(type='line',points_model_m=[[v/1000 for v in points[i]],[v/1000 for v in points[(i+1)%4]]]) for i in range(4)])
    state=dict(document=document,pid=731,features=[],setup_id=17,machine_type=1,operation_counts=[],
        setups=1,callbacks={},calls=[],writes=[],depth_scalar=3.,separation=3.,scale=1.,curve_type=0,
        tree=[{'name':'UnitRectangle','type':'ProfileFeature'}],
        solids=[dict(box_m=[0,0,0,.02,.03,.005],mass_raw=[.01,.02,.003,3e-6])],capture_count=0)
    status=dict(active=False,subscribed=False,disconnected=False,event_count=0,overflow=0,callback_errors=[],
                callback_error_count=0,subscription_error=None,disconnect_errors=[])
    class Session:
        def __enter__(self):status.update(active=True,subscribed=True,disconnected=False);return self
        def __exit__(self,*args):
            status.update(active=False,disconnected=True)
            if state['callbacks'].get('cleanup'):state['callbacks']['cleanup']()
        def summary(self):return deepcopy(status)
    indices=[]
    def make_chain(label):
        def curve_at(index):
            assert type(index._obj) is c_int
            number=cast(index,POINTER(c_int)).contents.value
            assert 0<=number<4;indices.append((label,number))
            offset=state['separation'] if label=='bottom' else 0.
            def vertex(i):return [points[i][0]*state['scale']+101.,points[i][1]*state['scale']-42.,87.+offset]
            return N(GetTypeOfCurve=lambda:state['curve_type'],
                GetStart=lambda:N(GetCoordinates=lambda:vertex(number)),
                GetEnd=lambda:N(GetCoordinates=lambda:vertex((number+1)%4)))
        return N(IGetNumChains=lambda:1,GetNumOfCurves=lambda:4,GetCurveAtIndex=Mock(side_effect=curve_at))
    top,bottom=make_chain('top'),make_chain('bottom')
    class Feature:
        native_id=99;VolumeType=6;Suppressed=False;FeatureName='Open pocket';Axis=(0.,0.,1.)
        @property
        def Depth(self):return state['depth_scalar']
        def GetBoundParams(self):return (17.,29.,state['depth_scalar'])
        def GetStartPosition(self):return (101.,-42.,87.)
        def IGetTopSegChain(self):return top
        def IGetBottomSegChain(self):return bottom
        def IGetEnumRecords(self):raise AssertionError('Unsafe records getter forbidden')
    feature=Feature()
    def creator(*args):
        durable=json.loads(receipt.read_text(encoding='utf8'))
        assert status['active'] and durable['mutation_attempted'] and not durable['native_call_returned']
        assert durable['phase']=='CreateMillFeature2'
        assert args==(5,'UnitRectangle',False,3.,False,False,False,False,0.,-1,False,0,0)
        assert type(args[3]) is float and type(args[8]) is float
        assert all(type(args[i]) is bool for i in (2,4,5,6,7,10))
        state['writes'].append(args);state['features']=[feature];state['document']['needs_save']=True
        if state['callbacks'].get('creator'):state['callbacks']['creator']()
        if state.get('creator_error'):raise RuntimeError('Native creator failed')
        return state.get('creator_return',feature)
    setup=N(IGetEnumFeatures=lambda:list(state['features']),CreateMillFeature2=Mock(side_effect=creator))
    doc=N(GetCWObjectID=lambda obj:(obj.native_id,True),GetUnit=Mock(side_effect=AssertionError('Unsafe CAM unit getter')),
          IGetEnumRecords=Mock(side_effect=AssertionError('Unsafe record enumeration')))
    app=N(GetUseDocumentUnit=lambda:True,GetUnit=Mock(side_effect=AssertionError('Unsafe CAM unit getter')))
    sw_feature=CallableCOM(GetTypeName2=lambda:'ProfileFeature',IsSuppressed=lambda:False,GetSpecificFeature2=lambda:object())
    model=CallableCOM(IsOpenedReadOnly=lambda:False,GetConfigurationNames=lambda:['Default'],GetActiveSketch2=lambda:None,
        FeatureByName=Mock(return_value=sw_feature),GetUnits=lambda:[0,0,0,0,0])
    sw=N(GetProcessID=lambda:state['pid'],ActiveDoc=model)
    native=dict(app=app,doc=doc,setups=[setup])
    def snapshot(sw,clsid,tlb,path,*,check):
        check();assert status['active'];state['capture_count']+=1
        if state['callbacks'].get('snapshot'):state['callbacks']['snapshot']()
        check()
        result=dict(document=deepcopy(state['document']),saved_file_sha256=cam._file_hash(part),
            current_machine=dict(machine_type=state['machine_type']),
            feature_setups=[dict(native_id=state['setup_id'],feature_count=len(state['features'])) for _ in range(state['setups'])],
            operation_counts=deepcopy(state['operation_counts']),material_raw='fixture')
        return result,native
    original_member=cam._member
    def member(obj,name,*args):
        assert status['active'],'CAM getter after event disconnect'
        state['calls'].append(name)
        if state['callbacks'].get(name):state['callbacks'][name]()
        return original_member(obj,name,*args)
    monkeypatch.setattr(cam,'_member',member)
    monkeypatch.setattr(cam,'document_snapshot',lambda sw:deepcopy(state['document']))
    monkeypatch.setattr(cam,'_bootstrap',Mock(return_value=app))
    monkeypatch.setattr(cam,'_mill_snapshot',snapshot)
    monkeypatch.setattr(cam,'_typed',lambda obj,*args:obj)
    def items(values,tlb,read,limit=512):
        assert len(values)<=limit
        return list(values)
    monkeypatch.setattr(cam,'_items',items)
    monkeypatch.setattr(cam,'_read_sketch',lambda *args:deepcopy(sketch))
    monkeypatch.setattr(cam,'_features',lambda model:(deepcopy(state['tree']),[]))
    monkeypatch.setattr(cam,'_bodies',lambda model:deepcopy(state['solids']))
    monkeypatch.setattr(events,'CamMessageSession',lambda *args:Session())
    base=dict(process_id=731,expected_document_path=str(part),expected_source_sha256=cam._file_hash(part),
        expected_setup_native_id=17,sketch_spec=sketch_spec,depth_native=3,qualification_only=True,
        acknowledge_disposable_copy=True,message_policy='vendor_default')
    def run(action='prepare',**changes):
        return cam.qualify_mill_feature_units(sw,'clsid','tlb',**(base|{'action':action}|changes))
    def prepare():
        result=run();assert result['status']=='ok',result
        return result
    def apply(**changes):
        prepared=prepare()
        return run('apply',expected_state_sha256=prepared['state_sha256'],receipt_path=str(receipt),**changes)
    return N(**locals())


def test_prepare_then_apply_exact_double_abi_and_durable_returns(case):
    before=case.prepare()
    assert before['apply_eligible'] and not case.receipt.exists()
    assert 'dimensional_evidence' not in before
    out=case.run('apply',expected_state_sha256=before['state_sha256'],receipt_path=str(case.receipt))
    assert out['status']=='review_required' and out['readback_verified'] and out['geometric_readback_verified']
    assert out['new_feature_native_id']==99 and len(case.state['writes'])==1
    assert out['observed_native_units_per_mm']==pytest.approx(1.)
    assert out['interpreted_depth_mm']==pytest.approx(3.)
    assert case.indices==[('top',i) for i in range(4)]+[('bottom',i) for i in range(4)]
    assert json.loads(case.receipt.read_text(encoding='utf8'))==out
    assert all(not out[key] for key in ('model_saved','AFR_attempted','GOP_attempted','GTP_attempted','stock_edit_attempted',
        'sketch_edit_attempted','global_native_units_verified','feed_units_verified','production_qualified','unsupported_unit_getter_called'))
    case.doc.GetUnit.assert_not_called();case.doc.IGetEnumRecords.assert_not_called();case.app.GetUnit.assert_not_called()


@pytest.mark.parametrize('field,value',[('process_id',True),('process_id',0),('expected_setup_native_id',False),
    ('depth_native',True),('depth_native',3.),('depth_native',0),('depth_native',101),('qualification_only',1)])
def test_strict_inputs_fail_before_bootstrap(case,field,value):
    out=case.run(**{field:value})
    assert out['status']=='error';cam._bootstrap.assert_not_called()
    case.setup.CreateMillFeature2.assert_not_called()
    assert case.state['capture_count']==0


@pytest.mark.parametrize('change',['pid','hash','dirty','operations','setup_count','setup_id','machine'])
def test_preconditions_fail_without_creator(case,change):
    if change=='pid':case.state['pid']=732
    if change=='hash':case.part.write_bytes(b'changed disk')
    if change=='dirty':case.document['needs_save']=True
    if change=='operations':case.state['operation_counts']=[1]
    if change=='setup_count':case.state['setups']=2
    if change=='setup_id':case.state['setup_id']=18
    if change=='machine':case.state['machine_type']=3
    out=case.run()
    assert out['status']=='error';case.setup.CreateMillFeature2.assert_not_called()


def test_prepared_hash_mismatch_is_not_reprepared_or_applied(case):
    out=case.run('apply',expected_state_sha256='0'*64,receipt_path=str(case.receipt))
    assert out['status']=='error';case.setup.CreateMillFeature2.assert_not_called()


@pytest.mark.parametrize('change',['solid','tree','operation','second_feature'])
def test_unexpected_delta_after_creator_is_uncertain(case,change):
    def mutate():
        if change=='solid':case.state['solids'][0]['mass_raw'][3]*=2
        if change=='tree':case.state['tree'].append({'name':'Unexpected','type':'Extrusion'})
        if change=='operation':case.state['operation_counts']=[1]
        if change=='second_feature':case.state['features'].append(case.feature)
    case.state['callbacks']['creator']=mutate
    out=case.apply()
    assert out['status']=='uncertain' and not out['readback_verified']
    case.setup.CreateMillFeature2.assert_called_once()


@pytest.mark.parametrize('raw',[None,False])
def test_null_native_return_never_replayed_even_if_feature_created(case,raw):
    case.state['creator_return']=raw
    out=case.apply()
    assert out['status']=='uncertain' and out['native_call_returned']
    assert case.state['features']==[case.feature] and not case.indices
    case.setup.CreateMillFeature2.assert_called_once()


def test_native_exception_has_durable_attempt_without_return_or_readback(case):
    case.state['creator_error']=True
    out=case.apply()
    assert out['status']=='uncertain' and not out['native_call_returned']
    assert not case.indices and len(case.state['writes'])==1
    durable=json.loads(case.receipt.read_text(encoding='utf8'))
    assert durable['mutation_attempted'] and not durable['native_call_returned']


@pytest.mark.parametrize('phase',['before_setter','after_setter'])
def test_event_at_durable_boundary_stops_downstream_native_calls(case,monkeypatch,phase):
    prepared=case.prepare();write=cam._write_receipt
    def persist(path,report,**kwargs):
        write(path,report,**kwargs)
        if report['phase']==('CreateMillFeature2' if phase=='before_setter' else 'CreateMillFeature2_returned'):
            case.status['event_count']=1
    monkeypatch.setattr(cam,'_write_receipt',persist)
    out=case.run('apply',expected_state_sha256=prepared['state_sha256'],receipt_path=str(case.receipt))
    assert out['status']=='uncertain' and not out['readback_verified'] and not case.indices
    assert case.setup.CreateMillFeature2.call_count==(0 if phase=='before_setter' else 1)
    assert 'GetCWObjectID' not in case.state['calls']


def test_event_during_native_getter_stops_next_getter(case):
    case.state['callbacks']['GetUseDocumentUnit']=lambda:case.status.update(event_count=1)
    out=case.run()
    assert out['status']=='error'
    assert 'IGetEnumFeatures' not in case.state['calls']
    case.setup.CreateMillFeature2.assert_not_called()


@pytest.mark.parametrize('change',['event','disconnect','document','file'])
def test_cleanup_failure_has_no_postcleanup_cam_getters(case,change):
    def cleanup():
        if change=='event':case.status['event_count']=1
        if change=='disconnect':case.status.update(active=True,disconnected=False,disconnect_errors=['failure'])
        if change=='document':case.document['title']='changed'
        if change=='file':case.part.write_bytes(b'changed after Unadvise')
    prepared=case.prepare();case.state['callbacks']['cleanup']=cleanup
    out=case.run('apply',expected_state_sha256=prepared['state_sha256'],receipt_path=str(case.receipt))
    assert out['status']=='uncertain' and not out['readback_verified']
    assert out['post_cleanup_CAM_getters'] is False


def test_existing_dirty_feature_inspection_never_creates(case):
    case.state['features']=[case.feature];case.document['needs_save']=True
    out=case.run('inspect',expected_feature_native_id=99)
    assert out['status']=='review_required' and out['readback_verified'] and not out['apply_eligible']
    assert not out['mutation_attempted'] and not case.receipt.exists()
    case.setup.CreateMillFeature2.assert_not_called()


@pytest.mark.parametrize('feature_id',[None,100])
def test_existing_feature_requires_exact_id_before_contours(case,feature_id):
    case.state['features']=[case.feature]
    out=case.run('inspect',expected_feature_native_id=feature_id)
    assert out['status']=='error' and out['observed_feature_native_id']==99
    assert not case.indices and 'IGetTopSegChain' not in case.state['calls']
    case.setup.CreateMillFeature2.assert_not_called()


@pytest.mark.parametrize('action',['prepare','apply'])
def test_existing_feature_blocks_prepare_apply_before_contours(case,action):
    case.state['features']=[case.feature]
    args={} if action=='prepare' else {'expected_state_sha256':'0'*64,'receipt_path':str(case.receipt)}
    out=case.run(action,**args)
    assert out['status']=='error' and not case.indices
    assert 'IGetTopSegChain' not in case.state['calls'];case.setup.CreateMillFeature2.assert_not_called()


def test_correct_depth_metadata_with_wrong_actual_bottom_distance_fails(case):
    case.state['separation']=9.;case.state['depth_scalar']=3.
    out=case.apply()
    assert out['status']=='uncertain' and not out['geometric_readback_verified']
    assert out['after']['features'][0]['depth_native']==3.
    assert 'MEASURED_SEPARATION_DIFFERS_FROM_REQUESTED_DEPTH' in str(out['issue'])


def test_actual_contour_scale_not_document_unit_flag_determines_result(case):
    case.state['scale']=2.
    out=case.apply()
    assert out['status']=='review_required'
    assert out['observed_native_units_per_mm']==pytest.approx(2.)
    assert out['interpreted_depth_mm']==pytest.approx(1.5)
    assert out['after']['CAM_use_document_units_raw'] is True
    assert not out['global_native_units_verified']


@pytest.mark.parametrize('kind',[True,1])
def test_non_line_curve_or_non_strict_type_stops_endpoints(case,kind):
    case.state['curve_type']=kind
    out=case.apply()
    assert out['status']=='uncertain' and case.indices==[('top',0)]
    assert 'GetStart' not in case.state['calls'] and 'IGetBottomSegChain' not in case.state['calls']


def test_existing_receipt_immutable_without_native_calls(case):
    case.receipt.write_text('previous uncertain result',encoding='utf8')
    out=case.run('apply',expected_state_sha256='0'*64,receipt_path=str(case.receipt))
    assert out['status']=='error' and case.receipt.read_text()=='previous uncertain result'
    case.setup.CreateMillFeature2.assert_not_called();assert case.state['capture_count']==0


def test_geometry_proof_uses_actual_sw_endpoints_not_requested_echo(case):
    case.sketch['entities'][0]['points_model_m'][0][0]+=.001
    out=case.run()
    assert out['status']=='error';case.setup.CreateMillFeature2.assert_not_called()


def test_receipt_return_marker_is_written_before_any_new_id_getter(case):
    def check_durable():
        durable=json.loads(case.receipt.read_text(encoding='utf8'))
        assert durable['native_call_returned'] is True
        assert durable['phase']=='CreateMillFeature2_returned'
        case.state['callbacks'].pop('GetCWObjectID')
    case.state['callbacks']['GetCWObjectID']=check_durable
    out=case.apply()
    assert out['status']=='review_required'
