"""Output-only TURN1/2 safety regression; fake native objects, no CAD connection."""
from copy import deepcopy
import hashlib,json
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_turn_apt_postprocess as cam
from scripts import sw_cam_events as events

@pytest.fixture
def probe(tmp_path,monkeypatch):
    path=tmp_path/"turn.sldprt";path.write_bytes(b"saved")
    output=tmp_path/"new-output"/"operation.apt";receipt=tmp_path/"receipt.json"
    document=dict(path=str(path),title=path.name,type=1,needs_save=False)
    state=dict(on_enter=None,on_exit=None,on_post=None)
    native_calls=[];casts=[]
    class Session:
        def __init__(self):
            self.data=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,
                callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
        def __enter__(self):
            self.data.update(subscribed=True,active=True,disconnected=False)
            if state['on_enter']:state['on_enter']()
            return self
        def __exit__(self,*_):
            self.data.update(active=False,disconnected=True)
            if state['on_exit']:state['on_exit']()
        def summary(self):return deepcopy(self.data)
    session=Session();factory=Mock(return_value=session)
    def collection(items):return N(Count=len(items),Item=Mock(side_effect=lambda i:items[i]))
    feature=N(native_id=75);linked=collection([feature])
    toolpath=N(RecordCount=4)
    operation=N(native_id=130,OpernType=2,Suppressed=False,
        GetIsToolpathGenerated=Mock(return_value=True),IGetEnumToolpaths=Mock(return_value=collection([toolpath])),
        IGetAllFeatures=Mock(return_value=linked))
    setup=N(IGetEnumOperations=Mock(return_value=collection([operation])))
    feature_setup=N(IGetEnumFeatures=Mock(return_value=collection([feature])))
    stock=N(GetTurnWorkpieceType=Mock(return_value=1))
    machine=N(MachType=3,IGetEnumOpSetups=Mock(return_value=collection([setup])),
        IGetEnumSetups=Mock(return_value=collection([feature_setup])),IGetWorkpiece=Mock(return_value=stock),
        GetController2=Mock(return_value=(True,"turn",True)))
    doc=N(GetDocType=Mock(return_value=1),IGetMachine=Mock(return_value=machine),
        GetCWObjectID=Mock(side_effect=lambda obj:(obj.native_id,True)))
    app=N(IGetActiveDoc=Mock(return_value=doc));addin=N(GetCWApp=Mock(return_value=app))
    sw=N(GetProcessID=Mock(return_value=26552),GetAddInObject=Mock(return_value=addin))
    original_member=cam._member
    def member(obj,name,*args):
        native_calls.append((name,session.data['active']))
        if obj is not sw and obj is not addin:assert session.data['active'],name
        return original_member(obj,name,*args)
    allowed={'ICWApp4','ICWDoc3','ICWPartDoc','ICWMachine','ICWMachine5','ICWBaseSetup',
        'ICWBaseOpSetup','ICWOperation','ICWTurnOperation','ICWDispatchCollection','ICWToolpath','ICWTurnWorkpiece'}
    def typed(obj,name,*_):
        assert name in allowed,('Forbidden tool/thread cast',name)
        casts.append(name);return obj
    def post(file):
        intent=json.loads(receipt.read_text())
        assert intent['phase']=='PostProcess' and intent['native_dispatch_pending']
        assert not intent['native_call_attempted'] and not output.exists()
        assert file==str(output)
        if state['on_post']:return state['on_post']()
        output.write_bytes(b'PARTNO/QUALIFICATION\nUNITS/MM\nGOTO/1,2,3\nFINI\n')
        return 0
    operation.PostProcess=Mock(side_effect=post)
    forbidden=[]
    for obj,name in [(operation,'GenerateToolpath'),(app,'SaveActiveDocument'),(app,'ActiveDocGTP'),
            (machine,'SetController2'),(toolpath,'GetRecordAtIndex'),(toolpath,'GetEnumRecords'),
            (toolpath,'GetUnitRecordParam'),(operation,'GetTool')]:
        f=Mock(side_effect=AssertionError('Forbidden '+name));setattr(obj,name,f);forbidden.append(f)
    monkeypatch.setattr(cam,'_member',member);monkeypatch.setattr(cam,'_typed',typed)
    # Helpers accept the checked callback; their own _typed is patched too, never loaded.
    from scripts import sw_cam_turn_feature_attribute as helpers
    monkeypatch.setattr(helpers,'_typed',typed)
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(document))
    monkeypatch.setattr(helpers,'document_snapshot',lambda *_:deepcopy(document))
    monkeypatch.setattr(events,'CamMessageSession',factory)
    def call(action='inspect',**changes):
        args=dict(process_id=26552,expected_document_path=str(path),setup_index=0,operation_index=0,
            expected_operation_native_id=130,expected_operation_type=2,expected_linked_feature_ids=[75],
            expected_controller_name='turn',expected_record_count=4,expected_source_sha256=hashlib.sha256(b'saved').hexdigest(),
            action=action,qualification_only=True,message_policy='vendor_default')
        if action!='inspect':args['output_path']=str(output)
        return cam.qualify_turn_apt_postprocess(sw,'clsid','registered/camworks.tlb',**(args|changes))
    def apply(**changes):
        prepared=call('prepare');assert prepared['status']=='ok',prepared
        return call('apply',**(dict(expected_state_sha256=prepared['state_sha256'],receipt_path=str(receipt))|changes))
    return N(**locals())

@pytest.mark.parametrize('kind',[1,2])
def test_one_exact_apt_export_with_no_geometry_claim(probe,kind):
    probe.operation.OpernType=kind
    p=probe.call('prepare',expected_operation_type=kind)
    assert p['status']=='ok' and p['apply_eligible']
    assert not probe.output.parent.exists() and not probe.receipt.exists()
    r=probe.call('apply',expected_operation_type=kind,expected_state_sha256=p['state_sha256'],receipt_path=str(probe.receipt))
    assert r['status']=='review_required' and r['readback_verified'] and r['output_verified']
    assert r['native_call_attempted'] and r['native_call_returned'] and not r['native_dispatch_pending']
    assert type(r['native_hresult']) is int and r['native_hresult']==0
    assert r['before']==r['after'] and r['before']['selected_operation']['linked_feature_ids']==[75]
    for flag in ['productionNC','geometry_verified','units_verified','cut_coordinates_verified',
            'radius_vs_diameter_verified','tool_reference_verified','raw_output_interpreted',
            'CL_read_attempted','tool_readers_used','model_saved','toolpath_generation_attempted',
            'controller_changed','cnc_send_attempted','post_cleanup_cam_read_performed','automatic_retry_permitted']:
        assert r[flag] is False,flag
    probe.operation.PostProcess.assert_called_once_with(str(probe.output))
    for fn in probe.forbidden:fn.assert_not_called()
    assert json.loads(probe.receipt.read_text())['output']==r['output']

@pytest.mark.parametrize('field,value',[
    ('process_id',True),('setup_index',1.0),('operation_index',512),('expected_operation_native_id',0),
    ('expected_record_count',False),('expected_record_count',0),('expected_operation_type',True),
    ('expected_operation_type',1.0),('expected_operation_type',12),('expected_source_sha256','bad'),
    ('expected_document_path','relative.sldprt'),('qualification_only',1),('message_policy','accept'),
    ('expected_linked_feature_ids',[]),('expected_linked_feature_ids',[True]),('expected_linked_feature_ids',[1.0]),
    ('expected_linked_feature_ids',[75,75]),('expected_linked_feature_ids',[0]),('expected_linked_feature_ids',[2**32]),
    ('expected_linked_feature_ids',(75,)),('expected_controller_name',''),('expected_controller_name',' turn'),
    ('expected_controller_name','turn\x00'),('action','replay')])
def test_invalid_input_before_cam(probe,field,value):
    r=probe.call(**{field:value});assert r['status']=='error'
    probe.sw.GetAddInObject.assert_not_called();probe.operation.PostProcess.assert_not_called()

@pytest.mark.parametrize('change',['pid','dirty','source','type','generated','native_id','records','suppressed',
    'linked','duplicate_linked','not_apt','wrong_controller','unavailable_controller'])
def test_preconditions_stop_before_output(probe,change):
    args={}
    if change=='pid':probe.sw.GetProcessID.return_value=1
    elif change=='dirty':probe.document['needs_save']=True
    elif change=='source':probe.path.write_bytes(b'changed')
    elif change=='type':probe.operation.OpernType=12
    elif change=='generated':probe.operation.GetIsToolpathGenerated.return_value=False
    elif change=='native_id':probe.operation.native_id=131
    elif change=='records':probe.toolpath.RecordCount=3
    elif change=='suppressed':probe.operation.Suppressed=True
    elif change=='linked':probe.feature.native_id=76
    elif change=='duplicate_linked':probe.linked.Count=2;probe.linked.Item.side_effect=lambda _:probe.feature
    elif change=='not_apt':probe.machine.GetController2.return_value=(False,'turn',True)
    elif change=='wrong_controller':probe.machine.GetController2.return_value=(True,'Turn',True)
    else:probe.machine.GetController2.return_value=(True,'turn',False)
    assert probe.call('prepare',**args)['status']=='error'
    probe.operation.PostProcess.assert_not_called();assert not probe.output.parent.exists()

@pytest.mark.parametrize('value',[(0,'turn',True),(True,'turn',1),(True,None,True),(True,'p'),(True,'x'*4097,True)])
def test_native_controller_shape_is_exact(probe,value):
    probe.machine.GetController2.return_value=value
    assert probe.call()['status']=='error'

@pytest.mark.parametrize('change',['hash','source','controller','records','linked','native_id','type','suppressed'])
def test_prepared_state_cannot_be_rebound(probe,change):
    p=probe.call('prepare');args={}
    if change=='hash':args['expected_state_sha256']='f'*64
    elif change=='source':probe.path.write_bytes(b'changed')
    elif change=='controller':probe.machine.GetController2.return_value=(True,'other',True)
    elif change=='records':probe.toolpath.RecordCount=3
    elif change=='linked':probe.feature.native_id=76
    elif change=='native_id':probe.operation.native_id=131
    elif change=='type':probe.operation.OpernType=1
    else:probe.operation.Suppressed=True
    r=probe.call('apply',**(dict(expected_state_sha256=p['state_sha256'],receipt_path=str(probe.receipt))|args))
    assert r['status']=='error' and not r['native_call_attempted']
    probe.operation.PostProcess.assert_not_called()

@pytest.mark.parametrize('change',['missing','empty','sidecar','dirty','source','controller','records','linked','exception','false_return'])
def test_uncertain_output_preserved_and_never_replayed(probe,change):
    def post():
        if change!='missing':probe.output.write_text('' if change=='empty' else 'RAW UNINTERPRETED OUTPUT')
        if change=='exception':raise RuntimeError('native result unknown')
        if change=='sidecar':(probe.output.parent/'extra.txt').write_text('sidecar')
        elif change=='dirty':probe.document['needs_save']=True
        elif change=='source':probe.path.write_bytes(b'changed')
        elif change=='controller':probe.machine.GetController2.return_value=(True,'other',True)
        elif change=='records':probe.toolpath.RecordCount=5
        elif change=='linked':probe.feature.native_id=76
        elif change=='false_return':return False
        return 0
    probe.state['on_post']=post;r=probe.apply()
    assert r['status']=='uncertain' and not r['readback_verified'] and not r['output_verified']
    if change!='missing':assert probe.output.exists()
    old=probe.receipt.read_bytes()
    assert probe.call('apply',expected_state_sha256='a'*64,receipt_path=str(probe.receipt))['status']=='error'
    assert probe.receipt.read_bytes()==old;probe.operation.PostProcess.assert_called_once()

@pytest.mark.parametrize('when',['enter','post','exit'])
def test_message_stops_and_disconnect_has_no_cam_reads(probe,when):
    p=probe.call('prepare')
    def event():probe.session.data['event_count']=1
    probe.state['on_'+when]=event
    r=probe.call('apply',expected_state_sha256=p['state_sha256'],receipt_path=str(probe.receipt))
    assert not r['readback_verified'] and not r['output_verified'] and probe.session.data['disconnected']
    if when=='enter':probe.operation.PostProcess.assert_not_called()
    else:probe.operation.PostProcess.assert_called_once()

@pytest.mark.parametrize('change',['output','sidecar','disconnect_error'])
def test_cleanup_change_invalidates_success(probe,change):
    def callback():
        if change=='output':probe.output.write_text('changed')
        elif change=='sidecar':(probe.output.parent/'late.txt').write_text('late')
        else:probe.session.data['disconnect_errors'].append('failure')
    probe.state['on_exit']=callback
    # Prepare must happen before cleanup callback is armed.
    probe.state['on_exit']=None;p=probe.call('prepare');probe.state['on_exit']=callback
    r=probe.call('apply',expected_state_sha256=p['state_sha256'],receipt_path=str(probe.receipt))
    assert r['status']=='uncertain' and not r['readback_verified'] and not r['output_verified']
    probe.operation.PostProcess.assert_called_once()

@pytest.mark.parametrize('change',['directory','extension','receipt'])
def test_exclusive_paths(probe,change):
    args={}
    if change=='directory':probe.output.parent.mkdir()
    elif change=='extension':args['output_path']=str(probe.output.with_suffix('.nc'))
    else:probe.receipt.write_bytes(b'KEEP')
    if change=='receipt':
        assert probe.apply()['status']=='error' and probe.receipt.read_bytes()==b'KEEP'
    else:assert probe.call('prepare',**args)['status']=='error'
    probe.operation.PostProcess.assert_not_called()

def test_durable_intent_failure_stops_before_native_call(probe,monkeypatch):
    writer=cam._write_receipt
    def fail(path,report,**kw):
        if report['phase']=='PostProcess':raise OSError('cannot persist intent')
        writer(path,report,**kw)
    monkeypatch.setattr(cam,'_write_receipt',fail)
    r=probe.apply();assert r['status']=='error' and not r['native_call_attempted']
    probe.operation.PostProcess.assert_not_called()

def test_receipt_final_write_failure_invalidates_output(probe,monkeypatch):
    writer=cam._write_receipt
    def fail(path,report,**kw):
        if report['status']=='review_required':raise OSError('cannot persist final evidence')
        writer(path,report,**kw)
    monkeypatch.setattr(cam,'_write_receipt',fail)
    r=probe.apply();assert r['status']=='uncertain' and not r['readback_verified'] and not r['output_verified']
    probe.operation.PostProcess.assert_called_once();assert probe.output.exists()


@pytest.mark.parametrize('returned',[False,None,1,True,0.0])
def test_no_retval_hresult_rejects_boolean_none_or_non_sok(probe,returned):
    def post():
        probe.output.write_bytes(b'PRESERVE RAW OUTPUT')
        return returned
    probe.state['on_post']=post
    r=probe.apply()
    assert r['status']=='uncertain' and not r['output_verified'] and not r['readback_verified']
    assert type(r['native_hresult']) is type(returned) and r['native_hresult']==returned
    assert probe.output.read_bytes()==b'PRESERVE RAW OUTPUT'
    probe.operation.PostProcess.assert_called_once()
    for fn in probe.forbidden:fn.assert_not_called()


def test_actual_in_memory_postprocess_no_retval_returns_sok_integer():
    from ctypes import HRESULT
    from comtypes import IUnknown,GUID,COMMETHOD,BSTR,COMObject
    class IPost(IUnknown):
        _iid_=GUID('{DDFE8357-97A3-4585-AFD3-363A91CA28E4}')
        _methods_=[COMMETHOD([],HRESULT,'PostProcess',(['in'],BSTR,'fileName'))]
    seen=[]
    class Post(COMObject):
        _com_interfaces_=[IPost]
        def PostProcess(self,name):seen.append(name)
    obj=Post();ptr=obj.QueryInterface(IPost)
    value=cam._member(ptr,'PostProcess','in-memory-only.apt')
    assert type(value) is int and value==0 and seen==['in-memory-only.apt']
