"""Read-only fast definition candidate; retained CAM graph with full CAD boundaries.

Native parity and timing are unqualified. There is no mutation provider, write
lease, atomic snapshot or exclusion of external transient A-to-B-to-A changes.
"""
from copy import deepcopy
from time import perf_counter
from scripts import sw_cam_pocket_definition_capture_v2 as parent
from scripts import sw_cam_prebound_inventory as prebound
from scripts import sw_cam_read_batch_guard as retained
from scripts.sw_cam import _member
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_thread import _file_hash

require=parent.require
SCOPE='CURRENT_POCKET_FAST_DEFINITION_READ_V1'
READS=frozenset({'GetDocType','GetActiveConfigurationName','GetActiveConfiguration','SWConfigurationName','ConfigurationName','MachType','GetCWObjectID','IGetEnumSetups','IGetEnumFeatures','Axis','GetReferencePosition','Suppressed','FeatureName','VolumeType','SubType','IGetEnumOpSetups','IGetEnumOperations','OpernType','GetIsToolpathGenerated','IGetAllFeatures','IGetEnumToolpaths','RecordCount','IGetTool','IsMillTool','ToolType','CutDiameter','Protrusion','Count','Item','GetOwner','IGetIslandCount','Depth','IGetTaperAngle'})
INTERFACES=frozenset({'ICWConfiguration','ICWDispatchCollection','ICWBaseSetup','ICWSetup','ICWFeature','ICWMillFeature','ICWBaseOpSetup','ICWOperation','ICWMillOperation','ICWToolpath','ICWTool'})

class InventoryReadBatch(retained.ScopedCamReadBatch):
    def reject(self,ok,message):
        if not ok:
            self._invalid=True;self._completed=False
            raise ValueError(message)
    def read(self,obj,name,*args):
        self.reject(type(name)is str and name in READS,'Outside fixed retained inventory/header getters')
        for arg in args:self.reject(type(arg)is int or id(arg)in self._known_objects,'Argument outside retained inventory graph')
        return self._observe_read(obj,'getter',lambda:_member(obj,name,*args))
    def typed(self,obj,name):
        self.reject(type(name)is str and name in INTERFACES,'Outside fixed retained inventory/header interfaces')
        return self._observe_read(obj,'qi',lambda:_typed(obj,name,self.typelib_path))


def check_cad(guard,sw,context,observed,diagnostic):
    """Same immutable body, raw tree and analytic circle checks as the parent."""
    v=context['request']
    actual,model,_=guard._observe(lambda:parent._snapshot(sw,v['process_id'],v['expected_document_path'],context['spec']))
    expected=deepcopy(context['current_sketch_baseline']);expected['needs_save']=observed['document']['needs_save'];a,b=deepcopy(actual),deepcopy(expected);sa,sb=a.pop('solids'),b.pop('solids')
    require(a==b and parent._same_bodies(sa,sb),'CAD/sketch snapshot differs from immutable creator baseline')
    diagnostic['actual_sketch_snapshot']=actual
    sketch_feature=guard.read(model,'FeatureByName',context['spec']['sketch_name'])
    require(guard.read(sketch_feature,'GetTypeName2')=='ProfileFeature','Exact analytic sketch required')
    sketch=guard.read(sketch_feature,'GetSpecificFeature2');profile=guard._observe(lambda:parent._read_sketch(sw,sketch,context['spec']))
    require(profile==(context['creator']['circle_readback'] if parent.creator.saved_caps(v) else context['sketch']['sketch_readback']),'Native sketch circle differs')
    return actual


def capture(sw,clsid,tlb,context,check,diagnostic):
    """Same full payload; only fixed CAM inventory/header reads use retention."""
    diagnostic={} if diagnostic is None else diagnostic
    require(not diagnostic,'Fresh fast-definition diagnostic required')
    diagnostic.update(scope=SCOPE,capture_complete=False,native_parity_qualified=False,read_only=True,atomic_snapshot=False,transient_active_document_excursion_excluded=False,timing_seconds={})
    for path in (__file__,parent.__file__,prebound.__file__,prebound.parent.__file__,retained.__file__):
        rows=[p for p in context['pins']if parent.creator.same_path(p['path'],path)]
        require(len(rows)==1 and rows[0]['sha256']==_file_hash(path),'Exact fast-definition dependency pin required')
    observed=parent.identity(sw,context);v=context['request'];r=context['creator'];check()
    def owned():require(parent.identity(sw,context)==observed,'Definition context changed during capture')
    kwargs=dict(process_id=v['process_id'],expected_document=observed['document'],source_sha256=context['expected_source_sha256'],evidence_pins=context['pins'],verify_evidence=lambda:parent.verify_files(context),verify_owned_process=owned,check_events=check,evidence_pin_limit=128)
    batch=None;started=perf_counter()
    def timed(label,invoke):
        phase=perf_counter()
        try:return invoke()
        finally:diagnostic['timing_seconds'][label]=perf_counter()-phase
    try:
        with parent.ScopedCamDispatchGuard(sw,tlb,**kwargs)as guard:
            before=timed('before_cad',lambda:check_cad(guard,sw,context,observed,diagnostic.setdefault('before_cad',{})))
            phase=perf_counter()
            addin=guard.read(sw,'GetAddInObject',clsid);app=guard.typed(guard.read(addin,'GetCWApp'),'ICWApp4')
            doc=guard.typed(guard.read(app,'IGetActiveDoc'),'ICWDoc3');machine=guard.typed(guard.read(guard.typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
            diagnostic['timing_seconds']['bootstrap']=perf_counter()-phase
            def binding():
                kind=guard.read(doc,'GetDocType');mach=guard.read(machine,'MachType')
                require(type(kind)is int and kind==1 and type(mach)is int and mach==1,'Retained CAM document/machine differs')
                require(guard.read(doc,'GetActiveConfigurationName')==v['expected_cam_configuration'],'Retained CAM configuration differs')
            batch=InventoryReadBatch(sw,tlb,**kwargs,retained_objects=(doc,machine),verify_retained_binding=binding,max_native_calls=4096)
            phase=perf_counter()
            try:
                with batch:
                    state=prebound.capture_bound_inventory(doc,machine,batch,diagnostic.setdefault('inventory',{}),lambda d:None)
                    require(state['cam_configuration_name']==v['expected_cam_configuration'] and state['associated_sw_configuration']==v['expected_sw_configuration'],'Exact CAM/CAD configuration binding required')
                    baseline=deepcopy(context['expected_inventory']);baseline.pop('sw_reference');baseline.pop('all_solid_body_count')
                    for key in parent.OP_KEYS:baseline.pop(key)
                    current={k:deepcopy(value)for k,value in state.items()if k not in parent.OP_KEYS}
                    require(current==baseline,'Feature/setup/configuration definition differs from creator')
                    setups=parent.inventory._items(batch.read(machine,'IGetEnumSetups'),batch.typed,batch.read,1)
                    require(len(setups)==1 and parent._object_id(doc,setups[0],batch.read)==v['owner_setup_native_id'],'Exact feature owner required')
                    features=parent.inventory._items(batch.read(batch.typed(setups[0],'ICWBaseSetup'),'IGetEnumFeatures'),batch.typed,batch.read,1)
                    require(len(features)==1,'Exactly one native feature required')
                    header,feature=parent._feature_header(batch,doc,features[0]);require(header==r['feature_header'],'Feature header differs from definition receipt')
                batch.require_complete()
            finally:diagnostic['timing_seconds']['inventory_and_header']=perf_counter()-phase
            after=timed('after_cad',lambda:check_cad(guard,sw,context,observed,diagnostic.setdefault('after_cad',{})))
            a,b=deepcopy(before),deepcopy(after);sa,sb=a.pop('solids'),b.pop('solids')
            require(a==b and parent._same_bodies(sa,sb),'CAD/sketch body changed across retained inventory')
            guard._boundary()
        state.update(document=observed['document'],saved_file_sha256=context['expected_source_sha256'],selected_feature=header,operation_setup_count=len(state['operation_setups']),operation_counts=[x['operation_count']for x in state['operation_setups']],definition_authority=dict(scope=parent.SCOPE,recovery_receipt_sha256=context['evidence']['sha256'],save_receipt_sha256=context['save_pin']['sha256'],raw_creator_status=context['creator']['status'],saved_definition_binding_verified=True,persistence_verified=False,analytic_sketch_and_body_invariants_verified=True,island_geometry_verified=False,physical_depth_verified=False))
        if parent.creator.saved_caps(v) or context.get('origin_kind')=='creator':state['definition_authority']['origin_kind']=context['origin_kind']
        diagnostic.update(capture_complete=True,stage='complete',state=deepcopy(state),actual_sketch_snapshot=after)
        return state,dict(app=app,doc=doc,machine=machine,selected_feature=feature)
    finally:
        if batch is not None:diagnostic['retained_inventory']=batch.summary()
        diagnostic['elapsed_seconds']=perf_counter()-started
