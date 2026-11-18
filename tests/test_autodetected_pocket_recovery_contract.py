"""Independent pure authority/delta and fake read-only lifecycle checks."""
from copy import deepcopy
import hashlib,importlib,os,sys
from pathlib import Path
import pytest
STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',STAGE))
sys.path.insert(0,str(RUNTIME))
import scripts
if str(STAGE/'scripts') not in scripts.__path__:scripts.__path__.insert(0,str(STAGE/'scripts'))
core=importlib.import_module('scripts.sw_cam_autodetected_pocket_recovery')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def messages(n=0):return dict(subscribed=True,disconnected=True,active=False,event_count=n,events=[{}]*n)
@pytest.fixture
def packet(tmp_path):
    target=tmp_path/'working.SLDPRT';target.write_bytes(b'unchanged saved setup')
    q={k:('1'*64 if k.endswith('_sha256') else str(tmp_path/(k+'.json'))) for k in core.creator.KEYS if k.endswith(('_sha256','_path'))}
    q.update(process_id=731,expected_process_create_time=1234.25,expected_document_path=str(target),expected_source_sha256=sha(target),original_document_path=str(tmp_path/'original.SLDPRT'),owner_setup_native_id=64,expected_sw_configuration='Model',expected_cam_configuration='Mill0',expected_axis_native=[0.,0.,-1.],expected_origin_native=[0.,0.,0.],sketch_spec=dict(plane_axis='Z',plane_offset_mm=25.8,sketch_name='ScopeCircle',plane_name='ScopePlane',profile=dict(kind='circle',center_model_mm=[0.,0.,25.8],radius_mm=23.35)),depth_native=13.2,qualification_only=True,acknowledge_definition_only=True,message_policy='vendor_default')
    tree=[dict(name='Old'+str(i),type='BaseBody') for i in range(37)]
    suffix=[dict(name='CW грань-'+str(i),type='Attribute') for i in range(12)]
    before=dict(capture_complete=True,feature_count=0,operation_count=0,generated_operation_count=0,total_record_count=0,features=[],operations=[],feature_setups=[dict(native_id=64,feature_ids=[])],operation_setups=[dict(native_id=65,operation_count=0)],sw_reference=dict(feature_tree=tree,solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[1.,2.,3.,4.])]))
    after=deepcopy(before);after['feature_count']=1;after['features']=[dict(native_id=66,setup_native_id=64)];after['feature_setups'][0]['feature_ids']=[66];after['sw_reference']['feature_tree']+=deepcopy(suffix)
    header=dict(native_id=66,owner_setup_native_id=64,suppressed=False,axis_native=[0.,0.,-1.],volume_type=2,island_count=4,depth_native=13.2,taper_angle_native=0.)
    raw=dict(scope=core.creator.SCOPE,status='uncertain',phase='finished',failed_phase='after',reason='Unrequested inventory/CAD delta',issue=dict(type='ValueError',hresult=None,locations=[dict(function='verify_delta')]),request=q,feature_header=header,new_feature_native_id=66,before=before,before_confirmation=deepcopy(before),after=after,messages=messages())
    raw['document_before']=dict(path=str(target),type=1,needs_save=True)
    for k in ('dispatch_claimed','native_call_attempted','native_call_returned','native_return_nonnull','auto_detect_islands_requested'):raw[k]=True
    for k in ('native_dispatch_pending','Save_attempted','GOP_attempted','GTP_attempted','AFR_attempted','Import_attempted','model_saved','island_geometry_getter_attempted','automatic_replay',*core.FLAGS):raw[k]=False
    for k in ('before','before_confirmation','after'):raw[k+'_diagnostic']=dict(capture_complete=True)
    d=core.reconcile_raw(raw,suffix)
    v={k:q[k] for k in ('process_id','expected_process_create_time','expected_document_path','expected_source_sha256','expected_sw_configuration','expected_cam_configuration')}
    v.update(creator_receipt_path=str(tmp_path/'creator.json'),creator_receipt_sha256='2'*64,expected_feature_native_id=66,expected_attribute_suffix=suffix,receipt_path=str(tmp_path/'recovery.json'),qualification_only=True,message_policy='vendor_default')
    d.update(old=raw,request=deepcopy(v),receipt=Path(v['receipt_path']),consumed=False,pins=[dict(path=str(target),sha256=sha(target))],creator_pin=dict(path=v['creator_receipt_path'],sha256=v['creator_receipt_sha256']),marker_pin=dict(path=str(tmp_path/'marker.json'),sha256='3'*64),sketch=dict(after=dict(features=deepcopy(tree))),spec=q['sketch_spec'])
    return raw,suffix,d,v

def test_exact_37_prefix_and_12_suffix_reconciled_without_promoting_raw(packet):
    raw,suffix,d,v=packet;saved=deepcopy(raw);proof=core.reconcile_raw(raw,suffix)
    assert raw==saved and raw['status']=='uncertain' and all(raw[k] is False for k in core.FLAGS)
    assert proof['definition_proof']['island_count_readback']==4 and not proof['definition_proof']['physical_depth_verified']
    assert len(proof['expected_inventory']['sw_reference']['feature_tree'])==49
@pytest.mark.parametrize('damage',['missing_suffix','wrong_suffix_type','renamed_suffix','changed_old_prefix','middle_insertion','solid_change','extra_operation','other_failure','pending','old_save','old_event'])
def test_exact_historical_exception_is_not_a_general_tree_waiver(packet,damage):
    raw,suffix,d,v=packet
    if damage=='missing_suffix':suffix.pop()
    elif damage=='wrong_suffix_type':suffix[0]['type']='RefPlane'
    elif damage=='renamed_suffix':suffix[0]['name']='Other'
    elif damage=='changed_old_prefix':raw['after']['sw_reference']['feature_tree'][0]['name']='Changed'
    elif damage=='middle_insertion':raw['after']['sw_reference']['feature_tree'].insert(2,raw['after']['sw_reference']['feature_tree'].pop())
    elif damage=='solid_change':raw['after']['sw_reference']['solids'][0]['box_m'][0]=-.1
    elif damage=='extra_operation':raw['after']['operation_count']=1
    elif damage=='other_failure':raw['reason']='Other error'
    elif damage=='pending':raw['native_dispatch_pending']=True
    elif damage=='old_save':raw['Save_attempted']=True
    else:raw['messages']=messages(1)
    with pytest.raises(ValueError):core.reconcile_raw(raw,suffix)
@pytest.mark.parametrize('field,value',[('process_id',732),('expected_process_create_time',1234.5),('expected_source_sha256','0'*64),('expected_feature_native_id',67),('expected_document_path','C:/fixture/another.SLDPRT')])
def test_request_must_bind_original_identity_and_feature(packet,field,value):
    raw,suffix,d,v=packet;v[field]=value
    with pytest.raises(ValueError):core.bind_request(d,v)
@pytest.mark.parametrize('damage',['extra_attribute','removed_attribute','body','owner','island_count'])
def test_current_read_requires_exact_consumed_after_state(packet,damage):
    raw,suffix,d,v=packet;state=deepcopy(d['expected_inventory']);h=deepcopy(d['header'])
    if damage=='extra_attribute':state['sw_reference']['feature_tree'].append(dict(name='Another',type='Attribute'))
    elif damage=='removed_attribute':state['sw_reference']['feature_tree'].pop()
    elif damage=='body':state['sw_reference']['solids'][0]['box_m'][0]=-.1
    elif damage=='owner':h['owner_setup_native_id']=65
    else:h['island_count']=3
    with pytest.raises(ValueError):core.verify_observation(d,state,h)
def test_no_application_constructor_and_mutator_guards(packet):
    raw,suffix,d,v=packet
    class NoApp:
        def __getattr__(self,name):raise AssertionError('Application touched: '+name)
    ctx=core.ReadContext(NoApp(),'synthetic','metadata',v,d,{},lambda:None,lambda:None)
    assert len(ctx.data['sketch']['after']['features'])==49 and len(d['sketch']['after']['features'])==37
    for method in (ctx.create,ctx.adopt_post_import_baseline):
        with pytest.raises(ValueError):method()
    g=object.__new__(core.ReadGuard)
    with pytest.raises(ValueError):g.dispatch_once(lambda:None,persist_pending=lambda:None)
    for name in ('CreateMillFeature2','SaveActiveDocument','GenerateOperationPlan','GenerateToolpath','IGetIsland','SetDepth'):
        with pytest.raises(ValueError):g.read(None,name)
    with pytest.raises(ValueError):g.typed(None,'ICWIsland')
class Context:
    fault=None;instances=[]
    def __init__(self,sw,clsid,tlb,v,data,r,persist,runtime_check):
        self.v,self.data,self.r=v,data,r;self.calls=[];self.expected=dict(path=v['expected_document_path'],type=1,needs_save=True);self.closed=False;self.instances.append(self)
    def start(self):self.calls.append('start');self.r['document_before']=deepcopy(self.expected)
    def capture_basic(self,label):self.calls.append(label);self.r[label]=deepcopy(self.data['expected_inventory']);return self.r[label]
    def read_header(self,label):
        self.calls.append(label)
        if self.fault=='header_error' and label.endswith('after'):raise RuntimeError('getter failed')
        h=deepcopy(self.data['header'])
        if self.fault=='header_changed' and label.endswith('after'):h['island_count']=3
        self.r[label]=h;return h
    def verify_sketch(self):self.calls.append('sketch')
    def verify_owned(self):self.calls.append('owned')
    def verify_files(self):self.calls.append('files')
    def close(self):
        if self.closed:return
        self.closed=True;self.calls.append('close');self.r['messages']=messages(1 if self.fault=='events' else 0)
        if self.fault=='cleanup':raise RuntimeError('cleanup failed')
        if self.fault=='source_changed':Path(self.v['expected_document_path']).write_bytes(b'changed')
    def identity(self):return deepcopy(self.expected)
def run(packet,monkeypatch,fault=None,runtime=lambda:None):
    raw,suffix,d,v=packet;Context.fault=fault;Context.instances=[]
    monkeypatch.setattr(core,'preflight',lambda tlb:dict(application_calls=0))
    return core.run_read(None,'synthetic','metadata',v,prepared=d,_context_factory=Context,runtime_check=runtime)
def test_two_reads_success_preserves_original_uncertainty_and_no_mutations(packet,monkeypatch):
    r=run(packet,monkeypatch);assert r['status']=='definition_only' and all(r[k] for k in core.FLAGS)
    assert r['original_creator_status']=='uncertain' and not any(r['original_creator_flags'].values())
    assert Context.instances[0].calls==['start','before','feature_header_before','after','feature_header_after','sketch','owned','files','close']
    assert all(r[k] is False for k in ('mutation_attempted','Create_attempted','Save_attempted','GOP_attempted','GTP_attempted','automatic_replay','attribute_payload_verified','feature_association_verified','island_geometry_verified','physical_depth_verified'))
@pytest.mark.parametrize('fault',['header_error','header_changed','events','cleanup','source_changed','runtime'])
def test_any_failed_read_or_cleanup_revokes_all_success_flags(packet,monkeypatch,fault):
    count=[]
    def runtime():
        count.append(1)
        if fault=='runtime' and len(count)==2:raise RuntimeError('runtime changed')
    r=run(packet,monkeypatch,fault,runtime);assert r['status']=='error' and not any(r[k] for k in core.FLAGS)
    assert Context.instances[0].closed and not r['mutation_attempted'] and not r['Create_attempted']
@pytest.mark.parametrize('claim',['island_geometry_verified','physical_depth_verified','machining_eligible'])
def test_durable_read_receipt_rejects_geometry_or_machining_promotion(packet,monkeypatch,claim):
    raw,suffix,d,v=packet;r=run(packet,monkeypatch)
    r['evidence_pins'].append(dict(path=core.__file__,sha256=core._file_hash(core.__file__)))
    def read(path,digest):
        if Path(path)==Path(v['creator_receipt_path']):return raw,deepcopy(d['creator_pin'])
        return r,dict(path=str(d['receipt']),sha256='4'*64)
    monkeypatch.setattr(core,'read_pin',read)
    monkeypatch.setattr(core,'_authority_files',lambda *a,**k:deepcopy(d))
    assert core.verify_recovery_receipt(str(d['receipt']),'4'*64)['receipt']['status']=='definition_only'
    r[claim]=True
    with pytest.raises(ValueError,match='Unexpected recovery claim'):core.verify_recovery_receipt(str(d['receipt']),'4'*64)
