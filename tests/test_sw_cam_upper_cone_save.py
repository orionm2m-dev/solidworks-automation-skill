"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
from copy import deepcopy
import importlib.util,json,sys
from pathlib import Path
import pytest
from scripts import sw_cam_upper_cone_save as m
from scripts import sw_cam_upper_cone_feature as v5
from cam_face_test_fixtures import mass_pair

def state():return dict(document=dict(path='fixture.SLDPRT',needs_save=True),saved_file_sha256='a'*64,features=[dict(id=i) for i in range(20)],operations=[dict(id=i) for i in range(6)],sw_reference=dict(solids=[dict(mass_raw=[.001]*12,bounds=[0.,1.])]))

def test_save_allows_only_clean_flag_and_source_hash():
    before=state();after=deepcopy(before);after['document']['needs_save']=False;after['saved_file_sha256']='b'*64
    assert m.verify_save_delta(before,after,'b'*64)==after

@pytest.mark.parametrize('change',['feature','operation','dirty','other','hash','count'])
def test_save_delta_rejects_other_changes(change):
    before=state();after=deepcopy(before);after['document']['needs_save']=False;after['saved_file_sha256']='b'*64
    if change=='feature':after['features'][0]['id']=100
    elif change=='operation':after['operations'][0]['id']=100
    elif change=='dirty':after['document']['needs_save']=True
    elif change=='other':after['stock']='other'
    elif change=='hash':after['saved_file_sha256']='c'*64
    else:before['features'].append({})
    with pytest.raises(ValueError):m.verify_save_delta(before,after,'b'*64)

def request(tmp):
    return dict(action='save_existing_upper_cone',params=dict(cone_receipt_path=str(tmp/'cone.json'),cone_receipt_sha256='a'*64,
        process_id=123,expected_document_path=str(tmp/'part.SLDPRT'),expected_source_sha256='b'*64,expected_feature_native_id=400,
        receipt_path=str(tmp/'save.json'),qualification_only=True,acknowledge_disposable_copy=True,message_policy='vendor_default',
        addin_clsid='{00000000-0000-0000-0000-000000000000}',module_sha256=m._self_pin()['sha256']))

def test_request_is_save_only_and_marker_is_not_receipt_named(tmp_path):
    x=request(tmp_path);assert m.validate_request(x)['expected_feature_native_id']==400
    first=m.save_marker(x['params']['expected_document_path'],'b'*64,400)
    x['params']['receipt_path']=str(tmp_path/'renamed.json')
    assert m.save_marker(x['params']['expected_document_path'],'b'*64,400)==first

@pytest.mark.parametrize('change',['action','extra','pid_bool','id_bool','sha','ack','module','relative'])
def test_request_rejects_wrong_scope(change,tmp_path):
    x=request(tmp_path)
    if change=='action':x['action']='GTP'
    elif change=='extra':x['params']['generate']=True
    elif change=='pid_bool':x['params']['process_id']=True
    elif change=='id_bool':x['params']['expected_feature_native_id']=True
    elif change=='sha':x['params']['cone_receipt_sha256']='not_a_hash'
    elif change=='ack':x['params']['qualification_only']=False
    elif change=='module':x['params']['module_sha256']='0'*64
    else:x['params']['receipt_path']='relative.json'
    with pytest.raises(ValueError):m.validate_request(x)

@pytest.mark.parametrize('return_value,changes',[(0,False),(True,False),(-1,False),(0,True),(0,'mass_drift')])
def test_actual_save_core_once_and_raw_capture_persisted(tmp_path,monkeypatch,return_value,changes):
    import scripts.sw_cam_events as ev
    before=state();before['document']['path']=str(tmp_path/'part.SLDPRT');Path(before['document']['path']).write_bytes(b'before')
    before['saved_file_sha256']=m._file_hash(before['document']['path'])
    payload=dict(rough={'stable':1},finish={'stable':2});observation={'circle':'unchanged'}
    (tmp_path/'cone.json').write_text('{}');(tmp_path/'cone.marker.json').write_text('{}')
    loaded=dict(state=before,reference19={'reference':'nineteen'},payload=payload['rough'],finish_payload=payload['finish'],ids={},pins=[],lineage_pins=[],
        cone_receipt_pin=m._pin(tmp_path/'cone.json'),cone_marker_pin=m._pin(tmp_path/'cone.marker.json'),cone_observation=observation,sketch_spec={},ownership={},numerical_comparisons={})
    monkeypatch.setattr(m,'load_completed_upper_cone_feature',lambda *a,**kw:deepcopy(loaded))
    native_calls=[];saved=[False];ctxs=[]
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def typed(self,*a):return object()
    class Ctx:
        def __init__(self,loaded,args,sw,typelib,app,events,expected):
            self.loaded,self.args,self.app=loaded,args,app;self.expected_document=deepcopy(expected['document']);ctxs.append(self)
        def files(self):pass
        def owned(self):pass
        def identity(self):return self.expected_document
        def guard(self):return Guard()
    class Session:
        def __init__(self,*a):self.active=False;self.disconnected=False
        def __enter__(self):self.active=True;return self
        def __exit__(self,*a):self.active=False;self.disconnected=True
        def summary(self):return dict(subscribed=True,active=self.active,disconnected=self.disconnected,event_count=0)
    monkeypatch.setattr(m,'UpperConeSaveContext',Ctx);monkeypatch.setattr(ev,'CamMessageSession',Session)
    monkeypatch.setattr(m,'_bootstrap',lambda *a:object())
    def headers(ctx,*a):
        result=deepcopy(before)
        if saved[0]:
            result['document']['needs_save']=False;result['saved_file_sha256']=ctx.args['expected_source_sha256']
            if changes is True:result['operations'][0]['id']=999
        if changes=='mass_drift':result['sw_reference']['solids'][0]['mass_raw'][0]*=(1+5e-13 if saved[0] else 1+2e-13)
        return result,{}
    monkeypatch.setattr(m.cone,'_capture_headers',headers)
    monkeypatch.setattr(m.cone,'_capture_payload',lambda *a:deepcopy(payload))
    monkeypatch.setattr(m.cone,'_read_sketch_and_cone',lambda *a:deepcopy(observation))
    def native(obj,name):
        native_calls.append(name);assert name=='SaveActiveDocument'
        if type(return_value) is int and return_value==0:
            saved[0]=True;Path(before['document']['path']).write_bytes(b'after')
        return return_value
    monkeypatch.setattr(m,'_member',native)
    monkeypatch.setattr(m,'raw_part_identity',lambda sw:dict(before['document'],needs_save=False))
    result=m.save_existing_upper_cone(object(),'clsid','typelib',cone_receipt_path=str(tmp_path/'cone.json'),cone_receipt_sha256='a'*64,
        process_id=123,expected_document_path=before['document']['path'],expected_source_sha256=before['saved_file_sha256'],expected_feature_native_id=400,
        receipt_path=str(tmp_path/'save.json'),qualification_only=True,acknowledge_disposable_copy=True)
    assert native_calls==['SaveActiveDocument']
    if type(return_value) is int and return_value==0 and changes is not True:
        assert result['model_saved'] and result['readback_verified'] and result['checkpoint']['state']['document']['needs_save'] is False
        marker=json.loads(Path(result['marker_path']).read_text());assert marker['receipt_sha256']==m._file_hash(tmp_path/'save.json')
        checked=m.load_completed_upper_cone_save(str(tmp_path/'save.json'),m._file_hash(tmp_path/'save.json'),process_id=123,
            expected_document_path=before['document']['path'],expected_source_sha256=result['saved_file_sha256'],expected_feature_native_id=400)
        assert checked['state']==result['after_context'] and len(checked['lineage_pins'])==2
        assert checked['checkpoint']==result['checkpoint']
        bad=deepcopy(result);bad['source_transition']['strict_native_save_return']=1
        (tmp_path/'bad.json').write_text(json.dumps(bad))
        with pytest.raises(ValueError,match='source transition'):
            m.load_completed_upper_cone_save(str(tmp_path/'bad.json'),m._file_hash(tmp_path/'bad.json'),process_id=123,
                expected_document_path=before['document']['path'],expected_source_sha256=result['saved_file_sha256'],expected_feature_native_id=400)
    else:
        assert result['status']=='uncertain' and not result['model_saved']
        if changes is True:assert result['after_context']['operations'][0]['id']==999
    raw=(tmp_path/'save.json').read_bytes()
    with pytest.raises(ValueError):
        m.save_existing_upper_cone(object(),'clsid','typelib',cone_receipt_path=str(tmp_path/'cone.json'),cone_receipt_sha256='a'*64,
            process_id=123,expected_document_path=before['document']['path'],expected_source_sha256=before['saved_file_sha256'],expected_feature_native_id=400,
            receipt_path=str(tmp_path/'renamed.json'),qualification_only=True,acknowledge_disposable_copy=True)
    assert (tmp_path/'save.json').read_bytes()==raw and native_calls==['SaveActiveDocument']


def test_actual_eight_mass_deltas_preserve_raw_observations():
    pair=mass_pair()
    rows=[{'path':f'/sw_reference/solids/0/mass_raw/{i}','expected':pair[0]['sw_reference']['solids'][0]['mass_raw'][i],'actual':pair[1]['sw_reference']['solids'][0]['mass_raw'][i]} for i in range(8)]
    before=state();after=deepcopy(before);after['document']['needs_save']=False;after['saved_file_sha256']='b'*64
    for row in rows:
        index=int(row['path'].rsplit('/',1)[1]);before['sw_reference']['solids'][0]['mass_raw'][index]=row['expected'];after['sw_reference']['solids'][0]['mass_raw'][index]=row['actual']
    rawbefore,rawafter=deepcopy(before),deepcopy(after);diagnostic={}
    normalized=m.verify_save_delta(before,after,'b'*64,diagnostic=diagnostic)
    assert before==rawbefore and after==rawafter
    assert normalized['sw_reference']==before['sw_reference']
    assert len(diagnostic['accepted_numeric_deltas'])==8

@pytest.mark.parametrize('kind',['larger_mass','body_bounds','operation_geometry','nonfinite'])
def test_numeric_allowance_does_not_reach_geometry(kind):
    before=state();after=deepcopy(before);after['document']['needs_save']=False;after['saved_file_sha256']='b'*64
    if kind=='larger_mass':after['sw_reference']['solids'][0]['mass_raw'][0]*=1+1e-8
    elif kind=='body_bounds':after['sw_reference']['solids'][0]['bounds'][1]+=1e-14
    elif kind=='nonfinite':after['sw_reference']['solids'][0]['mass_raw'][0]=float('nan')
    else:after['operations'][0]['geometry_delta']=1e-20
    with pytest.raises(ValueError):m.verify_save_delta(before,after,'b'*64)
