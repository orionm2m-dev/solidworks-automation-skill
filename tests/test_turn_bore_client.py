from copy import deepcopy
from pathlib import Path
import ast,enum,hashlib,importlib.util,json,os,sys,uuid
import pytest
from pydantic import BaseModel,ConfigDict,Field,model_validator

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('bore_builder_under_test',ROOT/'scripts/sw_cam_inprocess_turn_bore.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)

def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return m.digest(path)

def tool():
    return dict(complete=True,native_id=277,tool_type_raw=15,info_raw='T02 boring',candidate=True,turn_tool_type_raw=1,insert_type_raw=1,holder_present=True,holder_type_raw=2,holder_id_raw=2,insert_dimensions_native=dict(Thickness=4.7625,IncludedAngle=80,NoseRadius=.4,InscribedCircle=12.7),holder_dimensions_native=dict(BoringBarDiameter=20,ShankLength=250,LeadAngle=0,BackClearAngle=0,FrontClearAngle=0,ZInsertOffset=0,XInsertOffset=0,Protrusion=0,HolderShape=0),reason='diamond_boring_bar_requires_physical_and_geometric_qualification')

@pytest.fixture
def params(tmp_path):
    q=tmp_path/'qualification';q.mkdir();protected=tmp_path/'part.sldprt';protected.write_bytes(b'synthetic saved part');archive=tmp_path/'archive.sldprt';archive.write_bytes(protected.read_bytes());copy=q/'copy.sldprt';copy.write_bytes(protected.read_bytes());dll=q/'host.dll';dll.write_bytes(b'synthetic dll');tlb=q/'host.tlb';tlb.write_bytes(b'synthetic tlb');cl=tmp_path/'prior.cl';cl.write_bytes(b'UNITS/MM\nPPRINT/ protected five streams\n')
    p=dict(process_id=1234,expected_process_creation_time=2000.25,expected_document_path=str(copy),expected_source_sha256=m.digest(copy),protected_document_path=str(protected),protected_source_sha256=m.digest(protected),protected_part_pins=[dict(path=str(x),sha256=m.digest(x)) for x in (protected,archive)],qualification_root=str(q),host_dll_path=str(dll),host_dll_sha256=m.digest(dll),host_tlb_path=str(tlb),host_tlb_sha256=m.digest(tlb),expected_host_module_version_id=str(uuid.uuid4()),reference_receipt_path=str(q/'snapshot.json'),reference_receipt_sha256='0'*64,protected_cl_path=str(cl),protected_cl_sha256=m.digest(cl),selected_tool_id=277,feature_id=76,anchor_id=132,default_name='Default',default_id=3,max_tools=64,native_receipt_path=str(q/'native.json'),receipt_path=str(q/'client.json'),module_sha256=m.digest(m.__file__),qualification_only=True,acknowledge_ram_only=True)
    kinds=[7,8,1,2,14,9,3,4,13];features=[74,74,75,75,76,76,77,77,78];counts=[40,19,97,43,0,66,0,0,0]
    rows=[dict(setup_index=0,operation_index=i,native_id=127+i,turn_operation_type=kinds[i],linked_feature_ids=[features[i]],suppressed=False,toolpath_generated=counts[i]>0,toolpath_record_counts=[counts[i]] if counts[i] else []) for i in range(9)]
    doc=dict(path=str(copy),title='copy.sldprt',type=1,needs_save=False,configuration='Default')
    host=dict(schema_version=1,scope='TURN_INPROCESS_READ_V1',engine_version='turn-reader-1',status='observed',stage='finished',read_only=True,mutation_attempted=False,readback_verified=True,process_id=p['process_id'],host_module_version_id=p['expected_host_module_version_id'],host_assembly_location=str(dll),elapsed_ms=1,document_before=doc,document_after=deepcopy(doc),inventory=dict(machine_type=3,operation_setup_count=1,operation_count=9,operations=rows),tools=[tool()],nc_parameters=[],nc_parameters_complete=True,cam_configuration='Mill - Metric - 0')
    owner=dict(alive=True,process_id=p['process_id'],create_time=p['expected_process_creation_time'],executable='C:/Program Files/Application/SLDWORKS.exe')
    baseline=dict(scope=m.reader.SCOPE,status='observed',phase='finished',read_only=True,mutation_attempted=False,readback_verified=True,batch_calls=1,native_dispatch_pending=False,source_sha256=p['expected_source_sha256'],request=m.reader_params(p),owner_before=owner,owner_after=deepcopy(owner),host_response=host)
    p['reference_receipt_sha256']=write(Path(p['reference_receipt_path']),baseline)
    return p

class Backend:
    def __init__(self,p,mode=''):
        self.p=p;self.mode=mode;self.calls=0
    def owner(self):return dict(alive=True,process_id=self.p['process_id'],create_time=self.p['expected_process_creation_time'],executable='C:/Program Files/Application/SLDWORKS.exe')
    def invoke_once(self,text):
        self.calls+=1
        if self.mode=='transport':raise RuntimeError('uncertain transport after dispatch')
        r=json.loads(text);p=self.p;doc=dict(path=p['expected_document_path'],title='copy.sldprt',type=1,needs_save=False,configuration=r['expected_sw_configuration']);cfg=dict(name=r['expected_cam_configuration'],object_name=r['expected_cam_configuration'],associated_sw_name=r['expected_sw_configuration']);before=dict(document=doc,configuration=cfg,inventory=r['expected_inventory'],tools=r['expected_tools']);after=deepcopy(before);after['document']['needs_save']=True;inv=after['inventory'];at=6
        for row in inv['operations'][at:]:row['operation_index']+=1
        inv['operations'].insert(at,dict(setup_index=0,operation_index=at,native_id=900,turn_operation_type=5,linked_feature_ids=[p['feature_id']],suppressed=False,toolpath_generated=False,toolpath_record_counts=[]));inv['operation_count']+=1
        h=dict(schema_version=1,scope=m.NATIVE_SCOPE,engine_version='turn-bore-builder-1',status='created_bound_nc_read_ram_only',stage='finished',process_id=p['process_id'],host_module_version_id=p['expected_host_module_version_id'],host_assembly_location=p['host_dll_path'],readback_verified=True,native_dispatch_pending=False,before=before,after_insert=deepcopy(after),after=after,new_operation_id=900,elapsed_ms=1,new_crib_entries=[])
        for k in ('model_saved','GTP_attempted','GOP_attempted','tool_creation_attempted','existing_tool_edit_attempted','persistence_qualified','physical_tool_qualified','production_qualified','protected_CL_bytes_compared'):h[k]=False
        for k in ('mutation_attempted','insert_attempted','insert_returned','bind_attempted','bind_returned','own_read_attempted','own_read_returned'):h[k]=True
        h['own_readback']=dict(operation_native_id=900,tool_native_id=p['selected_tool_id'],stage='finished',tool_getter_attempted=True,tool_getter_returned=True,tool_present=True,nc_getter_attempted=True,nc_getter_returned=True,nc_present=True,nc_interface_verified=True,spindle_speed_native=100,feed_rate_ipm_native=1,units_qualified=False)
        h['messages']=dict(subscribed=True,disconnected=True,active=False,event_count=0,overflow=0,callback_error_count=0,cleanup_error=None)
        if self.mode=='NC_error':h.update(status='uncertain',stage='own_readback',readback_verified=False);h['own_readback'].update(stage='IGetTurnNCParam',nc_getter_returned=False)
        if self.mode=='protected_count':h['after']['inventory']['operations'][0]['toolpath_record_counts']=[41]
        if self.mode=='wrong_own_tool':h['own_readback']['tool_native_id']=278
        if self.mode=='late_event':h['messages']['event_count']=1
        if self.mode=='old_tool_geometry':h['after_insert']['tools'][0]['insert_dimensions_native']['NoseRadius']=.8
        marker=dict(scope=m.NATIVE_SCOPE,status='claimed_no_replay',copy=p['expected_document_path'],sha256=p['expected_source_sha256'],feature_id=p['feature_id'],anchor_id=p['anchor_id'],receipt=p['native_receipt_path'])
        if self.mode=='bad_marker':marker['feature_id']=999
        if self.mode=='normalized_paths':
            marker['copy']=str(Path(marker['copy']).resolve());marker['receipt']=str(Path(marker['receipt']).resolve())
        write(m.marker_path(p),marker);durable=deepcopy(h);durable.pop('elapsed_ms');write(Path(p['native_receipt_path']),durable)
        if self.mode=='receipt_mismatch':h['own_readback']['spindle_speed_native']=101
        return json.dumps(h)

def test_offline_prepare_no_backend(params):
    out=m.dispatch_request(dict(action='qualify_create_bound_turn_bore',params=params),validate_only=True)
    assert out['native_called'] is False and out['native_request']['expected_inventory']['operation_count']==9
    assert out['native_request']['expected_inventory']['operations'][5]['toolpath_record_counts']==[66]
    assert not Path(params['native_receipt_path']).exists() and not m.marker_path(params).exists()

def test_complete_single_native_call(params):
    b=Backend(params);out=m.run(params,backend=b)
    assert out['status']=='created_bound_nc_read_ram_only' and out['readback_verified'] and b.calls==1
    assert not out['persistence_qualified'] and not out['protected_CL_bytes_compared']
    with pytest.raises(ValueError):m.run(params,backend=b)
    assert b.calls==1

@pytest.mark.parametrize('mode',['transport','NC_error','protected_count','wrong_own_tool','late_event','old_tool_geometry','bad_marker','receipt_mismatch'])
def test_failures_preserved_and_no_retry(params,mode):
    b=Backend(params,mode);out=m.run(params,backend=b)
    assert not out['readback_verified'] and out['status']=='uncertain' and b.calls==1
    if mode=='transport':assert out['native_dispatch_pending'] is True
    if mode=='NC_error':assert out['host_response']['own_readback']['tool_native_id']==277

@pytest.mark.parametrize('field,value',[('selected_tool_id',323),('feature_id',999),('anchor_id',131),('process_id',True),('default_id',True),('qualification_only',False),('expected_source_sha256','0'*64),('module_sha256','0'*64)])
def test_bad_prepare_rejects_before_dispatch(params,field,value):
    params[field]=value
    with pytest.raises(ValueError):m.prepare(params)

def test_authoritative_path_rejected(params):
    params['expected_document_path']=params['protected_document_path']
    with pytest.raises(ValueError):m.prepare(params)

def test_changed_baseline_file_rejected(params):
    Path(params['protected_document_path']).write_bytes(b'changed')
    with pytest.raises(ValueError):m.prepare(params)

def test_prior_marker_rejected(params):
    m.marker_path(params).write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError):m.prepare(params)

def test_immutable_copy_path_rejected(params):
    params['protected_part_pins'].append(dict(path=params['expected_document_path'],sha256=params['expected_source_sha256']))
    with pytest.raises(ValueError):m.prepare(params)

def wrapper():
    candidate=ROOT/'mcp-server/server.py'
    tree=ast.parse(candidate.read_text(encoding='utf-8-sig'));wanted={'SolidWorksCamQualifyTurnBoreInput','_turn_bore_qualification_payload','solidworks_cam_qualify_turn_bore'};tree.body=[x for x in tree.body if getattr(x,'name',None) in wanted]
    assert {x.name for x in tree.body} == wanted, 'Current server must contain the complete TURN bore wrapper'
    class Format(enum.Enum):JSON='json'
    class MCP:
        def tool(self,**kwargs):return lambda f:f
    ns=dict(BaseInput=BaseModel,ConfigDict=ConfigDict,Field=Field,model_validator=model_validator,ResponseFormat=Format,mcp=MCP(),SCRIPTS_DIR=str(ROOT/'scripts'),_selected_process_id=1234,_run_locked=lambda f,*a,**kw:f())
    exec(compile(tree,str(candidate),'exec'),ns)
    return ns

@pytest.mark.parametrize('mode',['hash','action','pid','duplicate','nonfinite','module','receipt_alias'])
def test_sealed_wrapper_rejects(params,tmp_path,mode):
    ns=wrapper();payload=dict(action='qualify_create_bound_turn_bore',params=params);path=tmp_path/'request.json'
    if mode=='action':payload['action']='Save'
    if mode=='pid':payload['params']['process_id']=4321
    if mode=='module':payload['params']['module_sha256']='0'*64
    if mode=='receipt_alias':payload['params']['receipt_path']=str(path)
    raw=json.dumps(payload)
    if mode=='duplicate':raw=raw.replace('"action":','"action":"duplicate","action":',1)
    if mode=='nonfinite':raw=raw.replace('2000.25','NaN')
    path.write_text(raw,encoding='utf-8');sha=m.digest(path)
    if mode=='hash':sha='0'*64
    with pytest.raises(ValueError):ns['_turn_bore_qualification_payload'](str(path),sha,1234)

def test_sealed_wrapper_one_offline_dispatch(params,tmp_path,monkeypatch):
    ns=wrapper();payload=dict(action='qualify_create_bound_turn_bore',params=params);path=tmp_path/'request.json';sha=write(path,payload);calls=[]
    class Adapter:
        @staticmethod
        def dispatch_request(value,validate_only=False):calls.append((value,validate_only));return {'status':'validated_offline'}
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_inprocess_turn_bore',Adapter)
    obj=ns['SolidWorksCamQualifyTurnBoreInput'](process_id=1234,request_path=str(path),request_sha256=sha,validate_only=True)
    assert ns['solidworks_cam_qualify_turn_bore'](obj)=={'status':'validated_offline'} and len(calls)==1 and calls[0][1]


def test_native_normalized_marker_paths(params):
    for name in ('expected_document_path','native_receipt_path'):
        params[name]=params[name].replace('\\','/')
    backend=Backend(params,'normalized_paths')
    out=m.run(params,backend=backend)
    assert out['status']=='created_bound_nc_read_ram_only' and out['readback_verified'] and backend.calls==1
