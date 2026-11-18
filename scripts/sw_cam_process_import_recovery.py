"""Read an already-returned isolated import after its local reader failed. No replay."""
from copy import deepcopy
from pathlib import Path
import math,re,os
from scripts import sw_cam_process_import as core
from scripts.sw_cam_comtypes import _interface_class
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_mill_inventory import _same_inventory,_same_bodies
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_operation_guard import solidworks_operation_lock
require=core.require
SCOPE='MILL_PROCESS_IMPORT_RECOVERY_READ_V1'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256',
      'expected_sw_configuration','expected_cam_configuration','import_receipt_path','import_receipt_sha256',
      'receipt_path','qualification_only','message_policy'}
TYPES=('ICWApp4','ICWDoc3','ICWConfiguration','ICWPartDoc','ICWMachine','ICWBaseSetup','ICWSetup',
       'ICWFeature','ICWMillFeature','ICWBaseOpSetup','ICWOperation','ICWMillOperation',
       'ICWToolpath','ICWDispatchCollection','ICWTool')
READS={'ActiveDoc','IGetActiveDoc','GetDocType','GetActiveConfigurationName','GetActiveConfiguration',
       'SWConfigurationName','ConfigurationName','IGetMachine','MachType','IGetEnumSetups',
       'IGetEnumFeatures','Axis','GetReferencePosition','Suppressed','FeatureName','VolumeType','SubType',
       'IGetEnumOpSetups','IGetEnumOperations','OpernType','GetIsToolpathGenerated','IGetAllFeatures',
       'IGetEnumToolpaths','RecordCount','IGetTool','IsMillTool','ToolType','CutDiameter','Protrusion',
       'Count','Item','GetCWObjectID'}
SUCCESS_FLAGS=('readback_verified','observation_verified','import_recovery_observed','inventory_stable',
               'CAD_body_fingerprint_unchanged','protected_files_unchanged','runtime_unchanged')
def same_path(a,b):return str(Path(a).resolve()).casefold()==str(Path(b).resolve()).casefold()
def validate(v):
    require(type(v)is dict and set(v)==KEYS,'Exact read-recovery fields required')
    require(v['qualification_only']is True and v['message_policy']=='vendor_default','Explicit qualification/default events required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**31,'Strict owned PID required')
    t=v['expected_process_create_time'];require(type(t)in(int,float)and math.isfinite(t)and t>0,'Exact lifetime required')
    for k,x in v.items():
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact SHA required')
    for k in('expected_sw_configuration','expected_cam_configuration'):
        require(type(v[k])is str and 0<len(v[k])<=4096,'Exact configuration names required')
    old,op=read_pin(v['import_receipt_path'],v['import_receipt_sha256']);q=old.get('request',{})
    require(old.get('scope')==core.SCOPE and old.get('status')=='uncertain'and old.get('phase')=='finished'and old.get('failed_phase')=='after','Exact terminal consumed post-import read failure required')
    require(old.get('reason')=='Unsupported CAM interface'and old.get('issue',{}).get('type')=='ValueError'
        and old['issue'].get('hresult')is None and any(x.get('function')=='_interface_class'for x in old['issue'].get('locations',[])),'Only identified local interface-whitelist failure supported')
    for k in('dispatch_claimed','mutation_attempted','native_call_attempted','native_call_returned','vendor_default_import_rebuild_allowed'):require(old.get(k)is True,'Missing returned import fact '+k)
    for k in('native_dispatch_pending','Save_attempted','GTP_attempted','GOP_attempted','AFR_attempted','explicit_rebuild_attempted','TechDB_write_attempted','automatic_replay','model_saved'):require(old.get(k)is False,'Unexpected previous action '+k)
    require(old.get('native_return_type')=='int'and type(old.get('native_return_value'))is int and old['native_return_value']==0,'Exact completed Import HRESULT0 required')
    require(not any(k in old for k in('cleanup_error','runtime_error','receipt_write_error')),'Unresolved old cleanup/runtime failure')
    require(core.event_health(old['messages'],active=False)==0,'Old CAM events prohibit recovery authority')
    require(core.event_health(old['import_event_baseline'],active=True)==0,'Old import event baseline must be empty')
    for k in('process_id','expected_process_create_time','expected_source_sha256'):
        require(type(q.get(k))is type(v[k])and q[k]==v[k],'Historical identity differs '+k)
    require(same_path(q['expected_document_path'],v['expected_document_path']),'Historical copy path differs')
    diag=old['after_diagnostic'];require(diag.get('capture_complete')is False and type(diag.get('native_read_count'))is int and diag['native_read_count']==4 and diag.get('last_native_method')=='GetActiveConfiguration','Exact known partial reader boundary required')
    require(old['after_diagnostic']['state']['cam_configuration_name']==v['expected_cam_configuration'],'Observed imported CAM configuration differs')
    require(old['before_diagnostic']['capture_complete']is True and old['before_confirmation_diagnostic']['capture_complete']is True
        and _same_inventory(old['before'],old['before_confirmation']),'Two original complete empty captures required')
    for s in(old['before'],old['before_confirmation']):
        require(s['operation_count']==0 and s['operations']==[]and s['features']==[]and all(x==0 and type(x)is int for x in s['operation_counts'])
            and all(x['feature_count']==0 and type(x['feature_count'])is int for x in s['feature_setups']),'Original target was not empty')
    document=old['post_import_document'];require(type(document.get('type'))is int and document['type']==1 and type(document.get('needs_save'))is bool and same_path(document['path'],v['expected_document_path']),'Exact observed post-import document required')
    export,ep=read_pin(q['export_receipt_path'],q['export_receipt_sha256'])
    require(old['export_receipt_pin']==ep and export.get('scope')==core.EXPORT_SCOPE and export.get('export_verified')is True
        and export.get('readback_verified')is True and export.get('source_unchanged')is True and export.get('runtime_unchanged')is True
        and export.get('phase')=='finished'and export.get('status')=='review_required'and export['before']==export['after'],'Verified original exporter required')
    require(core.event_health(export['messages'],active=False)==0 and export['output']==old['archive_pin'],'Exact clean exported archive required')
    marker=core.marker_path(q,old['archive_pin']['sha256']);require(same_path(marker,old['marker_path']),'Consumed target marker path differs')
    mark,mp=read_pin(str(marker),_file_hash(marker))
    require(mark.get('scope')==core.SCOPE and mark.get('automatic_replay')is False and same_path(mark['receipt_path'],op['path'])
        and same_path(mark['copy_path'],v['expected_document_path'])and mark['copy_sha256']==v['expected_source_sha256']
        and mark['archive_sha256']==old['archive_pin']['sha256'],'Exact consumed import marker required')
    pins=deepcopy(old['evidence_pins']);require(type(pins)is list and 1<=len(pins)<=48,'Bounded complete original pins required')
    for p in pins:core._observed_pin(p)
    needed=[(v['expected_document_path'],v['expected_source_sha256']),(q['original_document_path'],q['original_source_sha256']),
        (q['export_receipt_path'],q['export_receipt_sha256']),(old['archive_pin']['path'],old['archive_pin']['sha256']),
        (export['request']['expected_document_path'],export['request']['expected_source_sha256']),(core.__file__,_file_hash(core.__file__))]
    for path,sha in needed:require(any(same_path(p['path'],path)and p['sha256']==sha for p in pins),'Missing original protected pin')
    require(not os.path.samefile(v['expected_document_path'],q['original_document_path'])and not os.path.samefile(v['expected_document_path'],export['request']['expected_document_path']),'Target aliases protected original')
    pins.extend([op,mp,dict(path=__file__,sha256=_file_hash(__file__))])
    receipt=Path(v['receipt_path']);require(receipt.suffix.lower()=='.json'and receipt.parent.is_dir()and not receipt.exists()and not receipt.is_symlink(),'Fresh recovery receipt required')
    require(not any(same_path(receipt,p['path'])for p in pins),'Output aliases protected input')
    return dict(pins=pins,receipt=receipt,old=old,import_pin=op,marker_pin=mp,expected_document=deepcopy(document),
        archived_operations=deepcopy(export['before']['operations']),expected_sw_configuration=v['expected_sw_configuration'])
class _Prepared:
    def __init__(self,v,data):
        self.v=deepcopy(v);self.data=data;self.pins=[core._observed_pin(p)for p in data['pins']];self.used=False
        self.digest=_digest(dict(v=self.v,data={k:str(x)if isinstance(x,Path)else x for k,x in data.items()},pins=self.pins))
def prepare(v,*,runtime_check,_validate=validate):
    require(callable(runtime_check),'Runtime guard required');runtime_check();d=_validate(v);p=_Prepared(v,d);runtime_check();return p
def consume(p,v,runtime_check):
    require(type(p)is _Prepared and not p.used,'Unused same-call recovery preparation required');p.used=True
    require(_digest(p.v)==_digest(v)and p.digest==_digest(dict(v=p.v,data={k:str(x)if isinstance(x,Path)else x for k,x in p.data.items()},pins=p.pins)),'Prepared authority changed')
    runtime_check()
    for x in p.pins:core._observed_pin(x)
    require(not p.data['receipt'].exists()and not p.data['receipt'].is_symlink(),'Fresh recovery output required');runtime_check();return p.data
def preflight(tlb):
    classes={name:_interface_class(name,tlb)for name in TYPES}
    require(str(classes['ICWConfiguration']._iid_).upper()=='{F74643C0-2AE2-4446-BE21-8C43F7881882}','Exact public configuration IID required')
    for name,dispid in(('ConfigurationName',3),('SWConfigurationName',4)):
        m=next(m for m in classes['ICWConfiguration']._methods_ if m.name=='_get_'+name)
        require(m.idlflags[0]==dispid and 'propget'in m.idlflags and tuple(x[0]for x in m.paramflags)==(10,),'Public configuration getter ABI differs')
    return dict(typed_interfaces=list(TYPES),interfaces_verified=len(classes),native_application_calls=0)
class ReadGuard(ScopedCamDispatchGuard):
    def read(self,obj,name,*args):
        require(name in READS,'Only bounded recovery getter allowlist permitted');return super().read(obj,name,*args)
    def typed(self,obj,name):
        require(name in TYPES,'Only audited inventory interfaces permitted');return super().typed(obj,name)
    def dispatch_once(self,*args,**kwargs):raise ValueError('Native mutations prohibited in recovery read')
class ReadContext(core.ImportContext):
    def start(self):
        self.stack.enter_context(solidworks_operation_lock(timeout_seconds=1,process_id=self.v['process_id']))
        self.verify_files();self.expected=self.identity()
        require(self.expected==self.data['expected_document']and self.sw_configuration==self.v['expected_sw_configuration'],'Exact observed post-import document/configuration required')
        self.r['document_before']=deepcopy(self.expected)
        addin=_member(self.sw,'GetAddInObject',self.clsid);require(addin is not None,'CAM must remain loaded')
        self.app=_typed(_member(addin,'GetCWApp'),'ICWApp4',self.tlb)
        require(self.identity()==self.expected,'Bootstrap changed document')
        self.session=CamMessageSession(self.app,self.tlb);self.stack.enter_context(self.session);self.check_events()
    def guard(self):
        return ReadGuard(self.sw,self.tlb,process_id=self.v['process_id'],expected_document=self.expected,
            source_sha256=self.v['expected_source_sha256'],evidence_pins=self.data['pins'],
            verify_evidence=self.verify_files,verify_owned_process=self.verify_owned,check_events=self.check_events)
    def adopt_post_import_baseline(self):raise ValueError('No import in recovery read')
def run_read(sw,clsid,tlb,*,runtime_check,_prepared=None,_validate=validate,_preflight=preflight,_context_factory=ReadContext,**v):
    p=prepare(v,runtime_check=runtime_check,_validate=_validate)if _prepared is None else _prepared;d=consume(p,v,runtime_check);abi=_preflight(tlb)
    r=dict(scope=SCOPE,status='running',phase='preflight',request=deepcopy(v),receipt_path=str(d['receipt']),
        import_receipt_pin=d['import_pin'],consumed_import_marker_pin=d['marker_pin'],import_receipt_status=d['old']['status'],
        evidence_pins=deepcopy(d['pins']),abi=abi,source_before_sha256=v['expected_source_sha256'],
        import_attempted=False,Save_attempted=False,GTP_attempted=False,GOP_attempted=False,explicit_rebuild_attempted=False,
        mutation_attempted=False,automatic_replay=False,model_saved=False,CAM_migration_verified=False,
        stock_parameters_exported=False,feature_association_verified=False,production_qualified=False,**{k:False for k in SUCCESS_FLAGS})
    def persist():_write_receipt(d['receipt'],r)
    _write_receipt(d['receipt'],r,create=True);ctx=None
    try:
        ctx=_context_factory(sw,clsid,tlb,v,d,r,persist,runtime_check);ctx.start()
        before=ctx.capture('before',empty=False);after=ctx.capture('after',empty=False)
        require(before['capture_complete']is True and after['capture_complete']is True and _same_inventory(before,after),'Fresh complete imported inventory changed')
        require(before['cam_configuration_name']==v['expected_cam_configuration']and before['associated_sw_configuration']==v['expected_sw_configuration'],'Exact imported configuration changed')
        original=d['old']['before'];require(_same_bodies(original['sw_reference']['solids'],before['sw_reference']['solids'])
            and original['all_solid_body_count']==before['all_solid_body_count'],'CAD body fingerprint changed since import')
        r['archive_comparison']=core.compare_archive(d['archived_operations'],after['operations'])
        require(r['archive_comparison']['definition_count_matches'],'Imported definition count differs from archive')
        ctx.verify_owned();ctx.verify_files();ctx.close();runtime_check()
        r['after_cleanup_document']=ctx.identity();require(r['after_cleanup_document']==ctx.expected,'Document changed during cleanup')
        require(core.event_health(r['messages'],active=False)==0,'Recovery CAM events require review')
        for pin in d['pins']:require(_file_hash(pin['path'])==pin['sha256'],'Protected file changed after cleanup')
        r.update(status='review_required',phase='finished',source_after_sha256=_file_hash(v['expected_document_path']),
            reason='CONSUMED_IMPORT_RAM_READ_RECOVERED_ORIGINAL_UNCERTAIN_RETAINED_UNSAVED',**{k:True for k in SUCCESS_FLAGS})
    except Exception as error:
        r.update(status='error',failed_phase=r['phase'],phase='finished',issue=_error(error),reason=str(error),**{k:False for k in SUCCESS_FLAGS})
    finally:
        if ctx is not None:
            try:ctx.close()
            except Exception as error:r.update(status='error',cleanup_error=_error(error),**{k:False for k in SUCCESS_FLAGS})
        r['phase']='finished';persist()
    return r
def revoke_runtime(r,error):
    r.update(status='error',runtime_error=_error(error),**{k:False for k in SUCCESS_FLAGS});_write_receipt(Path(r['receipt_path']),r);return r
