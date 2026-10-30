"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
from copy import deepcopy
from pathlib import Path
import importlib.util,json,sys
import pytest
from scripts import sw_cam_raw_mill_face_move as m
from cam_face_test_fixtures import current
@pytest.fixture
def actual():return current()

def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return m._pin(path)



def fake_context(actual,tmp_path):
    current=m._projection(actual);source=tmp_path/'part.sldprt';source.write_bytes(b'current_source');sha=m._file_hash(source)
    current['source_sha256']=sha;current['state']['saved_file_sha256']=sha;current['state']['document']['path']=str(source)
    failed=write(tmp_path/'failed_insert.json',{'status':'uncertain'})
    guard=write(tmp_path/'original_attempt.json',{'status':'uncertain','automatic_replay':False})
    parent_data=dict(scope='RAW_MILL_FACE_APPEND_READONLY_RECOVERY_V1',phase='finished',status='observed',read_only=True,readback_verified=True,
      state_recovered=True,original_failure_resolved=True,route_order_qualified=False,placement_verified='APPENDED267_AFTER248_NOT_REQUESTED_AFTER196',
      process_id=23824,source_path=str(source),source_sha256=sha,face_feature_native_id=265,new_operation_native_id=267,
      failed_pin=failed,failed_marker_pin=guard,evidence_pins=[failed,guard],lineage_pins=[])
    cp=dict(state=deepcopy(current['state']),payload=dict(rough=deepcopy(current['payload']),finish=deepcopy(current['finish_payload'])),
      cone_observation=current['cone_observation'],face_observation=current['face_observation'],cone_sketch_spec=current['cone_sketch_spec'],
      face_sketch_spec=current['face_sketch_spec'],cone_feature_native_id=current['cone_feature_native_id'],face_feature_native_id=265,new_operation_native_id=267,source_sha256=sha)
    parent_data.update(checkpoint=cp,checkpoint_sha256=m._digest(cp));parent=write(tmp_path/'current_parent.json',parent_data);parent=m.read_pin(parent['path'],parent['sha256'])[1]
    loaded=m._cutover(dict(current,pins=[guard,parent],lineage_pins=[failed],failed_pin=failed,failed_marker_pin=guard),parent)
    return loaded,source,sha


def test_current_scope_does_not_read_archive_after_cutover(actual,tmp_path,monkeypatch):
    loaded,source,sha=fake_context(actual,tmp_path);archive=Path(loaded['predecessor_validation']['original_history_pins'][0]['path'])
    archive.write_text('changed after offline phase',encoding='utf-8');seen=[];original=m._file_hash
    def hashed(path):
        seen.append(m._key(path));assert m._key(path)!=m._key(archive)
        return original(path)
    monkeypatch.setattr(m,'_file_hash',hashed)
    ctx=m.CurrentMoveContext(loaded,{},None,None,None,None,loaded['state']);ctx.files()
    assert m._key(archive) not in seen
    loaded['state']['operation_count']=99
    with pytest.raises(ValueError,match='immutable context'):ctx.files()


def test_changed_live_pin_blocks_context(actual,tmp_path):
    loaded,_,_=fake_context(actual,tmp_path);Path(loaded['original_insert_marker_pin']['path']).write_text('tamper')
    ctx=m.CurrentMoveContext(loaded,{},None,None,None,None,loaded['state'])
    with pytest.raises(ValueError,match='dependency'):ctx.files()


def simulate(monkeypatch,loaded,source,sha,tmp_path,*,dirty=False,result=0,bad_payload=False,raises=False):
    before=deepcopy(loaded['state']);after=deepcopy(before)
    rows={r['native_id']:r for r in after['operations']};after['operations']=[rows[n] for n in m.AFTER_ORDER]
    for i,r in enumerate(after['operations']):r['operation_index']=i
    after['document']['needs_save']=dirty
    class Obj:
        def __init__(self,oid):self.oid=oid
    setups=[Obj(93),Obj(94),Obj(95)];ops={n:Obj(n) for n in m.BEFORE_ORDER};machine=Obj(9);calls=[]
    native={'doc':Obj(1),'machine':machine,'operations':ops}
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def typed(self,obj,name):return obj
        def read(self,obj,name,*args):
            if name=='IGetEnumOpSetups':return setups
            if name=='QueryInterface':return obj
            raise AssertionError(name)
        def dispatch_once(self,invoke,*,persist_pending):persist_pending();return invoke()
        def summary(self):return {'native_call_returned':not raises}
    class Context(m.CurrentMoveContext):
        def identity(self):return deepcopy(self.expected_document)
        def guard(self):return Guard()
    class Session:
        def __init__(self,*a):self.active=False
        def __enter__(self):self.active=True;return self
        def __exit__(self,*a):self.active=False
        def summary(self):return dict(subscribed=True,active=self.active,disconnected=not self.active,event_count=0)
    import scripts.sw_cam_events as events
    monkeypatch.setattr(events,'CamMessageSession',Session);monkeypatch.setattr(m,'CurrentMoveContext',Context)
    monkeypatch.setattr(m.capture.cone,'_bootstrap',lambda *a:Obj(2))
    monkeypatch.setattr(m.capture,'_items',lambda values,*args:list(values))
    monkeypatch.setattr(m,'_object_id',lambda doc,obj,read:obj.oid)
    monkeypatch.setattr(m,'raw_part_identity',lambda sw:deepcopy(after['document']))
    def headers(ctx,clsid,reference,count,diag,**kw):return deepcopy(before if not calls else after),native
    monkeypatch.setattr(m.capture,'_capture_headers',headers)
    def payload(ctx,state,native,diag,**kw):
        value=m.capture._payload(loaded)
        if bad_payload and calls:value['rough']['tamper']=True
        return value
    monkeypatch.setattr(m.capture,'_capture_payload',payload)
    monkeypatch.setattr(m.capture.cone,'_read_sketch_and_cone',lambda *a:deepcopy(loaded['cone_observation']))
    monkeypatch.setattr(m.capture.face,'_read_face',lambda *a,**kw:deepcopy(loaded['face_observation']))
    def member(obj,name,*args):
        calls.append((obj.oid,name,args))
        assert (obj.oid,name)==(93,'InsertOperationAfter') and tuple(v.oid for v in args[:2])==(267,196) and args[2] is False
        if raises:raise RuntimeError('simulated COM failure')
        return result
    monkeypatch.setattr(m,'_member',member)
    args=dict(loaded=loaded,process_id=23824,expected_document_path=str(source),expected_source_sha256=sha,
      receipt_path=str(tmp_path/'move.json'),qualification_only=True,acknowledge_disposable_copy=True)
    got=m._run_move(None,'clsid','type.tlb',**args)
    return got,calls,args,after


@pytest.mark.parametrize('dirty',[False,True])
def test_one_move_success_and_flat_terminal_loader(actual,tmp_path,monkeypatch,dirty):
    loaded,source,sha=fake_context(actual,tmp_path)
    got,calls,args,after=simulate(monkeypatch,loaded,source,sha,tmp_path,dirty=dirty)
    assert got['readback_verified'] and got['after_context']==after and len(calls)==1
    # Reject recursive predecessor loaders: the successor validates current receipt/proof directly.
    import scripts.sw_cam_raw_mill_face_operation_append_recovery as old
    monkeypatch.setattr(old,'load_completed_face_operation_recovery',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('archive loader invoked')))
    done=m.load_completed_move(args['receipt_path'],m._file_hash(args['receipt_path']),process_id=23824,
      expected_document_path=str(source),expected_source_sha256=sha)
    assert tuple(r['native_id'] for r in done['state']['operations'])==m.AFTER_ORDER and done['state']['document']['needs_save'] is dirty
    assert len(done['pins'])<=64 and done['lineage_pins']==[]
    original=Path(args['receipt_path']).read_bytes();args['receipt_path']=str(tmp_path/'another.json')
    with pytest.raises(ValueError,match='Attempt exists'):m._run_move(None,'clsid','type.tlb',**args)
    assert len(calls)==1 and original==(tmp_path/'move.json').read_bytes()


@pytest.mark.parametrize('mode',['bad_payload','wrong_return','exception'])
def test_uncertain_keeps_raw_and_never_replays(actual,tmp_path,monkeypatch,mode):
    loaded,source,sha=fake_context(actual,tmp_path)
    got,calls,args,after=simulate(monkeypatch,loaded,source,sha,tmp_path,bad_payload=mode=='bad_payload',result=None if mode=='wrong_return' else 0,raises=mode=='exception')
    assert got['status']=='uncertain' and not got['readback_verified'] and len(calls)==1
    disk=json.loads(Path(args['receipt_path']).read_text(encoding='utf-8-sig'))
    if mode=='bad_payload':assert disk['after_context']==after and disk['after_payload']['rough']['tamper']
    elif mode=='wrong_return':assert disk['native_return_type']=='NoneType' and disk['native_return_value'] is None and disk['native_return_value_recorded'] is True
    else:assert 'after_context' not in disk
    args['receipt_path']=str(tmp_path/'replay.json')
    with pytest.raises(ValueError):m._run_move(None,'clsid','type.tlb',**args)
    assert len(calls)==1

