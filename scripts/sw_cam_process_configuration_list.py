"""Bounded names/mapping of CAM configurations; never activate or mutate."""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_process_import_recovery as recovery
from scripts.sw_cam_process_import import event_health
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_mill_inventory import _same_inventory,_items
from scripts.sw_cam_mill_route_context import integer
from scripts.sw_cam_comtypes import _interface_class
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam import _error
from scripts.sw_cam_turn_post_option_context import NativePostOptions
require=recovery.require
SCOPE='MILL_CONSUMED_IMPORT_CAM_CONFIGURATION_LIST_V1'
KEYS=recovery.KEYS|{'empty_read_receipt_path','empty_read_receipt_sha256'}
COLLECTION_IID='{670DD771-2C33-11D6-A9A1-00062999E55F}'
EXTRA={'GetAllConfigurations','GetTypeInfo','GetTypeAttr','GetDocumentation'}
def text(value):
    require(type(value)is str and 0<len(value)<=1024,'Bounded nonempty configuration BSTR required');return value
def validate(v):
    require(type(v)is dict and set(v)==KEYS,'Exact configuration-list request required')
    d=recovery.validate({k:v[k]for k in recovery.KEYS})
    empty,p=read_pin(v['empty_read_receipt_path'],v['empty_read_receipt_sha256'])
    require(empty.get('scope')==recovery.SCOPE and empty.get('status')=='error'and empty.get('phase')=='finished'
        and empty.get('reason')=='Nonempty bounded imported operation table required','Exact observed empty active import recovery required')
    require({k:x for k,x in empty['request'].items()if k!='receipt_path'}=={k:v[k]for k in recovery.KEYS if k!='receipt_path'}
        and recovery.same_path(empty['request']['receipt_path'],empty['receipt_path']),'Empty reader owner/source/configuration request differs')
    require(empty['import_receipt_pin']==d['import_pin']and empty['consumed_import_marker_pin']==d['marker_pin'],'Empty reader predecessor differs')
    require(event_health(empty['messages'],active=False)==0 and not any(k in empty for k in('runtime_error','cleanup_error','receipt_write_error')),'Empty reader events/cleanup failed')
    for k in('import_attempted','Save_attempted','GTP_attempted','GOP_attempted','explicit_rebuild_attempted','mutation_attempted','automatic_replay','model_saved'):
        require(empty.get(k)is False,'Unexpected previous mutation '+k)
    a,b=empty['before'],empty['after'];require(a.get('capture_complete')is True and b.get('capture_complete')is True and _same_inventory(a,b),'Two complete stable empty inventories required')
    require(a['machine_type']==1 and a['features']==a['operations']==a['feature_setups']==a['operation_setups']==[]
        and all(type(a[k])is int and a[k]==0 for k in('feature_count','operation_count','generated_operation_count','total_record_count')),'Only observed empty active MILL supported')
    require(a['cam_configuration_name']==v['expected_cam_configuration']and a['associated_sw_configuration']==v['expected_sw_configuration'],'Empty configuration binding differs')
    require(empty['document_before']==d['expected_document'],'Empty reader changed document')
    require(not recovery.same_path(v['receipt_path'],p['path']),'Output aliases empty observation')
    d['pins'].extend([p,dict(path=__file__,sha256=_file_hash(__file__))]);d['empty_read_pin']=p;return d
def preflight(tlb):
    from ctypes import HRESULT,POINTER
    from comtypes.automation import IDispatch
    abi=recovery.preflight(tlb);cls=_interface_class('ICWDoc3',tlb)
    m=next(m for m in cls._methods_ if m.name=='GetAllConfigurations')
    require(m.restype is HRESULT and m.idlflags[0]==23 and m.argtypes==(POINTER(POINTER(IDispatch)),)
        and tuple(x[0]for x in m.paramflags)==(10,),'Exact public GetAllConfigurations ABI required')
    return dict(read_abi=abi,GetAllConfigurations_dispid=23,collection_owner_requires_runtime_public_typeinfo=True,native_application_calls=0)
def capture_configurations(app,*,read,typed,metadata,progress):
    row=dict(capture_complete=False,configurations=[],inactive_contents_observed=False,activation_attempted=False)
    progress(row);active=read(app,'IGetActiveDoc');doc=typed(active,'ICWDoc3')
    require(integer(read(doc,'GetDocType'),'document type')==1,'CAM part required')
    row['active_configuration_name']=text(read(doc,'GetActiveConfigurationName'));raw=read(doc,'GetAllConfigurations')
    require(raw is not None and bool(raw),'GetAllConfigurations returned null; no enumeration inference')
    row['collection_type_info']=metadata(raw);progress(row)
    require(row['collection_type_info']['guid']==COLLECTION_IID,'Configuration list does not identify public ICWDispatchCollection')
    collection=typed(raw,'ICWDispatchCollection');raw_count=read(collection,'Count')
    row['configuration_count_native_type']=type(raw_count).__name__;row['configuration_count_native']=raw_count if raw_count is None or type(raw_count)in(bool,int,float,str)else None;progress(row)
    count=integer(raw_count,'configuration count',1,16);row['configuration_count']=count
    for i in range(count):
        config=typed(read(collection,'Item',i),'ICWConfiguration')
        row['configurations'].append(dict(index=i,name=text(read(config,'ConfigurationName')),sw_configuration_name=text(read(config,'SWConfigurationName'))));progress(row)
    names=[x['name']for x in row['configurations']]
    require(len(set(names))==len(names)and names.count(row['active_configuration_name'])==1,'Unique list containing active configuration required')
    repeated_count=read(collection,'Count');row['configuration_count_after_native_type']=type(repeated_count).__name__;row['configuration_count_after_native']=repeated_count if repeated_count is None or type(repeated_count)in(bool,int,float,str)else None;progress(row)
    require(integer(repeated_count,'configuration count',1,16)==count and text(read(doc,'GetActiveConfigurationName'))==row['active_configuration_name'],'Configuration list/count or active selection changed')
    machine=typed(read(typed(active,'ICWPartDoc'),'IGetMachine'),'ICWMachine');require(integer(read(machine,'MachType'),'machine type')==1,'Active machine must remain MILL')
    features=operations=0
    for raw_setup in _items(read(machine,'IGetEnumSetups'),typed,read,8):
        setup=typed(raw_setup,'ICWBaseSetup');features+=len(_items(read(setup,'IGetEnumFeatures'),typed,read,64-features))
    for raw_setup in _items(read(machine,'IGetEnumOpSetups'),typed,read,8):
        setup=typed(raw_setup,'ICWBaseOpSetup');operations+=len(_items(read(setup,'IGetEnumOperations'),typed,read,32-operations))
    row.update(active_feature_count=features,active_operation_count=operations)
    require(features==0 and operations==0,'Active empty configuration changed')
    row.update(capture_complete=True,additional_configurations_observed=count>1,configuration_list_semantics='names_and_SW_mapping_only')
    progress(row);return row
class ReadGuard(recovery.ReadGuard):
    def read(self,obj,name,*args):
        require(name in recovery.READS|EXTRA,'Only configuration-list getters permitted');return ScopedCamDispatchGuard.read(self,obj,name,*args)
class ReadContext(recovery.ReadContext):
    def guard(self):
        return ReadGuard(self.sw,self.tlb,process_id=self.v['process_id'],expected_document=self.expected,
            source_sha256=self.v['expected_source_sha256'],evidence_pins=self.data['pins'],
            verify_evidence=self.verify_files,verify_owned_process=self.verify_owned,check_events=self.check_events)
    def capture(self,label):
        diagnostic={};self.r[label+'_diagnostic']=diagnostic;self.r['phase']=label;self.persist()
        with self.guard()as guard:
            def read(obj,name,*args):
                diagnostic['native_read_count']=diagnostic.get('native_read_count',0)+1
                require(diagnostic['native_read_count']<=512,'Configuration-list read limit')
                diagnostic['last_native_method']=name;return guard.read(obj,name,*args)
            class Metadata:
                pass
            meta=Metadata();meta.read=read
            def progress(row):diagnostic['state']=deepcopy(row);self.persist()
            row=capture_configurations(self.app,read=read,typed=guard.typed,
                metadata=lambda raw:NativePostOptions.metadata(meta,raw),progress=progress)
            guard._boundary()
        self.r[label]=deepcopy(row);self.persist();return row
def run_read(sw,clsid,tlb,*,runtime_check,_prepared=None,_validate=validate,_preflight=preflight,_context_factory=ReadContext,**v):
    p=recovery.prepare(v,runtime_check=runtime_check,_validate=_validate)if _prepared is None else _prepared
    d=recovery.consume(p,v,runtime_check);abi=_preflight(tlb)
    r=dict(scope=SCOPE,status='running',phase='preflight',request=deepcopy(v),receipt_path=str(d['receipt']),import_receipt_pin=d['import_pin'],
        empty_read_receipt_pin=d['empty_read_pin'],consumed_import_marker_pin=d['marker_pin'],import_receipt_status='uncertain',
        evidence_pins=deepcopy(d['pins']),abi=abi,readback_verified=False,runtime_unchanged=False,protected_files_unchanged=False,
        mutation_attempted=False,activation_attempted=False,import_attempted=False,Save_attempted=False,GTP_attempted=False,
        explicit_rebuild_attempted=False,model_saved=False,inactive_contents_observed=False,source_before_sha256=v['expected_source_sha256'])
    def persist():_write_receipt(d['receipt'],r)
    _write_receipt(d['receipt'],r,create=True);ctx=None
    try:
        ctx=_context_factory(sw,clsid,tlb,v,d,r,persist,runtime_check);ctx.start();a=ctx.capture('before');b=ctx.capture('after')
        require(a['capture_complete']is True and a==b,'Two stable complete configuration lists required')
        require(a['active_configuration_name']==v['expected_cam_configuration'],'Active CAM configuration changed')
        current=next(x for x in a['configurations']if x['name']==a['active_configuration_name'])
        require(current['sw_configuration_name']==v['expected_sw_configuration'],'Active CAD association changed')
        ctx.verify_owned();ctx.verify_files();ctx.close();runtime_check()
        r['after_cleanup_document']=ctx.identity();require(r['after_cleanup_document']==ctx.expected,'Document changed during cleanup')
        require(event_health(r['messages'],active=False)==0,'Configuration-list CAM events require review');ctx.verify_files()
        r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,protected_files_unchanged=True,
            source_after_sha256=_file_hash(v['expected_document_path']),configuration_count=a['configuration_count'],
            additional_configurations_observed=a['additional_configurations_observed'],reason='CONFIGURATION_NAMES_READ_NO_ACTIVATION_OR_INACTIVE_CONTENTS')
    except Exception as error:
        r.update(status='error',failed_phase=r['phase'],phase='finished',issue=_error(error),reason=str(error),readback_verified=False,runtime_unchanged=False,protected_files_unchanged=False)
    finally:
        if ctx is not None:
            try:ctx.close()
            except Exception as error:r.update(status='error',cleanup_error=_error(error),readback_verified=False,runtime_unchanged=False,protected_files_unchanged=False)
        r['phase']='finished';persist()
    return r
def revoke_runtime(r,error):
    r.update(status='error',runtime_error=_error(error),readback_verified=False,runtime_unchanged=False,protected_files_unchanged=False)
    _write_receipt(Path(r['receipt_path']),r);return r
