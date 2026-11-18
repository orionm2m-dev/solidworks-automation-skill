"""Create one serial flat cutter and assign only a selected current Rough.
Reuse established factory/field/profile/holder primitives; no operation setters/GTP.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_current_pocket_pair_read as reader
from scripts import sw_cam_neck_tool_candidate as factory
from scripts import sw_cam_serial_flat_tool as serial
from scripts import sw_cam_serial_flat_profile as geometry
from scripts import sw_cam_exact_cutter_reuse as reuse
from scripts import sw_cam_guide_group_configuration as configuration
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _object_id,_file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_tool_geometry import read_full_mill_tool
from scripts.sw_cam_shared_holder_geometry import read_holder_recipe,check_holder_pins

require=reader.require
prior=factory.prior
SCOPE='CURRENT_POCKET_CREATE_ASSIGN_ONE_FLAT_TOOL_V1'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','expected_feature_native_id','expected_operation_native_ids','selected_operation_native_id','current_context_receipt_path','current_context_receipt_sha256','recipe_path','recipe_sha256','holder_file_path','holder_file_sha256','holder_recipe_path','holder_recipe_sha256','receipt_path','qualification_only','acknowledge_one_tool_creation','message_policy'}
ACCEPTANCE=('readback_verified','current_context_verified','inventory_delta_verified','parameter_delta_verified','runtime_unchanged')
ACTIONS={'AddNewTool3','SetFilePathForUserDefinedHolder','SetTool','SaveActiveDocument'}|{'property:'+n for n in factory.FIELD_ORDER}


def shape(v):
    require(type(v)is dict and set(v)==KEYS,'Exact one-tool current-pair request required')
    for k in ('process_id','expected_feature_native_id','selected_operation_native_id'):
        require(type(v[k])is int and 0<v[k]<2**31,'Strict positive identity required')
    ids=v['expected_operation_native_ids'];require(type(ids)is list and len(ids)==2 and all(type(x)is int and 0<x<2**31 for x in ids) and len(set(ids))==2 and v['selected_operation_native_id']==ids[0],'Only explicit Rough of ordered two-operation pair may be assigned')
    require(type(v['expected_process_create_time'])in(int,float) and reader.math.isfinite(v['expected_process_create_time']) and v['expected_process_create_time']>0,'Exact finite owned lifetime required')
    for k,x in v.items():
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact pinned SHA required')
    require(v['qualification_only']is True and v['acknowledge_one_tool_creation']is True and v['message_policy']=='vendor_default','Explicit one-tool qualification required')


def marker_path(v):
    return Path(v['expected_document_path']).parent/('current_pair_tool_'+_digest(dict(scope=SCOPE,target=reader.definition.creator.canonical(v['expected_document_path']),source_sha256=v['expected_source_sha256']))+'.json')


def prepare(v):
    from scripts import sw_cam_current_pocket_context as current
    shape(v);bundle=current.load_current_baseline(v)
    state=bundle['state'];rows=state['operations']
    require(len(rows)==2 and [r['native_id']for r in rows]==v['expected_operation_native_ids'] and [r['mill_operation_type']for r in rows]==[0,1],'Exact current Rough/Contour pair required')
    require(all(r['linked_feature_ids']==[v['expected_feature_native_id']] and r['suppressed']is False and r['toolpath_generated']is False and not r['toolpath_record_counts']for r in rows),'No existing toolpath may be affected')
    recipe,rp=reader.definition.read_pin(v['recipe_path'],v['recipe_sha256']);proposed=serial.validate_recipe(recipe)
    require(all(type(proposed[n])is float for n in geometry.KEYS-geometry.INTEGER_FIELDS),'Tool dimensional inputs must be explicit DOUBLE values')
    holder=read_holder_recipe(v['holder_file_path'],v['holder_file_sha256'],v['holder_recipe_path'],v['holder_recipe_sha256'])
    d=bundle['context'];pins=d['pins']
    for pin in [rp]+recipe['source_pins']+holder['pins']+[reader.shared.file_pin(p,_file_hash(p))for p in (__file__,current.__file__,factory.__file__,serial.__file__,geometry.__file__,reuse.__file__,prior.__file__)]:
        old=[x for x in pins if reader.definition.creator.same_path(x['path'],pin['path'])]
        require(not old or all(x['sha256']==pin['sha256']for x in old),'Conflicting current tool evidence pin')
        if not old:pins.append(pin)
    require(len(pins)<=64,'Existing complete guard pin bound exceeded')
    receipt=Path(v['receipt_path']);marker=marker_path(v)
    for path in (receipt,marker):
        require(path.is_absolute() and path.suffix.lower()=='.json' and path.parent.is_dir() and not path.exists() and not path.is_symlink(),'Fresh receipt and target/source consumed marker required; no replay')
        require(not any(reader.definition.creator.same_path(str(path),p['path'])for p in pins),'Output aliases pinned input')
    require(receipt!=marker,'Receipt and consumed marker must differ')
    reader.definition.verify_files(d)
    return dict(bundle=bundle,recipe=recipe,recipe_pin=rp,holder=holder,proposed=proposed,receipt=receipt,marker=marker,request=deepcopy(v),consumed=False)


def preflight(tlb):
    from ctypes import HRESULT,POINTER
    from comtypes.automation import IDispatch
    from scripts.sw_cam_comtypes import _interface_class
    audit=reader.preflight(tlb);audit['factory']=factory.audit_interfaces(tlb,audit['generated_pin'])
    cls=_interface_class('ICWMillOperation',tlb);methods=[m for m in cls._methods_ if m.name=='SetTool']
    require(len(methods)==1 and methods[0].restype is HRESULT and methods[0].argtypes==(POINTER(IDispatch),) and tuple(x[0]for x in methods[0].paramflags)==(1,),'Exact existing selected tool-assignment ABI required')
    audit['assignment']=dict(interface='ICWMillOperation',member='SetTool',dispid=methods[0].idlflags[0],native_calls=0)
    return audit


def verify_pair_delta(before,after,*,selected_id,new_tool_id=None):
    """Tool-only definition changes; selected SetTool defaults stay observations."""
    old,now=before['inventory'],after['inventory'];expected=deepcopy(old)
    require(type(now['document']['needs_save'])is bool,'Strict current dirty flag required')
    expected['document']['needs_save']=now['document']['needs_save']
    if new_tool_id is not None:
        matches=[r for r in now['operations']if r['native_id']==selected_id]
        require(len(matches)==1 and type(new_tool_id)is int and new_tool_id>0 and matches[0]['assigned_tool']['native_id']==new_tool_id,'Assignment must bind the actual separately created tool')
        for row in expected['operations']:
            if row['native_id']==selected_id:row['assigned_tool']=deepcopy(matches[0]['assigned_tool'])
        expected['unique_tool_count']=len({r['assigned_tool']['native_id']for r in expected['operations']})
    require(expected==now,'Tool action changed protected full inventory')
    require(len(before['parameters'])==len(after['parameters'])==2,'Both full parameter rows required')
    for a,b in zip(before['parameters'],after['parameters']):
        require(a['operation_native_id']==b['operation_native_id'],'Parameter operation order changed')
        if new_tool_id is None or a['operation_native_id']!=selected_id:require(a==b,'Unselected operation parameters/tool changed')
        else:
            for key in ('operation_native_id','operation_type','feature_native_id','levels'):
                require(a[key]==b[key],'SetTool changed protected operation levels/identity')
            require(b['tool']['generic']['native_id']==new_tool_id and b['read_complete']is True,'Complete assigned tool parameter row required')
    return dict(inventory_delta_verified=True,parameter_delta_verified=True,selected_automatic_defaults_observed=new_tool_id is not None,automatic_defaults_qualified=False,unselected_parameters_unchanged=True,operation_parameter_setters_attempted=False)


class Journal(prior.Journal):
    def marker_state(self):return dict(super().marker_state(),scope=SCOPE)
    def pending(self,label):
        require(label in ACTIONS,'Action outside exact new-tool/assignment/Save scope')
        super().pending(label)


class Backend:
    # These methods keep the previously qualified factory and field dispatches.
    create=factory.NativeBackend.create
    created_classification=factory.NativeBackend.created_classification
    field=factory.NativeBackend.field
    property=factory.NativeBackend.property
    candidate=factory.NativeBackend.candidate
    attach_holder=prior.NativeBackend.attach_holder
    batch=prior.NativeBackend.batch
    catalogue=prior.NativeBackend.catalogue
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check,abi):
        self.sw,self.clsid,self.typelib_path=sw,clsid,tlb
        self.args=deepcopy(v);self.data=data;self.bundle=data['bundle'];self.d=self.bundle['context']
        self.report,self.persist,self.runtime_check,self.abi=report,persist,runtime_check,abi
        self.loaded=dict(pins=self.d['pins'],generated_pin=abi['generated_pin'])
        self.ctx=self;self.new_id=self.new_tool=self.crib=None;self.old_holders={};self.session=None;self.closed=False
    def files(self):reader.definition.verify_files(self.d);check_holder_pins(self.data['holder'])
    def identity(self):return reader.definition.identity(self.sw,self.d)['document']
    def owned(self):require(self.identity()==self.expected_document,'Current owned document changed');self.runtime_check()
    def events(self,active=True):
        self.report['messages']=self.session.summary()
        require(reader.shared.event_health(self.report['messages'],active=active)==0,'Any CAM event requires uncertain stop')
    def guard(self):
        return ScopedCamDispatchGuard(self.sw,self.typelib_path,process_id=self.args['process_id'],expected_document=self.expected_document,source_sha256=self.d['expected_source_sha256'],evidence_pins=self.d['pins'],verify_evidence=self.files,verify_owned_process=self.owned,check_events=self.events)
    def boundary(self):
        self.runtime_check();self.owned();self.events();self.files()
    def refresh_dirty(self):
        actual=self.identity();expected=deepcopy(self.expected_document);expected['needs_save']=actual['needs_save']
        require(type(actual['needs_save'])is bool and actual==expected,'Native tool action changed document beyond dirty flag')
        self.expected_document=actual;self.boundary()
    def start(self):
        self.files();self.expected_document=self.identity();require(self.expected_document['needs_save']is False,'Clean saved current baseline required')
        addin=_member(self.sw,'GetAddInObject',self.clsid);require(addin is not None,'CAM must already be loaded')
        self.app=_typed(_member(addin,'GetCWApp'),'ICWApp4',self.typelib_path)
        require(self.identity()==self.expected_document,'Bootstrap changed current target')
        self.session=reader.CamMessageSession(self.app,self.typelib_path);self.session.__enter__();self.events()
        with self.guard()as g:
            doc=g.typed(g.read(self.app,'IGetActiveDoc'),'ICWDoc3');machine=g.typed(g.read(g.typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
            self.native=dict(doc=doc,machine=machine);self.doc=doc
            self.crib=g.typed(g.read(machine,'IGetToolcrib'),'ICWToolcrib4');self.save_app=g.typed(self.app,'ICWApp')
    def capture_current(self,label):
        self.report['phase']=label;diagnostic={};self.report.setdefault('captures',[]).append(dict(label=label,diagnostic=diagnostic));self.persist()
        state,native=reader.definition.capture(self.sw,self.clsid,self.typelib_path,self.d,self.events,diagnostic)
        self.native.update(native)
        self.doc=self.native['doc']
        out={};self.report['captures'][-1]['parameter_observation']=out
        with reader.ReadGuard(self.sw,self.typelib_path,process_id=self.args['process_id'],expected_document=self.expected_document,source_sha256=self.d['expected_source_sha256'],evidence_pins=self.d['pins'],verify_evidence=self.files,verify_owned_process=self.owned,check_events=self.events,generated_pin=self.abi['generated_pin'],report=self.report)as batch:
            reader.read_pair(deepcopy(state),native,state['operations'],batch,out,self.persist)
        value=dict(inventory=state,parameters=out['parameters']);self.report['captures'][-1]['observation']=deepcopy(value);self.persist();return value
    def initial_tools(self):
        rows=self.catalogue();self.initial_catalogue=rows;self.handles={}
        batch=self.batch(max_native_calls=prior.CATALOGUE_BATCH_CALLS)
        with batch:
            raw_tools=_items(batch.read(self.crib,'GetAllTools'),batch.typed,batch.read,prior.MAX_TOOLS)
            for raw in raw_tools:
                tool=batch.typed(raw,'ICWTool');tid=_object_id(self.doc,tool,batch.read);self.handles[tid]=tool
                self.old_holders[tid]=batch.typed(batch.read(tool,'IGetMillToolHolder'),'ICWMillToolHolder')
        batch.require_complete();require(list(self.handles)==[x['native_id']for x in rows],'Initial tool catalogue identity/order changed')
        return rows
    def full_existing(self,tid,label):
        tool=self.handles[tid];r=next(x for x in self.initial_catalogue if x['native_id']==tid)
        generic=dict(native_id=tid,is_mill_tool=True,native_read_complete=True,tool_type_raw=r['tool_type_raw'],cut_diameter_native=r['CutDiameter'],protrusion_native=r['Protrusion'])
        diag={};self.report.setdefault('existing_tool_reads',[]).append(dict(native_id=tid,label=label,diagnostic=diag))
        batch=self.batch(tool)
        with batch:
            require(_object_id(self.doc,tool,batch.read)==tid and batch.read(tool,'IsMillTool')is True,'Exact existing MILL tool required')
            full=read_full_mill_tool(tool,generic=generic,read=batch.read,typed=batch.typed,diagnostic=diag)
            identity={n:batch.read(tool,n)for n in sorted(factory.TEXT_FIELDS)}
        batch.require_complete();self.persist();return dict(native_id=tid,full_tool=full,identity=identity)
    def assign_selected(self,pending):
        # Same proved ICWMillOperation.SetTool primitive, rebound by current IDs.
        from comtypes.automation import IDispatch
        oid=self.args['selected_operation_native_id'];fid=self.args['expected_feature_native_id']
        with self.guard()as g:
            result=g.read(self.doc,'GetCWObjectFromID',3,oid);require(type(result)in(tuple,list)and len(result)==2 and result[1]is True,'Exact selected operation lookup required')
            raw=result[0];op=g.typed(raw,'ICWOperation');mill=g.typed(raw,'ICWMillOperation')
            require(_object_id(self.doc,op,g.read)==oid and g.read(mill,'OpernType')==0 and g.read(op,'Suppressed')is False and g.read(op,'GetIsToolpathGenerated')is False,'Only current ungenerated Rough can receive tool')
            links=[_object_id(self.doc,x,g.read)for x in _items(g.read(op,'IGetAllFeatures'),g.typed,g.read,2)]
            require(links==[fid] and _object_id(self.doc,self.new_tool,g.read)==self.new_id,'Selected feature/new tool binding differs')
            require(g.read(self.new_tool,'ToolType')==1 and prior.scalar_equal(g.read(self.new_tool,'CutDiameter'),self.data['proposed']['CutDiameter']) and prior.scalar_equal(g.read(self.new_tool,'Protrusion'),self.data['proposed']['Protrusion']),'Qualified new tool geometry changed')
            dispatch=g.read(self.new_tool,'QueryInterface',IDispatch)
            return g.dispatch_once(lambda:_member(mill,'SetTool',dispatch),persist_pending=pending)
    def adopt_context(self,new_context):
        self.d=new_context;self.loaded['pins']=new_context['pins'];self.args['expected_source_sha256']=new_context['expected_source_sha256']
        self.expected_document=deepcopy(self.expected_document);self.expected_document['needs_save']=False
    def save(self):
        self.boundary() # No file-holding guard survives Save.
        self.report['Save_attempted']=True;self.persist()
        return _member(self.save_app,'SaveActiveDocument')
    def close(self):
        if self.closed:return
        self.closed=True
        if self.session is not None:
            try:self.session.__exit__(None,None,None)
            finally:self.events(False)


def run_backend(backend,journal,data):
    from scripts import sw_cam_current_pocket_context as current
    r=journal.report;v=data['request'];target=data['proposed'];recipe=data['recipe'];holder=data['holder'];initial=None
    try:
        backend.start();initial=backend.capture_current('before')
        require(initial==dict(inventory=data['bundle']['state'],parameters=data['bundle']['parameters']),'Fresh full current pair differs from immediate baseline')
        r['before']=deepcopy(initial);catalogue=backend.initial_tools();r['initial_catalogue']=deepcopy(catalogue)
        same=[x['native_id']for x in catalogue if x['tool_type_raw']==1 and prior.scalar_equal(x['CutDiameter'],target['CutDiameter'])]
        assigned=list(dict.fromkeys(x['assigned_tool']['native_id']for x in initial['inventory']['operations']))
        observed={tid:backend.full_existing(tid,'before')for tid in dict.fromkeys(assigned+same)}
        r['protected_tools_before']={str(tid):observed[tid]for tid in assigned}
        r['duplicate_policy']=reuse.require_new_exact_cutter(catalogue,[observed[tid]for tid in same],recipe['identity'],recipe['target'],accepted_identity_aliases=recipe['accepted_identity_aliases']);journal.persist()
        new_id=backend.create(lambda:journal.pending('AddNewTool3'),lambda x:journal.returned('AddNewTool3',x,pointer=True))
        forbidden={x['native_id']for k in ('feature_setups','operation_setups','operations')for x in initial['inventory'][k]}|{v['expected_feature_native_id']}
        require(new_id not in forbidden,'Created tool collides with protected CAM object identity')
        classification=backend.created_classification();r['factory_classification']=classification
        require(type(classification['MillToolType'])is int and classification['MillToolType']==1 and type(classification['MillToolSubType'])is int and classification['MillToolSubType']==3 and prior.scalar_equal(classification['EndRadius'],0.),'Native flat BOTH zero-radius template required')
        factory.verify_catalogue(catalogue,backend.catalogue(),new_id)
        for name in factory.FIELD_ORDER:
            if name=='Protrusion':
                value=backend.attach_holder(holder['file_path'],lambda:journal.pending('SetFilePathForUserDefinedHolder'));journal.returned('SetFilePathForUserDefinedHolder',value)
                require(type(value)is int and value==0,'Strict holder reference HRESULT0 required');backend.refresh_dirty()
            before=backend.field(name);row=dict(property=name,before=before,requested=target[name],readback_verified=False);r.setdefault('field_readbacks',[]).append(row);journal.persist()
            if not prior.scalar_equal(before,target[name]):
                value=backend.property(name,target[name],lambda name=name:journal.pending('property:'+name));journal.returned('property:'+name,value)
                require(value is None,'Existing property dispatch must return None');backend.refresh_dirty()
            row['actual']=backend.field(name);require(prior.scalar_equal(row['actual'],target[name]),'Immediate new-tool property readback differs: '+name);row['readback_verified']=True;journal.persist()
        candidate=backend.candidate('configured');r['configured_candidate']=candidate;r['candidate_qualification']=geometry.verify_candidate(candidate,recipe,holder)
        configured=backend.capture_current('configured_unassigned');verify_pair_delta(initial,configured,selected_id=v['selected_operation_native_id']);factory.verify_catalogue(catalogue,backend.catalogue(),new_id)
        r['assignment_attempted']=True
        value=backend.assign_selected(lambda:journal.pending('SetTool'));journal.returned('SetTool',value);require(type(value)is int and value==0,'Strict selected SetTool HRESULT0 required');backend.refresh_dirty()
        after=backend.capture_current('assigned');r['after_assignment']=deepcopy(after);r['delta_proof']=verify_pair_delta(initial,after,selected_id=v['selected_operation_native_id'],new_tool_id=new_id)
        r['protected_tools_after']={str(tid):backend.full_existing(tid,'after_assignment')for tid in assigned};require(r['protected_tools_before']==r['protected_tools_after'],'Existing assigned tool/holder changed')
        require(backend.candidate('assigned')==candidate,'Assignment changed the new full tool profile')
        factory.verify_catalogue(catalogue,backend.catalogue(),new_id);journal.persist()
        def save():
            value=backend.save();journal.returned('SaveActiveDocument',value);return value
        saved=current.save_current_baseline(r,data['bundle'],after,capture=backend.capture_current,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,adopt_context=backend.adopt_context)
        r['current_context']=saved['payload'];r['model_saved']=True;journal.persist()
        final=backend.candidate('saved');require(final==candidate,'Save changed full new tool/holder profile');r['final_candidate']=final
        r['protected_tools_saved']={str(tid):backend.full_existing(tid,'saved')for tid in assigned};require(r['protected_tools_saved']==r['protected_tools_before'],'Save changed protected original tool/holder')
        factory.verify_catalogue(catalogue,backend.catalogue(),new_id)
        backend.close();backend.runtime_check();document=backend.identity();require(document==backend.expected_document,'Document changed during cleanup');backend.files()
        r['after_cleanup_identity']=dict(document=deepcopy(document),saved_file_sha256=backend.d['expected_source_sha256'])
        require(reader.shared.event_health(r['messages'],active=False)==0,'Clean closed message transport required')
        r.update(status='review_required',phase='finished',exact_one_tool_created=True,selected_assignment_verified=True,automatic_defaults_qualified=False,**{k:True for k in ACCEPTANCE})
    except Exception as error:r.update(status='uncertain'if r.get('mutation_attempted')else'error',failed_phase=r.get('phase'),phase='finished',issue=_error(error),reason=str(error),**{k:False for k in ACCEPTANCE})
    finally:
        try:backend.close()
        except Exception as error:r.update(status='uncertain'if r.get('mutation_attempted')else'error',cleanup_error=_error(error),**{k:False for k in ACCEPTANCE})
        r['phase']='finished';journal.persist()
    return r


def run_tool(sw,clsid,tlb,v,*,prepared=None,runtime_check=lambda:None,_backend_factory=Backend):
    data=prepared if prepared is not None else prepare(v)
    require(data.get('consumed')is False and data['request']==v,'Exact unconsumed preparation required');data['consumed']=True
    abi=preflight(tlb);d=data['bundle']['context']
    for pin in (abi['generated_pin'],reader.shared.file_pin(tlb,_file_hash(tlb))):
        if not any(reader.definition.creator.same_path(pin['path'],p['path'])for p in d['pins']):d['pins'].append(pin)
    require(len(d['pins'])<=64,'Complete mutation guard pin limit exceeded');reader.definition.verify_files(d);runtime_check()
    r=dict(scope=SCOPE,status='prepared',phase='prepared',request=deepcopy(v),source_path=v['expected_document_path'],initial_source_sha256=v['expected_source_sha256'],receipt_path=str(data['receipt']),current_baseline_receipt_pin=data['bundle']['receipt_pin'],recipe=data['recipe'],recipe_pin=data['recipe_pin'],holder_recipe=data['holder'],abi=abi,evidence_pins=deepcopy(d['pins']),actions={},mutation_attempted=False,assignment_attempted=False,model_saved=False,Save_attempted=False,save_readback_verified=False,GOP_attempted=False,GTP_attempted=False,Import_attempted=False,operation_parameter_setters_attempted=False,TechDB_write_attempted=False,automatic_replay=False,physical_tool_identity_verified=False,physical_collet_seating_verified=False,units_verified=False,production_qualified=False,**{k:False for k in ACCEPTANCE})
    _write_receipt(data['receipt'],r,create=True);journal=Journal(r,data['receipt'],data['marker']);backend=_backend_factory(sw,clsid,tlb,v,data,r,journal.persist,runtime_check,abi)
    return run_backend(backend,journal,data)


def revoke(r,error):
    r.update(status='uncertain'if r.get('mutation_attempted')else'error',runtime_error=_error(error),**{k:False for k in ACCEPTANCE});_write_receipt(Path(r['receipt_path']),r);return r
