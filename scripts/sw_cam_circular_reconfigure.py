"""One generated circular rough revision: explicit fields, one GTP, Save and CL proof."""
from copy import deepcopy
from pathlib import Path
import math,re
from ctypes import POINTER,HRESULT,c_double,c_long
from ctypes.wintypes import VARIANT_BOOL
from comtypes.automation import IDispatch
from scripts import sw_cam_circular_nc_read as nc_read
from scripts import sw_cam_current_saved_generation as engine
from scripts import sw_cam_current_saved_generation_delta as delta
from scripts import sw_cam_current_saved_parameter_fields as fields
from scripts import sw_cam_current_circular_authority as authority
from scripts import sw_cam_current_parameter_capture as captures
from scripts.sw_cam_current_circular_continuation import CircularGenerationContext,CircularGenerationProof
from scripts.sw_cam_current_circular_context import NativeCircularContext
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_chamfer_clearance_read import pointer_value as plane_pointer

SCOPE='GENERATED_CIRCULAR_RECONFIGURE_V1'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','nc_receipt_path','nc_receipt_sha256','recipe_path','recipe_sha256','receipt_path','saved_cl_path','qualification_only','message_policy'}
ROUGH_ORDER=('first_depth','subsequent_depth','spiral_pitch')
NC_ORDER=('LinkToTool','GetSpndlSpeed','XYFeed','leadin_feed')
require=delta.require
same=authority.circular_state_equal


def cutting_from_read(value):
    return dict(nc=deepcopy(value['nc']),local_planes={k:deepcopy(v['value']) for k,v in value['local_planes'].items()})


def selected(state,oid):
    rows=[r for r in state['operations'] if r['native_id']==oid]
    require(len(rows)==1,'One explicit existing operation required')
    row=rows[0]
    require(row['suppressed'] is False and row['mill_operation_type']==0 and len(row['linked_feature_ids'])==1,'Unsuppressed own Rough required')
    require(type(row['toolpath_generated']) is bool and type(row['toolpath_record_counts']) is list,'Actual selected path state required')
    if row['toolpath_generated']:require(len(row['toolpath_record_counts'])==1 and type(row['toolpath_record_counts'][0]) is int and 0<row['toolpath_record_counts'][0]<=delta.MAX_RECORDS,'One bounded generated path required')
    else:require(row['toolpath_record_counts']==[],'Ungenerated path must have no records')
    return row


def validate_recipe(recipe,state):
    require(type(recipe) is dict and set(recipe)=={'operation_native_id','feature_native_id','expected_tool_native_id','rough','nc','qualification_only'},'Exact bounded recipe required')
    oid=recipe['operation_native_id'];require(type(oid) is int and oid>0 and recipe['qualification_only'] is True,'Explicit qualification target required')
    op=selected(state,oid);require(op['toolpath_generated'] is True,'Saved generated baseline required')
    require(op['linked_feature_ids']==[recipe['feature_native_id']] and op['assigned_tool']['native_id']==recipe['expected_tool_native_id'],'Recipe feature/tool differs')
    require(type(recipe['rough']) is list and [x.get('field') for x in recipe['rough']]==list(ROUGH_ORDER),'Only ordered two depths and spiral pitch allowed')
    row=fields.parameter_row(state,oid)
    require(fields.field_value(row,'entry_type')==4 and fields.field_value(row,'spiral_radius')>0,'Existing helix entry required')
    for change in recipe['rough']:
        require(set(change)=={'field','expected','new'},'Exact rough change required');spec=fields.FIELDS[change['field']]
        fields.checked_value(spec,change['expected']);fields.checked_value(spec,change['new'])
        require(fields.equal(fields.field_value(row,change['field']),change['expected']),'Actual rough field differs')
        if spec.mode=='pair':require(change['new'][0] is False and 0<change['new'][1]<=10.,'Absolute bounded native depth required')
        else:require(type(change['new']) is float and 0<change['new']<=1.,'Bounded helix pitch required')
    require(recipe['rough'][0]['new']==recipe['rough'][1]['new'],'Single equal first/subsequent depth required')
    require(type(recipe['nc']) is list and [x.get('field') for x in recipe['nc']]==list(NC_ORDER),'Only explicit link/spindle/XY/lead fields allowed')
    nc=state['cutting_context']['nc'];require(nc['GetSpeedFeedMethod']==0 and nc['GetIsLockSpindleSpeed'] is False,'Unlocked BY_OPERATION feed method required')
    for change in recipe['nc']:
        key=change['field'];require(set(change)=={'field','expected','new'} and fields.equal(nc[key],change['expected']),'Actual NC value differs')
        if key=='LinkToTool':require(type(change['expected']) is bool and change['new'] is False,'Explicit unlink only; no shared tool edits')
        elif key=='leadin_feed':
            v=change['new'];require(type(v) is dict and set(v)=={'value_native','is_percent','physical_units_verified'} and v['is_percent'] is False and v['physical_units_verified'] is False,'Explicit absolute native lead feed required');require(type(v['value_native']) is float and math.isfinite(v['value_native']) and 0<v['value_native']<=1000.,'Bounded lead feed required')
        else:require(type(change['new']) is float and math.isfinite(change['new']) and 0<change['new']<=(10000. if key=='GetSpndlSpeed' else 1000.),'Bounded positive DOUBLE NC value required')
    return deepcopy(recipe)


def expected_configuration(before,recipe):
    result=deepcopy(before);oid=recipe['operation_native_id'];row=dict(operation_native_id=oid)
    for change in recipe['rough']:result=fields.expected_field_state(result,row,change)
    for change in recipe['nc']:
        key=change['field'];result['cutting_context']['nc'][key]=deepcopy(change['new'])
        if key in ('GetSpndlSpeed','XYFeed'):
            for family in ('candidate_consumers','target_nc'):
                target=result['parameter_batch'][family][str(oid)];require(target['operation_native_id']==oid and target['read_complete'] is True,'Exact NC echo required');require(fields.equal(target['feeds_compensation'][key],change['expected']),'NC echo differs from receipt');target['feeds_compensation'][key]=change['new']
    return result


def _lifecycle_projection(state,oid):
    out=deepcopy(state);row=selected(out,oid);require(type(out['document']['needs_save']) is bool and type(out['sketch_state']['needs_save']) is bool,'Strict document and sketch dirty flags required');row['toolpath_generated']=None;row['toolpath_record_counts']=None;out['document']['needs_save']=None;out['sketch_state']['needs_save']=None;return out


def verify_configuration(before,after,recipe):
    oid=recipe['operation_native_id'];expected=expected_configuration(before,recipe)
    require(same(_lifecycle_projection(expected,oid),_lifecycle_projection(after,oid)),'Configuration changed a protected field or failed exact recipe readback')
    return dict(parameter_delta_verified=True,shared_tool_unchanged=True,protected_operation_count=len(before['operations'])-1,selected_cached_path_is_stale=True)


def verify_generation(before,after,oid):
    row=selected(after,oid);require(row['toolpath_generated'] is True,'One new generated path required')
    require(same(_lifecycle_projection(before,oid),_lifecycle_projection(after,oid)),'GTP changed protected fields or configured cutting values')
    return dict(selected_operation_native_id=oid,selected_generated_record_count=row['toolpath_record_counts'][0],protected_operation_count=len(before['operations'])-1,complete_captured_delta_verified=True)


def compare_replacement_cl(before,after,before_rows,after_rows,oid):
    from scripts.sw_cam_chamfer_cl_review import block_signature
    ids=[r['operation_native_id'] for r in before_rows];new=[r['operation_native_id'] for r in after_rows]
    require(ids==new and len(ids)==len(set(ids)) and ids.count(oid)==1,'Exact ordered generated inventory required')
    for parsed,rows in ((before,before_rows),(after,after_rows)):
        require(parsed.get('parse_complete') is True and parsed.get('native_count_matches') is True and parsed.get('declared_units')==['MM'] and len(parsed['operation_blocks'])==len(rows),'Complete metric native-count CL required')
        require(all(type(r['operation_native_id']) is int and r['operation_native_id']>0 and type(r['toolpath_record_counts']) is list and len(r['toolpath_record_counts'])==1 and type(r['toolpath_record_counts'][0]) is int and 0<r['toolpath_record_counts'][0]<=delta.MAX_RECORDS for r in rows),'Strict positive native CL context required')
        require(parsed.get('block_command_counts')==[r['toolpath_record_counts'][0] for r in rows],'CL block counts differ from explicit native context')
    require([x['raw'] for x in before['commands'] if x['name']=='BOX']==[x['raw'] for x in after['commands'] if x['name']=='BOX'],'CL stock declaration changed')
    protected=[];signatures=[block_signature(after,i) for i in range(len(new))]
    for i,value in enumerate(ids):
        if value==oid:continue
        require(before_rows[i]['toolpath_record_counts']==after_rows[i]['toolpath_record_counts'],'Protected native count changed');sig=block_signature(before,i);require(sig==signatures[i] and sum(x==sig for x in signatures)==1,'Protected complete CL stream changed or became ambiguous');protected.append(value)
    return dict(protected_complete_streams_verified=True,protected_operation_native_ids=protected,protected_block_count=len(protected),replaced_operation_native_id=oid,replaced_block_index=ids.index(oid),world_geometry_verified=False,production_qualified=False)


def validate(v):
    require(type(v) is dict and set(v)==KEYS,'Exact generated revision request required')
    require(type(v['process_id']) is int and v['process_id']>0 and type(v['expected_process_create_time']) in (int,float) and math.isfinite(v['expected_process_create_time']) and v['expected_process_create_time']>0,'Exact current owner required')
    require(v['qualification_only'] is True and v['message_policy']=='vendor_default','Explicit qualification/default-event policy required')
    for k in ('expected_source_sha256','nc_receipt_sha256','recipe_sha256'):require(type(v[k]) is str and re.fullmatch('[0-9a-f]{64}',v[k]),'Exact SHA required')
    source=Path(v['expected_document_path']);require(source.is_absolute() and source.suffix.lower()=='.sldprt' and source.is_file() and not source.is_symlink() and _file_hash(source)==v['expected_source_sha256'],'Exact saved source required')
    nc,np=read_pin(v['nc_receipt_path'],v['nc_receipt_sha256']);require(nc.get('scope')==nc_read.SCOPE and nc.get('status')=='review_required' and nc.get('phase')=='finished' and all(nc.get(k) is True for k in ('readback_verified','source_unchanged','runtime_unchanged','read_only')) and nc.get('mutation_attempted') is False and nc['before']==nc['after'],'Completed pure NC read required');clean_events(nc)
    for key in ('process_id','expected_process_create_time','expected_document_path','expected_source_sha256'):require(type(nc['request'][key]) is type(v[key]) and nc['request'][key]==v[key],'NC request identity differs: '+key)
    review,rp=read_pin(nc['request']['reconciliation_path'],nc['request']['reconciliation_sha256']);require(review.get('status')=='PASS_SCOPED_SAVE_CL_MAPPING_REVIEW' and review.get('save_once_verified') is True and review.get('capture_readback_verified') is True,'Pinned complete Save/CL review required')
    sp=review['pins']['save_receipt'];saved,sp=read_pin(sp['path'],sp['sha256']);state=deepcopy(saved['confirm_saved']);require(same(state,saved['postCL']['after']) and state['document']['needs_save'] is False and state['sketch_state']['saved_file_sha256']==v['expected_source_sha256'],'Exact saved authority required')
    require(review['pins']['saved_part']['sha256']==v['expected_source_sha256'] and Path(review['pins']['saved_part']['path']).resolve()==source.resolve() and nc['before']['inventory']==nc_read.inventory_projection(state),'Reconciled source and NC inventory differ')
    state['cutting_context']=cutting_from_read(nc['before']);recipe,recipepin=read_pin(v['recipe_path'],v['recipe_sha256']);recipe=validate_recipe(recipe,state);oid=recipe['operation_native_id'];require(oid==nc['request']['operation_native_id']==review['new_operation']['operation_native_id'],'One bound operation required')
    gp=saved['historical_generation_pin'];history,gp=read_pin(gp['path'],gp['sha256']);args=history['request']['params']
    loaded=engine.load_completed_configuration(args['configuration_receipt_path'],args['configuration_receipt_sha256'],process_id=v['process_id'],source_path=str(source),source_sha256=args['expected_source_sha256'],selected_ids=[oid]);require(loaded.get('mode')=='current_saved_circular','Established circular context required')
    cp=review['pins']['post_CL'];require(_file_hash(cp['path'])==cp['sha256'] and Path(cp['path']).stat().st_size==cp['bytes'],'Historical complete CL changed')
    from scripts.sw_cam_deep_guide_cl import _fresh_path
    output=_fresh_path(v['saved_cl_path']);receipt=Path(v['receipt_path']);require(receipt.is_absolute() and receipt.suffix.lower()=='.json' and receipt.parent.is_dir() and not receipt.exists() and not receipt.is_symlink(),'Fresh receipt required')
    marker=Path(np['path']).parent/('generated_circular_'+_digest(dict(scope=SCOPE,source=str(source.resolve()).casefold(),source_sha256=v['expected_source_sha256'],operation_native_id=oid,recipe_sha256=recipepin['sha256']))+'.json');require(not marker.exists() and not marker.is_symlink(),'Prior identical revision attempt exists; no replay')
    pins=[np,rp,sp,gp,recipepin,dict(path=__file__,sha256=_file_hash(__file__))];protected={source.resolve(),Path(cp['path']).resolve(),*(Path(p['path']).resolve() for p in pins),*(Path(p['path']).resolve() for p in loaded['pins'].values())};outs=[receipt,marker,output];require(len({p.resolve() for p in outs})==3 and not protected.intersection(p.resolve() for p in outs) and receipt.parent.resolve()!=output.parent.resolve() and marker.parent.resolve()!=output.parent.resolve(),'Output/evidence alias forbidden')
    return dict(state=state,nc=nc,recipe=recipe,recipe_pin=recipepin,pins=pins,loaded=loaded,args=args,cl_pin=cp,receipt=receipt,marker=marker,module_sha256=_file_hash(__file__))


def _abi(tlb):
    fields.preflight(tlb);engine.preflight(tlb);classes,_=nc_read.preflight(tlb)
    specs=(('ICWNCParam','SetSpndlSpeed',8,(c_double,),(0,)),('ICWNCParam','SetLeadinFeedrate',4,(c_double,VARIANT_BOOL),(0,0)),('ICWNCParam2','_set_XYFeed',23,(c_double,),(1,)),('ICWNCParam4','_set_LinkToTool',53,(VARIANT_BOOL,),(1,)))
    for owner,name,dispid,args,dirs in specs:
        methods=[m for m in classes[owner]._methods_ if m.name==name];require(len(methods)==1,'One exact NC setter required');m=methods[0];require(m.restype is HRESULT and m.idlflags[0]==dispid and m.argtypes==args and tuple(p[0] for p in m.paramflags)==dirs,'Fixed NC setter ABI differs')
    return classes


class RevisionContext(CircularGenerationContext):
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        args=deepcopy(data['args']);args.update(expected_source_sha256=v['expected_source_sha256'],saved_cl_path=v['saved_cl_path'])
        super().__init__(sw,clsid,tlb,args,data['loaded'],report,persist,runtime_check)
        self.revision=data;self.recipe=data['recipe'];self.oid=self.recipe['operation_native_id'];self.pins.extend(p for p in data['pins'] if Path(p['path']).suffix.lower()=='.json');self.data=deepcopy(self.data);self.data['recovery']={'expected_state':deepcopy(data['state'])};self.generated_once=False;self._native_read_limit=24000;self.nc_classes=nc_read.preflight(tlb)[0]
    def verify_files(self):
        super().verify_files()
        if getattr(self,'_capture_pin_scope',False):return
        if hasattr(self,'revision'):
            require(_file_hash(self.revision['cl_pin']['path'])==self.revision['cl_pin']['sha256'],'Historical full CL changed')
            require(_file_hash(__file__)==self.revision['module_sha256'],'Revision implementation changed')
    def _typed_nc4(self,raw,guard=None):
        def call():
            value=raw.QueryInterface(self.nc_classes['ICWNCParam4']);require(value is not None and bool(value) and isinstance(value,POINTER(self.nc_classes['ICWNCParam4'])),'Exact NC4 pointer required');return value
        if guard is not None:return guard._observe(call)
        self.check();value=call();self.check();return value
    def _target(self,read,typed):
        doc=self.native['doc'];found=read(doc,'GetCWObjectFromID',3,self.oid);require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact selected lookup required');op=typed(found[0],'ICWOperation');mill=typed(found[0],'ICWMillOperation')
        require(_object_id(doc,op,read)==self.oid and read(op,'Suppressed') is False and read(mill,'OpernType')==0,'Own unsuppressed rough required');require([_object_id(doc,x,read) for x in _items(read(op,'IGetAllFeatures'),typed,read,2)]==[self.recipe['feature_native_id']],'Exact feature link required');generic,tool=captures.read_generic_tool(op,doc,read,typed);require(generic['native_id']==self.recipe['expected_tool_native_id'],'Shared nominal tool assignment changed');return op,mill
    def read_cutting(self):
        start=self.boundary();op,mill=self._target(self.read,self.typed);raw=self.read(mill,'IGetNCParam');nc=self.typed(raw,'ICWNCParam');nc2=self.typed(raw,'ICWNCParam2');nc4=self._typed_nc4(raw)
        values={k:self.read(nc,k) for k in ('GetSpndlSpeed','GetCNCComp','GetTlpComp','GetClrPlaneUseSetupStatus','GetRpdPlaneUseSetupStatus','GetRetractType')};values['XYFeed']=self.read(nc2,'XYFeed')
        for k in ('GetSpeedFeedMethod','LinkToTool','GetIsLockSpindleSpeed','GetZFeedrate2','GetLeadinFeedratePercent'):values[k]=self.read(nc4,k)
        for k in ('GetSpndlSpeed','XYFeed','GetLeadinFeedratePercent'):values[k]=nc_read.finite(values[k])
        for k in ('GetCNCComp','GetTlpComp','GetRetractType','GetSpeedFeedMethod'):require(type(values[k]) is int,'Strict NC enum required')
        for k in ('GetClrPlaneUseSetupStatus','GetRpdPlaneUseSetupStatus','LinkToTool','GetIsLockSpindleSpeed'):require(type(values[k]) is bool,'Strict NC flag required')
        z=values['GetZFeedrate2'];require(type(z) in (tuple,list) and len(z)==2 and type(z[1]) is bool,'Exact Z feed pair required');values['GetZFeedrate2']=[nc_read.finite(z[0]),z[1]]
        self.check();values['leadin_feed']=nc_read.lead_pointer_value(nc,{});planes={}
        for name in ('GetRpdPlnPrms','GetClrPlanePrms'):self.check();planes[name]=plane_pointer(nc,name,{})
        self.check();require(self.boundary()==start,'Document changed during targeted NC capture');return dict(nc=values,local_planes=planes)
    def capture(self,label,partial):
        # A retained generated flag is a cache observation, never proof of the new recipe.
        if self.native is None:self.native={'doc':self.typed(self.read(self.app,'IGetActiveDoc'),'ICWDoc3')}
        op,_=self._target(self.read,self.typed);generated=self.read(op,'GetIsToolpathGenerated');require(type(generated) is bool,'Actual generated flag required');self.attempted=[self.oid] if generated else []
        state=super().capture(label,partial);state['cutting_context']=self.read_cutting();partial.clear();partial.update(deepcopy(state));self.report[label]=state;self.persist();return state
    def set_change(self,kind,change,*,pending,returned):
        with self.guard() as guard:
            op,mill=self._target(guard.read,guard.typed)
            if kind=='rough':
                spec=fields.FIELDS[change['field']];rough=guard.typed(op,'ICWRghMillOp');found=guard.read(self.native['doc'],'GetCWObjectFromID',1,self.recipe['feature_native_id']);require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact feature required');feature=guard.read(found[0],'QueryInterface',IDispatch)
                args=(feature,) if spec.mode=='feature' else ();actual=guard.read(rough,spec.getter,*args);require(fields.equal(list(actual) if isinstance(actual,tuple) else actual,change['expected']),'Immediate rough expected value changed')
                def invoke():
                    a=(feature,change['new']) if spec.mode=='feature' else tuple(change['new']);value=_member(rough,spec.setter,*a);returned(value);return value
            else:
                raw=guard.read(mill,'IGetNCParam');nc=guard.typed(raw,'ICWNCParam');nc2=guard.typed(raw,'ICWNCParam2');nc4=self._typed_nc4(raw,guard);key=change['field']
                if key=='leadin_feed':actual=guard._observe(lambda:nc_read.lead_pointer_value(nc,{}))
                else:actual=guard.read(nc4 if key=='LinkToTool' else nc2 if key=='XYFeed' else nc,key)
                # Spindle changes may derive XY feed; its final explicit write is still required.
                if key!='XYFeed':require(fields.equal(actual,change['expected']),'Immediate NC expected value changed')
                else:require(type(actual) in (float,int) and math.isfinite(actual) and actual>0,'Finite observed coupled XY feed required');self.report['xy_before_explicit_write']=actual;self.persist()
                def invoke():
                    if key=='LinkToTool':value=getattr(nc4,'_ICWNCParam4__com__set_LinkToTool')(False)
                    elif key=='GetSpndlSpeed':value=_member(nc,'SetSpndlSpeed',change['new'])
                    elif key=='XYFeed':value=getattr(nc2,'_ICWNCParam2__com__set_XYFeed')(change['new'])
                    else:value=getattr(nc,'_ICWNCParam__com_SetLeadinFeedrate')(change['new']['value_native'],False)
                    returned(value);return value
            result=guard.dispatch_once(invoke,persist_pending=pending)
        require(type(result) is int and result==0,'Exact setter HRESULT0 required; no replay')
        # A local immediate getter proves the written scalar without another full capture.
        self.boundary()
        if kind=='nc':observed=self.read_cutting()['nc'][change['field']]
        else:
            op,_=self._target(self.read,self.typed);rough=self.typed(op,'ICWRghMillOp');spec=fields.FIELDS[change['field']];args=()
            if spec.mode=='feature':args=(self.read(self.read(self.native['doc'],'GetCWObjectFromID',1,self.recipe['feature_native_id'])[0],'QueryInterface',IDispatch),)
            observed=self.read(rough,spec.getter,*args);observed=list(observed) if isinstance(observed,tuple) else observed
        require(fields.equal(observed,change['new']),'Immediate setter readback differs');return observed
    def generate(self,oid,state,*,pending,returned):
        require(oid==self.oid and not self.generated_once,'One explicit selected GTP only')
        with self.guard() as guard:
            op,mill=self._target(guard.read,guard.typed);generic,tool=captures.read_generic_tool(op,self.native['doc'],guard.read,guard.typed)
            require(fields.equal(captures.read_tool_dimensions(tool,generic,guard),fields.parameter_row(state,oid)['tool']),'Immediate full nominal tool changed')
            require(type(guard.read(self.app,'IsBackgroundProcessForGTPOver')) is bool,'Boolean background observation required')
            def claim():pending();self.generated_once=True
            def invoke():value=_member(mill,'GenerateToolpath');returned(value);return value
            value=guard.dispatch_once(invoke,persist_pending=claim)
        require(type(value) is int and value==0,'Exact GTP HRESULT0 required; no replay')


class RevisionJournal(engine.Journal):
    def marker_state(self):return dict(scope=SCOPE,receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),source_before_sha256=self.report['source_before_sha256'],recipe_pin=self.report['recipe_pin'],status=self.report['status'],phase=self.report['phase'],automatic_replay=False)
    def pending(self,name):
        allowed={*(f'rough:{x}' for x in ROUGH_ORDER),*(f'nc:{x}' for x in NC_ORDER),'GTP:'+str(self.report['operation_native_id']),'SaveActiveDocument','postCL'};require(name in allowed,'Action outside bounded recipe')
        if name.startswith(('rough:','nc:')):self.report.update(mutation_attempted=True,parameter_setter_attempted=True)
        super().pending(name)


def run_once(backend,journal,data,v):
    r=journal.report;recipe=data['recipe'];oid=recipe['operation_native_id'];proof=CircularGenerationProof(backend,reference=data['state'])
    def observe(label):
        row=dict(label=label,capture_complete=False,state={});r['captures'].append(row);r['phase']=label;journal.persist();actual=backend.capture(label,row['state']);require(all(actual.get(k) is True for k in ('capture_complete','parameter_capture_complete','extended_capture_complete')),'Complete full capture required');row.update(capture_complete=True,state=deepcopy(actual));r[label]=deepcopy(actual);journal.persist();return actual
    try:
        journal.create();backend.start();before=observe('before');require(same(before,data['state']),'Fresh full state differs from pinned saved/NC context');validate_recipe(recipe,before);backend.boundary();journal.claim()
        for kind,changes in (('nc',recipe['nc']),('rough',recipe['rough'])):
            for change in changes:
                name=kind+':'+change['field'];journal.action(name);r['parameter_setter_attempted']=True;journal.persist()
                actual=backend.set_change(kind,change,pending=lambda n=name:journal.pending(n),returned=lambda value,n=name:journal.returned(n,value));r['actions'][name]['immediate_readback']=deepcopy(actual);journal.persist()
        configured=observe('configured');r['configuration_proof']=verify_configuration(before,configured,recipe);r['selected_cached_path_is_stale']=True;journal.persist()
        name='GTP:'+str(oid);journal.action(name);backend.generate(oid,configured,pending=lambda:journal.pending(name),returned=lambda value:journal.returned(name,value));generated=observe('generated');r['generation_proof']=verify_generation(configured,generated,oid);r['selected_cached_path_is_stale']=False;journal.persist()
        backend.boundary();journal.action('SaveActiveDocument');r['save_stage']={'before_state_reused_from':'generated','save_pending':False};journal.persist()
        def returned(value):
            journal.returned('SaveActiveDocument',value);r['save_stage'].update(native_call_returned=True,save_pending=False,native_return_type=type(value).__name__,native_return_value=value if type(value) in (int,bool,float,str) or value is None else None);journal.persist()
        journal.pending('SaveActiveDocument');r['save_stage']['save_pending']=True;journal.persist();backend.save(returned=returned);sha=backend.adopt_saved_source(r['save_stage']);r.update(source_after_sha256=sha,saved_file_sha256=sha);journal.persist()
        saved=observe('saved');proof.verify_saved(generated,saved);confirm=observe('confirm_saved');require(same(saved,confirm),'Two complete saved captures differ');r.update(model_saved=True,save_readback_verified=True,source_update_verified=True);journal.persist()
        rows=delta.inventory(saved)['generated'];journal.action('postCL');detail={};r['postCL']=detail;journal.persist();post=backend.export_cl('postCL',saved,rows,detail,pending=lambda:journal.pending('postCL'),returned=lambda value:journal.returned('postCL',value));r['postCL']=deepcopy(post);journal.persist()
        historical=dict(output=data['cl_pin'],expected_generated_operations=delta.inventory(data['state'])['generated']);r['CL_preservation']=compare_replacement_cl(backend.parse_cl(historical),backend.parse_cl(post),historical['expected_generated_operations'],rows,oid);backend.boundary();backend.finish();r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,continuation_verified=True,reason='ONE_SELECTED_RECONFIGURATION_GTP_SAVE_AND_PROTECTED_CL_VERIFIED')
    except Exception as error:r.update(status='uncertain' if r.get('mutation_attempted') else 'error',failed_phase=r['phase'],phase='finished',issue=_error(error),reason=str(error),readback_verified=False,runtime_unchanged=False,continuation_verified=False)
    finally:
        try:backend.close()
        except Exception as error:r.update(status='uncertain' if r.get('mutation_attempted') else 'error',cleanup_error=_error(error),readback_verified=False,runtime_unchanged=False,continuation_verified=False)
        journal.persist()
    return r


def finalize_runtime_failure(result,error):
    result.update(status='uncertain' if result.get('mutation_attempted') else 'error',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,continuation_verified=False,production_qualified=False)
    _write_receipt(Path(result['receipt_path']),result)
    if result.get('marker_created'):_write_receipt(Path(result['dispatch_marker_path']),dict(scope=SCOPE,status=result['status'],receipt_path=result['receipt_path'],receipt_sha256=_file_hash(result['receipt_path']),automatic_replay=False))
    return result


def dispatch(sw,clsid,tlb,*,runtime_check,_context_factory=RevisionContext,**v):
    data=validate(v);require(data['loaded']['addin_clsid'].casefold()==clsid.casefold(),'Exact historical CAM add-in required');_abi(tlb)
    r=dict(scope=SCOPE,status='error',phase='preflight',request=deepcopy(v),receipt_path=v['receipt_path'],dispatch_marker_path=str(data['marker']),recipe_pin=data['recipe_pin'],recipe=deepcopy(data['recipe']),operation_native_id=data['recipe']['operation_native_id'],evidence_pins=deepcopy(data['pins']),source_before_sha256=v['expected_source_sha256'],historical_CL_pin=data['cl_pin'],actions={},captures=[],native_read_count=0,receipt_created=False,marker_created=False,mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,GTP_attempted=False,save_attempted=False,CL_export_attempted=False,parameter_setter_attempted=False,tool_assignment_attempted=False,GOP_attempted=False,AFR_attempted=False,operation_creation_attempted=False,automatic_replay=False,automatic_rollback=False,model_saved=False,save_readback_verified=False,source_update_verified=False,readback_verified=False,continuation_verified=False,runtime_unchanged=False,cutting_conditions_qualified=False,world_geometry_verified=False,production_qualified=False,reopen_persistence_verified=False)
    journal=RevisionJournal(v['receipt_path'],data['marker'],r);backend=_context_factory(sw,clsid,tlb,v,data,r,journal.persist,runtime_check);runtime_check();result=run_once(backend,journal,data,v)
    try:runtime_check()
    except Exception as error:return finalize_runtime_failure(result,error)
    return result
