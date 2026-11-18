"""Read one saved Rough/Contour pair using existing parameter and plane readers.
No configuration, tool creation, assignment, generation or persistence is exposed.
"""
from copy import deepcopy
from pathlib import Path
import inspect
import math
import re
from scripts import sw_cam_pocket_definition_context as definition
from scripts import sw_cam_mill_current_parameters as parameters
from scripts import sw_cam_guide_group_parameters as guide
from scripts import sw_cam_process_import as shared
from scripts.sw_cam import _member, _error
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_mill_inventory import _items

pocket, fields, protected = guide.pocket, guide.fields, guide.protected
require = shared.require
SCOPE='CURRENT_SAVED_POCKET_PAIR_PARAMETERS_READ_V1'
FLAGS=('readback_verified','parameter_read_complete','inventory_unchanged','source_unchanged','runtime_unchanged')
AUTHORITY_PREFIXES=('definition_recovery_receipt','definition_save_receipt','definition_gop_receipt','definition_gop_save_receipt')
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','expected_feature_native_id','expected_operation_native_ids','receipt_path','qualification_only','message_policy'}|{p+s for p in AUTHORITY_PREFIXES for s in ('_path','_sha256')}
INTERFACES={'ICWDoc3','ICWPartDoc','ICWMachine','ICWBaseOpSetup','ICWOpSetup3','ICWDispatchCollection','ICWOperation','ICWMillOperation','ICWFeature','ICWRghMillOp','ICWMillOperation3','ICWToolpathParam','ICWPosition','ICWUnitVector','ICWNCParam','ICWNCParam2','ICWNCParam3','ICWNCParam4','ICWFinishMillOp','ICWFinishMillOp2','ICWFinishMillOp3','ICWLeadInOut','ICWTool','ICWMillTool','ICWMillToolHolder'}
READS=pocket.CAM_GETTERS|fields.GETTERS|protected.MEMBERS|set(pocket.leads.LEAD_FIELDS)|set(pocket.finish.MILL_TOOL_FIELDS+pocket.finish.HOLDER_FIELDS)|{'IGetMillToolHolder','IGetActiveDoc','IGetMachine','IGetEnumOpSetups','IGetEnumOperations'}
MAX_CALLS=1800


def shape(v):
    require(type(v)is dict and set(v)==KEYS,'Exact saved pair reader request required')
    for k in ('process_id','expected_feature_native_id'):
        require(type(v[k])is int and 0<v[k]<2**31,'Strict positive native identity required')
    require(type(v['expected_process_create_time'])in(int,float) and math.isfinite(v['expected_process_create_time']) and v['expected_process_create_time']>0,'Exact finite lifetime required')
    ids=v['expected_operation_native_ids']
    require(type(ids)is list and len(ids)==2 and all(type(i)is int and 0<i<2**31 for i in ids) and len(set(ids))==2,'Two strict distinct ordered operation IDs required')
    require(v['qualification_only']is True and v['message_policy']=='vendor_default','Explicit raw-observation qualification required')
    for k,x in v.items():
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact SHA required')


def select_pair(d,v):
    state=d['saved_plan_inventory'];rows=state['operations']
    require(state['document']['needs_save']is False and state['saved_file_sha256']==v['expected_source_sha256'],'Clean saved current pair required')
    require(len(rows)==2 and [r['native_id']for r in rows]==v['expected_operation_native_ids'],'Exact full two-operation order required')
    for kind,row in enumerate(rows):
        require(type(row['mill_operation_type'])is int and row['mill_operation_type']==kind and row['linked_feature_ids']==[v['expected_feature_native_id']] and row['all_linked_features_observed']is True and row['suppressed']is False and row['toolpath_generated']is False and not row['toolpath_record_counts'],'Exact ungenerated own Rough/Contour pair required')
        require(row['assigned_tool']['native_read_complete']is True and row['assigned_tool']['is_mill_tool']is True,'Complete assigned MILL tool observation required')
    require(len({r['setup_native_id']for r in rows})==1 and len(state['operation_setups'])==1,'One explicit operation setup required')
    return deepcopy(rows)


def prepare(v):
    shape(v);d=definition.load_saved_plan(v)
    require(v['expected_process_create_time']==d['request']['expected_process_create_time'],'Saved plan process lifetime differs')
    targets=select_pair(d,v)
    path=Path(v['receipt_path'])
    require(path.suffix.lower()=='.json' and path.parent.is_dir() and not path.exists() and not path.is_symlink(),'Fresh JSON read receipt required')
    require(not any(definition.creator.same_path(str(path),p['path'])for p in d['pins']),'Read output aliases protected input')
    for source in (__file__,definition.__file__,parameters.__file__,guide.__file__,pocket.__file__,fields.__file__,protected.__file__,pocket.planes.__file__,pocket.nc.__file__):
        pin=shared.file_pin(source,_file_hash(source))
        if not any(definition.creator.same_path(pin['path'],p['path'])for p in d['pins']):d['pins'].append(pin)
    require(len(d['pins'])<=64,'Existing complete guard pin bound exceeded')
    return dict(context=d,targets=targets,request=deepcopy(v),receipt=path,consumed=False)


def preflight(tlb):
    from scripts.sw_cam_comtypes import _interface_class
    cls=_interface_class('ICWDoc3',tlb)
    generated=shared.file_pin(inspect.getfile(cls),_file_hash(inspect.getfile(cls)))
    # Reuse the exact resolver already used by the proven guide reader. Intercept
    # its observation callback so only public metadata is loaded; QI never runs.
    class MetadataOnly:
        typelib_path=tlb
        generated_pin=generated
        reject=staticmethod(require)
        def observed(self,obj,kind,name,invoke):return None
    probe=MetadataOnly()
    for name in sorted(INTERFACES):guide.ParameterReadBatch.typed(probe,None,name)
    from ctypes import HRESULT,POINTER,c_double
    from ctypes.wintypes import VARIANT_BOOL
    z=pocket.cam_class('ICWNCParam4',tlb,generated)
    zmethods=[m for m in z._methods_ if m.name=='GetZFeedrate2']
    require(len(zmethods)==1 and zmethods[0].restype is HRESULT and zmethods[0].idlflags[0]==50 and zmethods[0].argtypes==(POINTER(c_double),POINTER(VARIANT_BOOL)) and tuple(x[0]for x in zmethods[0].paramflags)==(2,2),'Exact reused Z-feed getter ABI required')
    return dict(generated_pin=generated,interface_names=sorted(INTERFACES),z_feed_abi_verified=True,
        nc=pocket.nc.audit_interfaces(tlb,generated),planes=pocket.planes.audit_interfaces(tlb,generated),
        protected_finish=protected.audit(tlb,generated),application_connections=0,native_calls=0)


class ReadGuard(ScopedCamDispatchGuard):
    def __init__(self,*args,generated_pin,report,**kwargs):
        self.generated_pin=generated_pin;self.report=report;self.calls=0
        super().__init__(*args,**kwargs)
    def reject(self,condition,message):
        if not condition:self._invalid=True;raise ValueError(message)
    def observed(self,obj,kind,name,invoke):
        self.calls+=1;self.reject(self.calls<=MAX_CALLS,'Selected pair native-read budget exceeded')
        self.report['last_native_read']=dict(kind=kind,member=name,returned=False,index=self.calls)
        result=self._observe(invoke)
        self.report['last_native_read']['returned']=True
        self.report['parameter_native_read_count']=self.calls
        return result
    def read(self,obj,name,*args):
        if name=='QueryInterface':
            from comtypes.automation import IDispatch
            self.reject(len(args)==1 and args[0]is IDispatch,'Only existing feature IDispatch conversion permitted')
        else:self.reject(name in READS,'Only selected parameter getters permitted')
        return self.observed(obj,'getter',name,lambda:_member(obj,name,*args))
    def typed(self,obj,name):
        self.reject(name in INTERFACES,'Interface outside selected parameter scope')
        return guide.ParameterReadBatch.typed(self,obj,name)
    def plane(self,obj,name,diagnostic):
        self.reject(name in pocket.planes.POINTER_FIELDS,'Only reviewed plane pointer getters permitted')
        return self.observed(obj,'getter',name,lambda:pocket.planes.pointer_value(obj,name,diagnostic))
    def dispatch_once(self,*a,**kw):raise ValueError('Read-only pair context forbids native mutation')


def read_pair(state,native,targets,batch,report,persist):
    """Reuse own-operation levels/rough/finish + once-per-tool dimension cache."""
    doc=native['doc'];machine=batch.typed(batch.read(batch.typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
    setups=_items(batch.read(machine,'IGetEnumOpSetups'),batch.typed,batch.read,1)
    require(len(setups)==1 and _object_id(doc,setups[0],batch.read)==targets[0]['setup_native_id'],'Current own operation setup differs')
    operations=_items(batch.read(batch.typed(setups[0],'ICWBaseOpSetup'),'IGetEnumOperations'),batch.typed,batch.read,2)
    ids=[_object_id(doc,op,batch.read)for op in operations]
    require(ids==[r['native_id']for r in targets],'Current enumerated pair order differs')
    native=dict(native,operations=dict(zip(ids,operations)))
    try:
        parameters.capture_rows(state,native,targets,feature_id=targets[0]['linked_feature_ids'][0],read=batch.read,typed=batch.typed,boundary=batch._boundary)
    finally:
        report['parameters']=state.get('operation_parameters',[]);persist()
    for row,out in zip(targets,report['parameters']):
        raw=native['operations'][row['native_id']];feature=native['selected_feature']
        out['nc']=pocket.read_nc_settings(raw,setups[0],read=batch.read,typed=batch.typed,pointer_read=batch.plane,diagnostic=out.setdefault('nc_diagnostic',{}),persist=persist)
        if row['mill_operation_type']==1:
            out['finish_fields']=fields.read_cached_fields(batch,raw,feature,out.setdefault('finish_field_diagnostic',{}))
            out['protected_finish']=protected.read_protected(raw,feature,read=batch.read,typed=batch.typed,record=lambda k,x:out.setdefault('protected_raw',{}).update({k:pocket.rough.bounded_raw_observation(x)}))
            out['leads']=pocket.leads.read_lead_details(raw,feature,read=batch.read,typed=batch.typed,lead_typed=lambda x:batch.typed(x,'ICWLeadInOut'))
        persist()
    require(len(report['parameters'])==2 and all(r['read_complete']is True for r in report['parameters']),'Two complete parameter rows required')
    report['unique_tool_dimension_reads']=len({r['assigned_tool']['native_id']for r in targets})
    batch._boundary()


class Context:
    def __init__(self,sw,clsid,tlb,v,bundle,report,persist,runtime_check,abi):
        self.sw,self.clsid,self.tlb,self.v=sw,clsid,tlb,v
        self.bundle,self.d,self.r,self.persist=bundle,bundle['context'],report,persist
        self.runtime_check,self.abi=runtime_check,abi;self.session=None;self.closed=False
    def identity(self):
        value=definition.identity(self.sw,self.d)
        require(value['document']==self.d['saved_plan_inventory']['document'] and value['document']['needs_save']is False,'Saved clean document identity changed')
        return value
    def events(self,active=True):
        self.r['messages']=self.session.summary()
        require(shared.event_health(self.r['messages'],active=active)==0,'Any CAM event rejects read acceptance')
    def start(self):
        self.runtime_check();self.expected=self.identity();self.r['document_before']=deepcopy(self.expected['document'])
        addin=_member(self.sw,'GetAddInObject',self.clsid);require(addin is not None,'CAM must already be loaded')
        self.app=_typed(_member(addin,'GetCWApp'),'ICWApp4',self.tlb)
        require(self.identity()==self.expected,'Bootstrap changed document/source')
        self.session=CamMessageSession(self.app,self.tlb);self.session.__enter__();self.events()
    def capture(self,label):
        self.r['phase']=label;diagnostic={};self.r[label+'_diagnostic']=diagnostic;self.persist()
        state,native=definition.capture(self.sw,self.clsid,self.tlb,self.d,self.events,diagnostic)
        require(state==self.d['saved_plan_inventory'],'Current full saved-plan inventory differs')
        self.r[label]=deepcopy(state);self.persist();return state,native
    def observe(self,state,native):
        self.r['phase']='selected_parameters';self.persist()
        def owned():require(self.identity()==self.expected,'Selected context changed during parameters')
        with ReadGuard(self.sw,self.tlb,process_id=self.v['process_id'],expected_document=self.expected['document'],source_sha256=self.v['expected_source_sha256'],evidence_pins=self.d['pins'],verify_evidence=lambda:definition.verify_files(self.d),verify_owned_process=owned,check_events=self.events,generated_pin=self.abi['generated_pin'],report=self.r)as batch:
            read_pair(deepcopy(state),native,self.bundle['targets'],batch,self.r,self.persist)
        self.r['parameter_guard']=batch.summary()
    def close(self):
        if self.closed:return
        self.closed=True
        if self.session is not None:
            try:self.session.__exit__(None,None,None)
            finally:self.events(False)


def run_read(sw,clsid,tlb,v,*,prepared=None,runtime_check=lambda:None,_context_factory=Context):
    bundle=prepared if prepared is not None else prepare(v)
    require(bundle.get('consumed')is False and bundle['request']==v,'Exact unconsumed same-call preparation required');bundle['consumed']=True
    d=bundle['context'];definition.verify_files(d);abi=preflight(tlb)
    for pin in (abi['generated_pin'],shared.file_pin(tlb,_file_hash(tlb))):
        if not any(definition.creator.same_path(pin['path'],p['path'])for p in d['pins']):d['pins'].append(pin)
    require(len(d['pins'])<=64,'Complete parameter guard pin bound exceeded')
    r=dict(scope=SCOPE,status='running',phase='prepared',request=deepcopy(v),receipt_path=str(bundle['receipt']),authority_scope=d['authority_scope'],evidence_pins=deepcopy(d['pins']),abi=abi,read_only=True,mutation_attempted=False,Save_attempted=False,GOP_attempted=False,GTP_attempted=False,Import_attempted=False,tool_creation_attempted=False,tool_assignment_attempted=False,automatic_replay=False,full_tool_profiles_read=False,physical_tool_qualified=False,native_units_verified=False,cutting_conditions_qualified=False,island_geometry_verified=False,production_qualified=False,source_before_sha256=v['expected_source_sha256'],**{k:False for k in FLAGS})
    def persist():_write_receipt(bundle['receipt'],r)
    _write_receipt(bundle['receipt'],r,create=True);ctx=None
    try:
        runtime_check();ctx=_context_factory(sw,clsid,tlb,v,bundle,r,persist,runtime_check,abi);ctx.start()
        before,native=ctx.capture('before');ctx.observe(before,native);after,_=ctx.capture('after')
        require(before==after,'Full inventory changed during parameter reads')
        ctx.close();runtime_check();r['after_cleanup_identity']=ctx.identity()
        require(r['after_cleanup_identity']==ctx.expected,'Document/source changed during cleanup')
        require(shared.event_health(r['messages'],active=False)==0,'Clean disconnected event transport required')
        definition.verify_files(d);require(_file_hash(v['expected_document_path'])==v['expected_source_sha256'],'Source changed after reading')
        r.update(status='observed',phase='finished',source_after_sha256=v['expected_source_sha256'],**{k:True for k in FLAGS})
    except Exception as error:r.update(status='error',failed_phase=r['phase'],phase='finished',issue=_error(error),reason=str(error),**{k:False for k in FLAGS})
    finally:
        if ctx is not None:
            try:ctx.close()
            except Exception as error:r.update(status='error',cleanup_error=_error(error),**{k:False for k in FLAGS})
        r['phase']='finished';persist()
    return r


def revoke(r,error):
    r.update(status='error',runtime_error=_error(error),**{k:False for k in FLAGS});_write_receipt(Path(r['receipt_path']),r);return r
