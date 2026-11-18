"""Seven explicit Rough fields, one diagnostic first GTP, one Save and raw CL.
Existing current-context, field, generation/export and Save primitives only.
"""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_current_pair_tool as tool
from scripts import sw_cam_current_pocket_context as current
from scripts import sw_cam_current_saved_parameter_fields as fields
from scripts import sw_cam_current_saved_generation as engine
from scripts import sw_cam_current_generation_native as generation
from scripts import sw_cam_setup_transform_observation as transforms
from scripts import sw_cam_current_pocket_generation_delta as delta
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam import _member,_error
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_deep_guide_cl import _fresh_path
from scripts.sw_cam_generic_cl_reader import parse_generic_cl_bytes
from scripts import sw_cam_generic_cl_reader as cl_reader
from scripts import sw_cam_generic_cl_reader_bounded as cl_bounded

reader=tool.reader
require=tool.require
SCOPE='CURRENT_POCKET_SEVEN_FIELDS_FIRST_GTP_SAVE_CL_V1'
FIELD_NAMES=('entry_type','spiral_radius','spiral_pitch','first_depth','subsequent_depth','side_allowance','floor_allowance')
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','expected_feature_native_id','expected_operation_native_ids','selected_operation_native_id','current_context_receipt_path','current_context_receipt_sha256','recipe_path','recipe_sha256','receipt_path','saved_cl_path','qualification_only','acknowledge_settings_generation_save_export','message_policy'}
FLAGS=('readback_verified','current_context_verified','inventory_delta_verified','parameter_delta_verified','generation_verified','CL_verified','runtime_unchanged')


def shape(v):
    require(type(v)is dict and set(v)==KEYS,'Exact bounded current Rough request required')
    for k in ('process_id','expected_feature_native_id','selected_operation_native_id'):
        require(type(v[k])is int and 0<v[k]<2**31,'Strict positive owned identity required')
    ids=v['expected_operation_native_ids'];require(type(ids)is list and len(ids)==2 and all(type(x)is int and 0<x<2**31 for x in ids) and len(set(ids))==2 and v['selected_operation_native_id']==ids[0],'Only first Rough of exact ordered pair may generate')
    require(type(v['expected_process_create_time'])in(int,float) and math.isfinite(v['expected_process_create_time']) and v['expected_process_create_time']>0,'Exact finite process lifetime required')
    for k,x in v.items():
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute bound paths required')
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact immutable SHA required')
    require(v['qualification_only']is True and v['acknowledge_settings_generation_save_export']is True and v['message_policy']=='vendor_default','Explicit diagnostic settings/GTP/Save/export admission required')


def marker_path(v):
    return Path(v['expected_document_path']).parent/('current_pocket_first_gtp_'+_digest(dict(scope=SCOPE,target=reader.definition.creator.canonical(v['expected_document_path']),source_sha256=v['expected_source_sha256']))+'.json')


def prepare(v):
    shape(v);bundle=current.load_current_baseline(v)
    snapshot=dict(inventory=bundle['state'],parameters=bundle['parameters']);state=delta.flatten(snapshot)
    rows=state['operations'];require([r['mill_operation_type']for r in rows]==[0,1] and all(r['toolpath_generated']is False and r['toolpath_record_counts']==[]for r in rows),'Only a first path on an ungenerated Rough/Contour pair is admitted')
    require(state['generated_operation_count']==0 and state['total_record_count']==0,'Zero baseline paths required; no fabricated preCL')
    recipe,pin=reader.definition.read_pin(v['recipe_path'],v['recipe_sha256']);plan=fields.compile_plan(state,recipe)
    require(len(plan['rows'])==1,'One selected Rough recipe required');row=plan['rows'][0]
    require(row['operation_native_id']==v['selected_operation_native_id'] and row['feature_native_id']==v['expected_feature_native_id'] and row['existing_tool_native_id']is None,'No tool assignment in this packet')
    require(tuple(x['field']for x in row['fields'])==FIELD_NAMES,'Exactly seven ordered fixed Rough fields required')
    actual=fields.parameter_row(state,row['operation_native_id'])
    require(fields.equal(actual['rough']['depth']['DepthAllow']['raw'],fields.field_value(actual,'floor_allowance')),'Actual floor alias must match before any setter')
    d=bundle['context'];extra=[pin]+[reader.shared.file_pin(p,_file_hash(p))for p in (__file__,delta.__file__,fields.__file__,engine.__file__,generation.__file__,transforms.__file__,transforms.metadata_reader.__file__,current.__file__,tool.__file__,delta.existing.__file__,cl_reader.__file__,cl_bounded.__file__)]
    d['pins']=current._pins(d['pins']+extra);require(len(d['pins'])<=64,'Complete evidence exceeds existing bounded guard')
    receipt=Path(v['receipt_path']);marker=marker_path(v);cl=_fresh_path(v['saved_cl_path'])
    for output in (receipt,marker):
        require(output.suffix.lower()=='.json' and output.parent.is_dir() and not output.exists() and not output.is_symlink(),'Fresh receipt and unused target/source marker required; no replay')
        require(not any(reader.definition.creator.same_path(str(output),p['path'])for p in d['pins']),'Output aliases protected evidence')
    require(receipt!=marker and not any(reader.definition.creator.same_path(str(cl),p['path'])for p in d['pins']),'Outputs must be distinct from authority')
    reader.definition.verify_files(d)
    return dict(bundle=bundle,recipe=recipe,recipe_pin=pin,plan=plan,request=deepcopy(v),receipt=receipt,marker=marker,consumed=False)


def preflight(tlb):
    out=reader.preflight(tlb);fields.preflight(tlb);engine.preflight(tlb)
    out.update(fixed_fields_abi_verified=True,generation_save_export_abi_verified=True,setup_transform=transforms.preflight(tlb))
    return out


class Journal(engine.Journal):
    def marker_state(self):return dict(super().marker_state(),scope=SCOPE)
    def pending(self,name):
        require(name in {'GTP:'+str(self.report['selected_operation_native_ids'][0]),'SaveActiveDocument','postCL'}|{'field:'+n for n in FIELD_NAMES},'Outside fixed current Rough actions')
        if name.startswith('field:'):
            self.report.update(mutation_attempted=True,operation_parameter_setters_attempted=True)
        super().pending(name)


def read_pair(state,native,targets,batch,report,persist,observations):
    """Existing exact pair plumbing with explicit generated-state allowance."""
    doc=native['doc'];machine=batch.typed(batch.read(batch.typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
    setups=_items(batch.read(machine,'IGetEnumOpSetups'),batch.typed,batch.read,1)
    require(len(setups)==1 and _object_id(doc,setups[0],batch.read)==targets[0]['setup_native_id'],'Current operation setup differs')
    operations=_items(batch.read(batch.typed(setups[0],'ICWBaseOpSetup'),'IGetEnumOperations'),batch.typed,batch.read,2)
    ids=[_object_id(doc,op,batch.read)for op in operations];require(ids==[r['native_id']for r in targets],'Complete ordered pair differs')
    native['operations']=dict(zip(ids,operations))
    try:reader.parameters.capture_rows(state,native,targets,feature_id=targets[0]['linked_feature_ids'][0],read=batch.read,typed=batch.typed,boundary=batch._boundary,generation_observations=observations)
    finally:report['parameters']=state.get('operation_parameters',[]);persist()
    for row,out in zip(targets,report['parameters']):
        raw=native['operations'][row['native_id']];feature=native['selected_feature']
        out['nc']=reader.pocket.read_nc_settings(raw,setups[0],read=batch.read,typed=batch.typed,pointer_read=batch.plane,diagnostic=out.setdefault('nc_diagnostic',{}),persist=persist)
        if row['mill_operation_type']==1:
            out['finish_fields']=reader.fields.read_cached_fields(batch,raw,feature,out.setdefault('finish_field_diagnostic',{}))
            out['protected_finish']=reader.protected.read_protected(raw,feature,read=batch.read,typed=batch.typed,record=lambda k,x:out.setdefault('protected_raw',{}).update({k:reader.pocket.rough.bounded_raw_observation(x)}))
            out['leads']=reader.pocket.leads.read_lead_details(raw,feature,read=batch.read,typed=batch.typed,lead_typed=lambda x:batch.typed(x,'ICWLeadInOut'))
        persist()
    require(len(report['parameters'])==2 and all(x['read_complete']is True for x in report['parameters']),'Complete paired parameters required')
    report['unique_tool_dimension_reads']=len({x['assigned_tool']['native_id']for x in targets});batch._boundary()


def verify_transform(row,levels):
    require(row.get('setup_transform_complete')is True,'Complete actual operation setup transform required')
    c=row['transform_components'];vectors=c['vectors'];axes=[vectors[n]['coordinates_raw']for n in ('x_axis','y_axis','z_axis')]
    values=[x for a in axes for x in a]+vectors['translation']['coordinates_raw']+row['origin']['coordinates_raw']+row['axis']['coordinates_raw']+[c['scale_raw']]
    require(all(type(x)in(int,float) and math.isfinite(x)for x in values) and c['scale_raw']>0,'Finite positive-scale transform required')
    dot=lambda a,b:sum(x*y for x,y in zip(a,b))
    require(all(abs(dot(a,a)-1)<=1e-8 for a in axes) and all(abs(dot(axes[i],axes[j]))<=1e-8 for i,j in ((0,1),(0,2),(1,2))),'Observed transform axes are not orthonormal')
    a,b,caxis=axes;det=dot(a,[b[1]*caxis[2]-b[2]*caxis[1],b[2]*caxis[0]-b[0]*caxis[2],b[0]*caxis[1]-b[1]*caxis[0]])
    require(abs(det-1)<=1e-8,'Right-handed observed transform required')
    for label,key in (('origin','origin_native'),('axis','axis_native')):
        require(len(row[label]['coordinates_raw'])==len(levels['setup'][key])==3 and all(type(b)in(int,float) and math.isfinite(b) and abs(a-b)<=1e-8 for a,b in zip(row[label]['coordinates_raw'],levels['setup'][key])),'Transform origin/axis differs from current operation levels')
    # Values remain raw; scale/translation are not silently converted to world.
    return dict(setup_transform_complete=True,finite_orthonormal_positive_scale=True,determinant=det,CL_world_mapping_verified=False,units_verified=False)


class Backend(tool.Backend):
    generate=generation.NativeGenerationContext.generate
    export_cl=generation.NativeGenerationContext.export_cl
    parse_cl=generation.NativeGenerationContext.parse_cl
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.tlb=self.typelib_path;self.attempted=[]
        self.loaded['selected_ids']=[self.args['selected_operation_native_id']]
    @property
    def source(self):return self.d['expected_source_sha256']
    def files(self):reader.definition.verify_files(self.d)
    def boundary(self):
        super().boundary();return deepcopy(self.expected_document)
    def capture_current(self,label):
        self.report['phase']=label;diag={};record=dict(label=label,diagnostic=diag);self.report.setdefault('captures',[]).append(record);self.persist()
        state,native=reader.definition.capture(self.sw,self.clsid,self.typelib_path,self.d,self.events,diag)
        self.native.update(native);self.doc=self.native['doc'];observations={}
        for row in state['operations']:
            if row['toolpath_generated']:
                counts=row['toolpath_record_counts'];require(row['native_id']in self.attempted and len(counts)==1 and type(counts[0])is int and 0<counts[0]<=100000,'Only attempted selected positive path may be read')
                observations[row['native_id']]=deepcopy(counts)
        out={};record['parameter_observation']=out
        with reader.ReadGuard(self.sw,self.typelib_path,process_id=self.args['process_id'],expected_document=self.expected_document,source_sha256=self.source,evidence_pins=self.d['pins'],verify_evidence=self.files,verify_owned_process=self.owned,check_events=self.events,generated_pin=self.abi['generated_pin'],report=self.report)as batch:
            read_pair(deepcopy(state),self.native,state['operations'],batch,out,self.persist,observations)
        value=dict(inventory=state,parameters=out['parameters']);record['observation']=deepcopy(value);self.persist();return value
    def capture(self,label,partial):
        value=delta.flatten(self.capture_current(label));partial.clear();partial.update(value);return partial
    def set_field(self,row,change,pending,returned):
        return fields.write_field_once(self,self.native['doc'],row,change,pending=pending,returned=returned)
    def read_field(self,row,change):
        with self.guard()as guard:
            op,feature=fields.target(guard,self.native['doc'],row);owner=guard.typed(op,'ICWRghMillOp');spec=fields.FIELDS[change['field']];args=[]
            if spec.mode=='feature':
                from comtypes.automation import IDispatch
                args=[guard.read(feature,'QueryInterface',IDispatch)]
            value=guard.read(owner,spec.getter,*args);value=list(value)if type(value)is tuple else value
            fields.checked_value(spec,value);return value
    def setup_transform(self,selected_id):
        out={};self.report['setup_transform']=out;self.persist();count=0
        with self.guard()as guard:
            def admission():
                nonlocal count
                count+=1;require(count<=128,'Fixed setup transform read budget exceeded');out['native_read_count']=count
            def typed(obj,name):
                require(name in set(transforms.INTERFACES)|{'ICWMillOperation3','ITypeInfo'},'Outside fixed transform metadata scope');admission()
                if name=='ITypeInfo':
                    from comtypes.typeinfo import ITypeInfo
                    return guard._observe(lambda:obj.QueryInterface(ITypeInfo))
                return guard.typed(obj,name)
            def raw(obj,name,args,entry,observe):
                require(name in transforms.RAW_READS,'Outside fixed raw transform getters');admission();entry.update(attempted=True,returned=False,owned_output_storage=True,automatic_retry=False)
                try:
                    result=guard.read(obj,name,*args);entry.update(returned=True,hresult_type=type(result).__name__,hresult=result if type(result)is int else None);return result
                except Exception as error:entry['issue']=_error(error);raise
                finally:entry['outputs']=observe();self.persist()
            transforms.read_setup_transform(self.native['operations'][selected_id],typed=typed,raw_call=raw,row=out,boundary=guard._fast)
        self.persist();return out


def run_backend(backend,journal,data):
    r=journal.report;v=data['request'];oid=v['selected_operation_native_id'];plan=data['plan'];row=plan['rows'][0]
    try:
        journal.create();backend.start();before=backend.capture_current('before');r['before']=deepcopy(before)
        require(before==dict(inventory=data['bundle']['state'],parameters=data['bundle']['parameters']),'Fresh current pair differs from saved authority')
        transform=backend.setup_transform(oid);r['setup_transform_proof']=verify_transform(transform,fields.parameter_row(delta.flatten(before),oid)['levels']);journal.persist()
        backend.boundary();journal.claim();backend.boundary()
        for change in row['fields']:
            name='field:'+change['field'];actual=backend.read_field(row,change);require(fields.equal(actual,change['expected']),'Immediate expected field changed')
            result=dict(field=change['field'],before=actual,requested=change['new'],setter_attempted=False,readback_verified=False);r['field_readbacks'].append(result);journal.persist()
            if not fields.equal(actual,change['new']):
                journal.action(name);result['setter_attempted']=True
                backend.set_field(row,change,lambda name=name:journal.pending(name),lambda value,name=name:journal.returned(name,value));backend.refresh_dirty()
            result['actual']=backend.read_field(row,change);require(fields.equal(result['actual'],change['new']),'Immediate field readback differs');result['readback_verified']=True;journal.persist()
        configured=backend.capture_current('configured');fields.verify_final(delta.flatten(before),delta.flatten(configured),plan,{},observed_floor_alias=True)
        r['configured']=deepcopy(configured);r.update(inventory_delta_verified=True,parameter_delta_verified=True);journal.persist()
        name='GTP:'+str(oid);journal.action(name)
        backend.generate(oid,delta.flatten(configured),pending=lambda:journal.pending(name),returned=lambda value:journal.returned(name,value))
        action=r['actions'][name];require(action['returned']is True and action['native_return_type']=='int' and type(action['native_return_value'])is int and action['native_return_value']==0,'Strict selected GTP int0 required');backend.refresh_dirty()
        generated=backend.capture_current('generated');r['generated']=deepcopy(generated);journal.persist();r['generation_proof']=delta.verify_generation(configured,generated,oid,action);journal.persist()
        confirm=backend.capture_current('confirm_generated');require(confirm==generated,'Two complete post-GTP captures differ');r['generation_verified']=True;journal.persist()
        journal.action('SaveActiveDocument')
        def save():
            value=backend.save();journal.returned('SaveActiveDocument',value);return value
        saved=current.save_current_baseline(r,data['bundle'],generated,capture=backend.capture_current,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,adopt_context=backend.adopt_context)
        r['current_context']=saved['payload'];r['model_saved']=True;r['saved']=dict(inventory=saved['state'],parameters=saved['parameters']);journal.persist()
        saved_state=delta.flatten(r['saved']);selected=next(x for x in saved_state['operations']if x['native_id']==oid);rows=[dict(operation_native_id=oid,toolpath_record_counts=selected['toolpath_record_counts'])]
        journal.action('postCL');export={};r['postCL']=export
        backend.export_cl('postCL',saved_state,rows,export,pending=lambda:journal.pending('postCL'),returned=lambda value:journal.returned('postCL',value))
        parsed=backend.parse_cl(export);r['first_CL_proof']=delta.verify_first_cl(parsed,oid,selected['toolpath_record_counts'][0]);r['CL_verified']=True;journal.persist()
        backend.close();backend.runtime_check();document=backend.identity();require(document==backend.expected_document,'Document changed during cleanup');backend.files()
        require(reader.shared.event_health(r['messages'],active=False)==0,'Clean event cleanup required')
        r['after_cleanup_identity']=dict(document=document,saved_file_sha256=backend.source)
        r.update(status='review_required',phase='finished',**{key:True for key in FLAGS})
    except Exception as error:
        r.update(status='uncertain'if r.get('mutation_attempted')or r.get('CL_export_attempted')else'error',failed_phase=r.get('phase'),phase='finished',reason=str(error),issue=_error(error),**{key:False for key in FLAGS})
    finally:
        try:backend.close()
        except Exception as error:r.update(status='uncertain'if r.get('mutation_attempted')or r.get('CL_export_attempted')else'error',cleanup_error=_error(error),**{key:False for key in FLAGS})
        r['phase']='finished';journal.persist()
    return r


def run(sw,clsid,tlb,v,*,prepared=None,runtime_check=lambda:None,_backend_factory=Backend):
    data=prepare(v)if prepared is None else prepared;require(data.get('consumed')is False and data['request']==v,'Exact prepared request may be consumed once');data['consumed']=True
    abi=preflight(tlb);d=data['bundle']['context'];d['pins']=current._pins(d['pins']+[abi['generated_pin'],reader.shared.file_pin(tlb,_file_hash(tlb))]);reader.definition.verify_files(d);runtime_check()
    r=dict(scope=SCOPE,status='prepared',phase='prepared',request=deepcopy(v),configuration_receipt_pin=data['bundle']['receipt_pin'],current_baseline_receipt_pin=data['bundle']['receipt_pin'],selected_operation_native_ids=[v['selected_operation_native_id']],recipe=data['recipe'],recipe_pin=data['recipe_pin'],evidence_pins=deepcopy(d['pins']),abi=abi,actions={},captures=[],field_readbacks=[],mutation_attempted=False,operation_parameter_setters_attempted=False,GTP_attempted=False,GOP_attempted=False,Import_attempted=False,Save_attempted=False,save_attempted=False,save_readback_verified=False,model_saved=False,CL_export_attempted=False,automatic_replay=False,preCL_exported=False,baseline_generated_operation_count=0,generated_current_context_readable_by_old_loader=False,production_qualified=False,physical_tool_qualified=False,native_units_verified=False,cutting_conditions_qualified=False,island_geometry_verified=False,geometry_sweep_verified=False,**{key:False for key in FLAGS})
    journal=Journal(data['receipt'],data['marker'],r);backend=_backend_factory(sw,clsid,tlb,v,data,r,journal.persist,runtime_check,abi)
    return run_backend(backend,journal,data)


def revoke(r,error):
    r.update(status='uncertain'if r.get('mutation_attempted')or r.get('CL_export_attempted')else'error',runtime_error=_error(error),**{key:False for key in FLAGS});reader._write_receipt(Path(r['request']['receipt_path']),r);return r
