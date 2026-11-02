"""Bounded append/configure/generate/save engine for two local rough/finish pairs.

Only trusted native adapters implement mutations. This module supplies identities,
protected-prefix checks and a once-only state machine. It exposes no COM entrypoint.
"""
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import hashlib
from scripts import sw_cam_guide_group_definitions as definitions
from scripts import sw_cam_guide_group_configuration as config
from scripts import sw_cam_guide_group_generation as generation
from scripts.sw_cam_rough_firstcut import require

group=config.group
SCOPE='SAVED_LOCAL_ROUGH_FINISH_GROUP_V1'
KEYS=('left_rough','left_finish','right_rough','right_finish')


def ids(rows,key):
    out=[r[key] for r in rows]
    require(all(type(v)is int and 0<v<2**31 for v in out) and len(out)==len(set(out)),
        'Unique positive actual native IDs required')
    return out


def marker_key(source_path,source_sha256):
    require(type(source_sha256)is str and len(source_sha256)==64 and all(c in '0123456789abcdef' for c in source_sha256),'Exact source SHA256 required')
    key=str(Path(source_path).resolve()).replace('\\','/').casefold()
    return hashlib.sha256((SCOPE+'\0'+key+'\0'+source_sha256).encode()).hexdigest()


def validate_plan(plan,baseline):
    require(type(plan)is dict and set(plan)=={'rows','tool','feed_policy','physical_cutting_conditions_qualified'},'Exact selected plan required')
    require(plan['physical_cutting_conditions_qualified']is False,'Provisional conditions remain unqualified')
    ops=baseline['binding']['operations'];old=ids(ops,'native_id')
    require(len(old)==17 and len(baseline['parameters'])==8,'Saved17/8 baseline required')
    require(len([r for r in ops if r['toolpath_generated']is True])==14,'Saved14 path baseline required')
    require(all(type(r['toolpath_generated'])is bool for r in ops),'Strict generated flags required')
    require(set(ids(baseline['parameters'],'operation_native_id'))<=set(old),'Parameter rows outside baseline')
    rows=plan['rows'];require(type(rows)is list and len(rows)==4 and [r['key']for r in rows]==list(KEYS),'Exactly two ordered rough/finish pairs required')
    pairs=[(r['feature_native_id'],r['operation_type'])for r in rows]
    require(all(type(f)is int and 0<f<2**31 and type(k)is int for f,k in pairs),'Strict selected feature/kind IDs required')
    require(pairs==[(pairs[0][0],0),(pairs[0][0],1),(pairs[2][0],0),(pairs[2][0],1)] and pairs[0][0]!=pairs[2][0],'Two distinct selected features required')
    for row in rows:
        fid=row['feature_native_id'];require(str(fid)in baseline['binding']['features'],'Actual saved feature header required')
        require(not any(fid in o['linked_feature_ids']for o in ops),'Feature already has operations; no replay')
        require(type(row['default_operation_id'])is int and row['default_operation_id']>0 and type(row['default_operation_name'])is str and row['default_operation_name'],'Observed exact default choice required')
        require(type(row['expected_levels'])is dict and row['expected_levels'],'Actual expected machining levels required')
        require(row['operation_setup_native_id']==ops[-1]['setup_native_id'],'Exact append setup required')
        specs=config.ROUGH_FIELDS if row['operation_type']==0 else config.FINISH_FIELDS
        require(type(row['fields'])is dict and set(row['fields'])=={s[0]for s in specs},'Exact bounded recipe field set required')
    tool=plan['tool'];require(type(tool)is dict and type(tool.get('native_id'))is int and tool['native_id']>0 and tool.get('native_read_complete')is True,'Actually verified serial tool required')
    policy=plan['feed_policy'];require(type(policy)is dict and set(policy)==set(KEYS),'Explicit per-selected-row feed policy required')
    for transitions in policy.values():
        require(type(transitions)is list and len(transitions)<=8,'Bounded feed transition list required')
        seen=[]
        for pair in transitions:
            require(type(pair)is list and len(pair)==2 and all(type(v)in(int,float) and isfinite(v)and v>0 for v in pair)and pair[0]!=pair[1],'Finite positive nonidentical feed pairs required')
            require(pair not in seen,'Duplicate feed pair');seen.append(pair)
    return deepcopy(plan)


def learned_contract(targets,plan,baseline):
    require(type(targets)is list and len(targets)==4,'Four actual inserted targets required')
    actual=ids(targets,'operation_native_id');require(not set(actual)&set(ids(baseline['binding']['operations'],'native_id')),'New IDs collide with protected route')
    for target,row in zip(targets,plan['rows']):
        require(all(group.exact(target[k],v)for k,v in row.items()),'Learned identity or selected recipe changed')
    return actual


def protect_binding(baseline,current,selected_count):
    a=baseline['operations'];b=current['operations'];require(type(selected_count)is int and 0<=selected_count<=4,'Bounded appended operation count')
    require(len(b)==len(a)+selected_count and group.exact(b[:len(a)],a),'Protected operations changed')
    value=deepcopy(current);value['operations']=value['operations'][:len(a)]
    setup=a[-1]['setup_index'];require(value['operation_setups'][setup]['native_id']==a[-1]['setup_native_id'],'Append setup changed')
    value['operation_setups'][setup]['operation_count']-=selected_count
    require(group.exact(value,baseline),'Protected setup or native feature geometry changed')


def protect_snapshot(baseline,current,selected_count):
    protect_binding(baseline['binding'],current['binding'],selected_count)
    require(len(current['parameters'])==len(baseline['parameters'])+selected_count,'Every protected/selected parameter row required')
    require(group.exact(current['parameters'][:len(baseline['parameters'])],baseline['parameters']),'Protected eight parameter groups changed')
    ids(current['parameters'],'operation_native_id')


def verify_assigned_binding(definitions,current,assigned_ids,wanted):
    require(type(assigned_ids)is list and len(assigned_ids)==len(set(assigned_ids)),'Unique verified assignment IDs required')
    expected=deepcopy(definitions)
    rows={r['native_id']:r for r in expected['operations']}
    require(set(assigned_ids)<=set(rows),'Assignment outside actual definitions')
    for oid in assigned_ids:rows[oid]['assigned_tool']=deepcopy(wanted)
    require(group.exact(expected,current),'SetTool changed another binding or generated a path')


def verify_generation(configured,generated,targets,counts,policy):
    wanted=ids(targets,'operation_native_id');require(set(counts)==set(wanted),'Every selected GTP must be verified')
    value=deepcopy(generated);changed=[];byid={t['operation_native_id']:t for t in targets}
    before={r['operation_native_id']:r for r in configured['parameters']}
    for row in value['binding']['operations']:
        oid=row['native_id']
        if oid not in byid:continue
        require(type(counts[oid])is list and len(counts[oid])==1 and type(counts[oid][0])is int and counts[oid][0]>0,'One verified positive CL stream per target')
        require(row['toolpath_generated']is True and row['toolpath_record_counts']==counts[oid],'Selected GTP result differs')
        old=next(x for x in configured['binding']['operations']if x['native_id']==oid)
        require(old['toolpath_generated']is False and old['toolpath_record_counts']==[],'Cannot regenerate an existing path')
        row.update(toolpath_generated=False,toolpath_record_counts=[])
    for row in value['parameters']:
        oid=row['operation_native_id']
        if oid not in byid:continue
        a=before[oid]['nc']['feeds_compensation']['XYFeed'];b=row['nc']['feeds_compensation']['XYFeed']
        if not group.exact(a,b):
            require(any(group.exact([a,b],p)for p in policy[byid[oid]['key']]),'Unanticipated GTP feed change; retain completed paths and stop before Save')
            row['nc']['feeds_compensation']['XYFeed']=deepcopy(a);changed.append(dict(operation_native_id=oid,before=a,after=b))
    require(group.exact(value,configured),'GTP changed an unapproved field, path or tool')
    return dict(exact_parameters_verified=True,allowed_feed_changes=changed,physical_cutting_conditions_qualified=False)


@dataclass(frozen=True)
class Hooks:
    # Adapter hooks must verify full own parameters and all preserved fields.
    verify_assignment: object
    configure_selected: object
    verify_configured: object
    verify_saved_cl: object


def run_backend(backend,journal,loaded,hooks,*,plan_compiler=None):
    """Once-only append4/assign4/configure/GTP4/Save1. Never retries a claimed action."""
    r=journal.report;baseline=deepcopy(loaded['guide_parameters']['expected_parameters'])
    plan=validate_plan(loaded['local_plan'],baseline)if 'local_plan'in loaded else None
    require(plan is not None or callable(plan_compiler),'Trusted fresh-catalogue plan compiler required')
    r.update(scope=SCOPE,status='error',phase='preflight',actions={},actual_new_ids=[],mutation_attempted=False,
        native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,
        model_saved=False,readback_verified=False,automatic_retry=False,automatic_rollback=False,
        physical_cutting_conditions_qualified=False,production_qualified=False,geometry_accepted=False,
        persistence_after_reopen_verified=False,continuation_ready=False)
    try:
        journal.create();backend.start();r['before']=backend.capture_snapshot('before',full=True)
        require(group.exact(r['before'],baseline),'Fresh saved17/8 baseline differs')
        if plan is None:
            plan=validate_plan(plan_compiler(backend,loaded),baseline)
        r['plan']=deepcopy(plan);journal.persist()
        # Prior saved14 CL is authority; no redundant native before export.
        current=r['before']['binding'];anchor=current['operations'][-1]['native_id'];backend.learned=[]
        for recipe in plan['rows']:
            label='insert:'+recipe['key'];entry=journal.entry(label)
            def returned(raw):
                require(entry['attempted']is True and entry.get('native_dispatch_pending')is True and entry['returned']is False,'Insertion bypassed durable claim')
                entry.update(returned=True,status='returned',native_dispatch_pending=False,returned_interface_pointer=True)
                r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist()
            oid=backend.insert(recipe,anchor,lambda:journal.pending(label),returned)
            entry['actual_native_id']=oid;r['actual_new_ids'].append(oid);journal.persist()
            after=backend.capture_binding('after_'+recipe['key'])
            definition=definitions.verify_one_addition(current,after,recipe,oid,anchor)
            backend.learned.append(dict(deepcopy(recipe),operation_native_id=oid,assigned_tool=deepcopy(definition['assigned_tool'])))
            journal.verified(label,definition);current=after;anchor=oid
        learned_contract(backend.learned,plan,baseline)
        r['definitions']=backend.capture_snapshot('definitions',full=True);protect_snapshot(baseline,r['definitions'],4)
        own={x['operation_native_id']:x for x in r['definitions']['parameters']};assigned_ids=[]
        for target in backend.learned:
            oid=target['operation_native_id'];require(group.exact(own[oid]['levels'],target['expected_levels']),'New actual machining levels differ')
            label='SetTool:'+str(oid);journal.execute(label,lambda pending:backend.assign(target,pending));backend.refresh_dirty()
            target['assigned_tool']=deepcopy(plan['tool'])
            captured=backend.capture_snapshot('after_tool_'+str(oid),own=target)
            protect_binding(baseline['binding'],captured['binding'],4)
            assigned_ids.append(oid);verify_assigned_binding(r['definitions']['binding'],captured['binding'],assigned_ids,plan['tool'])
            require(len(captured['parameters'])==1,'Exactly assigned own parameter group required')
            actual=captured['parameters'][0];hooks.verify_assignment(own[oid],actual,target,loaded)
            require(actual['operation_native_id']==oid and group.exact(actual['tool']['generic'],plan['tool']),'Immediate assigned tool readback differs')
            config.verify_automatic_target(own[oid],actual)
            r.setdefault('after_tool_parameters',{})[str(oid)]=deepcopy(actual);journal.verified(label,actual)
        r['after_tools']=backend.capture_snapshot('after_tools',full=True);protect_snapshot(baseline,r['after_tools'],4)
        verify_assigned_binding(r['definitions']['binding'],r['after_tools']['binding'],assigned_ids,plan['tool'])
        for actual in r['after_tools']['parameters'][8:]:
            require(group.exact(actual,r['after_tool_parameters'][str(actual['operation_native_id'])]),'Another assignment changed an already observed target')
        for target in backend.learned:hooks.configure_selected(backend,journal,target,loaded)
        r['configured']=backend.capture_snapshot('configured',full=True);protect_snapshot(baseline,r['configured'],4)
        hooks.verify_configured(r['after_tools'],r['configured'],backend.learned,loaded)
        counts={}
        for target in backend.learned:
            label='GTP:'+str(target['operation_native_id']);journal.execute(label,lambda pending:backend.generate(target,pending));backend.refresh_dirty()
            outcome=backend.outcome(target);generation.status_contract(outcome,target,True)
            counts[target['operation_native_id']]=deepcopy(outcome['record_counts']);journal.verified(label,outcome)
        r['generated']=backend.capture_snapshot('generated',full=True)
        # Persist completed GTP evidence before checking automatic parameter changes.
        r['completed_gtp_counts']=deepcopy(counts);r['learned_targets']=deepcopy(backend.learned);journal.persist()
        r['generation_verification']=verify_generation(r['configured'],r['generated'],backend.learned,counts,plan['feed_policy'])
        r['save_stage']={};journal.entry('SaveActiveDocument')
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(r['generated'])
            r['saved']=backend.capture_snapshot('saved',full=True);return r['saved']
        def verify(value):require(group.exact(value,r['generated']),'Save changed complete21/12 snapshot')
        def save():
            value=backend.save();entry=r['actions']['SaveActiveDocument'];require(entry['attempted']is True,'Save bypassed pending')
            entry.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(value))
            r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist();return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['source_sha256'],'Saved source did not advance')
            r.update(saved_source_sha256=value,model_saved=True);journal.persist();return value
        config.save_core.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,
            claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',r['saved_source_sha256'])
        r['saved_cl']=backend.export('saved',r['saved']['binding'])
        r['saved_cl_verification']=hooks.verify_saved_cl(loaded['generated']['saved_cl'],r['saved_cl'],backend.learned,r['saved'])
        backend.finish();r.update(status='saved_local_group_review_required',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:
        from scripts.sw_cam import _error
        r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:generation.close_checked(backend,r)
        except Exception as exc:
            from scripts.sw_cam import _error
            r.update(status='uncertain'if r['mutation_attempted']else'error',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        journal.persist()
    return r
