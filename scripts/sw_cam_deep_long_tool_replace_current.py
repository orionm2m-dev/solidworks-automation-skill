"""Fresh scoped replacement with reusable exact-delta group orchestration.

The immutable historical producer remains available for existing receipts.
This module never retries a claimed native action. The default post-generation
contract is exact; an explicit source/tool-bound allowlist can admit selected
XY-feed pairs solely for nominal geometry, never production cutting conditions.
"""
from copy import deepcopy
from pathlib import Path
import json, math, re
from scripts import sw_cam_deep_long_tool_replace as historical
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam import _member, _error
from scripts.sw_cam_rough_firstcut import require

common,group,generation=historical.common,historical.group,historical.generation
writer,config,cl,authority=historical.writer,historical.config,historical.cl,historical.authority
SCOPE='EXISTING_DEEP_GUIDE_LONG_TOOL_REPLACEMENT_V3'
ACTION='replace_existing_deep_guide_tool'
IDS,PAIRS,OLD=historical.IDS,historical.PAIRS,historical.OLD
PARAMS=historical.PARAMS
POLICY_KEY='post_generation_feed_policy'
marker_path=historical.marker_path


def _positive(value):
    return type(value) in (int,float) and math.isfinite(value) and value>0


def _parameter_rows(rows):
    require(type(rows)is list and 1<=len(rows)<=64,'Bounded complete parameter rows required')
    result={}
    for row in rows:
        require(type(row)is dict and type(row.get('operation_native_id'))is int and row['operation_native_id']>0,'Positive strict operation identity required')
        oid=row['operation_native_id'];require(oid not in result,'Duplicate operation parameter group')
        result[oid]=row
    return result


def compile_feed_policy(policy, *, source_sha256, tool_native_id, selected_ids, baseline_rows):
    """Validate a finite sealed allowlist; no observed delta can extend it."""
    require(type(source_sha256)is str and re.fullmatch('[0-9a-f]{64}',source_sha256),'Exact source digest required')
    require(type(tool_native_id)is int and tool_native_id>0,'Positive actual tool identity required')
    require(type(selected_ids)in(list,tuple) and 1<=len(selected_ids)<=32 and all(type(i)is int and i>0 for i in selected_ids)and len(set(selected_ids))==len(selected_ids),'Unique selected operation IDs required')
    rows=_parameter_rows(baseline_rows);require(set(selected_ids)<=set(rows),'Selected operation lacks baseline')
    if policy is None:policy={'mode':'exact'}
    require(type(policy)is dict,'Explicit feed policy object required')
    if policy.get('mode')=='exact':
        require(set(policy)=={'mode'},'Exact mode has no permissions')
        return deepcopy(policy)
    require(set(policy)=={'mode','source_sha256','tool_native_id','operations'} and policy['mode']=='nominal_geometry_only','Exact nominal feed policy fields required')
    require(policy['source_sha256']==source_sha256 and type(policy['tool_native_id'])is int and policy['tool_native_id']==tool_native_id,'Feed policy source/tool differs')
    ops=policy['operations'];require(type(ops)is list and 1<=len(ops)<=len(selected_ids),'Bounded per-operation feed permissions required')
    seen=set()
    for op in ops:
        require(type(op)is dict and set(op)=={'operation_native_id','xy_feed_pairs'},'Only per-operation XY-feed pairs supported')
        oid=op['operation_native_id'];require(type(oid)is int and oid in selected_ids and oid not in seen,'Feed permission outside selected unique operations');seen.add(oid)
        old=rows[oid]['nc']['feeds_compensation']['XYFeed'];require(_positive(old),'Positive finite authoritative baseline feed required')
        pairs=op['xy_feed_pairs'];require(type(pairs)is list and 1<=len(pairs)<=8,'Finite bounded explicit feed pairs required')
        keys=set()
        for pair in pairs:
            require(type(pair)is dict and set(pair)=={'before','after'},'Exact before/after pair required')
            a,b=pair['before'],pair['after'];require(_positive(a)and _positive(b)and group.exact(a,old)and not group.exact(a,b),'Positive finite feed pair must begin at authoritative baseline and change it')
            key=(type(a).__name__,a,type(b).__name__,b);require(key not in keys,'Duplicate feed pair');keys.add(key)
    return deepcopy(policy)


def verify_post_generation_parameters(before, after, *, selected_ids, policy, source_sha256, tool_native_id):
    """Preserve every raw field except exact predeclared XY-feed transitions."""
    oldrows=_parameter_rows(before);newrows=_parameter_rows(after)
    require(list(oldrows)==list(newrows),'Complete parameter identity/order changed')
    checked=compile_feed_policy(policy,source_sha256=source_sha256,tool_native_id=tool_native_id,selected_ids=selected_ids,baseline_rows=before)
    allowed={r['operation_native_id']:r['xy_feed_pairs']for r in checked.get('operations',[])}
    changes=[]
    for oid,old in oldrows.items():
        new=newrows[oid];expected=deepcopy(old)
        a=old['nc']['feeds_compensation']['XYFeed'];b=new['nc']['feeds_compensation']['XYFeed']
        if not group.exact(a,b):
            require(oid in selected_ids and any(group.exact(p,{'before':a,'after':b})for p in allowed.get(oid,[])),'Post-generation XY feed change not explicitly allowed: '+str(oid))
            expected['nc']['feeds_compensation']['XYFeed']=deepcopy(b)
            changes.append({'operation_native_id':oid,'field':'nc.feeds_compensation.XYFeed','before':deepcopy(a),'after':deepcopy(b)})
        require(group.exact(expected,new),'Unlisted post-generation parameter change: '+str(oid))
    return dict(verified=True,mode=checked['mode'],permitted_changes=changes,
        protected_parameter_groups_exact=True,physical_cutting_conditions_qualified=False,production_qualified=False)


def saved_targets(learned, snapshot, wanted):
    rows=_parameter_rows(snapshot['parameters']);result=deepcopy(learned)
    for target in result:
        row=rows[target['operation_native_id']]
        require(group.exact(row['tool'],wanted),'Saved assigned dimensions differ')
        target.update(reference_nc=deepcopy(row['nc']['feeds_compensation']),assigned_tool=deepcopy(wanted['generic']),
            tool_native_id=wanted['generic']['native_id'],reference_tool_dimensions=deepcopy(wanted))
    return result


def baseline_contract(loaded):
    snapshot=loaded['guide_parameters']['expected_parameters'];targets=loaded['deep_targets']
    writer.fields.learned_targets(targets)
    require([t['operation_native_id']for t in loaded['guide_parameters']['targets']]==[322,324,326,328], 'Exact protected shallow reader targets required')
    require(tuple(t['operation_native_id']for t in targets)==IDS,'Exact saved four deep operations required')
    require(tuple((t['feature_native_id'],t['operation_type'])for t in targets)==PAIRS,'Exact deep feature/type mapping required')
    require(tuple(r['native_id']for r in snapshot['binding']['operations'])==OLD+IDS,'Exact saved seventeen-definition route required')
    require([r['operation_native_id']for r in snapshot['parameters']]==[322,324,326,328,*IDS],'Full protected4 plus deep4 parameter groups required')
    cl.contract(snapshot['binding'])
    tool=loaded['configuration_tool'];require(type(tool['native_id'])is int and tool['native_id']>0 and tool['native_id']not in set(OLD+IDS+(273,69,93,80,81,82,83)), 'Unique actually created new tool required')
    require(tool['is_mill_tool']is True and tool['native_read_complete']is True and tool['tool_type_raw']==1 and tool['cut_diameter_native']==2.,'Actual new flat D2 mill tool required')
    dims=loaded['replacement_tool_dimensions'];require(group.exact(dims['generic'],tool),'Exact new native tool projection required')
    for key,value in [('MillToolType',1),('MillToolSubType',3),('EffCutlength',6.),('ShankDia',4.),('OverallLen',40.),('EndRadius',0.)]:
        require(dims['mill'][key]['recorded']is True and type(dims['mill'][key]['raw']) in (int,float) and math.isclose(dims['mill'][key]['raw'],value,rel_tol=0.,abs_tol=1e-8),'OSG3130520 observed field differs: '+key)
    catalogue=loaded['tool_catalogue_ids'];require(len(catalogue)==len(set(catalogue))and catalogue.count(tool['native_id'])==1,'Unique created tool in unchanged catalogue required')
    for t in targets:
        row=next(x for x in snapshot['parameters']if x['operation_native_id']==t['operation_native_id'])
        nc=row['nc']['feeds_compensation']
        require(group.exact(nc,t['reference_nc']),'Authoritative target NC differs from saved baseline')
        require(set(nc)=={'GetSpndlSpeed','GetTlpComp','GetCNCComp','GetRetractType','XYFeed'} and _positive(nc['GetSpndlSpeed'])and _positive(nc['XYFeed'])and nc['GetTlpComp']==1 and nc['GetCNCComp']==0 and nc['GetRetractType']==0,'Supported saved compensation and finite geometry-only feeds required')
    return snapshot

class NativeBackend(historical.NativeBackend):
    def generate(self,target,pending):
        require(group.exact(self.read_nc(target),target['reference_nc']),'Exact restored NC/feed required before GTP')
        generation.status_contract(self.outcome(target),target,None)
        with self.ctx.guard()as guard:
            raw,_=self.target(guard,target);tool,_=read_generic_tool(raw,self.doc,guard.read,guard.typed)
            require(group.exact(tool,self.loaded['configuration_tool']),'New tool changed before GTP')
            mill=guard.typed(raw,'ICWMillOperation')
            return guard.dispatch_once(lambda:_member(mill,'GenerateToolpath'),persist_pending=pending)

class Journal(historical.Journal):
    def _marker_state(self):
        value=super()._marker_state()
        value.update(scope=SCOPE,historical_engine_pin=deepcopy(self.report['historical_engine_pin']))
        return value

class DeepGuideHooks:
    """Scoped geometry adapter; the orchestration and delta contract are reusable."""
    baseline=staticmethod(baseline_contract)
    verify_route=staticmethod(historical.verify_route)
    verify_restorable=staticmethod(historical.verify_restorable)
    verify_configured=staticmethod(historical.verify_parameters)
    verify_protected_cl=staticmethod(historical.verify_protected_cl)
    @staticmethod
    def fields(target):
        return config.ROUGH_FIELDS if target['operation_type']==0 else config.FINISH_FIELDS


def run_replacement_group(backend,journal,loaded,hooks):
    require(not journal.created and not journal.claimed,'A prior or partial replacement attempt must never replay')
    r=journal.report
    r.update(status='error',phase='preflight',actions={},mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,
      SetTool_attempted=False,setter_attempted=False,GTP_attempted=False,save_attempted=False,model_saved=False,readback_verified=False,continuation_ready=False,
      operation_creation_attempted=False,tool_creation_attempted=False,automatic_retry=False,automatic_rollback=False,physical_cutting_conditions_qualified=False,
      geometry_acceptance_complete=False,production_qualified=False,persistence_after_reopen_verified=False)
    try:
        baseline=hooks.baseline(loaded)
        selected=tuple(t['operation_native_id']for t in backend.learned)
        policy=compile_feed_policy(r['request'].get(POLICY_KEY),source_sha256=r['source_sha256'],tool_native_id=loaded['configuration_tool']['native_id'],selected_ids=selected,baseline_rows=baseline['parameters'])
        r['post_generation_feed_policy']=deepcopy(policy)
        journal.create();backend.start();r['before']=backend.capture_snapshot('before',full=True)
        require(group.exact(r['before'],baseline),'Current saved17/14 snapshot changed after tool creation')
        r['before_cl_reference']=deepcopy(loaded['created_saved_cl']);cl._verified(r['before_cl_reference'])
        wanted=loaded['replacement_tool_dimensions'];assigned=[]
        oldrows={x['operation_native_id']:x for x in baseline['parameters']}
        for target in backend.learned:
            oid=target['operation_native_id'];name='SetTool:'+str(oid)
            journal.execute(name,lambda pending:backend.assign(target,pending));backend.refresh_dirty()
            actual=backend.capture_snapshot('assigned_'+str(oid),own=target);assigned.append(oid)
            hooks.verify_route(baseline['binding'],actual['binding'],loaded['configuration_tool'],assigned)
            require(len(actual['parameters'])==1 and actual['parameters'][0]['operation_native_id']==oid,'Immediate own-target readback required')
            own=actual['parameters'][0];hooks.verify_restorable(oldrows[oid],own,wanted);journal.verified(name,own)
            # Restore only actual automatic recipe changes, never silently accept them.
            for spec in hooks.fields(target):
                expected=config.field_value(oldrows[oid],spec);current=config.field_value(own,spec)
                if group.exact(current,expected):continue
                name='Restore:'+str(oid)+':'+spec[0]
                journal.execute(name,lambda pending,spec=spec,expected=expected:backend.set_field(target,spec,expected,pending));backend.refresh_dirty()
                observed=backend.field(target,spec);require(group.exact(observed,expected),'Restored recipe immediate readback differs');journal.verified(name,observed)
            actual_nc=backend.read_nc(target);expected_nc=oldrows[oid]['nc']['feeds_compensation']
            if not group.exact(actual_nc,expected_nc):
                require(group.exact(dict(actual_nc,GetCNCComp=0),expected_nc),'Unrequested NC/feed change')
                name='CNC0:'+str(oid);journal.execute(name,lambda pending:backend.set_nc(target,actual_nc,pending));backend.refresh_dirty()
                observed=backend.read_nc(target);require(group.exact(observed,expected_nc),'NC restoration immediate readback differs');journal.verified(name,observed)
        r['configured']=backend.capture_snapshot('configured',full=True)
        hooks.verify_route(baseline['binding'],r['configured']['binding'],loaded['configuration_tool'],selected)
        hooks.verify_configured(baseline['parameters'],r['configured']['parameters'],wanted);counts={}
        for target in backend.learned:
            oid=target['operation_native_id'];name='GTP:'+str(oid)
            journal.execute(name,lambda pending:backend.generate(target,pending));backend.refresh_dirty()
            observed=backend.outcome(target);generation.status_contract(observed,target,True)
            counts[oid]=deepcopy(observed['record_counts']);journal.verified(name,observed)
        r['generated']=backend.capture_snapshot('generated',full=True)
        hooks.verify_route(baseline['binding'],r['generated']['binding'],loaded['configuration_tool'],selected,counts)
        r['phase']='post_generation_parameter_validation'
        r['completed_gtp_ids']=list(counts)
        r['post_generation_validation']={'verified':False,'requires_explicit_adoption_if_rejected':True,'native_regeneration_must_not_replay':True}
        r['post_generation_validation']=verify_post_generation_parameters(r['configured']['parameters'],r['generated']['parameters'],selected_ids=selected,policy=policy,source_sha256=r['source_sha256'],tool_native_id=loaded['configuration_tool']['native_id'])
        r['generated_state_verified_before_save']=True
        r['save_stage']={};journal.entry('SaveActiveDocument')
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(r['generated'])
            r['saved']=backend.capture_snapshot('saved',full=True);return r['saved']
        def verify(value):require(group.exact(value,r['generated']),'Save changed complete route or parameters')
        def save():
            value=backend.save();entry=r['actions']['SaveActiveDocument'];require(entry['attempted']is True,'Save bypassed pending marker')
            entry.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(value));r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist();return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['source_sha256'],'Save did not advance source hash')
            r.update(saved_source_sha256=value,model_saved=True);journal.persist();return value
        config.save_core.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',r['saved_source_sha256'])
        r['saved_cl']=backend.export('saved',r['saved']['binding']);r['protected_cl']=hooks.verify_protected_cl(r['before_cl_reference'],r['saved_cl']);r['cutcom_review']=cl.verify_no_new_cutcom(r['saved_cl']);r['saved_actual_four_paths_exported']=True;backend.finish()
        r['replacement_checkpoint_context']=dict(source_sha256=r['saved_source_sha256'],prior_source_sha256=r['source_sha256'],tool_creation_pin=deepcopy(r['tool_creation_pin']),
          document=deepcopy(r['source_transition']['document']),configuration=deepcopy(loaded['guide_parameters']['configuration']),saved_snapshot=deepcopy(r['saved']),
          saved_cl=deepcopy(r['saved_cl']),learned_targets=saved_targets(backend.learned,r['saved'],wanted),tool_dimensions=deepcopy(wanted),tool_catalogue_ids=deepcopy(loaded['tool_catalogue_ids']),
          operation_order=[x['native_id']for x in r['saved']['binding']['operations']],generated_ids=[x['native_id']for x in r['saved']['binding']['operations']if x['toolpath_generated']],process_id=r['request']['process_id'],ownership=deepcopy(r['ownership']),persistence_after_reopen_verified=False)
        r['replacement_checkpoint_context']['post_generation_feed_policy']=deepcopy(policy)
        r['replacement_checkpoint_context']['post_generation_validation']=deepcopy(r['post_generation_validation'])
        r.update(status='saved_replacement_review_required',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:
        r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:generation.close_checked(backend,r)
        except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']else'error',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        try:journal.persist()
        except Exception as exc:r['receipt_write_error']=_error(exc);r['continuation_ready']=False
    return r


def prepare_request(request,*,creation_loader=None):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']=='replace_existing_deep_guide_tool','Exact replacement action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)in(PARAMS,PARAMS|{POLICY_KEY}),'Exact replacement parameters required')
    require(p['acknowledgement']=='assign_existing_four_only_geometric_feeds_not_production_qualified','Explicit bounded replacement scope required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict owned process ID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute explicit path required')
        if key.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA256 required')
    require(p['module_sha256']==historical._file_hash(__file__),'Replacement module changed')
    if creation_loader is None:
        from scripts import sw_cam_long_cut_reconciliation as created
        creation_loader=created.load_completed
    context=creation_loader(p['tool_creation_receipt_path'],p['tool_creation_receipt_sha256'],process_id=p['process_id'],expected_document_path=p['expected_document_path'],expected_source_sha256=p['expected_source_sha256'])
    loaded=historical.projection_from_creation(context);baseline=baseline_contract(loaded)
    policy=compile_feed_policy(p.get(POLICY_KEY),source_sha256=p['expected_source_sha256'],tool_native_id=loaded['configuration_tool']['native_id'],selected_ids=IDS,baseline_rows=baseline['parameters'])
    if POLICY_KEY in p:p[POLICY_KEY]=policy
    wanted=common._pin(__file__);old=common._pin(historical.__file__)
    loaded['pins']=common._merge(loaded['pins'],[wanted]);require(len(loaded['pins'])<=64,'Bounded active dependency closure exceeds64')
    loaded['historical_engine_pin']=old
    receipt_data,receipt_pin=authority.read_pin(p['tool_creation_receipt_path'],p['tool_creation_receipt_sha256'])
    require(receipt_data['saved_source_sha256']==p['expected_source_sha256']and receipt_data['process_id']==p['process_id'],'Creation source or owned process differs')
    require(historical._file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Current saved source changed')
    loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],[receipt_pin,common._pin(__file__)])
    require(len(loaded['checkpoint_pins'])<=320,'Bounded checkpoint closure exceeds320')
    common._check(loaded['pins']);common._check(loaded['checkpoint_pins'])
    registration=common.discover_export_registration(loaded,context['long_cut_tool_checkpoint']['registration']['clsid'])
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    require(common._pin(typelib)in loaded['pins'],'Actual CAM typelib changed')
    abi=historical.audit_interfaces(typelib,loaded['generated_pin']);p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name']
    loaded['native_guard_preflight']=historical.guard_constructor_preflight(p,loaded,typelib)
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path'])
    marker=marker_path(p)
    outputs=[receipt,progress,marker,cl._fresh_path(p['saved_cl_path'])]
    protected={common._key(x['path'])for x in loaded['pins']+loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(x)for x in outputs})==len(outputs),'Distinct replacement outputs required')
    for out in outputs:require(not out.exists()and not out.is_symlink()and common._key(out)not in protected,'Fresh nonaliased output and once marker required')
    for out in (receipt,progress,marker):require(out.parent.is_dir(),'Existing diagnostic parent required')
    return p,loaded,registration,typelib,abi,receipt,marker,receipt_pin


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,abi,receipt,marker,pin=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,scope=SCOPE,
      tool_native_id=loaded['configuration_tool']['native_id'],existing_target_ids=list(IDS),protected_definitions=13,protected_paths=10,
      maximum_SetTool=4,maximum_GTP=4,maximum_Save=1,native_guard_preflight=loaded['native_guard_preflight'],historical_engine_pin=loaded['historical_engine_pin'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=historical.authority.reopen.sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),historical_engine_pin=deepcopy(loaded['historical_engine_pin']),
          source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],ownership=deepcopy(loaded['ownership']),
          tool_creation_pin=pin,interface_audit=abi,live_pins=deepcopy(loaded['pins']),checkpoint_pins=deepcopy(loaded['checkpoint_pins']),
          replacement_tool=deepcopy(loaded['replacement_tool_dimensions']))
        journal=Journal(report,receipt,marker);backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        return run_replacement_group(backend,journal,loaded,DeepGuideHooks())
