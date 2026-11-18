"""One unsaved pocket definition with four autodetected islands; no process generation.

A complete scalar/header readback is definition-only evidence. Native island
geometry, feature association, physical depth, stock and machining remain unqualified.
"""
from copy import deepcopy
from pathlib import Path
from ctypes import HRESULT, POINTER, c_long, c_double
from ctypes.wintypes import VARIANT_BOOL
import math
import re

from comtypes import BSTR
from comtypes.automation import IDispatch, VARIANT
from scripts import sw_cam_process_import as shared
from scripts.sw_cam import _member, _error
from scripts.sw_cam_comtypes import _interface_class
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_inventory import _same_bodies
from scripts.sw_cam_mill_qualification import _vector
from scripts.sw_cam_profile_sketch import _input, _snapshot as sketch_snapshot, _read_sketch
from scripts.sw_operation_guard import solidworks_operation_lock
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_added_pocket_delta import close as native_depth_close, TOL_NATIVE

SCOPE = 'MILL_ONE_AUTODETECTED_FOUR_ISLAND_DEFINITION_V1'
KEYS = {'process_id','expected_process_create_time','expected_document_path','expected_source_sha256',
        'original_document_path','original_source_sha256','setup_receipt_path','setup_receipt_sha256',
        'setup_save_receipt_path','setup_save_receipt_sha256','sketch_receipt_path','sketch_receipt_sha256',
        'native_geometry_path','native_geometry_sha256','owner_setup_native_id','expected_sw_configuration',
        'expected_cam_configuration','expected_axis_native','expected_origin_native','sketch_spec','depth_native','receipt_path','qualification_only',
        'acknowledge_definition_only','message_policy'}
CAPS_KEYS = {'source_variant','caps_receipt_path','caps_receipt_sha256','caps_geometry_receipt_path',
             'caps_geometry_receipt_sha256','caps_save_receipt_path','caps_save_receipt_sha256','caps_saved_sha256',
             'caps_inventory_receipt_path','caps_inventory_receipt_sha256','caps_export_receipt_path','caps_export_receipt_sha256'}


def saved_caps(v): return v.get('source_variant') == 'saved_cam_caps'


FLAGS = ('definition_readback_verified','inventory_delta_verified','source_unchanged','runtime_unchanged')
require = shared.require


def canonical(value):
    return str(Path(value).resolve()).casefold()


def same_path(a,b):
    return type(a) is str and type(b) is str and canonical(a)==canonical(b)


def number(value):
    require(type(value) in (int,float) and math.isfinite(value),'Finite numeric required')
    return float(value)


def shape(v):
    require(type(v) is dict and (set(v)==KEYS or (saved_caps(v) and set(v)==KEYS|CAPS_KEYS)),
            'Exact feature-only request or saved_cam_caps variant required')
    require(type(v['process_id']) is int and 0<v['process_id']<2**31,'Exact PID required')
    require(number(v['expected_process_create_time'])>0,'Exact lifetime required')
    require(v['qualification_only'] is True and v['acknowledge_definition_only'] is True
            and v['message_policy']=='vendor_default','Explicit definition-only qualification required')
    require(type(v['owner_setup_native_id']) is int and 0<v['owner_setup_native_id']<2**31,'Actual owner ID required')
    for k,x in v.items():
        if k.endswith('_sha256'):require(type(x) is str and re.fullmatch('[0-9a-f]{64}',x),'Exact SHA required')
        if k.endswith('_path'):require(type(x) is str and Path(x).is_absolute(),'Explicit absolute path required')
    for k in ('expected_sw_configuration','expected_cam_configuration'):
        require(type(v[k]) is str and 0<len(v[k])<=1024,'Bounded configuration name required')
    for key,wanted in [('expected_axis_native',[0.,0.,-1.]),('expected_origin_native',[0.,0.,0.])]:
        value=v[key];require(type(value)is list and len(value)==3 and all(type(x)in(int,float)and math.isfinite(x)for x in value)and value==wanted,'Explicit bounded -Z zero-origin frame required')
    spec=_input(v['sketch_spec']);require(spec['plane_axis']=='Z' and spec['profile']['kind']=='circle','One model-Z circle required')
    require(0<number(v['depth_native'])<=100,'Positive native depth <=100 required')
    require(Path(v['expected_document_path']).suffix.lower()==Path(v['original_document_path']).suffix.lower()=='.sldprt','Native part paths required')
    require(canonical(v['expected_document_path'])!=canonical(v['original_document_path']),'Protected original cannot be target')
    return spec


def clean(r):
    require(shared.event_health(r['messages'],active=False)==0,'Clean closed event transport required')
    require(not any(k in r for k in ('issue','cleanup_error','runtime_error')),'No unresolved receipt issue allowed')


def prepare(v):
    spec=shape(v); pins=[]
    for path,sha in [('expected_document_path','expected_source_sha256'),('original_document_path','original_source_sha256'),('native_geometry_path','native_geometry_sha256')]:
        pins.append(shared.file_pin(v[path],v[sha]))
    require(not Path(v['expected_document_path']).samefile(v['original_document_path']),'Separate physical working copy required')
    setup,sp=read_pin(v['setup_receipt_path'],v['setup_receipt_sha256']);saved,svp=read_pin(v['setup_save_receipt_path'],v['setup_save_receipt_sha256']);sketch,kp=read_pin(v['sketch_receipt_path'],v['sketch_receipt_sha256']);pins.extend([sp,svp,kp])
    require(setup.get('status')=='review_required' and setup.get('phase')=='finished'
            and setup.get('operation')=='setup' and setup.get('readback_verified') is True
            and setup.get('native_call_returned') is True and setup.get('model_saved') is False,'Successful existing setup creation required');clean(setup)
    caps_data=validate_saved_caps(v,spec,sketch,pins) if saved_caps(v) else None
    setup_source_sha=v['caps_saved_sha256'] if caps_data else v['original_source_sha256']
    before,after=setup['before'],setup['after']
    require(same_path(before['document']['path'],v['expected_document_path'])
            and before['saved_file_sha256']==setup_source_sha,'Exact source-to-working setup lineage required')
    require(before['feature_setups']==[] and before['operation_counts']==[] and before['document']['needs_save'] is False,'Setup must start from clean empty CAM')
    require(same_path(after['document']['path'],v['expected_document_path']) and after['saved_file_sha256']==setup_source_sha,'Setup must preserve original working bytes')
    require(len(after['feature_setups'])==1 and after['operation_counts'] in ([],[0]),'Exactly one empty setup required')
    owner=after['feature_setups'][0]
    require(setup.get('new_setup_native_id')==owner['native_id']==v['owner_setup_native_id']
            and owner['feature_count']==0 and owner['axis_native']==v['expected_axis_native']
            and owner['origin_native']==v['expected_origin_native'],'Exact selected -Z zero-origin setup required')
    require(saved.get('status')=='review_required' and saved.get('phase')=='finished' and saved.get('action')=='save'
            and saved.get('machine_kind')=='mill_qualification' and saved.get('save_readback_verified') is True
            and saved.get('native_return_type')=='int' and type(saved.get('native_return_value')) is int
            and saved['native_return_value']==0,'Successful existing zero-op setup Save required');clean(saved)
    final=saved['final_state'];save_before=deepcopy(saved['before'])
    require(save_before.pop('machine_kind',None)=='mill_qualification' and save_before.pop('process_id',None)==v['process_id'],'Saved setup belongs to exact process and MILL scope')
    require(save_before==after,'Save baseline must match exact created setup')
    require(final['feature_setups']==after['feature_setups'] and final['operation_counts']==after['operation_counts']
            and final['document']['needs_save'] is False and final['saved_file_sha256']==v['expected_source_sha256']
            and same_path(final['document']['path'],v['expected_document_path']),'Exact saved empty setup binding required')
    if not caps_data:
        require(sketch.get('status')=='ok' and sketch.get('phase')=='finished' and sketch.get('native_readback_verified') is True
                and sketch.get('saved') is False and sketch.get('CAD_solid_edit_attempted') is False and sketch.get('CAM_calls')==0,'Successful sketch-only receipt required')
        for state in (sketch['before'],sketch['after']):
            require(same_path(state['path'],v['expected_document_path']) and state['saved_file_sha256']==v['expected_source_sha256']
                    and state['pid']==v['process_id'] and state['spec']==spec,'Exact sketch source/spec/PID required')
        require(sketch['before']['needs_save'] is False and sketch['after']['needs_save'] is True,'Exact known sketch dirty transition required')
        require(len(sketch['before']['solids'])==len(sketch['after']['solids'])==1 and _same_bodies(sketch['before']['solids'],sketch['after']['solids']),'One unchanged solid fingerprint required')
    receipt=Path(v['receipt_path']);require(receipt.suffix.lower()=='.json' and receipt.parent.is_dir() and not receipt.exists() and not receipt.is_symlink(),'Fresh JSON receipt required')
    marker=Path(v['expected_document_path']).parent/('pocket_definition_'+_digest(dict(scope=SCOPE,target=canonical(v['expected_document_path']),sketch=spec['sketch_name']))+'.json')
    require(not marker.exists(),'This target/sketch feature attempt is consumed; no replay')
    require(canonical(receipt) not in {canonical(p['path'])for p in pins}|{canonical(marker)},'Output aliases protected evidence')
    return dict(request=deepcopy(v),spec=spec,pins=pins,setup=deepcopy(owner),sketch=sketch,receipt=receipt,marker=marker,consumed=False,caps_data=caps_data)


def preflight(tlb):
    cls=_interface_class('ICWSetup',tlb);methods=[m for m in cls._methods_ if m.name=='CreateMillFeature2'];require(len(methods)==1,'One public factory required');m=methods[0]
    args=(c_long,BSTR,VARIANT_BOOL,c_double,VARIANT_BOOL,VARIANT_BOOL,VARIANT_BOOL,VARIANT_BOOL,c_double,c_long,VARIANT_BOOL,c_long,c_long,POINTER(POINTER(IDispatch)))
    require(m.restype is HRESULT and m.idlflags[0]==8 and m.argtypes==args and tuple(x[0]for x in m.paramflags)==(1,)*13+(10,),'Exact public CreateMillFeature2 ABI required')
    # Metadata-only compatibility for every interface reached by the shared inventory.
    from scripts.sw_cam_process_import_recovery import preflight as inventory_preflight
    inventory_preflight(tlb)
    specs=[('ICWFeature','_get_Axis',2,(POINTER(VARIANT),),(10,),True),
           ('ICWFeature','GetOwner',16,(POINTER(POINTER(IDispatch)),),(10,),False),
           ('ICWFeature','_get_Suppressed',5,(POINTER(VARIANT_BOOL),),(10,),True),
           ('ICWMillFeature','IGetIslandCount',26,(POINTER(c_long),),(10,),False),
           ('ICWMillFeature','_get_Depth',9,(POINTER(c_double),),(10,),True),
           ('ICWMillFeature','IGetTaperAngle',13,(POINTER(c_double),),(10,),False)]
    for owner,name,dispid,args,flags,prop in specs:
        cls=_interface_class(owner,tlb);matches=[m for c in cls.__mro__ for m in c.__dict__.get('_methods_',[])if m.name==name]
        require(len(matches)==1,'Unique public scalar getter required: '+name);m=matches[0]
        require(m.restype is HRESULT and m.idlflags[0]==dispid and m.argtypes==args
                and tuple(x[0]for x in m.paramflags)==flags and ('propget'in m.idlflags)==prop,'Scalar getter ABI differs: '+name)
    return dict(interface='ICWSetup',method='CreateMillFeature2',dispid=8,auto_detect_islands=True,application_calls=0)


def same_inventory(a,b):
    aa,bb=deepcopy(a),deepcopy(b); ar=aa.pop('sw_reference');br=bb.pop('sw_reference')
    return aa==bb and ar['feature_tree']==br['feature_tree'] and _same_bodies(ar['solids'],br['solids'])


def verify_delta(before,after,header,v):
    require(before['feature_count']==before['operation_count']==before['generated_operation_count']==before['total_record_count']==0,'Empty pre-feature inventory required')
    fid=header['native_id'];actual=deepcopy(after);rows=actual['features'];require(len(rows)==1 and rows[0]['native_id']==fid and rows[0]['setup_native_id']==v['owner_setup_native_id'],'One exact new feature required')
    require(header['owner_setup_native_id']==v['owner_setup_native_id'] and header['volume_type']==2
            and header['suppressed'] is False and header['axis_native']==v['expected_axis_native']
            and native_depth_close(header['depth_native'],v['depth_native']) and header['depth_native']>0
            and header['island_count']==4,'Pocket scalar definition differs')
    require(actual['operation_count']==actual['generated_operation_count']==actual['total_record_count']==0,'Creation unexpectedly added operations or paths')
    actual['features']=[];actual['feature_count']=0
    require(len(actual['feature_setups'])==1 and actual['feature_setups'][0]['feature_ids']==[fid],'Exact one-feature membership required')
    actual['feature_setups'][0]['feature_ids']=[]
    require(same_inventory(before,actual),'Unrequested inventory/CAD delta')
    return dict(new_feature_native_id=fid,exact_owner=True,requested_depth_readback=True,island_count_readback=4,
                depth_comparison=dict(requested_native=v['depth_native'],observed_native=header['depth_native'],
                                      absolute_tolerance_native=TOL_NATIVE,relative_tolerance=0,
                                      native_units_verified=False),
                definition_only=True,island_geometry_verified=False,physical_depth_verified=False,
                association_verified=False,production_qualified=False)

class Context(shared.ImportContext):
    """Reuse identity/events/file guard and bounded inventory, never import dispatch."""
    def start(self):
        self.stack.enter_context(solidworks_operation_lock(timeout_seconds=1,process_id=self.v['process_id']))
        self.verify_files();self.expected=self.identity()
        wanted_dirty=self.data.get('initial_dirty',False) if saved_caps(self.v) else True
        require(self.expected['needs_save'] is wanted_dirty,'Exact initial saved/sketch dirty state required')
        require(self.sw_configuration==self.v['expected_sw_configuration'],'Exact CAD configuration required')
        addin=_member(self.sw,'GetAddInObject',self.clsid);require(addin is not None,'CAM must already be loaded')
        self.app=_typed(_member(addin,'GetCWApp'),'ICWApp4',self.tlb)
        require(self.identity()==self.expected,'Bootstrap changed document')
        self.session=CamMessageSession(self.app,self.tlb);self.stack.enter_context(self.session);self.check_events()
        self.verify_sketch()
        self.r['document_before']=deepcopy(self.expected);self.persist()

    def verify_sketch(self):
        if saved_caps(self.v):return verify_saved_caps_sketch(self)
        with self.guard() as guard:
            observed,model,_=guard._observe(lambda:sketch_snapshot(self.sw,self.v['process_id'],self.v['expected_document_path'],self.data['spec']))
            expected=self.data['sketch']['after']
            a,b=deepcopy(observed),deepcopy(expected);sa,sb=a.pop('solids'),b.pop('solids')
            require(a==b and _same_bodies(sa,sb),'Actual sketch/CAD state differs from pinned creation receipt')
            feature=guard.read(model,'FeatureByName',self.data['spec']['sketch_name'])
            require(feature is not None and guard.read(feature,'GetTypeName2')=='ProfileFeature','Exact profile sketch required')
            sketch=guard.read(feature,'GetSpecificFeature2')
            actual=guard._observe(lambda:_read_sketch(self.sw,sketch,self.data['spec']))
            require(actual==self.data['sketch']['sketch_readback'],'Actual analytic circle differs from creator readback')
            self.r['circle_readback']=deepcopy(actual);guard._boundary()

    def capture_basic(self,label):
        state=self.capture(label,empty=False)
        require(state['cam_configuration_name']==self.v['expected_cam_configuration']
                and state['associated_sw_configuration']==self.v['expected_sw_configuration'],'Exact CAM/CAD binding required')
        require(len(state['feature_setups'])==1 and state['feature_setups'][0]['native_id']==self.v['owner_setup_native_id']
                and state['feature_setups'][0]['axis_native']==self.v['expected_axis_native']
                and state['feature_setups'][0]['origin_native']==self.v['expected_origin_native'],'Exact one -Z zero-origin setup required')
        return state

    def create(self,pending,returned):
        with self.guard() as guard:
            doc=guard.typed(guard.read(self.app,'IGetActiveDoc'),'ICWDoc3')
            machine=guard.typed(guard.read(guard.typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
            setups=shared._items(guard.read(machine,'IGetEnumSetups'),guard.typed,guard.read,8)
            require(len(setups)==1 and _object_id(doc,setups[0],guard.read)==self.v['owner_setup_native_id'],'One exact current owner required')
            setup=guard.typed(setups[0],'ICWSetup')
            def invoke():
                self.r.update(native_call_attempted=True,phase='CreateMillFeature2');self.persist()
                value=_member(setup,'CreateMillFeature2',0,self.data['spec']['sketch_name'],False,float(self.v['depth_native']),False,False,False,False,0.,-1,True,0,0)
                returned(value);return value
            raw=guard.dispatch_once(invoke,persist_pending=pending)
        self.r['dispatch_guard']=guard.summary();self.persist()
        require(raw is not None and type(raw) not in (int,float,bool,str,bytes,list,tuple),'Non-scalar returned native feature required')
        if saved_caps(self.v):adopt_created_document(self)
        with self.guard() as guard:
            doc=guard.typed(guard.read(self.app,'IGetActiveDoc'),'ICWDoc3')
            base=guard.typed(raw,'ICWFeature');mill=guard.typed(raw,'ICWMillFeature')
            fid=_object_id(doc,base,guard.read);require(type(fid) is int and fid>0,'Actual native feature ID required')
            self.r['new_feature_native_id']=fid;self.persist()
            owner=_object_id(doc,guard.read(base,'GetOwner'),guard.read)
            h=dict(native_id=fid,owner_setup_native_id=owner,suppressed=guard.read(base,'Suppressed'),
                   axis_native=_vector(guard.read(base,'Axis')))
            self.r['feature_header']=h;self.persist()
            for name,key in [('VolumeType','volume_type'),('IGetIslandCount','island_count')]:
                value=guard.read(mill,name);require(type(value) is int,'Strict native integer: '+name);h[key]=value;self.persist()
            for name,key in [('Depth','depth_native'),('IGetTaperAngle','taper_angle_native')]:h[key]=number(guard.read(mill,name))
            require(h['taper_angle_native']==0.0,'Unexpected tapered feature')
            guard._boundary()
        self.r['feature_header']=deepcopy(h);self.persist();return h


def revoke(r,error):
    r.update(status='uncertain' if r.get('dispatch_claimed') else 'error',phase='finished',runtime_error=_error(error))
    for key in FLAGS:r[key]=False
    _write_receipt(Path(r['receipt_path']),r);return r


def create_one(sw,clsid,tlb,v,*,runtime_check=lambda:None,prepared=None,_context_factory=Context):
    data=prepared if prepared is not None else prepare(v)
    require(data.get('consumed') is False and data.get('request')==v,'One unchanged prepared bundle required')
    data['consumed']=True
    for p in data['pins']:require(_file_hash(p['path'])==p['sha256'],'Prepared evidence changed before dispatch context')
    abi=preflight(tlb);pins=data['pins']
    for p in (Path(__file__),Path(tlb)):
        if p.is_file():pins.append(shared.file_pin(str(p),_file_hash(p)))
    r=dict(scope=SCOPE,status='running',phase='prepared',request=deepcopy(v),receipt_path=str(data['receipt']),
           marker_path=str(data['marker']),evidence_pins=deepcopy(pins),abi=abi,dispatch_claimed=False,
           native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,
           auto_detect_islands_requested=True,definition_only=True,geometry_unqualified=True,
           island_geometry_verified=False,physical_depth_verified=False,feature_association_verified=False,
           machining_eligible=False,production_qualified=False,Save_attempted=False,GOP_attempted=False,
           GTP_attempted=False,AFR_attempted=False,Import_attempted=False,model_saved=False,
           island_geometry_getter_attempted=False,automatic_replay=False)
    for key in FLAGS:r[key]=False
    def persist():_write_receipt(data['receipt'],r)
    _write_receipt(data['receipt'],r,create=True);ctx=None
    try:
        runtime_check();ctx=_context_factory(sw,clsid,tlb,v,data,r,persist,runtime_check);ctx.start()
        before=ctx.capture_basic('before');confirmed=ctx.capture_basic('before_confirmation')
        require(same_inventory(before,confirmed),'Pre-feature inventory changed')
        require(before['feature_count']==before['operation_count']==before['generated_operation_count']==before['total_record_count']==0,'Only empty one-setup CAM admitted')
        def pending():
            r.update(dispatch_claimed=True,native_dispatch_pending=True,phase='CreateMillFeature2_pending')
            _write_receipt(data['marker'],dict(scope=SCOPE,request_digest=_digest(v),receipt_path=str(data['receipt']),source_sha256=v['expected_source_sha256'],automatic_replay=False),create=True);persist()
        def returned(value):
            r.update(native_call_returned=True,native_dispatch_pending=False,native_return_type=type(value).__name__,native_return_nonnull=value is not None,phase='CreateMillFeature2_returned');persist()
        header=ctx.create(pending,returned)
        after=ctx.capture_basic('after');r['definition_proof']=verify_delta(before,after,header,v)
        final=ctx.capture_basic('after_confirmation');require(same_inventory(after,final),'Post-feature inventory changed')
        verify_delta(before,final,header,v);ctx.verify_sketch();ctx.verify_owned();ctx.verify_files();ctx.close();runtime_check()
        require(ctx.identity()==ctx.expected,'Owned document changed during cleanup')
        for p in pins:require(_file_hash(p['path'])==p['sha256'],'Protected file changed after cleanup')
        require(shared.event_health(r['messages'],active=False)==0,'Any CAM event rejects definition acceptance')
        r.update(status='definition_only',phase='finished',reason='FOUR_ISLAND_COUNT_AND_SCALAR_DEFINITION_OBSERVED_GEOMETRY_AND_MACHINING_UNQUALIFIED')
        for key in FLAGS:r[key]=True
    except Exception as error:
        r.update(status='uncertain' if r['dispatch_claimed'] else 'error',failed_phase=r['phase'],phase='finished',issue=_error(error),reason=str(error))
        for key in FLAGS:r[key]=False
    finally:
        if ctx is not None:
            try:ctx.close()
            except Exception as error:
                r.update(status='uncertain' if r['dispatch_claimed'] else 'error',cleanup_error=_error(error))
                for key in FLAGS:r[key]=False
        r['phase']='finished';persist()
    return r

def batch_payloads(batch, names):
    require(batch.get('status') == 'success' and [x.get('name') for x in batch.get('results', [])] == names,
            'Exact successful native batch order required')
    out=[]
    for row in batch['results']:
        require(row.get('outcome', {}).get('status') == 'success' and row['result'].get('isError') is False,
                'Successful native row required')
        payloads=[x['parsed_json'] for x in row['result']['content'] if type(x.get('parsed_json')) is dict]
        require(len(payloads)==1,'One parsed native payload required');out.append(payloads[0])
    return out


def validate_saved_caps(v, spec, sketch, pins):
    records={}
    for name in ('caps','caps_geometry','caps_save','caps_inventory','caps_export'):
        records[name],pin=read_pin(v[name+'_receipt_path'],v[name+'_receipt_sha256']);pins.append(pin)
    caps,geo,save,inventory,export=(records[k] for k in ('caps','caps_geometry','caps_save','caps_inventory','caps_export'))
    require(caps.get('scope')=='EXISTING_CAP_REMAINING_THREE_CONTINUATION_V1' and
            caps.get('status')=='caps_observed_ram_only' and caps.get('phase')=='finished' and
            caps.get('completed_count')==4 and caps.get('adopted_count')==1 and
            all(caps.get(k)is True for k in ('readback_verified','source_unchanged','selection_cleanup_verified')) and
            caps.get('native_dispatch_pending') is False and caps.get('model_saved') is False and caps.get('CAM_calls')==0,
            'Completed four-cap native definition required')
    cq=caps['source_request']
    require(cq['process_id']==v['process_id'] and cq['expected_process_creation_time']==v['expected_process_create_time'] and
            same_path(cq['expected_document_path'],v['expected_document_path']) and
            same_path(cq['protected_document_path'],v['original_document_path']) and
            cq['protected_source_sha256']==v['original_source_sha256'] and cq['expected_configuration']==v['expected_sw_configuration'],
            'Native cap owner/source binding differs')
    require([x['index'] for x in caps['actions']]==[1,2,3] and
            all(x['attempted'] is True and x['returned_object'] is True and x['pending'] is False and x['readback_verified'] is True for x in caps['actions']),
            'Exact completed remaining-cap sequence required')
    require(caps['profiles_after']==caps['preflight_profiles'] and caps['after']['needs_save'] is True,
            'Final native cap profiles/dirty state differ')
    require(geo.get('scope')=='FOUR_CAM_MANUFACTURING_CAP_STEP_PROOF_V1' and geo.get('passed') is True and
            geo.get('stage')=='FINISHED' and geo.get('inputs_unchanged') is True and
            geo['proof'].get('mode')=='full' and all(geo['proof'].get(k)is True for k in ('passed','whole_body_proof','local_proof')) and
            geo['proof']['top_profiles'].get('passed') is True and len(geo['proof']['top_profiles']['faces'])==4 and
            geo.get('boolean_fuzzy_mm')==0 and geo.get('healing_applied') is False and geo.get('residual_volume_waiver') is False,
            'Accepted full cap Boolean/top-profile proof required')
    require(same_path(geo['inputs']['candidate']['path'],v['native_geometry_path']) and
            geo['inputs']['candidate']['sha256']==v['native_geometry_sha256'],'Exact proved candidate STEP required')
    for pin in list(geo['inputs'].values())+[geo['module']]+geo['reused_sources']:
        pins.append(shared.file_pin(pin['path'],pin['sha256']))
    exported=batch_payloads(export,['solidworks_connect','solidworks_continue_existing_sketch_caps','solidworks_export_active','solidworks_inspect_open_documents'])
    native_copy=deepcopy(exported[1]);native_copy.pop('runtime_identity',None)
    require(native_copy.pop('process_id',None)==v['process_id'],'Exported cap payload owner differs')
    require(native_copy==caps,'Actual export must follow the exact completed cap result')
    e=exported[2]
    require(e.get('status')=='ok' and e.get('success') is True and e.get('format')=='step' and
            e.get('process_id')==v['process_id'] and same_path(e['document']['path'],v['expected_document_path']) and
            same_path(e['output_path'],v['native_geometry_path']),'Native STEP export binding differs')
    saved=batch_payloads(save,['solidworks_connect','solidworks_inspect_open_documents','solidworks_save_document','solidworks_inspect_open_documents'])
    s=saved[2]
    require(s.get('status')=='ok' and s.get('success') is True and s.get('save_referenced') is False and
            s.get('process_id')==v['process_id'] and same_path(s['document']['path'],v['expected_document_path']),
            'Actual single-document CAD Save required')
    for observed,dirty in ((saved[1],True),(saved[3],False)):
        require(observed.get('process_id')==v['process_id'] and observed.get('document_count')==1 and
                len(observed['documents'])==1 and same_path(observed['active_document']['path'],v['expected_document_path']) and
                same_path(observed['documents'][0]['path'],v['expected_document_path']) and observed['documents'][0]['needs_save'] is dirty,
                'Exact native CAD Save dirty transition required')
    require(inventory.get('process_id')==v['process_id'] and inventory.get('status')=='review_required' and
            inventory.get('phase')=='finished' and inventory.get('readback_verified') is True and
            inventory.get('inventory_read_complete') is True and inventory.get('mutation_attempted') is False,
            'Saved cap zero-CAM read authority required');clean(inventory)
    for observed in (inventory['before'],inventory['after']):
        require(same_path(observed['document']['path'],v['expected_document_path']) and observed['document']['needs_save'] is False and
                observed['saved_file_sha256']==v['caps_saved_sha256'] and observed['features']==[] and
                observed['feature_setups']==[] and observed['operation_setups']==[] and observed['operation_counts']==[] and observed['operation_count']==0,
                'Exact saved cap SHA and empty CAM required')
        ref=observed['sw_reference']
        require(ref['feature_tree']==caps['after']['features'] and _same_bodies(ref['solids'],caps['after']['solids']),
                'Saved cap CAD fingerprint differs from completed native result')
    require(sketch.get('status')=='ok' and sketch.get('native_readback_verified') is True and
            sketch.get('CAM_calls')==0 and sketch['after']['spec']==spec and sketch['before']['spec']==spec,
            'Historical circle geometry specification required')
    return dict(baseline=deepcopy(inventory['after']['sw_reference']),historical_circle_role='geometry_spec_only',
                caps_saved_sha256=v['caps_saved_sha256'],full_geometry_proof_pin=dict(path=v['caps_geometry_receipt_path'],sha256=v['caps_geometry_receipt_sha256']))


def adopt_created_document(ctx):
    """Observe only the dirty flag change after this consumed Create; never set it."""
    ctx.verify_files();ctx.check_events()
    before=deepcopy(ctx.expected);actual=ctx.identity()
    ctx.r['post_create_document_observation']=dict(before=before,after=deepcopy(actual));ctx.persist()
    require(before['needs_save'] is False and type(actual.get('needs_save')) is bool and
            actual==dict(before,needs_save=actual['needs_save']),'Create changed more than the observed dirty flag')
    ctx.expected=actual;ctx.verify_files();ctx.check_events();ctx.persist()


def verify_saved_caps_sketch(ctx):
    from scripts import sw_cam_profile_sketch as profile
    baseline=ctx.data['caps_data']['baseline']
    spec=ctx.data['spec'];record={}
    ctx.r.setdefault('saved_caps_sketch_checks',[]).append(record);ctx.persist()
    require(len(ctx.r['saved_caps_sketch_checks'])<=2,'Bounded inline sketch verification required')
    def capture(label):
        with ctx.guard() as g:
            state,model,_=g._observe(lambda:sketch_snapshot(ctx.sw,ctx.v['process_id'],ctx.v['expected_document_path'],spec))
            record[label]=dict(snapshot=deepcopy(state));ctx.persist()
            require(state['pid']==ctx.v['process_id'] and same_path(state['path'],ctx.v['expected_document_path']) and
                    state['saved_file_sha256']==ctx.v['expected_source_sha256'] and state['needs_save'] is ctx.expected['needs_save'] and
                    state['features']==baseline['feature_tree'] and _same_bodies(state['solids'],baseline['solids']),
                    'Current saved cap CAD baseline differs')
            f=g.read(model,'FeatureByName',spec['sketch_name'])
            require(f is not None and g.read(f,'GetTypeName2')=='ProfileFeature' and g.read(f,'IsSuppressed') is False,
                    'Exact unsuppressed existing circle required')
            raw=g.read(f,'GetSpecificFeature2');diagnostic={};record[label]['native_diagnostic']=diagnostic;ctx.persist()
            actual=g._observe(lambda:_read_sketch(ctx.sw,raw,spec,diagnostic=diagnostic))
            def plane():
                inverse=profile.call(raw.ModelToSketchTransform,'Inverse');profile._rigid_transform(inverse)
                mu=profile.call(ctx.sw,'GetMathUtility');origin=profile._point(mu,[0.,0.,0.],inverse);tip=profile._point(mu,[0.,0.,1.],inverse)
                return dict(origin_m=origin,normal=[b-a for a,b in zip(origin,tip)])
            frame=g._observe(plane);record[label].update(circle_readback=actual,sketch_plane_geometry=frame);ctx.persist()
            require(abs(frame['origin_m'][2]-spec['plane_offset_mm']/1000)<=profile.TOL_M and
                    abs(abs(frame['normal'][2])-1)<=1e-9 and all(abs(x)<=1e-9 for x in frame['normal'][:2]),
                    'Actual circle plane geometry differs')
            g._boundary();return record[label]
    before=capture('before');after=capture('after')
    require(same_saved_sketch_capture(before,after),'Inline existing-circle read changed current state')
    ctx.r['circle_readback']=deepcopy(after['circle_readback']);record['readback_verified']=True;ctx.persist()


def same_saved_sketch_capture(before,after):
    a,b=deepcopy(before),deepcopy(after);sa=a['snapshot'].pop('solids');sb=b['snapshot'].pop('solids')
    return a==b and _same_bodies(sa,sb)
