"""Read-only deep-guide inspection and deterministic recipe preflight.

Reuses the corrected ten-path authority, typed parameter reader and catalogue
reader. Does not insert operations, assign tools, change fields, GTP, or Save.
"""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_guide_corrected_reopen as authority
from scripts import sw_cam_guide_group_reader as reader
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_mill_selected_plan_context import read_header
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam import _error
from scripts.sw_cam_rough_firstcut import require

common,group=authority.common,authority.group
SCOPE='SAVED_DEEP_GUIDE_INSPECT_PREFLIGHT_V1'
FEATURES=(80,81)
ORDER=(195,196,267,247,248,271,143,144,320,322,324,326,328)
GENERATED=(267,247,248,271,143,320,322,324,326,328)
REFS=((80,322,324),(81,326,328))
PARAMS={'process_id','expected_document_path','expected_source_sha256','corrected_receipt_path',
 'corrected_receipt_sha256','geometry_path','geometry_sha256','module_sha256','receipt_path','progress_path','acknowledgement'}


def baseline_contract(loaded):
    selected=loaded['guide_parameters'];baseline=selected['baseline'];rows=baseline['operations']
    require(tuple(x['native_id']for x in rows)==ORDER,'Exact protected13 operation order required')
    require(tuple(x['native_id']for x in rows if x['toolpath_generated']is True)==GENERATED,'Exact protected10 generated paths required')
    require(all(type(v)is int and v>0 for x in rows for v in x['toolpath_record_counts']),'Strict positive existing path counts required')
    require(all(type(x['toolpath_generated'])is bool and len(x['toolpath_record_counts'])==int(x['toolpath_generated']) for x in rows),'Exactly one stream per generated operation and none otherwise required')
    require(not any(f in x['linked_feature_ids']for x in rows for f in FEATURES),'Deep guides already have operations; no replay')
    require(selected['document']['needs_save']is False,'Saved clean document required')
    require(group.exact(selected['expected_parameters']['binding'],baseline),'Saved parameter baseline differs')
    require(group.exact(loaded['generated']['saved'],selected['expected_parameters']),'Correction saved snapshot differs')
    return baseline


def geometry_contract(geometry,historical):
    require(geometry.get('width_and_end_radius_verified')is True and geometry.get('native_calls')==0,'Exact offline capsule geometry required')
    require(geometry['source_part_sha256']==historical['saved_source_sha256'],'Geometry and historical native headers differ')
    require(historical['status']=='saved_configuration_no_toolpath' and historical['readback_verified']is True,'Verified historical headers required')
    state=historical['loaded_context_before']['state'];headers={};shapes={}
    for fid in FEATURES:
        rows=[x for x in geometry['features']if x['feature_native_id']==fid]
        hs=[x for x in state['features']if x['geometry']['native_id']==fid]
        require(len(rows)==len(hs)==1 and hs[0]['setup_native_id']==69,'Unique deep feature/header owner69 required')
        row=rows[0];header=hs[0]['geometry'];dim=row['dimensions']
        require(header['suppressed']is False and abs(row['floor_z_mm']-6.5)<1e-9 and abs(row['native_depth_mm']-4.4)<1e-9,'Exact deep feature floor/depth required')
        require(abs(dim['width_mm']-2.4)<1e-9 and abs(dim['end_radius_mm']-1.2)<1e-9,'Exact width2.4 radius1.2 required')
        require(row['header_start_to_exact_floor_vertex_error_mm']<1e-8,'Historical header-to-floor association changed')
        headers[str(fid)]=deepcopy(header);shapes[str(fid)]=deepcopy(row)
    return headers,shapes


def recipe_preflight(loaded,shapes):
    baseline=baseline_contract(loaded);observed=loaded['guide_parameters']['expected_parameters']['parameters']
    recipes=loaded['generated']['recipe'];out=[]
    for fid,roughid,finishid in REFS:
        for oid,kind in ((roughid,0),(finishid,1)):
            params=[x for x in observed if x['operation_native_id']==oid];rows=[x for x in recipes if x['operation_native_id']==oid]
            require(len(params)==len(rows)==1,'Unique saved reference recipe required')
            actual,reference=params[0],rows[0]
            require(actual['read_complete']is True and reference['operation_type']==kind,'Complete actual reference required')
            native=next(x for x in baseline['operations']if x['native_id']==oid)
            require(native['assigned_tool']['native_id']==273 and group.exact(reference['assigned_tool'],native['assigned_tool']),'Saved tool273 identity required')
            tool=actual['tool'];require(tool['dimension_read_complete']is True and tool['generic']['native_id']==273,'Actual tool dimensions required')
            nc=actual['nc']['feeds_compensation']
            require(type(nc['GetCNCComp'])is int and nc['GetCNCComp']==0 and type(nc['GetTlpComp'])is int and nc['GetTlpComp']==1,'Actual CNC0 and Tlp1 required')
            require(type(nc['GetSpndlSpeed'])in(int,float) and math.isfinite(nc['GetSpndlSpeed']) and nc['GetSpndlSpeed']>0
                and type(nc['XYFeed'])in(int,float) and math.isfinite(nc['XYFeed']) and nc['XYFeed']>0,'Actual finite positive spindle/feed required')
            fields=deepcopy(reference['fields'])
            expected_depths=([False,.3],[False,.3])if kind==0 else([.3,False],[.3,False])
            keys=('first_depth','subsequent_depth')if kind==0 else('first_depth','max_depth')
            require(all(group.exact(fields[k],v)for k,v in zip(keys,expected_depths)),'Explicit prior nonpercent0.3 depth recipe required')
            if kind==1:require(fields['bottom_finish']is False and fields['previous_allowance']==.05,'Saved side finish contract required')
            shape=shapes[str(fid)]
            out.append(dict(key='guide'+str(fid)+('_rough'if kind==0 else'_finish'),feature_native_id=fid,operation_type=kind,
                reference_operation_native_id=oid,new_operation_native_id=None,tool_native_id=273,
                reference_tool_dimensions=deepcopy(tool),fields=fields,reference_nc=deepcopy(nc),
                inherited_spindle_and_feed_are_process_qualified=False,
                target_levels=dict(top_world_mm=shape['floor_z_mm']+shape['native_depth_mm'],floor_world_mm=shape['floor_z_mm'],depth_mm=shape['native_depth_mm'],
                    max_axial_step_mm=.3,derive_from_linked_feature=True,do_not_copy_shallow_depth=True,nominal_layer_count=15,
                    full_previous_layer_before_descent=True,actual_deep_CL_chronology_verified=False),
                post_SetTool_policy='Read actual new tool/NC/field values; set only explicit differences and read back each changed field. Never assume SetTool preserves defaults or feeds.'))
    return dict(scope='DEEP_GUIDE_FOUR_RECIPE_PREFLIGHT_V1',rows=out,source_saved_sha256=loaded['generated']['saved_source_sha256'],
        protected_operation_order=list(ORDER),protected_generated_ids=list(GENERATED),append_after_native_id=328,
        maximum_new_definitions=4,expected_final_definition_count=17,maximum_new_GTP=4,maximum_Save=1,
        ready_for_native_mutation=False,catalogue_choices_required=True,created_or_configured=False,
        geometry_accepted=False,production_qualified=False,
        performance_policy='One full saved reference read at inspect boundary. During future setters read only changed fields; complete route/parameter checks after packet and Save, with all10 protected CL streams compared.')


def compile_definition_plan(observation,choices):
    require(observation.get('scope')==SCOPE and observation.get('status')=='observed' and observation.get('phase')=='finished'
      and observation.get('readback_verified')is True and observation.get('read_only')is True,'Completed deep inspection required')
    require(not any(k in observation for k in ('issue','failed_phase','cleanup_issue')),'Uncertain deep inspection')
    require(all(observation.get(k)is False for k in ('mutation_attempted','model_saved','GTP_attempted','setter_attempted')),'Read-only result required')
    require(group.exact(observation['before']['binding'],observation['after_binding']),'Protected route changed')
    require(group.exact(observation['deep_headers_before'],observation['deep_headers_after']),'Deep headers changed')
    plan=deepcopy(observation['preflight']);require(set(choices)=={r['key']for r in plan['rows']},'Four explicit catalogue selections required')
    for row in plan['rows']:
        choice=choices[row['key']];require(type(choice)is dict and set(choice)=={'name','default_operation_id'},'Exact actual catalogue choice required')
        require(type(choice['name'])is str and bool(choice['name'])and type(choice['default_operation_id'])is int and choice['default_operation_id']>0,'Strict actual choice required')
        cat=next(x for x in observation['guides']if x['feature_native_id']==row['feature_native_id'])['defaults_catalogue']
        entries=[e for c in cat if c['operation_type']==row['operation_type']for e in c['entries']if group.exact(e,choice)]
        require(len(entries)==1,'Catalogue choice absent or ambiguous; do not infer TechDB IDs')
        row.update(default_operation_name=choice['name'],default_operation_id=choice['default_operation_id'],feature_owner_setup_native_id=69,operation_setup_native_id=93)
    plan['catalogue_choices_required']=False;plan['definition_choices_observed']=True
    plan['ready_for_native_mutation']=False;plan['remaining']='Separate bounded writer preflight required; this module has no mutation capability.'
    return plan


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']=='inspect_deep_guide_group','Exact deep inspect action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact deep inspect fields required')
    require(p['acknowledgement']=='read_only_deep80_81_catalogues_preserve_corrected13_10','Explicit read-only scope required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict owned PID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute path required')
        if key.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact digest required')
    require(p['module_sha256']==_file_hash(__file__),'Inspect adapter changed')
    loaded,registration,typelib,abi,pin=authority.load_checkpoint(p)
    geometry,gpin=read_pin(p['geometry_path'],p['geometry_sha256'])
    require(len(geometry['source_pins'])==2,'Exact STEP and header receipts required')
    for item in geometry['source_pins']:
        actual=common._pin(item['path'])
        require(actual['sha256']==item['sha256'] and common._key(actual['path'])==common._key(item['path']),'Historical geometry dependency changed')
    hp=geometry['source_pins'][1];historical,_=read_pin(hp['path'],hp['sha256'])
    headers,shapes=geometry_contract(geometry,historical);preflight=recipe_preflight(loaded,shapes)
    extra=[common._pin(__file__),common._pin(reader.catalogue.__file__),gpin]+geometry['source_pins']
    loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],extra)
    require(len(loaded['pins'])<=64 and len(loaded['checkpoint_pins'])<=49,'Bounded read authority required')
    common._check(loaded['checkpoint_pins']);abi['deep_catalogues']=reader.audit_interfaces(typelib,loaded['generated_pin'])
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path'])
    require(progress.suffix.lower()=='.json','JSON progress path required')
    phase=progress.with_name(progress.stem+'.deep_baseline.json')
    outputs=(receipt,progress,phase);protected={common._key(x['path'])for x in loaded['pins']+loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(x)for x in outputs})==len(outputs),'Separate read outputs required')
    for path in outputs:require(path.parent.is_dir()and not path.exists()and not path.is_symlink()and common._key(path)not in protected,'Fresh separate output required')
    return p,dict(loaded=loaded,registration=registration,typelib=typelib,abi=abi,pin=pin,headers=headers,preflight=preflight)


class NativeBackend(authority.ParameterBackend):
    def inspect_guides(self,expected):
        self.boundary();doc=self.doc;state=dict(member='',returned=False,read_index=0)
        stats=dict(binding_native_calls=0,binding_checks=0,binding_elapsed_seconds=0.)
        binding=authority.generation.fast.make_configuration_check(self,doc,stats)
        self.report.setdefault('configuration_checks',[]).append(stats)
        protected=[self.args['expected_document_path'],self.args['receipt_path']]+[p['path']for p in self.loaded['pins']+self.loaded['checkpoint_pins']]
        with reader.journal.ReadProgressJournal(full_persist=self.persist,progress_path=self.args['progress_path'],describe=lambda:dict(state,phase='deep_catalogues'),max_updates=1024,protected_paths=protected)as progress:
            batch=reader.GroupReadBatch(self.sw,self.typelib_path,generated_pin=self.loaded['generated_pin'],process_id=self.args['process_id'],
                expected_document=self.ctx.identity(),source_sha256=self.args['expected_source_sha256'],evidence_pins=self.loaded['pins'],
                verify_evidence=self.ctx.files,verify_owned_process=self.ctx.owned,check_events=self.events,retained_objects=(doc,),
                verify_retained_binding=binding,max_native_calls=300,progress=progress.read,progress_state=state)
            def headers(with_catalogues):
                found_headers={};guides=[]
                for fid in FEATURES:
                    found=batch.read(doc,'GetCWObjectFromID',1,fid)
                    require(type(found)in(tuple,list)and len(found)==2 and found[1]is True,'Exact deep lookup required')
                    header,base=read_header(found[0],doc,batch.read,batch.typed,69)
                    require(group.exact(header,expected[str(fid)]),'Deep header changed from exact geometry proof')
                    found_headers[str(fid)]=header
                    if with_catalogues:guides.append(dict(feature_native_id=fid,header=deepcopy(header),defaults_catalogue=reader.read_catalogues(base,read=batch.read,typed=batch.typed)))
                return found_headers,guides
            try:
                with batch:
                    before,guides=headers(True);after,_=headers(False)
                batch.require_complete();progress.complete()
            finally:self.report['catalogue_read_batch']=batch.summary();self.persist()
        self.boundary();return before,guides,after


def run_backend(backend,p,plan,report,persist):
    try:
        backend.start();report['before_document']=backend.ctx.identity()
        report['phase']='protected_reference_read';report['before']=backend.capture_parameters('deep_baseline')
        require(group.exact(report['before'],plan['loaded']['guide_parameters']['expected_parameters']),'Actual protected reference fields changed')
        report['phase']='deep_catalogues';report['deep_headers_before'],report['guides'],report['deep_headers_after']=backend.inspect_guides(plan['headers'])
        require(group.exact(report['deep_headers_before'],report['deep_headers_after']),'Deep headers changed')
        report['after_binding']=backend.capture_binding('deep_inspect_after')
        require(group.exact(report['before']['binding'],report['after_binding']),'Protected13/10 route changed')
        backend.finish();report['after_document']=backend.ctx.identity()
        require(group.exact(report['before_document'],report['after_document'])and group.exact(report['after_document'],plan['loaded']['guide_parameters']['document']),'Clean document changed')
        require(_file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Source bytes changed')
        common._check(plan['loaded']['pins']);common._check(plan['loaded']['checkpoint_pins'])
        report.update(status='observed',phase='finished',readback_verified=True)
    except Exception as exc:report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:authority.generation.close_checked(backend,report)
        except Exception as exc:report.update(status='error',cleanup_issue=_error(exc),readback_verified=False)
        persist()
    return report


def dispatch_request(request,*,validate_only=False):
    p,plan=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,scope=SCOPE,source_sha256=p['expected_source_sha256'],
        live_pin_count=len(plan['loaded']['pins']),checkpoint_pin_count=len(plan['loaded']['checkpoint_pins']),expected_deep_headers=plan['headers'],preflight=plan['preflight'],interface_audit=plan['abi'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=authority.reopen.sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,status='prepared',phase='prepared',request=p,module_pin=common._pin(__file__),corrected_checkpoint_pin=plan['pin'],
            read_only=True,mutation_attempted=False,model_saved=False,GTP_attempted=False,setter_attempted=False,automatic_retry=False,
            readback_verified=False,geometry_accepted=False,production_qualified=False,ready_for_mutation=False,
            preflight=plan['preflight'],ownership=plan['loaded']['ownership'],interface_audit=plan['abi'],
            live_pins=plan['loaded']['pins'],checkpoint_pins=plan['loaded']['checkpoint_pins'])
        _write_receipt(p['receipt_path'],report,create=True);persist=lambda:_write_receipt(p['receipt_path'],report)
        backend=NativeBackend(plan['loaded'],p,sw,plan['registration']['clsid'],plan['typelib'],report,persist)
        return run_backend(backend,p,plan,report,persist)
