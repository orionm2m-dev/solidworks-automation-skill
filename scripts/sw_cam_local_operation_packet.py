"""Sealed saved-tool continuation for two local rough/finish pairs.

The native engine is reused unchanged. Historical creation/geometry authorities
are checked at phase boundaries; every module executing native reads or writes
remains in the bounded per-call closure. No request supplies executable code.
"""
from copy import deepcopy
from functools import partial
from pathlib import Path
import importlib
import hashlib
import inspect
import json
import re
import sys
from scripts import sw_cam_local_operation_assembly as assembly
from scripts import sw_cam_local_operation_group as engine
from scripts import sw_cam_local_operation_context as projection
from scripts import sw_cam_local_operation_native as native
from scripts import sw_cam_local_operation_cl as cl
from scripts import sw_cam_local_operation_nc as nc
from scripts import sw_cam_local_operation_recipe as recipe_hooks
from scripts import sw_cam_local_startpoint as entry
from scripts import sw_cam_root_microtool_nc as micro
from scripts import sw_cam_serial_flat_tool as serial
from scripts import sw_cam_mixed_root_finish as mixed
from scripts import sw_cam_deep_long_tool_replace as guard_reuse
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_mill_selected_plan_evidence import clean_events

common=guard_reuse.common
group=engine.group
SCOPE=engine.SCOPE
ACTION='create_local_rough_finish_group'
ACK='create4_assign4_configure_explicit_entry_and_nc_generate4_save1_export1_preserve17_8_14_no_gop_no_replay'
PARAMS={'process_id','expected_document_path','expected_source_sha256',
 'tool_receipt_path','tool_receipt_sha256','source_backup_path','source_backup_sha256',
 'recipe_path','recipe_sha256','choices','feed_policy','module_sha256',
 'receipt_path','progress_path','saved_cl_path','acknowledgement'}

# Fixed executable closure. Imported historical factories are not invoked by the
# retained native adapter; their immutable pins remain in phase_proof_pins.
LIVE_MODULES=tuple('sw_cam sw_cam_generation sw_cam_comtypes sw_cam_thread sw_cam_rough_firstcut\nsw_cam_dispatch_guard sw_cam_read_batch_guard sw_cam_route_read_batch\nsw_cam_mill_inventory sw_cam_mill_levels sw_cam_mill_qualification\nsw_cam_mill_route_context sw_cam_mill_feature_context sw_cam_mill_selected_plan_context\nsw_cam_upper_cone_feature sw_cam_feature_sketch sw_cam_mill_units_qualification sw_cam_configuration_binding sw_cam_events\nsw_operation_guard sw_executable_launch sw_connect sw_cam_grouped_face_recipe\nsw_cam_read_progress_journal sw_cam_chamfer_clearance_read sw_cam_chamfer_nc_planes\nsw_cam_circle_lifecycle_evidence sw_cam_face_interfaces sw_cam_finish_observation\nsw_cam_finish_lead_observation sw_cam_fresh_finish_field_batch\nsw_cam_fresh_finish_protected_read sw_cam_guide_field_read_batch\nsw_cam_guide_finish_compensation sw_cam_guide_generated_reopen\nsw_cam_guide_group_configuration sw_cam_guide_group_definitions\nsw_cam_guide_group_generation sw_cam_guide_group_parameters sw_cam_guide_group_reader\nsw_cam_guide_group_reopen sw_cam_deep_guide_group sw_cam_pocket_pair_read\nsw_cam_pocket_rough_apply sw_cam_rough_entry_parameters sw_cam_rough_startpoint_read\nsw_cam_ud14_save sw_cam_local_operation_assembly sw_cam_local_operation_group\nsw_cam_local_operation_context sw_cam_local_operation_native sw_cam_local_operation_cl\nsw_cam_local_operation_nc sw_cam_local_operation_recipe sw_cam_local_startpoint\nsw_cam_root_microtool_nc sw_cam_local_operation_packet'.split())


def _sha(value):
    require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact lowercase SHA256 required')
    return value


def read_json_pin(path,digest,*,limit=1048576):
    p=Path(path);require(p.is_absolute()and p.is_file()and not p.is_symlink()and 0<p.stat().st_size<=limit,'Bounded absolute evidence file required')
    data=p.read_bytes();require(hashlib.sha256(data).hexdigest()==_sha(digest)and _file_hash(p)==digest,'Evidence bytes or current digest differ')
    def pairs(rows):
        out={}
        for key,value in rows:
            require(key not in out,'Duplicate evidence JSON key');out[key]=value
        return out
    value=json.loads(data.decode('utf-8-sig'),object_pairs_hook=pairs,
        parse_constant=lambda _:(_ for _ in()).throw(ValueError('Nonfinite JSON value')))
    require(type(value)is dict,'Object evidence required')
    return value,common._pin(p)


def marker_path(p):
    return common.local_evidence_root()/('local_operation_group_'+engine.marker_key(p['expected_document_path'],p['expected_source_sha256'])+'.json')


def validate_choices_and_policy(p):
    choices=p['choices'];policy=p['feed_policy']
    require(type(choices)is dict and set(choices)==set(engine.KEYS),'Four exact default selection keys required')
    for row in choices.values():
        require(type(row)is dict,'Default selection object required')
        if row=={'selection':'unique_native_default'}:continue
        require(set(row)=={'name','default_operation_id'}and type(row['name'])is str and row['name']and type(row['default_operation_id'])is int and row['default_operation_id']>0,'Exact default name/ID required')
    require(type(policy)is dict and set(policy)==set(engine.KEYS),'Four explicit feed policies required')
    from math import isfinite
    for rows in policy.values():
        require(type(rows)is list and len(rows)<=8,'Bounded explicit feed transitions required')
        seen=[]
        for pair in rows:
            require(type(pair)is list and len(pair)==2 and all(type(v)in(int,float)and isfinite(v)and v>0 for v in pair)and pair[0]!=pair[1]and pair not in seen,'Exact positive finite feed pairs required')
            require(pair[0]==35.,'Permission must begin at the explicitly configured XY feed')
            seen.append(pair)


def native_source_audit(live):
    """Audit actual inherited callable source files, not only import names."""
    wanted={common._key(v['path'])for v in live}
    methods=[]
    for cls,names in (
      (NativeBackend,('start','boundary','refresh_dirty','save','saved_hash','finish','close','events','batch','target','typed_field','owner','set_field','capture_snapshot','capture_binding','insert','assign','generate','outcome','export','verify_catalogue','observe_default_catalogues')),
      (entry.EntryAdapter,('typed','create_point','create_position','point_state','position_state','created_type','set_point_position','attach_point')),
      (assembly.Journal,('create','entry','pending','execute','verified','persist'))):
        for name in names:
            method=getattr(cls,name);path=inspect.getsourcefile(method)
            require(path is not None and common._key(path)in wanted,'Executed native/lifecycle source absent from live closure: '+name)
            methods.append(dict(owner=cls.__name__,member=name,path=str(Path(path).resolve())))
    from scripts import sw_cam_circle_lifecycle_evidence as identity
    from scripts import sw_cam_mill_qualification as bootstrap
    for name,fn in [('raw_part_identity',identity.raw_part_identity),('identity_nonnull',identity._nonnull),('identity_native_call',identity.call),('bootstrap',bootstrap._bootstrap),('document_snapshot',bootstrap.document_snapshot)]:
        path=inspect.getsourcefile(fn)
        require(path is not None and common._key(path)in wanted,'Indirect native identity source absent: '+name)
        methods.append(dict(owner='indirect_guard_identity',member=name,path=str(Path(path).resolve())))
    return dict(status='actual_callable_sources_covered',methods=methods,live_module_count=len(LIVE_MODULES))


def partition_pins(context,loaded,extra_pins):
    require(len(LIVE_MODULES)==len(set(LIVE_MODULES)),'Duplicate executable module role')
    modules=[importlib.import_module('scripts.'+n)for n in LIVE_MODULES]
    live=[common._pin(m.__file__)for m in modules]
    inherited=common._merge(context['pins'],context['offline_export_proof_pins'],
        context.get('checkpoint_pins',[]),loaded.get('checkpoint_pins',[]),extra_pins)
    generated=loaded['generated_pin'];metadata=[v for v in inherited if Path(v['path']).name.lower()=='camworks.tlb']
    require(len(metadata)==1,'One exact native CAM typelib required')
    live=common._merge(live,[generated],metadata)
    # Every already imported project dependency is pinned as phase proof, even if
    # a historical loader previously carried it outside the native closure.
    imported=[common._pin(m.__file__)for name,m in tuple(sys.modules.items())
        if name.startswith('scripts.')and getattr(m,'__file__',None)and Path(m.__file__).suffix=='.py']
    allpins=common._merge(inherited,imported,live)
    keys={common._key(v['path'])for v in live}
    source_key=common._key(loaded['guide_parameters']['document']['path'])
    source_rows=[v for v in allpins if common._key(v['path'])==source_key]
    require(all(v['sha256']==context['source_sha256']for v in source_rows),'Initial mutable source pin differs')
    phase=[v for v in allpins if common._key(v['path'])not in keys and common._key(v['path'])!=source_key]
    loaded['initial_source_pins']=source_rows
    require(1<=len(live)<=63 and len(phase)<=1024,'Bounded live/source and phase proof closure required')
    common._check(allpins)
    loaded.update(pins=live,checkpoint_pins=[],phase_proof_pins=phase)
    loaded['pin_partition']=dict(live_file_count=len(live),maximum_with_source=len(live)+1,
        phase_proof_count=len(phase),initial_mutable_source_pin_count=len(source_rows),all_evidence_preserved=True,
        phase_checkpoints=['prepare','before_native_start','before_save','after_export_and_cleanup'],
        role='native_callable_and_guard_dependencies_live_historical_and_pure_authorities_at_phase_boundaries')
    loaded['native_source_audit']=native_source_audit(live)
    return loaded['pin_partition']


def phase_proofs(loaded,report,label,persist):
    common._check(loaded['phase_proof_pins'])
    report.setdefault('phase_proof_checks',[]).append(dict(phase=label,verified=True,count=len(loaded['phase_proof_pins'])))
    persist()


class NativeBackend(native.NativeBackend):
    """Only add complete offline-proof boundaries; native methods are reused."""
    def start(self):
        phase_proofs(self.loaded,self.report,'before_native_start',self.persist)
        return super().start()
    def save(self):
        phase_proofs(self.loaded,self.report,'before_save',self.persist)
        return super().save()
    def finish(self):
        value=super().finish()
        phase_proofs(self.loaded,self.report,'after_export_and_cleanup',self.persist)
        return value


def run_once(backend,journal,loaded,*,plan_compiler=None):
    # Must precede the frozen engine's report reset and its finally/persist path.
    require(not journal.created and not journal.claimed,'Existing or claimed Journal cannot be re-entered')
    require(not journal.receipt.exists()and not journal.marker.exists(),'Prior group evidence forbids a fresh wrapper replay')
    return engine.run_backend(backend,journal,loaded,assembly.hooks(),plan_compiler=plan_compiler)


def prepare_request(request,*,creation_loader=None):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Exact local group action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact local group parameter set required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict selected process ID required')
    require(p['acknowledgement']==ACK,'Explicit bounded native action scope required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute explicit path required')
        if key.endswith('_sha256'):_sha(value)
    require(p['module_sha256']==_file_hash(__file__),'Installed local group producer changed')
    validate_choices_and_policy(p)
    require(p['source_backup_sha256']==p['expected_source_sha256'],'Backup must match current authoritative source')
    require(common._key(p['source_backup_path'])!=common._key(p['expected_document_path']),'Distinct immutable source backup required')
    for name in ('expected_document_path','source_backup_path'):
        path=Path(p[name]);require(path.is_file()and not path.is_symlink()and _file_hash(path)==p['expected_source_sha256'],'Saved source/backup differs')
    recipe,recipe_pin=read_json_pin(p['recipe_path'],p['recipe_sha256'])
    loader=serial.load_completed if creation_loader is None else creation_loader
    outer=loader(str(Path(p['tool_receipt_path']).resolve()),p['tool_receipt_sha256'],process_id=p['process_id'],
        expected_document_path=p['expected_document_path'],expected_source_sha256=p['expected_source_sha256'])
    require(outer['source_sha256']==p['expected_source_sha256']and outer['ownership']['process_id']==p['process_id'],'Completed tool source/PID differs')
    loaded=projection.project_context(outer,recipe,None,p['choices'],verify_feature=mixed.verify_pocket,feed_policy=p['feed_policy'])
    require(common._key(loaded['guide_parameters']['document']['path'])==common._key(p['expected_document_path']),'Current document path differs')
    loaded['tool_catalogue_ids']=engine.ids(outer['serial_flat_catalogue'],'native_id')
    loaded['source_sha256']=outer['source_sha256']
    source_pin=common._pin(p['source_backup_path']);receipt_pin=common._pin(p['tool_receipt_path'])
    require(receipt_pin['sha256']==p['tool_receipt_sha256'],'Completed tool receipt changed')
    partition_pins(outer,loaded,[source_pin,receipt_pin,recipe_pin,common._pin(__file__)])
    registration=common.discover_export_registration(loaded,outer['registration']['clsid'])
    require(group.exact(registration,outer['registration']),'Checked native registration changed')
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    require(common._pin(typelib)in loaded['pins'],'Current native type library differs')
    abi=dict(generation=native.generation.audit(typelib,loaded['generated_pin']),
        nc=micro.audit(typelib,loaded['generated_pin']))
    p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name']
    loaded['native_guard_preflight']=guard_reuse.guard_constructor_preflight(p,loaded,typelib)
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path']);marker=marker_path(p)
    outputs=[receipt,progress,marker,cl.prior._fresh_path(p['saved_cl_path'])]
    protected={common._key(v['path'])for v in loaded['pins']+loaded['phase_proof_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(v)for v in outputs})==len(outputs),'Separate group output paths required')
    for out in outputs:
        require(not out.exists()and not out.is_symlink()and common._key(out)not in protected,'Fresh nonaliased outputs and source-only marker required')
    for out in outputs[:3]:require(out.parent.is_dir(),'Existing diagnostic output parent required')
    loaded.update(dispatch_ready=True,local_verified_context=deepcopy(outer),local_recipe=deepcopy(recipe),sealed_choices=deepcopy(p['choices']),sealed_feed_policy=deepcopy(p['feed_policy']))
    return p,loaded,outer,registration,typelib,abi,receipt,marker,receipt_pin,recipe_pin


def validate_completed(report,loaded):
    r=report;baseline=loaded['guide_parameters']['expected_parameters']
    require(r['scope']==SCOPE and r['status']=='saved_local_group_review_required'and r['phase']=='finished','Completed local group receipt required')
    require(r['model_saved']is True and r['readback_verified']is True and r['continuation_ready']is True and r.get('native_dispatch_pending')is False,'Saved verified nonpending group required')
    for key in ('production_qualified','physical_cutting_conditions_qualified','geometry_accepted','persistence_after_reopen_verified'):
        require(r[key]is False,'Unqualified machining and persistence boundaries must remain explicit')
    require(not r.get('issue')and not r.get('cleanup_issue'),'No unresolved native or cleanup failure permitted')
    clean_events(r)
    require(group.exact(r['before'],baseline),'Exact complete baseline required')
    plan=engine.validate_plan(r['plan'],baseline);targets=r['learned_targets']
    compiled=projection.project_context(loaded['local_verified_context'],loaded['local_recipe'],r['actual_default_catalogues'],r['request']['choices'],verify_feature=mixed.verify_pocket,feed_policy=r['request']['feed_policy'])
    require(group.exact(compiled['local_plan'],plan),'Final plan differs from actual catalogues and sealed choices/recipe')
    ids=engine.learned_contract(targets,plan,baseline)
    require(r['actual_new_ids']==ids and group.exact(plan['feed_policy'],r['request']['feed_policy']),'Learned IDs or sealed feed policy changed')
    engine.protect_snapshot(baseline,r['definitions'],4);engine.protect_snapshot(baseline,r['after_tools'],4)
    engine.protect_snapshot(baseline,r['configured'],4)
    engine.verify_assigned_binding(r['definitions']['binding'],r['after_tools']['binding'],ids,loaded['configuration_tool'])
    recipe_hooks.verify_configured(r['after_tools'],r['configured'],targets,loaded)
    counts={int(k):v for k,v in r['completed_gtp_counts'].items()}
    engine.verify_generation(r['configured'],r['generated'],targets,counts,plan['feed_policy'])
    require(group.exact(r['generated'],r['saved']),'Saved complete state changed')
    actions=r['actions'];required=['insert:'+k for k in engine.KEYS]+['SetTool:'+str(i)for i in ids]+['GTP:'+str(i)for i in ids]+['SaveActiveDocument']
    allowed=set(required)
    for target in targets:
        oid=str(target['operation_native_id']);specs=engine.config.ROUGH_FIELDS if target['operation_type']==0 else engine.config.FINISH_FIELDS
        required += [oid+':'+spec[0]for spec in specs]+[oid+':NC:GetSpndlSpeed',oid+':NC:XYFeed']
        if target['operation_type']==0:required += [oid+':entry:'+name for name in ('CreateStartPointInstance','CreatePosition','SetPointCoordinates','SetPointPosition','AddStartPoint','SetStartPointList')]
        allowed.add('CNC0:'+oid)
    allowed.update(required)
    require(set(required)<=set(actions)<=allowed,'Exact declared action set required; no unrelated action may be adopted')
    for name,row in actions.items():
        require(row.get('readback_verified')is True and row.get('native_dispatch_pending',False)is False,'All actions must have complete readback')
        if row['attempted']is True:require(row['returned']is True,'Every claimed native action must return')
        else:require(row.get('observed',{}).get('already_satisfied')is True,'Only explicit already-satisfied actions may be unclaimed')
    for prefix,total in [('insert:',4),('SetTool:',4),('GTP:',4)]:
        require(sum(name.startswith(prefix)for name in actions)==total,'Bounded native action count differs')
    native_required=['insert:'+k for k in engine.KEYS]+['SetTool:'+str(i)for i in ids]+['GTP:'+str(i)for i in ids]+['SaveActiveDocument']
    native_required += [str(t['operation_native_id'])+':entry:'+name for t in targets if t['operation_type']==0 for name in ('CreateStartPointInstance','CreatePosition','SetPointCoordinates','SetPointPosition','AddStartPoint','SetStartPointList')]
    require(all(actions[n]['attempted']is True and actions[n]['returned']is True for n in native_required),'Required actions must actually execute once')
    definitions={row['native_id']:row for row in r['definitions']['binding']['operations']}
    for target in targets:
        oid=target['operation_native_id'];inserted=actions['insert:'+target['key']]
        require(type(inserted.get('actual_native_id'))is int and inserted['actual_native_id']==oid
            and group.exact(inserted['observed'],definitions[oid]),'Insert action readback differs from actual learned definition')
        assigned=actions['SetTool:'+str(oid)]['observed']
        require(group.exact(assigned,r['after_tool_parameters'][str(oid)]),'SetTool action readback differs from immediate own snapshot')
        outcome=actions['GTP:'+str(oid)]['observed']
        native.generation.status_contract(outcome,target,True)
        require(group.exact(outcome['record_counts'],counts[oid]),'GTP action readback differs from completed path counts')
    new=_sha(r['saved_source_sha256']);require(new!=r['source_sha256'],'Saved source must advance')
    require(actions['SaveActiveDocument']['observed']==new,'Save readback hash differs')
    require(r['source_transition']['source_before_sha256']==r['source_sha256']and r['source_transition']['source_after_sha256']==new and type(r['source_transition']['strict_save_return'])is int and r['source_transition']['strict_save_return']==0,'Exact native source transition required')
    require(r['source_transition']['document']['needs_save']is False,'Saved document must be clean')
    proof=cl.verify_saved(loaded['generated']['saved_cl'],r['saved_cl'],targets,r['saved'])
    require(r['saved_cl']['source_sha256']==new,'CL export must refer to new saved source')
    require([x['phase']for x in r['phase_proof_checks']]==['before_native_start','before_save','after_export_and_cleanup']and all(x['verified']is True for x in r['phase_proof_checks']),'Whole phase authority checks required')
    return dict(status='saved_local_group_authority_verified',operation_ids=ids,
        protected_operations=17,protected_parameters=8,protected_cl_streams=14,
        saved_operations=21,saved_parameters=12,saved_cl_streams=18,cl_verification=proof,
        source_sha256=new,nominal_geometry_accepted=False,physical_cutting_conditions_qualified=False,production_qualified=False)


def dispatch_request(request,*,validate_only=False):
    p,loaded,outer,registration,typelib,abi,receipt,marker,pin,recipe_pin=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,scope=SCOPE,
        expected_counts=dict(operations=21,parameters=12,paths=18,tools=21),
        pin_partition=loaded['pin_partition'],native_guard_preflight=loaded['native_guard_preflight'],
        feature_ids=[v['header']['native_id']for v in loaded['root_pocket_full_features']],tool_native_id=loaded['configuration_tool']['native_id'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['phase_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=deepcopy(p),module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],
            ownership=deepcopy(loaded['ownership']),tool_receipt_pin=pin,recipe_pin=recipe_pin,
            live_pins=deepcopy(loaded['pins']),phase_proof_pins=deepcopy(loaded['phase_proof_pins']),
            pin_partition=deepcopy(loaded['pin_partition']),native_source_audit=deepcopy(loaded['native_source_audit']),
            interface_audit=abi,tool_dimensions=deepcopy(loaded['local_tool_dimensions']))
        journal=assembly.Journal(report,receipt,marker)
        backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist,before_generate=nc.before_generate,exporter=cl.export_saved)
        compile_plan=partial(assembly.compile_in_session,verified_context=outer,recipe=loaded['local_recipe'],choices=p['choices'],feed_policy=p['feed_policy'],verify_feature=mixed.verify_pocket)
        result=run_once(backend,journal,loaded,plan_compiler=compile_plan)
        if result['readback_verified']is True:
            try:
                result['terminal_verification']=validate_completed(result,loaded)
                result['saved_checkpoint']=dict(source_path=p['expected_document_path'],source_sha256=result['saved_source_sha256'],document=deepcopy(result['source_transition']['document']),
                    configuration=deepcopy(loaded['guide_parameters']['configuration']),snapshot=deepcopy(result['saved']),saved_cl=deepcopy(result['saved_cl']),
                    learned_targets=deepcopy(result['learned_targets']),tool_catalogue=deepcopy(loaded['serial_flat_catalogue']),tool_dimensions=deepcopy(loaded['local_tool_dimensions']),
                    full_native_features=deepcopy(loaded['root_pocket_full_features']),feature_specs=deepcopy(loaded['root_pocket_specs']),
                    current_counts=dict(operations=21,parameters=12,paths=18,tools=21),nominal_geometry_accepted=False,production_qualified=False)
            except Exception as exc:
                from scripts.sw_cam import _error
                result.update(status='uncertain',readback_verified=False,continuation_ready=False,terminal_issue=_error(exc))
            journal.persist()
        return result
