"""Independent portable creator authority and one-shot lifecycle regression tests."""
import ast
from copy import deepcopy
import hashlib,importlib,json,os,sys
from pathlib import Path
import pytest
STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',STAGE))
sys.path.insert(0,str(RUNTIME))
import scripts
if str(STAGE/'scripts') not in scripts.__path__:scripts.__path__.insert(0,str(STAGE/'scripts'))
core=importlib.import_module('scripts.sw_cam_autodetected_pocket')
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,v):p.write_text(json.dumps(v),encoding='utf-8');return digest(p)
def messages(events=0):return dict(subscribed=True,active=False,disconnected=True,event_count=events,events=[{}]*events)
def body():return dict(box_m=[-1.,-1.,0.,1.,1.,1.],mass_raw=[1.,2.,3.,4.])
@pytest.fixture
def packet(tmp_path):
    original=tmp_path/'original.SLDPRT';original.write_bytes(b'protected original')
    target=tmp_path/'working.SLDPRT';target.write_bytes(b'saved empty setup')
    native=tmp_path/'native.step';native.write_bytes(b'pinned step')
    spec=dict(plane_axis='Z',plane_offset_mm=25.8,sketch_name='CAM_UPPER_PROFILE_R25',plane_name='CAM_UPPER_PLANE_R25',profile=dict(kind='circle',center_model_mm=[0.,0.,25.8],radius_mm=23.35))
    doc=dict(path=str(target),title=target.name,type=1,needs_save=True)
    owner=dict(native_id=408,feature_count=0,axis_native=[0.,0.,-1.],origin_native=[0.,0.,0.])
    before=dict(document={**doc,'needs_save':False},saved_file_sha256=digest(original),feature_setups=[],operation_counts=[])
    after=deepcopy(before);after['document']['needs_save']=True;after['feature_setups']=[owner];after['operation_counts']=[0]
    setup=dict(status='review_required',phase='finished',operation='setup',readback_verified=True,native_call_returned=True,model_saved=False,new_setup_native_id=408,messages=messages(),before=before,after=after)
    final=deepcopy(after);final['document']['needs_save']=False;final['saved_file_sha256']=digest(target)
    saved=dict(status='review_required',phase='finished',action='save',machine_kind='mill_qualification',save_readback_verified=True,native_return_type='int',native_return_value=0,messages=messages(),before={**deepcopy(after),'machine_kind':'mill_qualification','process_id':731},final_state=final)
    sb=dict(path=str(target),saved_file_sha256=digest(target),pid=731,spec=spec,needs_save=False,solids=[body()],features=[])
    sa=deepcopy(sb);sa['needs_save']=True;sa['features']=[dict(name=spec['sketch_name'],type='ProfileFeature')]
    sketch=dict(status='ok',phase='finished',native_readback_verified=True,saved=False,CAD_solid_edit_attempted=False,CAM_calls=0,before=sb,after=sa,sketch_readback=dict(circle='verified'))
    paths={name:tmp_path/(name+'.json') for name in ('setup','save','sketch')}
    for name,row in [('setup',setup),('save',saved),('sketch',sketch)]:dump(paths[name],row)
    v=dict(process_id=731,expected_process_create_time=1234.25,expected_document_path=str(target),expected_source_sha256=digest(target),original_document_path=str(original),original_source_sha256=digest(original),setup_receipt_path=str(paths['setup']),setup_receipt_sha256=digest(paths['setup']),setup_save_receipt_path=str(paths['save']),setup_save_receipt_sha256=digest(paths['save']),sketch_receipt_path=str(paths['sketch']),sketch_receipt_sha256=digest(paths['sketch']),native_geometry_path=str(native),native_geometry_sha256=digest(native),owner_setup_native_id=408,expected_sw_configuration='Model',expected_cam_configuration='Mill0',sketch_spec=spec,depth_native=13.2,receipt_path=str(tmp_path/'receipt.json'),qualification_only=True,acknowledge_definition_only=True,message_policy='vendor_default')
    v.update(expected_axis_native=[0.,0.,-1.],expected_origin_native=[0.,0.,0.])
    return dict(v=v,setup=setup,save=saved,sketch=sketch,paths=paths)
def change_receipt(p,name,edit):
    row=deepcopy(p[name]);edit(row)
    keys={'setup':'setup_receipt_sha256','save':'setup_save_receipt_sha256','sketch':'sketch_receipt_sha256'}
    p['v'][keys[name]]=dump(p['paths'][name],row)
def inventory():
    return dict(feature_count=0,operation_count=0,generated_operation_count=0,total_record_count=0,features=[],operations=[],feature_setups=[dict(native_id=408,feature_ids=[],axis_native=[0.,0.,-1.],origin_native=[0.,0.,0.])],operation_setups=[],cam_configuration_name='Mill0',associated_sw_configuration='Model',configuration_name='Mill0',sw_reference=dict(feature_tree=[dict(name='pinned')],solids=[body()]))
def header():return dict(native_id=999,owner_setup_native_id=408,volume_type=2,suppressed=False,axis_native=[0.,0.,-1.],depth_native=13.2,island_count=4)
def after_inventory():
    r=inventory();r['feature_count']=1;r['features']=[dict(native_id=999,setup_native_id=408)];r['feature_setups'][0]['feature_ids']=[999];return r
class FakeContext:
    instances=[];fault=None
    def __init__(self,sw,clsid,tlb,v,data,r,persist,runtime_check):
        self.v,self.data,self.r,self.persist=v,data,r,persist;self.expected=dict(path=v['expected_document_path'],type=1,needs_save=True);self.calls=[];self.closed=False;self.instances.append(self)
    def start(self):self.calls.append('start')
    def capture_basic(self,label):
        self.calls.append(label)
        if self.fault==label:raise RuntimeError(label+' getter error')
        r=after_inventory() if label.startswith('after') else inventory()
        if self.fault=='extra_operation' and label.startswith('after'):r['operation_count']=1;r['operations']=[dict(native_id=1001)]
        if self.fault=='body_change' and label.startswith('after'):r['sw_reference']['solids'][0]['box_m'][0]-=1
        return r
    def create(self,pending,returned):
        self.calls.append('create');pending();assert self.data['marker'].exists()
        if self.fault=='dispatch':raise RuntimeError('dispatch uncertain')
        self.r['native_call_attempted']=True;returned(object());self.r['new_feature_native_id']=999
        if self.fault=='readback':raise RuntimeError('header getter failed')
        if self.fault=='protected_file':Path(self.v['original_document_path']).write_bytes(b'changed')
        h=header()
        if self.fault=='wrong_islands':h['island_count']=3
        return h
    def verify_sketch(self):self.calls.append('verify_sketch')
    def verify_owned(self):self.calls.append('verify_owned')
    def verify_files(self):self.calls.append('verify_files')
    def identity(self):return deepcopy(self.expected)
    def close(self):
        if self.closed:return
        self.closed=True;self.calls.append('close');self.r['messages']=messages(1 if self.fault=='events' else 0)
        if self.fault=='cleanup':raise RuntimeError('disconnect failed')
def execute(packet,monkeypatch,fault=None,runtime_check=lambda:None):
    FakeContext.instances=[];FakeContext.fault=fault
    monkeypatch.setattr(core,'preflight',lambda tlb:dict(application_calls=0))
    return core.create_one(None,'synthetic',str(STAGE/'missing-fixture.tlb'),packet['v'],runtime_check=runtime_check,_context_factory=FakeContext)
def test_actual_source_setup_sketch_prepare(packet):
    p=core.prepare(packet['v']);assert p['setup']['native_id']==408 and p['spec']['profile']['radius_mm']==23.35
    assert not p['consumed'] and len(p['pins'])==6
@pytest.mark.parametrize('field,value',[('process_id',True),('owner_setup_native_id',408.0),('expected_process_create_time',float('inf')),('depth_native',True),('qualification_only',1),('message_policy','approve'),('new_flag',True)])
def test_request_scope_is_strict(packet,field,value):
    packet['v'][field]=value
    with pytest.raises(ValueError):core.prepare(packet['v'])
@pytest.mark.parametrize('damage',['original_target','wrong_setup','wrong_axis','wrong_origin','save_pid','sketch_pid','wrong_sketch_hash','dirty_before','changed_solid','setup_events','save_bool_return','failed_sketch'])
def test_lineage_rejects_each_unbound_authority(packet,damage):
    if damage=='original_target':packet['v']['original_document_path']=packet['v']['expected_document_path']
    elif damage=='wrong_setup':packet['v']['owner_setup_native_id']=409
    elif damage in ('wrong_axis','wrong_origin'):
        k='axis_native' if damage=='wrong_axis' else 'origin_native';change_receipt(packet,'setup',lambda r:r['after']['feature_setups'][0].__setitem__(k,[0.,0.,1.]))
    elif damage=='save_pid':change_receipt(packet,'save',lambda r:r['before'].__setitem__('process_id',732))
    elif damage=='sketch_pid':change_receipt(packet,'sketch',lambda r:r['after'].__setitem__('pid',732))
    elif damage=='wrong_sketch_hash':change_receipt(packet,'sketch',lambda r:r['after'].__setitem__('saved_file_sha256','0'*64))
    elif damage=='dirty_before':change_receipt(packet,'sketch',lambda r:r['before'].__setitem__('needs_save',True))
    elif damage=='changed_solid':change_receipt(packet,'sketch',lambda r:r['after']['solids'][0]['box_m'].__setitem__(0,-2.))
    elif damage=='setup_events':change_receipt(packet,'setup',lambda r:r.__setitem__('messages',messages(1)))
    elif damage=='save_bool_return':change_receipt(packet,'save',lambda r:r.__setitem__('native_return_value',False))
    else:change_receipt(packet,'sketch',lambda r:r.__setitem__('status','uncertain'))
    with pytest.raises(ValueError):core.prepare(packet['v'])
def test_definition_only_success_and_consumed_target_sketch(packet,monkeypatch):
    r=execute(packet,monkeypatch);assert r['status']=='definition_only' and all(r[k] for k in core.FLAGS)
    assert r['definition_proof']['island_count_readback']==4 and not r['island_geometry_verified'] and not r['machining_eligible']
    assert FakeContext.instances[0].calls.count('create')==1
    packet['v']['receipt_path']=str(Path(packet['v']['receipt_path']).with_name('second.json'))
    with pytest.raises(ValueError,match='consumed'):core.prepare(packet['v'])
@pytest.mark.parametrize('fault',['dispatch','readback','wrong_islands','extra_operation','body_change','events','cleanup','protected_file','after_confirmation'])
def test_after_claim_failure_is_uncertain_and_no_replay(packet,monkeypatch,fault):
    r=execute(packet,monkeypatch,fault);assert r['status']=='uncertain' and not any(r[k] for k in core.FLAGS)
    ctx=FakeContext.instances[0];assert ctx.calls.count('create')==1 and ctx.closed and Path(r['marker_path']).exists()
    if fault=='dispatch':assert r['native_dispatch_pending'] and not r['native_call_returned']
    if fault=='readback':assert r['native_call_returned'] and r['new_feature_native_id']==999
    assert not r['automatic_replay'] and not r['Save_attempted'] and not r['GTP_attempted'] and not r['GOP_attempted']
def test_pre_dispatch_getter_failure_does_not_claim_mutator(packet,monkeypatch):
    r=execute(packet,monkeypatch,'before_confirmation');assert r['status']=='error' and not r['dispatch_claimed']
    assert 'create' not in FakeContext.instances[0].calls and not Path(r['marker_path']).exists()
def test_runtime_change_after_cleanup_revokes_acceptance(packet,monkeypatch):
    calls=[]
    def runtime():
        calls.append(1)
        if len(calls)==2:raise RuntimeError('runtime changed')
    r=execute(packet,monkeypatch,runtime_check=runtime);assert r['status']=='uncertain' and not any(r[k] for k in core.FLAGS)
def test_prepared_request_cannot_be_changed(packet,monkeypatch):
    p=core.prepare(packet['v']);packet['v']['depth_native']=12.
    with pytest.raises(ValueError,match='unchanged prepared'):core.create_one(None,'synthetic','absent',packet['v'],prepared=p,_context_factory=FakeContext)
def test_mutation_scope_is_only_one_public_feature_factory():
    t=ast.parse((STAGE/'scripts/sw_cam_autodetected_pocket.py').read_text(encoding='utf-8-sig'))
    calls=[n for n in ast.walk(t) if isinstance(n,ast.Call)]
    names=[a.value for n in calls for a in n.args if isinstance(a,ast.Constant) and isinstance(a.value,str)]
    forbidden={'Save','Save3','SaveAs','GenerateOperationPlan','GenerateToolpath','GenerateNCCode','ExtractMachinableFeatures','ImportCAMData','IGetIslands','GetIsland','IGetIsland','GetStartPosition','GetBoundParams'}
    assert not forbidden.intersection(names)
    assert names.count('CreateMillFeature2')>=1
@pytest.mark.parametrize('mode',['ok','null','native_error','header_error','bool_island'])
def test_actual_factory_once_and_stop_after_ambiguous_result(packet,monkeypatch,mode):
    trace=[]
    class Node:
        def __init__(self,name):self.name=name
    app,doc,machine,setup,feature=[Node(n) for n in ('app','doc','machine','setup','feature')]
    values={(id(app),'IGetActiveDoc'):doc,(id(doc),'IGetMachine'):machine,(id(machine),'IGetEnumSetups'):[setup],(id(feature),'GetOwner'):setup,(id(feature),'Suppressed'):False,(id(feature),'Axis'):[0.,0.,-1.],(id(feature),'VolumeType'):2,(id(feature),'IGetIslandCount'):4,(id(feature),'Depth'):13.2,(id(feature),'IGetTaperAngle'):0.}
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*exc):trace.append('guard_closed')
        def typed(self,raw,name):trace.append(('QI',name));return raw
        def read(self,raw,name,*args):
            trace.append(('read',name))
            if name=='IGetIslandCount' and mode=='header_error':raise RuntimeError('island count getter failed')
            if name=='IGetIslandCount' and mode=='bool_island':return True
            return values[(id(raw),name)]
        def dispatch_once(self,invoke,*,persist_pending):persist_pending();trace.append('dispatch');return invoke()
        def summary(self):return dict(test_fake=True)
        def _boundary(self):trace.append('boundary')
    ctx=object.__new__(core.Context);ctx.app=app;ctx.tlb='metadata';ctx.v=packet['v'];ctx.data=dict(spec=packet['v']['sketch_spec']);ctx.r={};ctx.persist=lambda:None;ctx.guard=lambda:Guard()
    monkeypatch.setattr(core.shared,'_items',lambda value,*args:value)
    monkeypatch.setattr(core,'_object_id',lambda owner,raw,read:408 if raw is setup else 999)
    factory=[]
    def member(raw,name,*args):
        assert raw is setup and name=='CreateMillFeature2';assert trace.index('pending')<trace.index('dispatch')
        factory.append(args)
        if mode=='native_error':raise RuntimeError('native factory failed')
        return None if mode=='null' else feature
    monkeypatch.setattr(core,'_member',member)
    pending=lambda:trace.append('pending')
    returned=lambda value:trace.append(('returned',value is not None))
    if mode=='ok':
        result=ctx.create(pending,returned);assert result['native_id']==999 and result['island_count']==4
    else:
        with pytest.raises((ValueError,RuntimeError)):ctx.create(pending,returned)
    assert len(factory)==1
    assert factory[0]==(0,packet['v']['sketch_spec']['sketch_name'],False,13.2,False,False,False,False,0.,-1,True,0,0)
    assert trace.count('dispatch')==1
    assert not any(isinstance(x,tuple) and x[0]=='QI' and 'Island' in x[1] for x in trace)
    if mode in ('null','native_error'):assert ('QI','ICWFeature') not in trace
    if mode=='native_error':assert not any(isinstance(x,tuple) and x[0]=='returned' for x in trace)
    if mode in ('header_error','bool_island'):assert ('read','Depth') not in trace and ctx.r['new_feature_native_id']==999
