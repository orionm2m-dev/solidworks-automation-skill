import os,sys,importlib.util,json
from pathlib import Path
from copy import deepcopy
import pytest
root=os.environ.get('SOLIDWORKS_SKILL_ROOT')
if root:sys.path.insert(0,root)
spec=importlib.util.spec_from_file_location('inprocess_client',Path(__file__).parents[1]/'scripts/sw_cam_inprocess_reader.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.fixture
def fixture(tmp_path):
    for name in ('part.SLDPRT','host.dll','host.tlb'):(tmp_path/name).write_bytes(name.encode())
    p=dict(process_id=123,expected_process_creation_time=1700000000.0,expected_document_path=str(tmp_path/'part.SLDPRT'),expected_source_sha256=m.digest(tmp_path/'part.SLDPRT'),host_dll_path=str(tmp_path/'host.dll'),host_dll_sha256=m.digest(tmp_path/'host.dll'),host_tlb_path=str(tmp_path/'host.tlb'),host_tlb_sha256=m.digest(tmp_path/'host.tlb'),expected_host_module_version_id='12345678-1234-1234-1234-123456789abc',max_operations=8,max_tools=4,receipt_path=str(tmp_path/'result.json'),reference_receipt_path=None,reference_receipt_sha256=None)
    doc=dict(path=p['expected_document_path'],title='part.SLDPRT',type=1,needs_save=False,configuration='Default')
    op=dict(setup_index=0,operation_index=0,native_id=322,turn_operation_type=5,linked_feature_ids=[76],suppressed=False,toolpath_generated=False,toolpath_record_counts=[])
    inv=dict(machine_type=3,operation_setup_count=1,operation_count=1,operations=[op])
    tool=dict(complete=True,native_id=323,tool_type_raw=15,info_raw='T02',candidate=True,turn_tool_type_raw=1,insert_type_raw=1,holder_present=True,holder_type_raw=2,holder_id_raw=2,insert_dimensions_native={k:80.0 for k in m.INSERT_DIMENSIONS},holder_dimensions_native={k:(1 if k=='HolderShape' else 20.0) for k in m.HOLDER_DIMENSIONS})
    payload=dict(schema_version=1,scope='TURN_INPROCESS_READ_V1',engine_version='turn-reader-1',status='observed',read_only=True,mutation_attempted=False,readback_verified=True,process_id=123,host_module_version_id=p['expected_host_module_version_id'],host_assembly_location=p['host_dll_path'],stage='finished',document_before=doc,document_after=deepcopy(doc),inventory=inv,tools=[tool],elapsed_ms=10.0,nc_parameters=[],nc_parameters_complete=True)
    return p,payload

class Fake:
    def __init__(self,p,payload,hook=None):self.p=p;self.payload=payload;self.calls=0;self.requests=[];self.hook=hook;self.owner_calls=0
    def owner(self):
        self.owner_calls+=1
        return dict(alive=True,process_id=self.p['process_id'],create_time=self.p['expected_process_creation_time'],executable='C:/SOLIDWORKS/SLDWORKS.exe')
    def read_once(self,text):
        self.calls+=1;self.requests.append(json.loads(text))
        if self.hook:self.hook()
        return json.dumps(self.payload)

def test_complete_run_one_batch_no_hidden_mutation(fixture):
    p,v=fixture;b=Fake(p,v);r=m.run_read(p,backend=b)
    assert r['status']=='observed' and r['readback_verified'] and b.calls==1 and b.owner_calls==2
    assert set(b.requests[0])=={'schema_version','expected_process_id','expected_document_path','cam_addin_clsid','max_operations','max_tools'}
    assert not r['mutation_attempted'] and not r['model_saved'] and not r['GTP_attempted']
    assert json.loads(Path(p['receipt_path']).read_text())['host_response']==v

@pytest.mark.parametrize('field,value',[('process_id',True),('process_id',0),('expected_process_creation_time',False),('expected_process_creation_time',float('nan')),('max_operations',65),('max_operations',False),('max_tools',0),('max_tools',65),('expected_source_sha256','X'*64),('host_dll_sha256','abc'),('expected_host_module_version_id','invalid'),('expected_document_path','relative.SLDPRT'),('host_dll_path','relative.dll'),('reference_receipt_path','relative.json'),('nc_operation_ids',[322,322]),('nc_operation_ids',[True]),('nc_operation_ids',list(range(1,10)))])
def test_bad_request_rejected_before_any_call(fixture,field,value):
    p,v=fixture;p[field]=value;b=Fake(p,v)
    with pytest.raises((ValueError,TypeError)):m.run_read(p,backend=b)
    assert b.calls==0

@pytest.mark.parametrize('change',['pid','mvid','dll','scope','engine','schema_bool','mutation','readonly','not_verified','doc_after','doc_type_bool','duplicate_op','too_many','bad_setup','negative_count','nongenerated_counts','duplicate_tool','tool_id_bool','candidate_type_bool','candidate_nan','host_error','unknown_status'])
def test_bad_response_never_verified(fixture,change):
    p,v=fixture
    if change=='pid':v['process_id']=999
    elif change=='mvid':v['host_module_version_id']='22345678-1234-1234-1234-123456789abc'
    elif change=='dll':v['host_assembly_location']=str(Path(p['host_dll_path']).with_name('other.dll'))
    elif change=='scope':v['scope']='other'
    elif change=='engine':v['engine_version']='old'
    elif change=='schema_bool':v['schema_version']=True
    elif change=='mutation':v['mutation_attempted']=True
    elif change=='readonly':v['read_only']=False
    elif change=='not_verified':v['readback_verified']=False
    elif change=='doc_after':v['document_after']['needs_save']=True
    elif change=='doc_type_bool':v['document_before']['type']=True
    elif change=='duplicate_op':v['inventory']['operations']*=2;v['inventory']['operation_count']=2
    elif change=='too_many':v['inventory']['operation_count']=99
    elif change=='bad_setup':v['inventory']['operations'][0]['setup_index']=8
    elif change=='negative_count':v['inventory']['operations'][0]['toolpath_generated']=True;v['inventory']['operations'][0]['toolpath_record_counts']=[-1]
    elif change=='nongenerated_counts':v['inventory']['operations'][0]['toolpath_record_counts']=[40]
    elif change=='duplicate_tool':v['tools']*=2
    elif change=='tool_id_bool':v['tools'][0]['native_id']=True
    elif change=='candidate_type_bool':v['tools'][0]['holder_type_raw']=True
    elif change=='candidate_nan':v['tools'][0]['insert_dimensions_native']['IncludedAngle']=float('nan')
    elif change=='host_error':v.update(status='error',readback_verified=False,message='HOST_THREAD_MISMATCH')
    elif change=='unknown_status':v['status']='partial'
    b=Fake(p,v);r=m.run_read(p,backend=b);assert r['status']=='error' and not r['readback_verified'] and b.calls==1

@pytest.mark.parametrize('filekey',['expected_document_path','host_dll_path','host_tlb_path'])
def test_input_change_during_batch_caught(fixture,filekey):
    p,v=fixture;b=Fake(p,v,lambda:Path(p[filekey]).write_bytes(b'changed'));r=m.run_read(p,backend=b);assert r['status']=='error' and b.calls==1

def test_reused_receipt_never_replays(fixture):
    p,v=fixture;b=Fake(p,v);m.run_read(p,backend=b)
    with pytest.raises(ValueError):m.run_read(p,backend=b)
    assert b.calls==1

def test_dead_owner_never_calls(fixture):
    p,v=fixture;b=Fake(p,v);b.owner=lambda:dict(alive=False,process_id=123,create_time=1700000000.0,executable='C:/SLDWORKS.exe');r=m.run_read(p,backend=b);assert r['status']=='error' and b.calls==0

def test_lifetime_change_after_call_caught(fixture):
    p,v=fixture;b=Fake(p,v);base=b.owner
    def owner():
        r=base()
        if b.owner_calls==2:r['create_time']+=1
        return r
    b.owner=owner;r=m.run_read(p,backend=b);assert r['status']=='error' and b.calls==1

def test_host_exception_preserved_without_retry(fixture):
    p,v=fixture;b=Fake(p,v)
    def fail(text):b.calls+=1;raise RuntimeError('native error')
    b.read_once=fail;r=m.run_read(p,backend=b);assert r['status']=='error' and r['native_dispatch_pending'] and b.calls==1

def test_json_duplicate_and_size_rejected():
    for value in ('{"a":1,"a":2}','[NaN]',' '*1048577):
        with pytest.raises(ValueError):m.decode(value)

def ref_for(p,v):
    inv=deepcopy(v['inventory']);ops=inv['operations'];state=dict(document=v['document_before'],inventory=deepcopy(inv),operations=[{k:x[k] for k in ('setup_index','operation_index','native_id','turn_operation_type','linked_feature_ids','suppressed')} for x in ops])
    state['inventory'].update(feature_count=1,feature_counts_by_setup=[1],stock={'type':3})
    return dict(status='observed',read_only=True,mutation_attempted=False,readback_verified=True,source_sha256=p['expected_source_sha256'],before=state,after=deepcopy(state))

def test_reference_comparison_is_scoped_to_claimed_metadata(fixture):
    p,v=fixture;ref=ref_for(p,v);x=m.compare_reference(v,ref,p);assert x['verified'] and not x['tool_geometry_compared'] and not x['CL_bytes_compared']

def test_changed_operation_link_fails_pinned_reference(fixture):
    p,v=fixture;ref=ref_for(p,v);v['inventory']['operations'][0]['linked_feature_ids']=[99]
    with pytest.raises(ValueError):m.compare_reference(v,ref,p)

@pytest.mark.parametrize('error',[False,True])
def test_optional_nc_raw_values_and_partial_failure(fixture,error):
    p,v=fixture;p['nc_operation_ids']=[322];v['nc_parameters']=[dict(operation_native_id=322,status='observed',spindle_speed_native=100.0,feed_rate_ipm_native=0.2)];v['nc_parameters_complete']=not error
    if error:v['nc_parameters']=[dict(operation_native_id=322,status='error',stage='IGetTurnNCParam',hresult=-1,error_type='COMException',message='error')]
    b=Fake(p,v);r=m.run_read(p,backend=b);assert r['status']=='observed' and b.requests[0]['nc_operation_ids']==[322] and r['host_response']['nc_parameters_complete']==(not error)

def test_inconsistent_nc_completion_rejected(fixture):
    p,v=fixture;p['nc_operation_ids']=[322];v['nc_parameters']=[dict(operation_native_id=322,status='error',stage='IGetTurnNCParam',hresult=-1,error_type='COMException')];v['nc_parameters_complete']=True
    with pytest.raises(ValueError):m.validate_response(json.dumps(v),m.validate_params(p))

@pytest.mark.parametrize('case',['missing_insert','foreign_holder','holder_shape_float','unsolicited_nc','configuration_change','configuration_missing'])
def test_strict_native_shape(fixture,case):
    p,v=fixture
    if case=='missing_insert':v['tools'][0]['insert_dimensions_native'].pop('Thickness')
    elif case=='foreign_holder':v['tools'][0]['holder_dimensions_native']['foo']=1
    elif case=='holder_shape_float':v['tools'][0]['holder_dimensions_native']['HolderShape']=1.0
    elif case=='unsolicited_nc':v['nc_parameters']=[dict(operation_native_id=322,status='observed',spindle_speed_native=1.0,feed_rate_ipm_native=1.0)]
    elif case=='configuration_change':v['document_after']['configuration']='Other'
    else:v['document_before'].pop('configuration')
    with pytest.raises(ValueError):m.validate_response(json.dumps(v),m.validate_params(p))

def test_legacy_reference_configuration_is_explicitly_not_compared(fixture):
    p,v=fixture;ref=ref_for(p,v)
    ref['before']['document'].pop('configuration');ref['after']['document'].pop('configuration')
    assert m.compare_reference(v,ref,p)['configuration_compared'] is False

def test_reference_configuration_is_compared_when_available(fixture):
    p,v=fixture;ref=ref_for(p,v)
    assert m.compare_reference(v,ref,p)['configuration_compared'] is True
    v['document_before']['configuration']='Other'
    with pytest.raises(ValueError):m.compare_reference(v,ref,p)
