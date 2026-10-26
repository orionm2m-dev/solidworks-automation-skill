"""Output-only TURN1/2 safety regression; fake native objects, no CAD connection."""
from copy import deepcopy
import hashlib,json
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_generic_cl as cam
from scripts import sw_cam_events as events

@pytest.fixture
def probe(tmp_path,monkeypatch):
    path=tmp_path/"turn.sldprt";path.write_bytes(b"saved")
    output=tmp_path/"new-output"/"machine.cl";receipt=tmp_path/"receipt.json"
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
    toolpath=N(RecordCount=40)
    operation=N(native_id=161,OpernType=12,Suppressed=False,
        GetIsToolpathGenerated=Mock(return_value=True),IGetEnumToolpaths=Mock(return_value=collection([toolpath])),
        IGetAllFeatures=Mock(return_value=linked))
    ungenerated=[N(native_id=200+i,OpernType=(1,2,3,9)[i%4],GetIsToolpathGenerated=Mock(return_value=False),IGetEnumToolpaths=Mock(side_effect=AssertionError("No toolpaths getter on ungenerated"))) for i in range(15)]
    operations=[operation]+ungenerated
    setup=N(IGetEnumOperations=Mock(return_value=collection(operations)))
    feature_setup=N(IGetEnumFeatures=Mock(return_value=collection([feature])))
    stock=N(GetTurnWorkpieceType=Mock(return_value=1))
    machine=N(MachType=3,IGetEnumOpSetups=Mock(return_value=collection([setup])),
        IGetEnumSetups=Mock(return_value=collection([feature_setup])),IGetWorkpiece=Mock(return_value=stock),
        GetController2=Mock(return_value=(True,"",False)))
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
        assert intent['phase']=='SaveCLFile' and intent['native_dispatch_pending']
        assert not intent['native_call_attempted'] and not output.exists()
        assert file==str(output)
        if state['on_post']:return state['on_post']()
        output.write_bytes(b'UNINTERPRETED GENERIC CL\n')
        return 0
    machine.SaveCLFile=Mock(side_effect=post)
    forbidden=[]
    for obj,name in [(operation,'GenerateToolpath'),(machine,'GenerateOperations'),(app,'ActiveDocExtractMachinableFeatures'),(operation,'PostProcess'),(app,'SaveActiveDocument'),(app,'ActiveDocGTP'),
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
        args=dict(process_id=26552,expected_document_path=str(path),expected_operation_count=16,
            expected_generated_operation_count=1,expected_total_record_count=40,
            expected_source_sha256=hashlib.sha256(b'saved').hexdigest(),action=action,
            qualification_only=True,acknowledge_machine_scope=True,message_policy='vendor_default')
        if action!='inspect':args['output_path']=str(output)
        return cam.export_generic_cl(sw,'clsid','registered/camworks.tlb',**(args|changes))
    def apply(**changes):
        prepared=call('prepare');assert prepared['status']=='ok',prepared
        return call('apply',**(dict(expected_state_sha256=prepared['state_sha256'],receipt_path=str(receipt))|changes))
    return N(**locals())


def test_machine_export_without_valid_controller_preserves_all_ungenerated(probe):
    p=probe.call('prepare');assert p['status']=='ok' and p['apply_eligible']
    assert not probe.output.parent.exists() and not probe.receipt.exists()
    r=probe.call('apply',expected_state_sha256=p['state_sha256'],receipt_path=str(probe.receipt))
    assert r['status']=='review_required' and r['readback_verified'] and r['output_verified']
    assert r['before']==r['after'] and len(r['after']['operation_identities'])==16
    assert r['after']['controller']==dict(is_apt=True,name='',success=False)
    assert r['native_hresult']==0 and type(r['native_hresult']) is int
    assert r['export_scope']=='whole_current_turn_machine'
    for name in ('productionNC','geometry_verified','units_verified','model_saved','toolpath_generation_attempted',
                 'GOP_attempted','AFR_attempted','controller_changed','post_cleanup_cam_read_performed','raw_output_interpreted'):
        assert r[name] is False
    probe.machine.SaveCLFile.assert_called_once_with(str(probe.output))
    for fn in probe.forbidden:fn.assert_not_called()
    for op in probe.ungenerated:op.IGetEnumToolpaths.assert_not_called()
    assert json.loads(probe.receipt.read_text())['output']==r['output']

@pytest.mark.parametrize('field,value',[
 ('process_id',True),('expected_operation_count',0),('expected_operation_count',16.0),
 ('expected_generated_operation_count',False),('expected_generated_operation_count',17),
 ('expected_total_record_count',0),('expected_total_record_count',40.0),('expected_source_sha256','bad'),
 ('expected_document_path','relative.sldprt'),('qualification_only',1),('acknowledge_machine_scope',1),
 ('message_policy','accept'),('action','replay')])
def test_invalid_input_stops_before_cam(probe,field,value):
    assert probe.call(**{field:value})['status']=='error'
    probe.sw.GetAddInObject.assert_not_called();probe.machine.SaveCLFile.assert_not_called()

@pytest.mark.parametrize('change',['pid','dirty','source','machine_type','generated','records','duplicate_id'])
def test_exact_preconditions(probe,change):
    if change=='pid':probe.sw.GetProcessID.return_value=1
    elif change=='dirty':probe.document['needs_save']=True
    elif change=='source':probe.path.write_bytes(b'changed')
    elif change=='machine_type':probe.machine.MachType=1
    elif change=='generated':probe.operation.GetIsToolpathGenerated.return_value=False
    elif change=='records':probe.toolpath.RecordCount=39
    else:probe.ungenerated[0].native_id=161
    assert probe.call('prepare')['status']=='error'
    probe.machine.SaveCLFile.assert_not_called()

@pytest.mark.parametrize('change',['hash','controller','native_id','type','output'])
def test_stale_prepare_stops_before_dispatch(probe,change):
    p=probe.call('prepare');extra={}
    if change=='hash':extra['expected_state_sha256']='f'*64
    elif change=='controller':probe.machine.GetController2.return_value=(False,'',False)
    elif change=='native_id':probe.ungenerated[0].native_id=999
    elif change=='type':probe.ungenerated[0].OpernType=8
    else:extra['output_path']=str(probe.output.with_name('changed.cl'))
    r=probe.call('apply',**(dict(expected_state_sha256=p['state_sha256'],receipt_path=str(probe.receipt))|extra))
    assert r['status']=='error' and not r['native_call_attempted'];probe.machine.SaveCLFile.assert_not_called()

@pytest.mark.parametrize('change',['missing','empty','sidecar','dirty','source','controller','records','new_generated','type','native_id','exception','hresult1','boolfalse','none'])
def test_partial_failure_never_replayed_and_retains_bytes(probe,change):
    def post():
        if change!='missing':probe.output.write_bytes(b'' if change=='empty' else b'RAW')
        if change=='exception':raise RuntimeError('native unknown')
        if change=='sidecar':(probe.output.parent/'extra.txt').write_text('extra')
        elif change=='dirty':probe.document['needs_save']=True
        elif change=='source':probe.path.write_bytes(b'changed')
        elif change=='controller':probe.machine.GetController2.return_value=(True,'changed',True)
        elif change=='records':probe.toolpath.RecordCount=41
        elif change=='new_generated':
            probe.ungenerated[0].GetIsToolpathGenerated.return_value=True
            probe.ungenerated[0].IGetEnumToolpaths.side_effect=None
            probe.ungenerated[0].IGetEnumToolpaths.return_value=probe.collection([N(RecordCount=3)])
        elif change=='type':probe.ungenerated[0].OpernType=8
        elif change=='native_id':probe.ungenerated[0].native_id=999
        elif change=='hresult1':return 1
        elif change=='boolfalse':return False
        elif change=='none':return None
        return 0
    probe.state['on_post']=post;r=probe.apply()
    assert r['status']=='uncertain' and not r['readback_verified'] and not r['output_verified']
    if change!='missing':assert probe.output.exists()
    if change in {'records','new_generated'}:assert r['after']['inventory'] and not r['after']['capture_complete']
    preserved=probe.receipt.read_bytes()
    assert probe.call('apply',expected_state_sha256='a'*64,receipt_path=str(probe.receipt))['status']=='error'
    assert probe.receipt.read_bytes()==preserved;probe.machine.SaveCLFile.assert_called_once()

@pytest.mark.parametrize('when',['enter','post','exit','count'])
def test_event_stops_next_cam_read(probe,when):
    p=probe.call('prepare')
    def event():probe.session.data['event_count']=1;return 0
    if when=='count':
        original=probe.cam._member if hasattr(probe,'cam') else cam._member
        def member(obj,name,*args):
            value=original(obj,name,*args)
            if name=='Count':event()
            return value
        probe.monkeypatch.setattr(cam,'_member',member)
    else:probe.state['on_'+when]=event
    start=len(probe.native_calls)
    r=probe.call('apply',expected_state_sha256=p['state_sha256'],receipt_path=str(probe.receipt))
    assert not r['readback_verified'] and probe.session.data['disconnected']
    if when in {'enter','count'}:probe.machine.SaveCLFile.assert_not_called()
    if when=='count':assert probe.native_calls[start:][-1][0]=='Count'

@pytest.mark.parametrize('change',['output','sidecar','disconnect'])
def test_after_cleanup_has_no_cam_and_invalidates_output(probe,change):
    p=probe.call('prepare')
    def callback():
        if change=='output':probe.output.write_bytes(b'changed')
        elif change=='sidecar':(probe.output.parent/'late.txt').write_text('x')
        else:probe.session.data['disconnect_errors'].append('failed')
    probe.state['on_exit']=callback
    r=probe.call('apply',expected_state_sha256=p['state_sha256'],receipt_path=str(probe.receipt))
    assert r['status']=='uncertain' and not r['output_verified'];probe.machine.SaveCLFile.assert_called_once()

@pytest.mark.parametrize('phase',['SaveCLFile','finished'])
def test_receipt_failure_before_or_after_dispatch(probe,monkeypatch,phase):
    writer=cam._write_receipt
    def fail(path,report,**kw):
        if report['phase']==phase:raise OSError('receipt unavailable')
        writer(path,report,**kw)
    monkeypatch.setattr(cam,'_write_receipt',fail)
    r=probe.apply();assert not r['output_verified']
    assert probe.machine.SaveCLFile.call_count==(phase=='finished')

@pytest.mark.parametrize('change',['existing_dir','existing_receipt','extension','unc'])
def test_exclusive_local_paths(probe,change):
    args={}
    if change=='existing_dir':probe.output.parent.mkdir()
    elif change=='existing_receipt':probe.receipt.write_text('KEEP')
    elif change=='extension':args['output_path']=str(probe.output.with_suffix('.apt'))
    else:args['output_path']=r'\\server\share\new\output.cl'
    if change=='existing_receipt':r=probe.apply();assert probe.receipt.read_text()=='KEEP'
    else:r=probe.call('prepare',**args)
    assert r['status']=='error';probe.machine.SaveCLFile.assert_not_called()


def test_actual_in_memory_com_void_hresult_has_integer_result():
    from ctypes import HRESULT
    from comtypes import IUnknown,GUID,COMMETHOD,BSTR,COMObject
    class IProbe(IUnknown):
        _iid_=GUID('{17433FE5-2D23-4751-A694-F6BE241EDE08}')
        _methods_=[COMMETHOD([],HRESULT,'SaveCLFile',(['in'],BSTR,'fileName'))]
    seen=[]
    class Probe(COMObject):
        _com_interfaces_=[IProbe]
        def SaveCLFile(self,name):seen.append(name)
    obj=Probe();ptr=obj.QueryInterface(IProbe)
    result=cam._member(ptr,'SaveCLFile','in-memory-only.cl')
    assert result==0 and type(result) is int
    assert seen==['in-memory-only.cl']


def test_oversized_native_file_retained_but_unverified(probe):
    def post():
        with probe.output.open('wb') as stream:stream.truncate(64*1024*1024+1)
        return 0
    probe.state['on_post']=post
    r=probe.apply()
    assert r['status']=='uncertain' and not r['output_verified']
    assert probe.output.stat().st_size==64*1024*1024+1
    probe.machine.SaveCLFile.assert_called_once()


def test_machine4_runtime_whitelist_matches_primary_generated_typelib():
    import ast
    from scripts import sw_cam_comtypes
    runtime=Path(__file__).resolve().parents[1]
    planned={'_INTERFACES_addition':{'ICWMachine4':sw_cam_comtypes._INTERFACES['ICWMachine4']}}
    generated=runtime/'.venv/Lib/site-packages/comtypes/gen/_FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0.py'
    if not generated.exists():pytest.skip('Installed CAM generated typelib unavailable on this test host')
    tree=ast.parse(generated.read_text(encoding='utf-8-sig'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ICWMachine4')
    iid=next(n.value.args[0].value for n in cls.body if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='_iid_' for x in n.targets))
    assert planned['_INTERFACES_addition']=={'ICWMachine4':iid}
    derived=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ICWMachine5')
    assert len(derived.bases)==1 and derived.bases[0].id=='ICWMachine4'
    methods=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(x,ast.Attribute) and isinstance(x.value,ast.Name) and x.value.id=='ICWMachine4' and x.attr=='_methods_' for x in n.targets))
    method=next(n for n in methods.elts if n.args[2].value=='SaveCLFile')
    assert method.args[1].id=='HRESULT' and len(method.args)==4
    assert method.args[0].elts[0].args[0].value==14
    arg=method.args[3]
    assert [x.value for x in arg.elts[0].elts]==['in'] and arg.elts[1].id=='BSTR' and arg.elts[2].value=='fileName'


def test_prepare_queries_only_machine5_and_apply_reuses_it(probe):
    p=probe.call('prepare');assert p['status']=='ok'
    assert 'ICWMachine5' in probe.casts and 'ICWMachine4' not in probe.casts
    assert not probe.receipt.exists() and not probe.output.parent.exists()
    r=probe.call('apply',expected_state_sha256=p['state_sha256'],receipt_path=str(probe.receipt))
    assert r['status']=='review_required' and 'ICWMachine4' not in probe.casts
    probe.machine.SaveCLFile.assert_called_once()


def test_machine5_qi_failure_preflight_creates_neither_receipt_nor_output(probe,monkeypatch):
    typed=cam._typed
    def fail(obj,name,*args):
        if name=='ICWMachine5':raise RuntimeError('QI unsupported')
        return typed(obj,name,*args)
    monkeypatch.setattr(cam,'_typed',fail)
    assert probe.call('prepare')['status']=='error'
    assert probe.call('apply',expected_state_sha256='a'*64,receipt_path=str(probe.receipt))['status']=='error'
    assert not probe.receipt.exists() and not probe.output.parent.exists()
    probe.machine.SaveCLFile.assert_not_called()


def test_actual_in_memory_inherited_savecl_via_derived_interface():
    from ctypes import HRESULT
    from comtypes import IUnknown,GUID,COMMETHOD,BSTR,COMObject
    class IBase(IUnknown):
        _iid_=GUID('{9041D54A-87A4-466E-84A5-03DF40DF1D64}')
        _methods_=[COMMETHOD([],HRESULT,'SaveCLFile',(['in'],BSTR,'fileName'))]
    class IDerived(IBase):
        _iid_=GUID('{50892D46-6A3E-46A8-AF05-A76E73EAB395}')
        _methods_=[COMMETHOD([],HRESULT,'AdditionalMethod')]
    seen=[]
    class Probe(COMObject):
        _com_interfaces_=[IDerived]
        def SaveCLFile(self,name):seen.append(name)
        def AdditionalMethod(self):pass
    obj=Probe();ptr=obj.QueryInterface(IDerived)
    result=cam._member(ptr,'SaveCLFile','in-memory-inherited.cl')
    assert type(result) is int and result==0 and seen==['in-memory-inherited.cl']
