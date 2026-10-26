from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from scripts import sw_cam_mill_stock as cam
from scripts import sw_cam_events as events

@pytest.fixture
def probe(tmp_path,monkeypatch):
    path=tmp_path/'MILL.sldprt';path.write_bytes(b'part')
    source=tmp_path/'WIP.stl';source.write_bytes(b'solid reviewed endsolid')
    source_sha=cam._file_hash(source);part_sha=cam._file_hash(path)
    proof=tmp_path/'containment.json';proof.write_text('{}')
    evidence=tmp_path/'evidence.json'
    data=dict(status='reviewed_manufacturing_stock',source_kind='turning_simulation_wip',stock_stl_path=str(source),stock_stl_sha256=source_sha,target_part_sha256=part_sha,units='mm',geometric_containment_verified=True,derivation='reviewed turning simulation output',containment_evidence_path=str(proof),containment_evidence_sha256=cam._file_hash(proof))
    def evidence_ref(**changes):
        evidence.write_text(json.dumps(data|changes));return dict(path=str(evidence),sha256=cam._file_hash(evidence))
    receipt=tmp_path/'receipt.json'
    document=dict(path=str(path),title=path.name,type=1,needs_save=False)
    old=dict(type_raw=1,bounds_native=[-1,-1,-1,1,1,1])
    initial=dict(document=document,saved_file_sha256=part_sha,current_machine={'machine_type':1},feature_setups=[],operation_counts=[],material_raw='Stainless Steel',stock=old)
    state=dict(current=deepcopy(initial),writes=[],on_write=None,on_exit=None)
    events_state=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,callback_errors=[],disconnect_errors=[])
    class Session:
        def __enter__(self):events_state.update(subscribed=True,active=True);return self
        def __exit__(self,*_):
            events_state.update(disconnected=True,active=False)
            if state['on_exit']:state['on_exit']()
        def summary(self):return deepcopy(events_state)
    def put(*args):
        durable=json.loads(receipt.read_text());assert durable['mutation_attempted'] and not durable['native_call_returned']
        assert args==(str(source),0,'',0) and events_state['active']
        state['writes'].append(args)
        state['current']['stock']=dict(type_raw=4,bounds_native=[-2,-2,-2,2,2,2],stl_path=str(source),stl_sha256=source_sha,length_units_raw=0,coordinate_system='',offsets_native=[0.]*6,uniform_flags=[False]*3)
        state['current']['document']['needs_save']=True
        if state['on_write']:state['on_write']()
        return True
    stock=SimpleNamespace(DefineWorkpieceFromSTL2=Mock(side_effect=put))
    def snapshot(*_,**kw):kw.get('check',lambda:None)();return deepcopy(state['current']),dict(app=object(),stock=stock)
    snapshots=Mock(side_effect=snapshot)
    monkeypatch.setattr(cam,'_snapshot',snapshots);monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(state['current']['document']))
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    monkeypatch.setattr(cam,'_bootstrap',lambda *_:object())
    def run(action='apply',**extra):
        args=dict(expected_document_path=str(path),action=action,qualification_only=True,message_policy='vendor_default')
        if action=='apply':args.update(stl_path=str(source),stl_sha256=source_sha,stock_evidence=evidence_ref(),expected_state_sha256=cam._digest(state['current']),receipt_path=str(receipt))
        return cam.configure_mill_stock(object(),'clsid','tlb',**(args|extra))
    return SimpleNamespace(**locals())


def test_one_stock_assignment_explicit_mm_no_bb(probe):
    out=probe.run()
    assert out['readback_verified'] and out['status']=='review_required' and len(probe.state['writes'])==1
    assert not out['model_saved'] and not out['physical_stock_independently_qualified'] and not out['GTP_attempted']
    assert json.loads(probe.receipt.read_text())==out

@pytest.mark.parametrize('action',['inspect','prepare'])
def test_read_does_not_write(probe,action):
    assert probe.run(action)['status']=='ok' and not probe.state['writes']
    assert not probe.receipt.exists()

@pytest.mark.parametrize('name,value',[('status','draft'),('source_kind','printed_product_mesh'),('stock_stl_sha256','0'*64),('target_part_sha256','0'*64),('units','inch'),('geometric_containment_verified',False),('derivation',''),('containment_evidence_sha256','0'*64)])
def test_bad_stock_provenance_blocks_write(probe,name,value):
    evidence=probe.evidence_ref(**{name:value})
    # run creates its default evidence: bind a separate immutable proof instead.
    other=probe.tmp_path/'bad.json';other.write_bytes(probe.evidence.read_bytes())
    out=probe.run(stock_evidence={'path':str(other),'sha256':cam._file_hash(other)})
    assert out['status']=='error' and not probe.state['writes']

@pytest.mark.parametrize('case',['dirty','features','operations','stale'])
def test_preconditions_block_assignment(probe,case):
    extra={};s=probe.state['current']
    if case=='dirty':s['document']['needs_save']=True
    if case=='features':s['feature_setups']=[{'feature_count':1}]
    if case=='operations':s['operation_counts']=[0]
    if case=='stale':extra['expected_state_sha256']='0'*64
    assert probe.run(**extra)['status']=='error' and not probe.state['writes']

@pytest.mark.parametrize('case',['type','units','offset','path','sha','material','event','file'])
def test_unexpected_postwrite_state_stops(probe,case):
    def change():
        s=probe.state['current'];stock=s['stock']
        if case=='type':stock['type_raw']=1
        if case=='units':stock['length_units_raw']=3
        if case=='offset':stock['offsets_native'][0]=.1
        if case=='path':stock['stl_path']='other'
        if case=='sha':stock['stl_sha256']='0'*64
        if case=='material':s['material_raw']='other'
        if case=='event':probe.events_state['event_count']=1
        if case=='file':probe.source.write_bytes(b'changed')
    probe.state['on_write']=change
    out=probe.run();assert out['status']=='uncertain' and not out['readback_verified']
    if case=='event':assert probe.snapshots.call_count==2

@pytest.mark.parametrize('kind',['event','source','document','disconnect'])
def test_cleanup_no_CAM_reads(probe,kind):
    def finish():
        if kind=='event':probe.events_state['event_count']=1
        if kind=='source':probe.source.write_bytes(b'other')
        if kind=='document':probe.state['current']['document']['title']='other'
        if kind=='disconnect':probe.events_state['disconnected']=False
    probe.state['on_exit']=finish
    out=probe.run();assert out['status']=='uncertain' and probe.snapshots.call_count==4
    assert not out['post_cleanup_CAM_getters']

@pytest.mark.parametrize('raw',[None,[],[0,0,0,1,1,1,1],[0,0,0,0,1,1,True],[0,0,0,float('nan'),1,1,True],[False,0,0,1,1,1,True]])
def test_invalid_native_bounds(raw):
    with pytest.raises(ValueError):cam._bbox(raw)


@pytest.mark.parametrize('action',['inspect','prepare'])
def test_initial_read_is_subscribed_and_event_is_fail_stop(probe,action):
    original=probe.snapshots.side_effect
    def snapshot(*args,**kwargs):
        assert probe.events_state['active'] and probe.events_state['subscribed']
        result=original(*args,**kwargs)
        probe.events_state['event_count']=1
        kwargs['check']()
        return result
    probe.snapshots.side_effect=snapshot
    extra={'machine_index':None} if action=='inspect' and hasattr(probe,'target') else {}
    out=probe.run(action,**extra)
    assert out['status']=='error' and not probe.state['writes']
    assert probe.snapshots.call_count==1 and out['messages']['disconnected']

@pytest.mark.parametrize('action',['inspect','prepare'])
def test_readonly_cleanup_file_change_is_detected(probe,action):
    probe.state['on_exit']=lambda:probe.path.write_bytes(b'changed during disconnect')
    extra={'machine_index':None} if action=='inspect' and hasattr(probe,'target') else {}
    out=probe.run(action,**extra)
    assert out['status']=='error' and not probe.state['writes']
    assert probe.snapshots.call_count==1
