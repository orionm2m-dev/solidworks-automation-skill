from copy import deepcopy
from contextlib import nullcontext
from types import SimpleNamespace
import importlib
import pytest
from scripts import sw_cam_mill_current_compound_read as m


class Native(dict):pass


def collection(rows):return dict(Count=len(rows),Item=lambda i:rows[i])


@pytest.fixture
def env(monkeypatch):
    e=dict(calls=[],hook=lambda name:None,digest='a'*64,dirty=False,
        process=dict(alive=True,process_id=123,create_time=100.25,executable=r'C:\bin\SLDWORKS.exe'))
    setup0=Native(_id=69,Axis=[0.,0.,-1.],GetReferencePosition=[0.,0.,0.])
    setup1=Native(_id=71,Axis=[0.,0.,1.],GetReferencePosition=[0.,0.,0.])
    f0=dict(_id=64)
    target=dict(_id=70,VolumeType=11,SubType=0,Shape=2,Suppressed=False,FeatureName='compound',Axis=[0.,0.,1.],
        Depth=7.6,GetBoundParams=[-9999000.,-9999000.,7.6],GetStartPosition=[0.,0.,-12.6],GetOwner=setup1,GetNumOfSteps=3,
        GetTypeAtStep=lambda i:1 if i==1 else 2)
    positions=[dict(GetCoordinates=[0.,0.,z]) for z in (-12.6,-12.3,-5.5)]
    target['GetCylParams']=lambda i:(18.,6.8,positions[i])
    target['GetConeParams']=lambda i:(18.,18.6,.3,.3,positions[i],False,.7853981633974483) if i==0 else (17.,18.,.5,.5,positions[i],False,.7853981633974483)
    setup0['IGetEnumFeatures']=collection([f0]);setup1['IGetEnumFeatures']=collection([target])
    tool=dict(_id=197,IsMillTool=True,ToolType=6,CutDiameter=8.,Protrusion=25.)
    op0=dict(_id=195,OpernType=1,Suppressed=False,GetIsToolpathGenerated=False,IGetAllFeatures=collection([f0]),IGetEnumToolpaths=collection([]),IGetTool=tool)
    op1=dict(_id=267,OpernType=1,Suppressed=False,GetIsToolpathGenerated=True,IGetAllFeatures=collection([f0]),IGetEnumToolpaths=collection([dict(RecordCount=40)]),IGetTool=tool)
    os0=dict(_id=93,IGetEnumOperations=collection([op0,op1]),GetSetup=setup0)
    os1=dict(_id=94,IGetEnumOperations=collection([]),GetSetup=setup1)
    machine=dict(MachType=1,IGetEnumSetups=collection([setup0,setup1]),IGetEnumOpSetups=collection([os0,os1]))
    doc=dict(GetDocType=1,IGetMachine=machine,GetCWObjectID=lambda x:(x['_id'],True),GetCWObjectFromID=lambda kind,fid:(target,True))
    app=dict(IGetActiveDoc=doc);addin=dict(GetCWApp=app);sw=dict(GetProcessID=123,GetAddInObject=lambda clsid:addin)
    class Session:
        def __init__(self,*args):
            self.state=dict(subscribed=True,active=False,disconnected=False,event_count=0);e['session']=self
        def __enter__(self):self.state['active']=True;return self
        def __exit__(self,*args):self.state.update(active=False,disconnected=True)
        def summary(self):return deepcopy(self.state)
    def member(obj,name,*args):
        e['calls'].append(name);value=obj[name];result=value(*args) if callable(value) else value
        e['hook'](name);return result
    monkeypatch.setattr(m,'_member',member);monkeypatch.setattr(m,'_typed',lambda raw,name,tlb:raw)
    monkeypatch.setattr(m,'_process_identity',lambda pid:deepcopy(e['process']))
    monkeypatch.setattr(m,'_file_hash',lambda path:e['digest'])
    monkeypatch.setattr(m,'document_snapshot',lambda sw:dict(path=r'C:\review\part.SLDPRT',title='part',type=1,needs_save=e['dirty']))
    monkeypatch.setattr(m,'solidworks_operation_lock',lambda **kw:nullcontext())
    monkeypatch.setattr(m,'CamMessageSession',Session);monkeypatch.setattr(m,'_abi',lambda path:dict(declared_getters_verified=5))
    args=dict(process_id=123,expected_process_create_time=100.25,expected_document_path=r'C:\review\part.SLDPRT',expected_source_sha256='a'*64,
        expected_feature_native_id=70,expected_feature_setup_native_id=71,expected_operation_setup_native_id=94,
        expected_operation_native_ids=[195,267],expected_generated_operation_count=1,expected_total_record_count=40,
        observation='three_step_profile',read_mode='current_saved',qualification_only=True,message_policy='vendor_default')
    e.update(args=args,sw=sw,doc=doc,target=target,setup1=setup1,os1=os1,op1=op1,tool=tool,positions=positions,machine=machine)
    e['run']=lambda **kw:m.inspect_current_saved_compound(sw,'clsid','fixture.tlb',**dict(args,**kw))
    return e


def test_real_synthetic_traversal_reuses_readers_two_captures_no_mutation(env):
    r=env['run']()
    assert r['status']=='review_required',r
    assert r['readback_verified'] and r['observation_verified'] and r['before']==r['after']
    b=r['before'];assert b['selected_operation_setup']==dict(native_id=94,feature_setup_native_id=71,operation_count=0)
    assert b['target_header']['axis_native']==[0.,0.,1.]
    assert [x['index'] for x in b['profile']['observed_steps']]==[0,1,2]
    assert b['profile']['observed_steps'][1]['diameter_native']==18.
    assert [x['native_id'] for x in b['operations']]==[195,267]
    assert b['operations'][1]['toolpath_record_counts']==[40]
    assert env['calls'].count('GetCylParams')==2 and env['calls'].count('GetConeParams')==4
    assert not any(x.startswith(('Set','Generate','Save','Add','Insert')) for x in env['calls'])
    for k in ('mutation_attempted','model_saved','GOP_attempted','GTP_attempted','units_verified','coordinate_frame_verified','production_qualified','historical_receipt_loaded','cl_coordinates_compared'):
        assert r[k] is False


def test_header_only_discovers_count_without_step_index(env):
    env['target']['GetNumOfSteps']=5;r=env['run'](observation='header_and_count')
    assert r['readback_verified'] and r['before']['number_of_steps_raw']==5
    assert 'GetTypeAtStep' not in env['calls'] and 'profile' not in r['before']


@pytest.mark.parametrize('count',[2,4,True,0,65])
def test_three_step_count_gate_before_any_index(env,count):
    env['target']['GetNumOfSteps']=count;r=env['run']()
    assert r['status']=='error' and not r['observation_verified']
    assert 'GetTypeAtStep' not in env['calls'] and r['before']['number_of_steps_raw']==count


@pytest.mark.parametrize('change', ['lookup_id','owner','setup_membership','op_setup_owner','op_id','records','machine','type','suppressed'])
def test_actual_native_identity_and_membership_gates(env,change):
    if change=='lookup_id':env['doc']['GetCWObjectFromID']=lambda *args:(dict(env['target'],_id=72),True)
    elif change=='owner':env['target']['GetOwner']={'_id':69}
    elif change=='setup_membership':env['setup1']['_id']=72
    elif change=='op_setup_owner':env['os1']['GetSetup']={'_id':69}
    elif change=='op_id':env['op1']['_id']=268
    elif change=='records':env['op1']['IGetEnumToolpaths']=collection([dict(RecordCount=41)])
    elif change=='machine':env['machine']['MachType']=3
    elif change=='type':env['target']['VolumeType']=2
    else:env['target']['Suppressed']=True
    r=env['run']();assert r['status']=='error' and 'GetTypeAtStep' not in env['calls']


@pytest.mark.parametrize('change',['source','dirty','lifetime','step_position','own_tool','operation_link'])
def test_returned_native_profile_retained_on_later_drift(env,change):
    count=0
    def hook(name):
        nonlocal count
        if name!='GetCylParams':return
        count+=1
        if count!=1:return
        if change=='source':env['digest']='b'*64
        elif change=='dirty':env['dirty']=True
        elif change=='lifetime':env['process']['create_time']=200.
        elif change=='step_position':env['positions'][0]['GetCoordinates']=[0.,0.,-12.7]
        elif change=='own_tool':env['tool']['Protrusion']=26.
        else:env['op1']['IGetAllFeatures']=collection([env['target']])
    env['hook']=hook;r=env['run']()
    assert r['status']=='error' and not r['readback_verified']
    assert r['before']['profile']['observed_steps'][1]['diameter_native']==18.
    assert any(d['method']=='GetCylParams' and d['returned'] for d in r['step_getter_diagnostics'])
    if change in ('step_position','own_tool','operation_link'):
        assert r['after']['capture_complete'] and r['before']!=r['after']
    else:assert 'after' not in r


@pytest.mark.parametrize('method',['GetNumOfSteps','GetCylParams','GetConeParams','GetCoordinates'])
def test_event_immediate_stop_retains_returned_shape(env,method):
    def hook(name):
        if name==method:env['session'].state['event_count']=1
    env['hook']=hook;r=env['run']()
    assert r['status']=='error' and env['calls'][-1]==method
    assert r['step_getter_diagnostics'][-1]['returned']
    assert 'converted_output_shape' in r['step_getter_diagnostics'][-1]
    assert 'after' not in r and r['messages']['disconnected']


def test_native_exception_no_fallback_or_second_capture(env):
    def fail(i):raise OSError('unsupported cone getter')
    env['target']['GetConeParams']=fail;r=env['run']()
    assert r['status']=='error' and env['calls'][-1]=='GetConeParams'
    assert not r['step_getter_diagnostics'][-1]['returned'] and 'after' not in r


@pytest.mark.parametrize('field,value',[('process_id',True),('expected_process_create_time',True),('expected_process_create_time',float('nan')),('expected_document_path','relative.sldprt'),('expected_source_sha256','bad'),('expected_feature_native_id',True),('expected_operation_native_ids',[True]),('expected_operation_native_ids',[195,195]),('expected_generated_operation_count',3),('expected_total_record_count',True),('read_mode','historical'),('observation','all_steps'),('qualification_only',False),('message_policy','auto_accept')])
def test_bad_admission_no_native(env,field,value):
    r=env['run'](**{field:value});assert r['status']=='error' and not env['calls']


@pytest.mark.parametrize('field,value',[('alive',False),('create_time',101),('executable','other.exe'),('process_id',124)])
def test_lifetime_gate_before_bootstrap(env,field,value):
    env['process'][field]=value;r=env['run']();assert r['status']=='error' and not env['calls']


def test_dirty_saved_source_rejected_before_cam(env):
    env['dirty']=True;r=env['run']();assert r['status']=='error' and 'GetAddInObject' not in env['calls']


def test_declared_metadata_only(monkeypatch):
    mod=importlib.import_module('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0')
    monkeypatch.setattr(m,'_interface_class',lambda name,path:getattr(mod,name))
    assert m._abi('no-CAD')['declared_getters_verified']==5


@pytest.mark.parametrize('defect',['iid','dispid','direction','property'])
def test_abi_corruption_rejected_without_native(monkeypatch,defect):
    mod=importlib.import_module('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0')
    real=mod.ICWBaseOpSetup
    methods=[SimpleNamespace(name=x.name,restype=x.restype,idlflags=list(x.idlflags),argtypes=x.argtypes,paramflags=x.paramflags) for x in real._methods_]
    target=next(x for x in methods if x.name=='GetSetup')
    fake=SimpleNamespace(_iid_=real._iid_,_methods_=methods)
    if defect=='iid':fake._iid_='wrong'
    elif defect=='dispid':target.idlflags[0]=31
    elif defect=='direction':target.paramflags=((2,'ret'),)
    else:target.idlflags.append('propput')
    monkeypatch.setattr(m,'_interface_class',lambda name,path:fake if name=='ICWBaseOpSetup' else getattr(mod,name))
    with pytest.raises(ValueError):m._abi('no-CAD')


def test_cleanup_event_revokes_success_preserves_complete_captures(env,monkeypatch):
    original=m.CamMessageSession
    class DirtyCleanup(original):
        def __exit__(self,*args):
            super().__exit__(*args);self.state['event_count']=1
    monkeypatch.setattr(m,'CamMessageSession',DirtyCleanup)
    r=env['run']()
    assert r['status']=='error' and not r['readback_verified']
    assert r['before']['capture_complete'] and r['after']['capture_complete']
    assert env['calls'][-1]=='GetProcessID'
