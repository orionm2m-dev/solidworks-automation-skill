from array import array
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from scripts import sw_cam_mill_qualification as cam
from scripts import sw_cam_events as events

@pytest.fixture
def probe(tmp_path,monkeypatch):
    path=tmp_path/'MILL_QUAL.sldprt';path.write_bytes(b'part')
    receipt=tmp_path/'receipt.json'
    target=dict(machine_type=1,name='Qualified mill',machine_id='MILL01',description='catalogue')
    old=dict(machine_type=3,name='Turn',machine_id='TURN01',description='catalogue')
    initial=dict(document=dict(path=str(path),title=path.name,type=1,needs_save=False),saved_file_sha256=cam._file_hash(path),
                 current_machine=old,mill_catalogue=[target],feature_setups=[],operation_counts=[],material_raw='Steel',
                 extend_holes_to_stock=False,unit_record_raw='raw')
    state=dict(current=deepcopy(initial),writes=[],on_write=None,on_snapshot=None,on_exit=None)
    data=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,callback_errors=[],disconnect_errors=[])
    class Session:
        def __enter__(self):data.update(subscribed=True,active=True);return self
        def __exit__(self,*_):
            data.update(active=False,disconnected=True)
            if state['on_exit']:state['on_exit']()
        def summary(self):return deepcopy(data)
    def put(kind,args):
        durable=json.loads(receipt.read_text())
        assert durable['mutation_attempted'] and not durable['native_call_returned'] and data['active']
        state['writes'].append((kind,args))
        if kind=='machine':state['current']['current_machine']=deepcopy(target)
        else:
            assert isinstance(args[0],array) and args[0].typecode=='d' and args[2] is False
            state['current']['feature_setups'].append(dict(native_id=77,name='Setup',feature_count=0,axis_native=list(args[0]),origin_native=list(args[1]),origin_type_raw=0))
        state['current']['document']['needs_save']=True
        if state['on_write']:state['on_write']()
        return SimpleNamespace(native_id=77)
    doc=SimpleNamespace(SetMachine2=Mock(side_effect=lambda obj:put('machine',(obj,))),GetCWObjectID=Mock(side_effect=lambda obj:(obj.native_id,True)))
    machine=SimpleNamespace(InsertMillSetup=Mock(side_effect=lambda *args:put('setup',args)))
    def snapshot(*_,**kw):
        check=kw.get('check',lambda:None);check()
        if state['on_snapshot']:state['on_snapshot']()
        check()
        return deepcopy(state['current']),dict(app=object(),doc=doc,machine=machine,candidates=[object()],setups=[object() for _ in state['current']['feature_setups']])
    snapshots=Mock(side_effect=snapshot)
    monkeypatch.setattr(cam,'_snapshot',snapshots)
    monkeypatch.setattr(cam,'_typed',lambda obj,*_:obj)
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(state['current']['document']))
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    monkeypatch.setattr(cam,'_bootstrap',lambda *_:object())
    defaults=dict(expected_document_path=str(path),operation='machine',machine_index=0,qualification_only=True,message_policy='vendor_default')
    def run(action='apply',**extra):
        args=defaults|dict(action=action)
        if action=='apply':args.update(expected_state_sha256=cam._digest(dict(snapshot=state['current'],operation=extra.get('operation',args['operation']),machine_index=extra.get('machine_index',args['machine_index']),direction=cam._direction(extra['direction']) if extra.get('direction') is not None else None)),receipt_path=str(receipt))
        return cam.configure_mill_qualification(object(),'clsid','tlb',**(args|extra))
    def setup():state['current']['current_machine']=deepcopy(target)
    return SimpleNamespace(**locals())


def test_machine_exact_assignment_and_durable_receipt(probe):
    out=probe.run()
    assert out['status']=='review_required' and out['readback_verified'] and len(probe.state['writes'])==1
    assert not out['model_saved'] and not out['GOP_attempted'] and not out['stock_qualified']
    assert out==json.loads(probe.receipt.read_text()) and out['messages']['disconnected']

@pytest.mark.parametrize('direction',[[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]])
def test_setup_one_empty_cardinal_origin_zero(probe,direction):
    probe.setup()
    out=probe.run(operation='setup',machine_index=None,direction=direction)
    assert out['readback_verified'] and out['new_setup_native_id']==77
    assert not out['AFR_attempted'] and not out['GTP_attempted']

@pytest.mark.parametrize('direction',[None,[],[0,0],[0,0,0],[1,1,0],[.5,0,0],[True,0,0],['1',0,0],[float('nan'),0,0],[float('inf'),0,0]])
def test_invalid_vector_before_native_read(probe,direction):
    with pytest.raises(ValueError):probe.run(operation='setup',machine_index=None,direction=direction)
    probe.snapshots.assert_not_called()

@pytest.mark.parametrize('kwargs',[dict(qualification_only=False),dict(message_policy='silent'),dict(action='unknown'),dict(operation='bad'),dict(machine_index=True),dict(machine_index=-1),dict(machine_index=128),dict(direction=[1,0,0]),dict(expected_state_sha256='bad'),dict(receipt_path='relative.json')])
def test_input_rejections_before_read(probe,kwargs):
    with pytest.raises(ValueError):probe.run(**kwargs)
    probe.snapshots.assert_not_called()

@pytest.mark.parametrize('action',['inspect','prepare'])
def test_no_mutation_on_read(probe,action):
    out=probe.run(action=action,**({'machine_index':None} if action=='inspect' else {}))
    assert out['status']=='ok' and not probe.state['writes'] and not probe.receipt.exists()

@pytest.mark.parametrize('case',['dirty','feature','op','empty_setup','empty_opsetup','stale','same','missing_index'])
def test_machine_preconditions_prevent_write(probe,case):
    s=probe.state['current'];extra={}
    if case=='dirty':s['document']['needs_save']=True
    if case=='feature':s['feature_setups']=[dict(native_id=8,name='existing',feature_count=1)]
    if case=='op':s['operation_counts']=[1]
    if case=='empty_setup':s['feature_setups']=[dict(native_id=8,name='existing',feature_count=0)]
    if case=='empty_opsetup':s['operation_counts']=[0]
    if case=='stale':extra['expected_state_sha256']='0'*64
    if case=='same':probe.setup()
    if case=='missing_index':extra['machine_index']=1
    out=probe.run(**extra)
    assert out['status']=='error' and not probe.state['writes']

@pytest.mark.parametrize('change',['event','unexpected_stock','wrong_axis','extra_feature','extra_setup','file'])
def test_setup_postwrite_failures_are_uncertain(probe,change):
    probe.setup()
    def changed():
        s=probe.state['current']
        if change=='event':probe.data['event_count']=1
        if change=='unexpected_stock':s['material_raw']='other'
        if change=='wrong_axis':s['feature_setups'][-1]['axis_native']=[0.,0.,-1.]
        if change=='extra_feature':s['feature_setups'][-1]['feature_count']=1
        if change=='extra_setup':s['feature_setups'].append(deepcopy(s['feature_setups'][-1]))
        if change=='file':probe.path.write_bytes(b'changed')
    probe.state['on_write']=changed
    out=probe.run(operation='setup',machine_index=None,direction=[0,0,1])
    assert out['status']=='uncertain' and not out['readback_verified'] and len(probe.state['writes'])==1
    if change=='event':assert probe.snapshots.call_count==2 and probe.doc.GetCWObjectID.call_count==0

@pytest.mark.parametrize('kind',['event','file','document','disconnect'])
def test_no_CAM_read_after_cleanup(probe,kind):
    def changed():
        if kind=='event':probe.data['event_count']=1
        if kind=='file':probe.path.write_bytes(b'changed')
        if kind=='document':probe.state['current']['document']['path']='other'
        if kind=='disconnect':probe.data['disconnected']=False
    probe.state['on_exit']=changed
    out=probe.run()
    assert out['status']=='uncertain' and not out['readback_verified']
    assert probe.snapshots.call_count==4 and not out['post_cleanup_CAM_getters']


def test_existing_receipt_never_replayed(probe):
    probe.receipt.write_text('{}')
    with pytest.raises(ValueError):probe.run()
    probe.snapshots.assert_not_called()


def test_snapshot_guard_stops_nested_count(monkeypatch,tmp_path):
    from scripts import sw_cam_turn_feature_attribute as guarded
    path=tmp_path/'actual.sldprt';path.write_bytes(b'actual')
    document=dict(path=str(path),title=path.name,type=1,needs_save=False)
    flag=[False];calls=[]
    class Catalogue:
        def Count(self):calls.append('Count');flag[0]=True;return 2
        def Item(self,i):calls.append('Item');raise AssertionError('must not reach Item')
    machine=SimpleNamespace(MachType=0)
    doc=SimpleNamespace(GetDocType=Mock(return_value=1),IGetMachine=Mock(return_value=machine))
    app=SimpleNamespace(IGetActiveDoc=Mock(return_value=doc),GetNumMachineOfType=Mock(return_value=2),GetMachines=Mock(return_value=Catalogue()))
    sw=SimpleNamespace(GetAddInObject=Mock(return_value=SimpleNamespace(GetCWApp=Mock(return_value=app))))
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(document))
    monkeypatch.setattr(cam,'_typed',lambda obj,*_:obj);monkeypatch.setattr(guarded,'_typed',lambda obj,*_:obj)
    def check():
        if flag[0]:raise ValueError('native event')
    with pytest.raises(ValueError,match='native event'):cam._snapshot(sw,'clsid','tlb',str(path),check=check)
    assert calls==['Count']


@pytest.mark.parametrize('action',['inspect','prepare'])
def test_initial_read_is_subscribed_and_event_is_fail_stop(probe,action):
    original=probe.snapshots.side_effect
    def snapshot(*args,**kwargs):
        assert probe.data['active'] and probe.data['subscribed']
        result=original(*args,**kwargs)
        probe.data['event_count']=1
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



def test_real_mill_snapshot_never_calls_unsafe_unit_getter(tmp_path,monkeypatch):
    path=tmp_path/'part.sldprt';path.write_bytes(b'fixture')
    state=dict(path=str(path),title=path.name,type=1,needs_save=False)
    machine=SimpleNamespace(MachType=1,Name='Mill',MachId='M1',Description='',
        IGetEnumSetups=Mock(return_value=[]),IGetEnumOpSetups=Mock(return_value=[]),IGetWorkpiece=Mock(return_value=None))
    doc=SimpleNamespace(GetDocType=Mock(return_value=1),IGetMachine=Mock(return_value=machine),ExtendHolesToStock=False,
        GetUnitRecordParam=Mock(side_effect=AssertionError('Known unsafe getter must never be called')))
    app=SimpleNamespace(IGetActiveDoc=Mock(return_value=doc),GetNumMachineOfType=Mock(return_value=0),GetMachines=Mock(return_value=[]))
    sw=SimpleNamespace(GetAddInObject=Mock(return_value=SimpleNamespace(GetCWApp=Mock(return_value=app))))
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(state))
    monkeypatch.setattr(cam,'_typed',lambda obj,*_:obj)
    monkeypatch.setattr(cam,'_items',lambda value,*args,**kw:list(value))
    result,_=cam._snapshot(sw,'clsid','tlb',str(path))
    assert result['unit_record_raw'] is None
    assert result['unit_record_status']=='unavailable_native_getter_disabled_after_RPC_failure'
    doc.GetUnitRecordParam.assert_not_called()


# 真实快照分支的有界假对象；不连接 CAD。
@pytest.fixture
def catalogue_probe(tmp_path,monkeypatch):
    from scripts import sw_cam_turn_feature_attribute as guarded
    path=tmp_path/'catalogue.sldprt';path.write_bytes(b'owned catalogue fixture')
    document=dict(path=str(path),title=path.name,type=1,needs_save=False)
    class Collection:
        def __init__(self,values):self.values=values
        @property
        def Count(self):return len(self.values)
        def Item(self,i):return self.values[i]
    machine=SimpleNamespace(MachType=0,IGetEnumSetups=Mock(return_value=Collection([])),
        IGetEnumOpSetups=Mock(return_value=Collection([])),IGetWorkpiece=Mock(return_value=None))
    doc=SimpleNamespace(GetDocType=Mock(return_value=1),IGetMachine=Mock(return_value=machine),
        ExtendHolesToStock=False,SetMachine2=Mock(side_effect=AssertionError('unexpected mutation')))
    rows=[SimpleNamespace(MachType=1,Name='Mill A',MachId='shared',Description='A'),
          SimpleNamespace(MachType=1,Name='Mill B',MachId='shared',Description='B')]
    app=SimpleNamespace(IGetActiveDoc=Mock(return_value=doc),GetNumMachineOfType=Mock(return_value=2),
        GetMachines=Mock(side_effect=lambda _:Collection(rows)))
    sw=SimpleNamespace(GetAddInObject=Mock(return_value=SimpleNamespace(GetCWApp=Mock(return_value=app))))
    data=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,callback_errors=[],disconnect_errors=[])
    class Session:
        def __enter__(self):data.update(subscribed=True,active=True);return self
        def __exit__(self,*_):data.update(active=False,disconnected=True)
        def summary(self):return deepcopy(data)
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(document))
    monkeypatch.setattr(cam,'_typed',lambda obj,*_:obj);monkeypatch.setattr(guarded,'_typed',lambda obj,*_:obj)
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    def run():return cam.configure_mill_qualification(sw,'clsid','tlb',expected_document_path=str(path),
        action='inspect',operation='machine',qualification_only=True,message_policy='vendor_default')
    return SimpleNamespace(**locals())


def test_real_duplicate_id_inspect_preserves_catalogue_and_context(catalogue_probe):
    p=catalogue_probe;out=p.run();d=out['snapshot_diagnostics'][0]
    assert out['status']=='ok' and d['capture_complete'] and d['catalogue_read_complete']
    assert d['document']==p.document and d['saved_file_sha256']==cam._file_hash(p.path)
    assert d['current_machine']=={'machine_type':0}
    assert d['duplicate_machine_ids']==[{'machine_id':'shared','catalogue_indices':[0,1]}]
    assert not d['catalogue_identity_unique']
    assert [x['catalogue_index'] for x in d['catalogue_entries']]==[0,1]
    assert [x['machine']['name'] for x in d['catalogue_entries']]==['Mill A','Mill B']
    p.doc.SetMachine2.assert_not_called()
    assert out['messages']['disconnected'] and not out['mutation_attempted']


def test_real_catalogue_count_mismatch_keeps_partial_and_stops(catalogue_probe):
    p=catalogue_probe;p.app.GetNumMachineOfType.return_value=3
    out=p.run();d=out['snapshot_diagnostics'][0]
    assert out['status']=='error' and not out['apply_eligible']
    assert out['error_code']=='MILL_CATALOGUE_COUNT_MISMATCH'
    assert d['catalogue_declared_count']==3 and d['catalogue_collection_count']==2
    assert not d['capture_complete'] and not d['catalogue_read_complete']
    assert d['document']==p.document and d['current_machine']=={'machine_type':0}
    p.machine.IGetEnumSetups.assert_not_called();p.doc.SetMachine2.assert_not_called()


def test_real_partial_catalogue_getter_failure_retains_prior_fields(catalogue_probe):
    p=catalogue_probe;p.rows[1].Description=Mock(side_effect=RuntimeError('native failed'))
    out=p.run();d=out['snapshot_diagnostics'][0]
    assert out['status']=='error' and d['stage']=='Description' and not d['capture_complete']
    assert d['catalogue_entries'][0]['read_complete']
    second=d['catalogue_entries'][1]
    assert not second['read_complete'] and second['machine']==dict(machine_type=1,name='Mill B',machine_id='shared')
    p.machine.IGetEnumSetups.assert_not_called();p.rows[1].Description.assert_called_once()
    assert out['messages']['disconnected'] and not out['apply_eligible']


def test_real_catalogue_event_stops_before_next_getter(catalogue_probe):
    p=catalogue_probe
    def name():p.data['event_count']=1;return 'event changed'
    p.rows[1].Name=Mock(side_effect=name);p.rows[1].MachId=Mock(side_effect=AssertionError('no subsequent getter'))
    out=p.run();d=out['snapshot_diagnostics'][0]
    assert out['status']=='error' and not d['capture_complete'] and d['stage']=='Name'
    assert d['catalogue_entries'][0]['read_complete']
    assert d['catalogue_entries'][1]['machine']=={'machine_type':1}
    p.rows[1].MachId.assert_not_called();p.machine.IGetEnumSetups.assert_not_called()


def test_same_machine_id_distinct_descriptors_allow_exact_selected_object(probe):
    target=probe.state['current']['mill_catalogue'][0]
    probe.state['current']['mill_catalogue'].append(target|dict(name='Other mill',description='other'))
    out=probe.run()
    assert out['readback_verified'] and out['selected_machine_unique']
    assert out['selected_machine_matching_catalogue_indices']==[0]
    assert out['selected_machine_catalogue_index']==0 and len(probe.state['writes'])==1


@pytest.mark.parametrize('action',['prepare','apply'])
def test_selected_duplicate_full_descriptor_refuses_before_write(probe,action):
    probe.state['current']['mill_catalogue']*=2
    out=probe.run(action)
    assert out['status']=='error' and out['error_code']=='MILL_SELECTED_MACHINE_DESCRIPTOR_AMBIGUOUS'
    assert out['selected_machine_matching_catalogue_indices']==[0,1]
    assert not out['apply_eligible'] and not out['mutation_attempted'] and not probe.state['writes']


def test_duplicate_unselected_full_descriptor_does_not_block_unique_selection(probe):
    other=probe.target|dict(name='Other',description='unselected')
    probe.state['current']['mill_catalogue'] += [deepcopy(other),deepcopy(other)]
    out=probe.run()
    assert out['readback_verified'] and out['selected_machine_matching_catalogue_indices']==[0]


@pytest.mark.parametrize('change',['order','name','selected_index'])
def test_prepare_binds_order_names_and_selected_index(probe,change):
    target=probe.state['current']['mill_catalogue'][0]
    probe.state['current']['mill_catalogue'].append(target|dict(name='Other',description='second'))
    prepared=probe.run('prepare');extra={}
    assert prepared['status']=='ok'
    if change=='order':probe.state['current']['mill_catalogue'].reverse()
    elif change=='name':probe.state['current']['mill_catalogue'][0]['name']='Changed'
    else:extra['machine_index']=1
    out=probe.run(expected_state_sha256=prepared['state_sha256'],**extra)
    assert out['status']=='error' and not probe.state['writes'] and not out['mutation_attempted']


def test_catalogue_reorder_between_captures_blocks_dispatch(probe):
    probe.state['current']['mill_catalogue'].append(probe.target|dict(name='Other'))
    calls=[0]
    def change():
        calls[0]+=1
        if calls[0]==2:probe.state['current']['mill_catalogue'].reverse()
    probe.state['on_snapshot']=change
    out=probe.run()
    assert out['status']=='error' and calls[0]==2 and not probe.state['writes']


def test_setup_allows_duplicate_catalogue_ids_without_selection(probe):
    probe.setup();probe.state['current']['mill_catalogue']*=2
    out=probe.run(operation='setup',machine_index=None,direction=[0,0,1])
    assert out['readback_verified'] and len(probe.state['writes'])==1
    assert 'selected_machine' not in out


def test_setup_prepare_hash_binds_direction(probe):
    probe.setup()
    prepared=probe.run('prepare',operation='setup',machine_index=None,direction=[0,0,1])
    assert prepared['status']=='ok'
    out=probe.run(operation='setup',machine_index=None,direction=[0,0,-1],expected_state_sha256=prepared['state_sha256'])
    assert out['status']=='error' and not out['mutation_attempted'] and not probe.state['writes']
