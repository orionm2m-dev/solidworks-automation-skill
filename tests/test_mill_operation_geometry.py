from copy import deepcopy
from contextlib import nullcontext
from ctypes import POINTER,cast,c_double,c_short
from ctypes.wintypes import VARIANT_BOOL
from comtypes import COMObject,COMError
from comtypes.automation import IDispatch
import pytest
from scripts import sw_cam_mill_operation_geometry as m

class LocalDispatch(COMObject):_com_interfaces_=[IDispatch]
def collection(rows):return dict(Count=len(rows),Item=lambda i:rows[i])
def set_pointer(output,value):
    value.AddRef();cast(output,POINTER(POINTER(IDispatch)))[0]=value

@pytest.fixture
def env(monkeypatch,tmp_path):
    e=dict(calls=[],hook=lambda name:None,digest='a'*64,dirty=False,base_null=False,base_error=False,param_error=False,decode_bad=False,qi_error=False,
        process=dict(alive=True,process_id=123,create_time=100.25,executable=r'C:\bin\SLDWORKS.exe'))
    local=LocalDispatch();ptr=local.QueryInterface(IDispatch);e['keepalive']=(local,ptr)
    setup0=dict(_id=40);setup1=dict(_id=41)
    f0=dict(_id=30,Suppressed=False,GetOwner=setup0);f1=dict(_id=31,Suppressed=False,GetOwner=setup1)
    setup0['IGetEnumFeatures']=collection([f0]);setup1['IGetEnumFeatures']=collection([f1])
    tool=dict(_id=20,IsMillTool=True,ToolType=1,CutDiameter=8.,Protrusion=25.)
    def base(feature,out):
        if feature is f0 and e['base_error']:raise COMError(-2147467259,'synthetic',None)
        if not (feature is f0 and e['base_null']):set_pointer(out,ptr)
        return 0
    def parameters(*outs):
        for p,v in zip(outs[:3],[7.6,7.6,-12.6]):cast(p,POINTER(c_double))[0]=v
        cast(outs[3],POINTER(c_short))[0]=-1
        if e['decode_bad']:cast(outs[0],POINTER(c_double))[0]=float('nan')
        set_pointer(outs[4],ptr)
        if e['param_error']:raise COMError(-2147467259,'synthetic',None)
        return 0
    tp={m.RAW_PARAMS:parameters}
    def operation(oid,feat,generated,records):return dict(_id=oid,OpernType=0,Suppressed=False,GetIsToolpathGenerated=generated,
        IGetAllFeatures=collection([feat]),IGetEnumToolpaths=collection([dict(RecordCount=n) for n in records]),IGetTool=tool,**{m.RAW_BASE:base})
    op0=operation(10,f0,False,[]);op1=operation(11,f1,True,[50])
    os0=dict(_id=50,IGetEnumOperations=collection([op0]),GetSetup=setup0);os1=dict(_id=51,IGetEnumOperations=collection([op1]),GetSetup=setup1)
    machine=dict(MachType=1,IGetEnumSetups=collection([setup0,setup1]),IGetEnumOpSetups=collection([os0,os1]))
    doc=dict(GetDocType=1,IGetMachine=machine,GetCWObjectID=lambda x:(x['_id'],True),GetCWObjectFromID=lambda kind,fid:({30:f0,31:f1}[fid],True))
    app=dict(IGetActiveDoc=doc);addin=dict(GetCWApp=app);sw=dict(GetProcessID=123,GetAddInObject=lambda clsid:addin)
    document=dict(path=str(tmp_path/'part.sldprt'),title='part',type=1,needs_save=False)
    generic=dict(native_id=20,is_mill_tool=True,native_read_complete=True,units_verified=False,holder_geometry_verified=False,tool_type_raw=1,cut_diameter_native=8.,protrusion_native=25.)
    rows=[dict(setup_index=i,setup_native_id=50+i,operation_index=0,native_id=10+i,mill_operation_type=0,base_operation_type=0,suppressed=False,toolpath_generated=bool(i),linked_feature_ids=[30+i],toolpath_record_counts=[50] if i else [],assigned_tool=deepcopy(generic)) for i in range(2)]
    state=dict(document=document,feature_setups=[dict(index=i,native_id=40+i,feature_ids=[30+i]) for i in range(2)],operation_setups=[dict(index=i,native_id=50+i,operation_count=1) for i in range(2)],operations=rows,operation_count=2)
    loaded=dict(state=state,binding=dict(expected_process_create_time=100.25),addin_clsid='{11111111-2222-3333-4444-555555555555}',pin=dict(path='authority.json',sha256='a'*64),pins={},recovery_pins={})
    class Session:
        def __init__(self,*a):self.state=dict(subscribed=True,active=False,disconnected=False,event_count=0);e['session']=self
        def __enter__(self):self.state['active']=True;return self
        def __exit__(self,*a):self.state.update(active=False,disconnected=True)
        def summary(self):return deepcopy(self.state)
    def member(obj,name,*args):
        e['calls'].append(name);value=obj[name];result=value(*args) if callable(value) else value;e['hook'](name);return result
    def typed(raw,name,tlb):
        if name=='ICWTpBaseFeature':
            e['qi_count']=e.get('qi_count',0)+1
            if e['qi_error'] and e['qi_count']%2==1:
                error=COMError(e.get('qi_hresult',-2147467262),'unsupported',None)
                if e.get('qi_bridge'):raise m.CamComBridgeError('CAM_COM_NATIVE_QI_FAILED','native_query_interface',error,source=raw,original=raw)
                raise error
            return tp
        return raw
    monkeypatch.setattr(m,'_member',member);monkeypatch.setattr(m,'_typed',typed);monkeypatch.setattr(m,'_process_identity',lambda pid:deepcopy(e['process']))
    monkeypatch.setattr(m,'_file_hash',lambda path:e['digest']);monkeypatch.setattr(m,'document_snapshot',lambda sw:dict(document,needs_save=e['dirty']))
    monkeypatch.setattr(m,'solidworks_operation_lock',lambda **kw:nullcontext());monkeypatch.setattr(m,'CamMessageSession',Session)
    monkeypatch.setattr(m,'preflight',lambda p:dict(native_calls=0));monkeypatch.setattr(m,'load_completed_configuration',lambda *a,**k:deepcopy(loaded))
    targets=[dict(operation_native_id=10+i,feature_native_id=30+i,feature_setup_native_id=40+i,operation_setup_native_id=50+i,mill_operation_type=0) for i in range(2)]
    args=dict(process_id=123,expected_process_create_time=100.25,expected_document_path=document['path'],expected_source_sha256='a'*64,
        configuration_receipt_path='authority.json',configuration_receipt_sha256='a'*64,anchor_operation_native_id=10,targets=targets)
    e.update(args=args,sw=sw,doc=doc,op0=op0,op1=op1,f0=f0,os1=os1,tool=tool,loaded=loaded,document=document,tp=tp)
    e['run']=lambda **kw:m.inspect_operation_geometry(sw,loaded['addin_clsid'],'fixture.tlb',**dict(args,**kw));return e


def test_real_synthetic_traversal_and_owned_outputs_twice(env):
    r=env['run']();assert r['readback_verified'],r
    assert r['before']==r['after'] and r['parameters_complete'] and r['raw_getter_attempts']==8
    assert env['calls'].count(m.RAW_BASE)==4 and env['calls'].count(m.RAW_PARAMS)==4
    p=r['before']['selected'][0]['parameters'];assert p['machining_depth_native']==7.6 and p['is_pattern_feature'] is True
    assert p['start_position']['present'] and not p['island_list']['present'] and not p['segment_chain']['present']
    assert not any(x.startswith(('Set','Generate','Save','Insert','Add')) for x in env['calls'])
    assert not r['empty_toolpath_cause_proven'] and not r['full_contours_read'] and r['messages']['disconnected']

@pytest.mark.parametrize('flag,outcome',[('base_null','null_base_feature'),('base_error','base_getter_COM_failure'),('param_error','parameter_getter_COM_failure')])
def test_null_or_native_failure_retained_and_other_target_read(env,flag,outcome):
    env[flag]=True;r=env['run']();assert r['readback_verified'],r
    assert not r['parameters_complete'] and r['before']['selected'][0]['outcome']==outcome
    assert len(r['before']['selected'])==2 and r['raw_getter_attempts']>=4
    if flag=='base_error':assert r['before']['selected'][0]['base_call']['issue']['hresult']==-2147467259
    if flag=='param_error':assert r['before']['selected'][0]['parameter_call']['outputs']['machining_depth_native']['raw']==7.6

@pytest.mark.parametrize('kind',['event','source','runtime','dirty'])
def test_returned_owned_outputs_preserved_before_unsafe_boundary(env,kind):
    count=0
    def hook(name):
        nonlocal count
        if name!=m.RAW_PARAMS:return
        count+=1
        if count!=1:return
        if kind=='event':env['session'].state['event_count']=1
        elif kind=='source':env['digest']='b'*64
        elif kind=='dirty':env['dirty']=True
        else:env['runtime_bad']=True
    env['hook']=hook
    def runtime():
        if env.get('runtime_bad'):raise ValueError('runtime drift')
    r=env['run'](runtime_check=runtime);assert not r['readback_verified'] and r['status']=='error'
    d=r['before']['selected'][0]['parameter_call'];assert d['returned'] and d['hresult']==0 and d['outputs']['machining_depth_native']['raw']==7.6
    assert env['calls'].count(m.RAW_PARAMS)==1 and r['messages']['disconnected']

@pytest.mark.parametrize('change',['lookup','owner','link','tool','records'])
def test_inventory_or_owner_change_stops_before_geometry(env,change):
    if change=='lookup':env['doc']['GetCWObjectFromID']=lambda *a:(dict(env['f0'],_id=32),True)
    elif change=='owner':env['f0']['GetOwner']=dict(_id=99)
    elif change=='link':env['op0']['IGetAllFeatures']=collection([dict(_id=31)])
    elif change=='tool':env['tool']['Protrusion']=26.
    else:env['op1']['IGetEnumToolpaths']=collection([dict(RecordCount=51)])
    r=env['run']();assert r['status']=='error' and m.RAW_BASE not in env['calls']

@pytest.mark.parametrize('flag',['decode_bad'])
def test_unsupported_output_or_interface_stops_without_fallback(env,flag):
    env[flag]=True;r=env['run']();assert r['status']=='error' and not r['readback_verified']
    assert env['calls'].count(m.RAW_BASE)==1 and len(r['before']['selected'])==1
    if flag=='qi_error':assert r['before']['selected'][0]['base_interface_call']['issue']['hresult']==-2147467262
    else:assert r['before']['selected'][0]['parameter_call']['outputs']['machining_depth_native']['untouched_or_nonfinite']

@pytest.mark.parametrize('key,value',[('process_id',True),('expected_process_create_time',True),('expected_source_sha256','bad'),('qualification_only',False),('anchor_operation_native_id',0),('targets',[])])
def test_invalid_input_precedes_native(env,key,value):
    r=env['run'](**{key:value});assert r['status']=='error' and not env['calls']


def test_cleanup_error_revokes_success(env,monkeypatch):
    original=m.CamMessageSession
    class BadCleanup(original):
        def __exit__(self,*a):super().__exit__(*a);self.state['disconnect_errors']=['failed']
    monkeypatch.setattr(m,'CamMessageSession',BadCleanup);r=env['run']()
    assert r['before']==r['after'] and not r['readback_verified'] and r['status']=='error'


def test_metadata_admission_precedes_bootstrap(env,monkeypatch):
    def fail(path):raise ValueError('missing interface')
    monkeypatch.setattr(m,'preflight',fail);r=env['run']();assert r['status']=='error' and not env['calls']


@pytest.mark.parametrize('bridge',[False,True])
def test_exact_unsupported_base_interface_continues_comparison(env,bridge):
    env['qi_error']=True;env['qi_bridge']=bridge;r=env['run']()
    assert r['readback_verified'] and not r['parameters_complete']
    first,second=r['before']['selected']
    assert first['outcome']=='declared_base_interface_unsupported' and second['parameters_complete']
    assert first['base_interface_call']['issue']['hresult']==-2147467262
    assert env['calls'].count(m.RAW_BASE)==4 and env['calls'].count(m.RAW_PARAMS)==2


@pytest.mark.parametrize('bridge',[False,True])
def test_other_qi_hresult_stops_probe(env,bridge):
    env['qi_error']=True;env['qi_bridge']=bridge;env['qi_hresult']=-2147467259
    r=env['run']();assert r['status']=='error' and not r['readback_verified']
    assert len(r['before']['selected'])==1 and env['calls'].count(m.RAW_BASE)==1
    assert r['before']['selected'][0]['base_interface_call']['issue']['hresult']==-2147467259
    assert not r['read_pending'] and r['messages']['disconnected']
