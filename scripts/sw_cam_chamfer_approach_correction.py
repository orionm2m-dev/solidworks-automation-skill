"""Bounded approach-only correction of one saved generated Contour operation."""
from copy import deepcopy
from pathlib import Path
import json
import math
import re
from scripts import sw_cam_chamfer_generate as generation
from scripts import sw_cam_chamfer_exports as exports
from scripts import sw_cam_chamfer_nc_planes as planes
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_ud14_save import run_one_existing_save

common, group = exports.common, exports.group
SCOPE = 'SAVED_CONTOUR_APPROACH_CORRECTION_V1'
SPECS = {
 'clearance_use_setup': ('nc','ICWNCParam','GetClrPlaneUseSetupStatus','SetClrPlaneUseSetupStatus','method','bool'),
 'clearance_parameters': ('local_planes','ICWNCParam','GetClrPlanePrms','SetClrPlanePrms','method','plane'),
 'feed_plane_distance': ('nc','ICWNCParam3','FeedPlaneDistance','FeedPlaneDistance','property','double'),
 'same': ('lead','ICWLeadInOut','GetIsSameLeadinout','SetIsSameLeadinout','method','bool'),
 'type': ('lead','ICWLeadInOut','LeadType','LeadType','property','long'),
 'radius': ('lead','ICWLeadInOut','GetArcRadius2','SetArcRadius2','method','triple'),
 'length': ('lead','ICWLeadInOut','GetLeadAmt2','SetLeadAmt2','method','triple'),
}
FORBIDDEN = ('assignment_attempted','feature_edit_attempted','tool_edit_attempted',
 'operation_creation_attempted','global_generation_attempted','GOP_attempted',
 'automatic_retry','automatic_replay','automatic_rollback','production_qualified',
 'geometry_acceptance_complete')


def scalar_value(value, kind):
    numeric = lambda v: type(v) is float and math.isfinite(v)
    if kind == 'bool': valid = type(value) is bool
    elif kind == 'long': valid = type(value) is int and -(2**31) <= value < 2**31
    elif kind == 'double': valid = numeric(value)
    elif kind == 'plane':
        valid = type(value) is list and len(value)==2 and numeric(value[0]) and type(value[1]) is int
    else:
        valid = type(value) is list and len(value)==3 and numeric(value[0]) and type(value[1]) is bool and numeric(value[2])
    require(valid,'Exact finite native field shape required: '+kind)
    return deepcopy(value)


def field_path(change):
    require(type(change) is dict and set(change)=={'key','side','before','after'},'Exact change fields required')
    require(change['key'] in SPECS,'Setter outside approach-only allowlist')
    section,_,getter,_,_,kind = SPECS[change['key']]
    require(change['side'] in ('lead_in','lead_out') if section=='lead' else change['side'] is None,
            'Exact lead side required')
    for key in ('before','after'):scalar_value(change[key],kind)
    return ('leads',change['side'],getter) if section=='lead' else (section,getter)


def at(state,path):
    for key in path:state=state[key]
    return state


def put(state,path,value):
    for key in path[:-1]:state=state[key]
    state[path[-1]]=deepcopy(value)


def planned_states(plan):
    require(plan.get('scope')==SCOPE and plan.get('production_qualified') is False,'Bounded qualification plan required')
    target=plan['target']
    require(type(target) is dict and set(target)=={'operation_native_id','feature_native_id','tool_native_id'}
        and all(type(v) is int and v>0 for v in target.values()),'Exact positive target identities required')
    require(type(plan['changes']) is list and 1<=len(plan['changes'])<=10,'One bounded grouped correction required')
    state=deepcopy(plan['baseline']);states=[deepcopy(state)];seen=set()
    for change in plan['changes']:
        path=field_path(change)
        require(path not in seen and group.exact(at(state,path),change['before'])
            and not group.exact(change['before'],change['after']),'Duplicate/stale/unchanged field recipe')
        seen.add(path);key=change['key']
        if key=='feed_plane_distance':
            require(state['nc']['GetUseCurrentMachiningDepthForFeedPlane'] is True
                and 0<change['after']<=2.,'Semantic current-depth feed plane required')
        if key=='clearance_use_setup':
            require(change['before'] is True and change['after'] is False,'Only local clearance selection supported')
        if key=='clearance_parameters':
            require(state['nc']['GetClrPlaneUseSetupStatus'] is False
                and change['after'][1]==change['before'][1] and 0<change['after'][0]<=2.,
                'Preserve observed clearance basis after local selection')
        if key=='same':
            require(change['before'] is True and change['after'] is False,'Only explicit lead unlink supported')
        if key in ('type','radius','length'):
            require(all(state['leads'][s]['GetIsSameLeadinout'] is False for s in ('lead_in','lead_out')),
                    'Detach shared definitions before independent correction')
            require(state['leads'][change['side']]['ArcAngle']==90.,'Existing ninety-degree arc required')
            wanted=1 if key=='type' else [1.,False,0.] if key=='radius' else [0.,False,0.]
            require(group.exact(change['after'],wanted),'Only reviewed R1 arc/zero-line correction supported')
        put(state,path,change['after']);states.append(deepcopy(state))
    require(group.exact(state,plan['expected']),'Expected projection differs from explicit changes')
    require(plan.get('entry_review_required') is True and plan.get('protected_paths_review_required') is True,
            'Corrected CL and protected-path review must remain explicit')
    return states


def validate_plan(plan,loaded,baseline):
    states=planned_states(plan);target=loaded['configured_contour']
    require(plan['target']==dict(operation_native_id=target['native_id'],feature_native_id=target['feature_native_id'],
        tool_native_id=target['tool_native_id']) and plan['source_sha256']==loaded['source_sha256'],'Plan identity differs')
    require(group.exact(states[0],baseline),'Actual saved NC/lead baseline differs')
    require(plan.get('geometry_precheck',{}).get('accepted_for_native_trial') is True
        and plan['geometry_precheck'].get('production_qualified') is False,'Reviewed nominal entry-envelope prerequisite required')
    common._check(plan['source_pins'])
    return states


def verify_route(reference,actual,operation_id,phase,*,saved_sha=None):
    require(phase in ('baseline','configured','generated'),'Exact route phase required')
    a,b=deepcopy(reference),deepcopy(actual)
    for state in (a,b):
        require(state['operation_count']==8 and len(state['operations'])==8 and len(state['features'])==21,
                'Exact eight-operation route required')
    old=next(x for x in a['operations'] if x['native_id']==operation_id)
    new=next(x for x in b['operations'] if x['native_id']==operation_id)
    require(old['toolpath_generated'] is True and old['toolpath_record_counts'],'Saved generated target required')
    if phase=='configured':
        require((new['toolpath_generated'] is False and new['toolpath_record_counts']==[]) or
            (new['toolpath_generated'] is True and group.exact(new['toolpath_record_counts'],old['toolpath_record_counts'])),
            'Setter may retain or invalidate only old target path')
    if phase=='generated':
        require(new['toolpath_generated'] is True and type(new['toolpath_record_counts']) is list
            and len(new['toolpath_record_counts'])==1 and all(type(x) is int and 0<x<=100000 for x in new['toolpath_record_counts']),
            'Positive regenerated target path required')
    counts=deepcopy(new['toolpath_record_counts'])
    if phase!='baseline':
        for key in ('toolpath_generated','toolpath_record_counts'):new[key]=deepcopy(old[key])
        require(type(b['document']['needs_save']) is bool,'Strict dirty flag required')
        b['document']['needs_save']=a['document']['needs_save']
    if saved_sha is not None:
        require(actual['document']['needs_save'] is False and b['saved_file_sha256']==saved_sha,
                'Saved clean document/hash required')
        b['saved_file_sha256']=a['saved_file_sha256']
    require(group.exact(a,b),'Protected setup, feature, tool binding or route changed')
    return counts


def verify_capture(loaded,before,value,*,phase,expected_approach,saved_sha=None):
    counts=verify_route(before['state'],value['state'],loaded['configured_contour']['native_id'],phase,saved_sha=saved_sha)
    for key in ('settings','binding','units'):
        require(group.exact(before[key],value[key]),'Protected settings changed: '+key)
    # The actual Contour reader returns finish/level_state, not NC planes.
    # NC and lead changes are independently checked in the approach projection.
    require(group.exact(before['selected_defaults'],value['selected_defaults']),
            'Protected Contour settings changed')
    require(group.exact(value['approach'],expected_approach),'Unapproved NC/lead field changed')
    if 'catalogue' in value:
        require(len(value['catalogue'])==18 and group.exact(value['catalogue'],before['catalogue'])
            and group.exact(value['selected_feature'],before['selected_feature']),'Catalogue/geometry changed')
    return counts


def save_projection(value):
    state=deepcopy(value['state']);state['document'].pop('needs_save',None);state.pop('saved_file_sha256',None)
    return dict(state=state,**{k:deepcopy(value[k]) for k in ('settings','binding','units','selected_defaults','approach')})


class Journal(generation.Journal):
    def marker_state(self):
        value=super().marker_state();value['scope']=SCOPE
        value['recipe_sha256']=self.report['recipe_pin']['sha256']
        if self.report.get('continuation'):
            value['continuation_receipt_sha256']=self.report['continuation']['failed_receipt_pin']['sha256']
        return value


def generate_save_finish(backend,journal,loaded,before,states):
    r=journal.report
    value=backend.generate(lambda:journal.pending('GenerateToolpath'));journal.returned('GenerateToolpath',value)
    require(type(value) is int and value==0,'Strict single-target GTP HRESULT0 required')
    backend.refresh_dirty();generated=backend.capture_narrow('generated');r['generated']=generated
    r['generated_record_counts']=verify_capture(loaded,before,generated,phase='generated',expected_approach=states[-1])
    r['actions']['GenerateToolpath']['readback_verified']=True;journal.persist()
    expected=save_projection(generated);r['save_stage']={}
    def capture(label):
        if label=='before':backend.boundary();return deepcopy(expected)
        final=backend.capture_full('saved');r['full_capture_count']+=1;r['actual_full_capture_count']+=1;r['final']=final
        counts=verify_capture(loaded,before,final,phase='generated',expected_approach=states[-1],saved_sha=r['saved_source_sha256'])
        require(group.exact(counts,r['generated_record_counts']),'Save changed generated target count')
        journal.persist();return save_projection(final)
    def save():
        value=backend.save();journal.returned('SaveActiveDocument',value);return value
    def saved_hash():
        digest=backend.saved_hash(r['save_stage'])
        require(digest!=r['initial_source_sha256'],'Save did not establish changed source bytes')
        r['saved_source_sha256']=digest;journal.persist();return digest
    run_one_existing_save(r['save_stage'],capture=capture,
        verify=lambda v:require(group.exact(v,expected),'Save changed accepted route/settings'),
        guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,
        save=save,saved_hash=saved_hash)
    r['actions']['SaveActiveDocument']['readback_verified']=True
    backend.finish();require(r['full_capture_count']==2,'Exactly two full captures required')
    r.update(status='review_required',phase='finished',readback_verified=True,model_saved=True)


def run_backend(backend,journal,loaded):
    r=journal.report;plan=loaded['approach_plan'];states=planned_states(plan)
    r.update(full_capture_count=0,reused_full_capture_count=0,actual_full_capture_count=0,mutation_attempted=False,readback_verified=False,model_saved=False,
        automatic_retry=False,automatic_replay=False,phase='preflight',status='running',actions={})
    try:
        backend.start();before=backend.capture_full('before');r['full_capture_count']+=1;r['actual_full_capture_count']+=1;r['before']=before
        exports.verify_observed(loaded,before)
        validate_plan(plan,loaded,before['approach']);journal.persist()
        for change in plan['changes']:
            label='field:'+(change['side']+':' if change['side'] else '')+change['key']
            require(group.exact(backend.read_change(change),change['before']),'Field changed before dispatch')
            value=backend.write_change(change,lambda label=label:journal.pending(label));journal.returned(label,value)
            prop=SPECS[change['key']][4]=='property'
            require(value is None if prop else type(value) is int and value==0,'Strict native setter outcome required')
            backend.refresh_dirty();actual=backend.read_change(change)
            require(group.exact(actual,change['after']),'Immediate native readback differs')
            r['actions'][label].update(readback_verified=True,observed=deepcopy(actual));journal.persist()
        configured=backend.capture_narrow('configured');r['configured']=configured;r['phase']='verify_configured'
        verify_capture(loaded,before,configured,phase='configured',expected_approach=states[-1]);journal.persist()
        generate_save_finish(backend,journal,loaded,before,states)
    except Exception as exc:
        r.update(status='uncertain' if r.get('mutation_attempted') else 'error',failed_phase=r['phase'],
            phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',readback_verified=False,cleanup_issue=_error(exc))
        journal.persist()
    return r


def normalize_approach(nc_values, lead_values, pointer_values):
    """Keep exact raw values, including unit/basis and paired lead ownership."""
    values = deepcopy(nc_values['values'])
    values.update(pointer_values['setup_use'])
    local = {k:[v['distance_native'],v['basis_raw']] for k,v in pointer_values['local_planes'].items()}
    leads = {side:{name:deepcopy(value['raw']) for name,value in fields.items()}
             for side,fields in lead_values.items()}
    return dict(nc=values,leads=leads,local_planes=local,setup_planes=deepcopy(pointer_values['setup_planes']))


class NativeBackend(generation.NativeBackend):
    def start(self):
        # Skip original generation's recipe/assignment audit and ungenerated assumptions.
        generation.prior.NativeBackend.start(self)

    def read_approach(self,label):
        from scripts import sw_cam_chamfer_clearance_read as clearance
        from scripts.sw_cam_finish_lead_observation import read_lead_details
        with self.ctx.guard() as g:
            raw,feature=self.target(g);dispatch=self.feature_dispatch(g,feature)
        held=dict(operation=raw,feature=feature)
        def binding():
            self.events()
            for key,ident in (('operation',self.args['operation_native_id']),('feature',self.args['feature_native_id'])):
                require(_object_id(self.native['doc'],held[key],_member)==ident,'Retained approach target changed')
            self.events()
        class CombinedApproachBatch(clearance.ReadBatch):
            def read(batch,obj,name,*args):
                if name in planes.GETTERS:return planes.PlaneReadBatch.read(batch,obj,name,*args)
                return super().read(obj,name,*args)
            def typed(batch,obj,name):
                if name in planes.INTERFACES:return planes.PlaneReadBatch.typed(batch,obj,name)
                return super().typed(obj,name)
        batch=CombinedApproachBatch(self.sw,self.typelib_path,generated_pin=self.loaded['generated_pin'],
            process_id=self.args['process_id'],expected_document=self.ctx.identity(),
            source_sha256=self.ctx.args['expected_source_sha256'],evidence_pins=self.loaded['pins'],
            verify_evidence=self.ctx.files,verify_owned_process=self.ctx.owned,check_events=self.events,
            retained_objects=(self.native['doc'],raw,feature,dispatch),verify_retained_binding=binding,max_native_calls=220)
        detail=dict(label=label);self.report.setdefault('approach_reads',[]).append(detail);self.persist()
        try:
            with batch:
                _,setup=clearance.read_setup_binding(self.native['doc'],self.loaded,read=batch.read,typed=batch.typed)
                detail['pointer']={}
                pointer=clearance.read_plane_parameters(raw,setup,read=batch.read,typed=batch.typed,
                    pointer_read=batch.plane,diagnostic=detail['pointer'],persist=self.persist)
                detail['scalars']={}
                scalar=planes.read_planes(raw,read=batch.read,typed=batch.typed,diagnostic=detail['scalars'])
                lead=read_lead_details(raw,dispatch,read=batch.read,typed=batch.typed,
                    lead_typed=lambda obj:batch.typed(obj,'ICWLeadInOut'))
            batch.require_complete()
            return normalize_approach(scalar,lead,pointer)
        finally:detail['batch']=batch.summary();self.persist()

    def capture_full(self,label):
        value=exports.ReadBackend.capture_export(self,label)
        value['approach']=self.read_approach(label)
        return value

    def close(self):
        try:super().close()
        finally:
            if self.session is not None:self.report['messages']=self.session.summary()
            self.persist()

    def capture_reconcile(self,label):
        # Rebind live headers without a duplicate full catalogue/feature capture.
        self.boundary();diagnostic=dict(phase=label)
        self.report.setdefault('header_observations',[]).append(diagnostic);self.persist()
        state,native=self.capture._capture_headers(self.ctx,self.clsid,self.loaded['state'],21,diagnostic)
        self.native,self.current_state=native,deepcopy(state)
        value=dict(state=state,**self.read_settings(label))
        value['selected_defaults']=self.operation_defaults(self.args['operation_native_id'],label)
        value['approach']=self.read_approach(label)
        return value

    def capture_narrow(self,label):
        value=generation.prior.NativeBackend.read_narrow(self,label)
        value['selected_defaults']=self.operation_defaults(self.args['operation_native_id'],label)
        value['approach']=self.read_approach(label)
        return value

    def field_owner(self,g,change):
        section,interface,_,_,_,_=SPECS[change['key']]
        raw,feature=self.target(g)
        if section=='lead':
            finish=g.typed(raw,'ICWFinishMillOp')
            getter='IGetLeadin' if change['side']=='lead_in' else 'IGetLeadout'
            owner=g.read(finish,getter,self.feature_dispatch(g,feature))
        else:owner=g.read(g.typed(raw,'ICWMillOperation'),'IGetNCParam')
        cls=planes.interface_class(interface,self.typelib_path,self.loaded['generated_pin'])
        return g.read(owner,'QueryInterface',cls)

    def read_change(self,change):
        _,_,getter,_,_,kind=SPECS[change['key']]
        with self.ctx.guard() as g:
            obj=self.field_owner(g,change)
            if kind=='plane':
                from scripts.sw_cam_chamfer_clearance_read import pointer_value
                value=g._observe(lambda:pointer_value(obj,getter,{}))
                value=[value['distance_native'],value['basis_raw']]
            else:value=g.read(obj,getter)
        if type(value) is tuple:value=list(value)
        return scalar_value(value,kind)

    def write_change(self,change,pending):
        _,_,_,setter,mode,kind=SPECS[change['key']]
        with self.ctx.guard() as g:
            obj=self.field_owner(g,change);value=deepcopy(change['after'])
            args=value if kind in ('plane','triple') else [value]
            return g.dispatch_once((lambda:setattr(obj,setter,value)) if mode=='property'
                else (lambda:_member(obj,setter,*args)),persist_pending=pending)


def audit_setters(typelib_path,generated_pin,plan):
    from ctypes import HRESULT, c_double, c_long
    from ctypes.wintypes import VARIANT_BOOL
    from scripts.sw_cam_chamfer_clearance_read import audit_interfaces
    base=audit_interfaces(typelib_path,generated_pin)
    rows=[]
    types={'bool':(VARIANT_BOOL,), 'long':(c_long,), 'double':(c_double,),
           'plane':(c_double,c_long), 'triple':(c_double,VARIANT_BOOL,c_double)}
    for change in plan['changes']:
        _,interface,_,setter,mode,kind=SPECS[change['key']]
        cls=planes.interface_class(interface,typelib_path,generated_pin)
        name='_set_'+setter if mode=='property' else setter
        found=[m for m in cls._methods_ if m.name==name]
        require(len(found)==1,'Exact setter declaration required: '+name);m=found[0]
        # Legacy NC plane setters have TLB flags0, not presumed [in].
        wanted_flags=(0,)*len(types[kind]) if interface=='ICWNCParam' else (1,)*len(types[kind])
        require(m.restype is HRESULT and m.argtypes==types[kind]
            and tuple(v[0] for v in m.paramflags)==wanted_flags
            and ('propput' in m.idlflags)==(mode=='property'),'Exact setter ABI differs: '+name)
        rows.append(dict(interface=interface,member=setter,dispid=int(m.idlflags[0]),paramflags=list(wanted_flags)))
    return dict(all_resolved=True,native_calls=0,reader_audit=base,members=rows)


def marker_path(source,source_sha,operation_id):
    key=_digest(dict(scope=SCOPE,source=common._key(source),source_sha256=source_sha,operation_native_id=operation_id))
    return common.local_evidence_root()/('contour_approach_'+key+'.json')


def make_checkpoint(report):
    context=deepcopy(report['loaded_context_before']);final=report['final']
    context.update(state=deepcopy(final['state']),source_sha256=report['saved_source_sha256'])
    context['configured_contour'].update(defaults=deepcopy(final['selected_defaults']),generated=True,
        record_counts=deepcopy(report['generated_record_counts']),geometry_acceptance_complete=False)
    context['approach_settings']=deepcopy(final['approach'])
    # The existing catalogue validator expects this small current proof.
    context['operation_checkpoint']=dict(final_observation={'tools':deepcopy(final['catalogue'])})
    context['current_context_sha256']=_digest(group.current_projection(context))
    context['authority_kind']='saved_contour_approach_geometry_review_pending'
    return dict(context=context,current=group.current_projection(context),
        source_sha256=report['saved_source_sha256'],approach=deepcopy(final['approach']))


def validate_terminal(r):
    require(r['scope']==SCOPE and r['status']=='review_required' and r['phase']=='finished'
        and r['readback_verified'] is True and r['model_saved'] is True and r['phase_proofs_verified'] is True,
        'Completed saved correction required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','receipt_write_error','phase_proof_error')),
            'Uncertain correction cannot become current authority')
    require(all(r[k] is False for k in FORBIDDEN) and r['full_capture_count']==2,'Unexpected action or acceptance claim')
    states=planned_states(r['plan']);loaded=r['loaded_context_before']
    exports.verify_observed(loaded,r['before'])
    validate_plan(r['plan'],loaded,r['before']['approach'])
    require(r['initial_source_sha256']==loaded['source_sha256']
        and r['setter_interface_audit']['all_resolved'] is True
        and r['setter_interface_audit']['native_calls']==0,'Initial authority or setter audit differs')
    require(group.exact(r['before']['approach'],states[0]),'Baseline recipe mismatch')
    for key,phase in (('configured','configured'),('generated','generated'),('final','generated')):
        counts=verify_capture(loaded,r['before'],r[key],phase=phase,expected_approach=states[-1],
            saved_sha=r['saved_source_sha256'] if key=='final' else None)
        if phase=='generated':require(group.exact(counts,r['generated_record_counts']),'Target counts differ')
    actions=dict(r.get('inherited_actions',{}),**r['actions'])
    require(not set(r.get('inherited_actions',{})).intersection(r['actions']),'Inherited dispatch cannot repeat')
    expected={'GenerateToolpath','SaveActiveDocument'}
    for change in r['plan']['changes']:
        label='field:'+(change['side']+':' if change['side'] else '')+change['key'];expected.add(label)
        action=actions[label];prop=SPECS[change['key']][4]=='property'
        require(group.exact(action['observed'],change['after']),'Action readback differs')
        require(action['native_return_type']=='NoneType' and action['native_return_value'] is None if prop else
            action['native_return_type']=='int' and type(action['native_return_value']) is int and action['native_return_value']==0,
            'Setter outcome differs')
    require(set(actions)==expected,'Exact effective action inventory required')
    for label,action in actions.items():
        require(action['attempted'] is True and action['returned'] is True and action['pending'] is False
            and action['readback_verified'] is True,'Pending or incomplete action')
    for label in ('GenerateToolpath','SaveActiveDocument'):
        action=r['actions'][label]
        require(action['native_return_type']=='int' and type(action['native_return_value']) is int
            and action['native_return_value']==0,'Strict GTP/Save return required')
    save=r['save_stage'];sha=r['saved_source_sha256'];transition=r['source_transition']
    require(save['save_readback_verified'] is True and save['native_call_returned'] is True
        and save['save_pending'] is False and save['saved_file_sha256']==sha
        and transition['source_before_sha256']==r['initial_source_sha256']
        and transition['source_after_sha256']==sha and sha!=r['initial_source_sha256']
        and transition['strict_save_return']==0,'Strict saved source transition required')
    require(group.exact(save['before'],save_projection(r['generated']))
        and group.exact(save['after'],save_projection(r['final'])),'Save projection differs')
    require(r['actual_full_capture_count']==(1 if r.get('continuation') else 2),
            'Exact new full capture count required')
    if r.get('continuation'):validate_continuation_report(r)
    clean_events(r)
    return make_checkpoint(r)


def setter_actions(plan):
    return {'field:'+(c['side']+':' if c['side'] else '')+c['key']:c for c in plan['changes']}


def verify_setter_actions(actions,plan):
    expected=setter_actions(plan)
    require(set(actions)==set(expected),'Exactly completed historical setters required')
    for label,change in expected.items():
        a=actions[label];prop=SPECS[change['key']][4]=='property'
        require(a['attempted'] is True and a['returned'] is True and a['pending'] is False
            and a['readback_verified'] is True and group.exact(a['observed'],change['after']),
            'Incomplete historical setter; never resume')
        require(a['native_return_type']=='NoneType' and a['native_return_value'] is None if prop else
            a['native_return_type']=='int' and type(a['native_return_value']) is int and a['native_return_value']==0,
            'Historical setter outcome differs')


def verify_failed_configuration(failed):
    require(failed['scope']==SCOPE and failed['status']=='uncertain' and failed['phase']=='finished'
        and failed['readback_verified'] is False and failed['model_saved'] is False
        and failed['mutation_attempted'] is True and failed['full_capture_count']==1
        and failed['phase_proofs_verified'] is True,'Exact pre-generation failed state required')
    require(failed.get('issue',{}).get('type')=='KeyError'
        and any(v.get('function')=='verify_capture' for v in failed['issue'].get('locations',[]))
        and not any(k in failed for k in ('generated','final','save_stage','saved_source_sha256',
            'source_transition','cleanup_issue','receipt_write_error','phase_proof_error')),
        'Only completed configuration verifier failure can continue')
    require(all(failed[k] is False for k in FORBIDDEN),'Failed attempt had an out-of-scope action')
    verify_setter_actions(failed['actions'],failed['plan'])
    loaded=failed['loaded_context_before'];states=planned_states(failed['plan'])
    exports.verify_observed(loaded,failed['before'])
    validate_plan(failed['plan'],loaded,failed['before']['approach'])
    verify_capture(loaded,failed['before'],failed['configured'],phase='configured',expected_approach=states[-1])
    require(failed['initial_source_sha256']==loaded['source_sha256']
        and failed['setter_interface_audit']['all_resolved'] is True,'Failed baseline authority differs')
    # The original exception path persisted the last active event snapshot;
    # close() did not refresh it. Do not invent historical disconnection proof.
    events=failed['messages']
    require(events.get('subscribed') is True and type(events.get('active')) is bool
        and type(events.get('disconnected')) is bool and not any(events.get(k) for k in
        ('event_count','events','overflow','callback_errors','callback_error_count',
         'subscription_error','disconnect_errors')),'Historical event errors prevent continuation')
    return failed


def continuation_marker_path(report):
    c=report['continuation']
    key=_digest(dict(scope=SCOPE,source=common._key(report['source_path']),
        source_sha256=report['initial_source_sha256'],failed_receipt_sha256=c['failed_receipt_pin']['sha256']))
    return common.local_evidence_root()/('contour_approach_continue_'+key+'.json')


def read_continuation_evidence(c):
    failed,_=read_pin(c['failed_receipt_pin']['path'],c['failed_receipt_pin']['sha256'])
    old_module=failed['module_pin'];archive=c['failed_module_archive_pin']
    require(archive['sha256']==old_module['sha256'] and common._key(archive['path'])!=common._key(old_module['path']),
        'Exact distinct original module archive required')
    common._check([archive,c['original_receipt_pin'],c['original_marker_pin']])
    require(c['original_receipt_pin']['sha256']==c['failed_receipt_pin']['sha256']
        and common._key(c['original_receipt_pin']['path'])==common._key(failed['receipt_path']),
        'Original failed receipt changed')
    marker,marker_pin=read_pin(c['failed_marker_pin']['path'],c['failed_marker_pin']['sha256'])
    old_marker=marker_path(failed['source_path'],failed['initial_source_sha256'],failed['operation_native_id'])
    require(c['original_marker_pin']['sha256']==marker_pin['sha256']
        and common._key(c['original_marker_pin']['path'])==common._key(old_marker)
        and group.exact(marker,Journal(failed,failed['receipt_path'],old_marker).marker_state()),
        'Original failed once-marker changed')
    # Only the superseded writer code may relocate; no other pin is refreshed.
    matches=[v for v in failed['live_pins'] if common._key(v['path'])==common._key(old_module['path'])]
    require(matches==[old_module],'One exact superseded writer pin required')
    common._check([v for v in failed['live_pins'] if v not in matches])
    common._check(failed['offline_proof_pins']);common._check(failed['bootstrap_export_pins'])
    verify_failed_configuration(failed)
    return failed


def validate_continuation_report(r):
    failed=read_continuation_evidence(r['continuation'])
    require(group.exact(r['inherited_actions'],failed['actions'])
        and set(r['actions'])=={'GenerateToolpath','SaveActiveDocument'},'Setters must be inherited, never replayed')
    require(group.exact(r['before'],failed['before'])
        and group.exact(r['inherited_configured'],failed['configured'])
        and group.exact(r['configured'],failed['configured'])
        and group.exact(r['reconciled'],failed['configured']), 'Fresh configured reconciliation differs')
    require(r['reused_full_capture_count']==1 and r['actual_full_capture_count']==1
        and r['full_capture_count']==2,'Exact reused/new read counts required')
    require(group.exact(group.current_projection(r['loaded_context_before']),
        group.current_projection(failed['loaded_context_before'])),'Historical baseline projection differs')


def run_continuation(backend,journal,loaded):
    r=journal.report;before=r['before'];states=planned_states(r['plan'])
    r.update(full_capture_count=1,reused_full_capture_count=1,actual_full_capture_count=0,
        mutation_attempted=False,readback_verified=False,model_saved=False,
        automatic_retry=False,automatic_replay=False,status='running',phase='reconcile_configured',actions={})
    try:
        backend.start();actual=backend.capture_reconcile('continuation_reconcile');r['reconciled']=actual
        verify_capture(r['loaded_context_before'],before,actual,phase='configured',expected_approach=states[-1])
        require(group.exact(actual,r['inherited_configured']),'Current configured state differs; no dispatch')
        r['configured']=actual;journal.persist()
        generate_save_finish(backend,journal,r['loaded_context_before'],before,states)
    except Exception as exc:
        r.update(status='uncertain' if r.get('mutation_attempted') else 'error',failed_phase=r['phase'],
            phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',readback_verified=False,cleanup_issue=_error(exc))
        journal.persist()
    return r


RESUME_FIELDS={'failed_receipt_path','failed_receipt_sha256','failed_marker_path','failed_marker_sha256',
    'failed_module_archive_path','failed_module_archive_sha256'}


def load_continuation_inputs(p):
    failed,receipt_pin=read_pin(p['failed_receipt_path'],p['failed_receipt_sha256'])
    old_marker=marker_path(failed['source_path'],failed['initial_source_sha256'],failed['operation_native_id'])
    c=dict(failed_receipt_pin=receipt_pin,failed_marker_pin=common._pin(p['failed_marker_path']),
        failed_module_archive_pin=common._pin(p['failed_module_archive_path']),
        original_receipt_pin=common._pin(failed['receipt_path']),original_marker_pin=common._pin(old_marker))
    require(c['failed_marker_pin']['sha256']==p['failed_marker_sha256']
        and c['failed_module_archive_pin']['sha256']==p['failed_module_archive_sha256'],'Continuation evidence pin differs')
    read_continuation_evidence(c)
    require(failed['process_id']==p['process_id'] and common._key(failed['source_path'])==common._key(p['expected_document_path'])
        and failed['initial_source_sha256']==p['expected_source_sha256']==_file_hash(p['expected_document_path']),
        'Existing unsaved source/process differs')
    for prefix,field in (('checkpoint_receipt','parent_pin'),('recipe','recipe_pin'),('nc_observation','nc_observation_pin'),
            ('clearance_observation','pointer_observation_pin')):
        require(p[prefix+'_sha256']==failed[field]['sha256']
            and common._key(p[prefix+'_path'])==common._key(failed[field]['path']),'Continuation parent inputs differ')
    require(common._key(p['historical_source_path'])==common._key(failed['historical_source_pin']['path']),
        'Historical source archive differs')
    current=common._pin(__file__);old=failed['module_pin']
    live=common._merge([v for v in failed['live_pins'] if v!=old],[current])
    offline=common._merge(failed['offline_proof_pins'],list(c.values()))
    common._check(live);common._check(offline);require(len(live)<=64,'Bounded continuation closure required')
    original=deepcopy(failed['loaded_context_before'])
    original.update(pins=live,offline_export_proof_pins=offline)
    loaded=deepcopy(original)
    loaded.update(state=deepcopy(failed['configured']['state']),continuation=c,
        continuation_before_context=original,continuation_failed=failed,approach_plan=deepcopy(failed['plan']))
    return loaded


def prepare_continuation(p,loaded):
    failed=loaded['continuation_failed']
    marker=continuation_marker_path(dict(continuation=loaded['continuation'],source_path=failed['source_path'],
        initial_source_sha256=failed['initial_source_sha256']))
    report,marker=prepare(p,loaded,marker_override=marker)
    report.update(continuation=deepcopy(loaded['continuation']),loaded_context_before=deepcopy(loaded['continuation_before_context']),
        before=deepcopy(failed['before']),inherited_configured=deepcopy(failed['configured']),
        inherited_actions=deepcopy(failed['actions']),
        inherited_event_disconnect_verified=failed['messages']['disconnected'] is True
            and failed['messages']['active'] is False,inherited_setter_interface_audit=deepcopy(failed['setter_interface_audit']))
    return report,marker

PARAMS = planes.PARAMS | {
 'nc_observation_path','nc_observation_sha256','clearance_observation_path','clearance_observation_sha256',
 'recipe_path','recipe_sha256','historical_source_path'}


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and
        request['action'] in ('correct_saved_contour_approach','continue_configured_contour_approach'),'Exact grouped correction action required')
    p=request['params'];fields=PARAMS|RESUME_FIELDS if request['action']=='continue_configured_contour_approach' else PARAMS
    require(type(p) is dict and set(p)==fields,'Exact correction request fields required')
    base={k:v for k,v in p.items() if k in planes.PARAMS};base['module_sha256']=_file_hash(planes.__file__)
    planes.validate_request(dict(action='read_nc_planes_and_leads',params=base))
    require(p['module_sha256']==_file_hash(__file__),'Exact correction module required')
    for key,value in p.items():
        if key.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
        if key.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute request path required')
    return deepcopy(p)


def load_inputs(p):
    from scripts import sw_cam_chamfer_clearance_read as clearance
    loaded=clearance.load_inputs(p)
    obs,pointer_pin=read_pin(p['clearance_observation_path'],p['clearance_observation_sha256'])
    require(obs.get('scope')==clearance.SCOPE and obs.get('status')=='observed' and obs.get('phase')=='finished'
        and obs.get('readback_verified') is True and obs.get('phase_proofs_verified_after_read') is True
        and obs.get('read_only') is True and not any(obs.get(k) for k in
            ('mutation_attempted','save_attempted','model_saved','GTP_attempted','export_attempted','issue','cleanup_issue','receipt_write_error')),
        'Completed unchanged pointer-plane observation required')
    target=planes.target_projection(loaded)
    require(obs['process_id']==p['process_id'] and obs['expected_source_sha256']==p['expected_source_sha256']
        and common._key(obs['expected_document_path'])==common._key(p['expected_document_path'])
        and obs['before_target']==obs['after_target']==target
        and obs['before_document']==obs['after_document']==loaded['state']['document']
        and obs['checkpoint_pin']==loaded['parent_pin'] and obs['nc_observation_pin']==loaded['nc_observation_pin'],
        'Pointer observation authority differs')
    clean_events(obs)
    archive=Path(p['historical_source_path'])
    require(archive.is_file() and archive.suffix.lower()=='.sldprt' and not archive.is_symlink()
        and common._key(archive)!=common._key(p['expected_document_path'])
        and _file_hash(archive)==p['expected_source_sha256'],'Separate exact historical source archive required')
    archive_pin=common._pin(archive)
    baseline=normalize_approach(loaded['nc_observation']['planes'],loaded['nc_observation']['leads'],obs)
    plan,recipe_pin=read_pin(p['recipe_path'],p['recipe_sha256']);validate_plan(plan,loaded,baseline)
    # These immutable model assets are still hashed before/after, but no native
    # profile/stock-file reader executes during this operation-only correction.
    retired_names={'500-20-ms-16142.mt','c40-m08em2.mh','sandvik_1K334_0800_XB1730.mt','c40-16erp412.mh','stock.stl'}
    retired=[v for v in loaded['pins'] if Path(v['path']).name in retired_names]
    require({Path(v['path']).name for v in retired}==retired_names,'Exact inactive profile/stock assets required')
    added=[common._pin(__file__),common._pin(generation.__file__)]
    import scripts.sw_cam_ud14_save as save_module
    added.append(common._pin(save_module.__file__))
    live=common._merge([v for v in loaded['pins'] if v not in retired],added)
    offline=common._merge(loaded['offline_export_proof_pins'],retired,
        [pointer_pin,recipe_pin,archive_pin],plan['source_pins'])
    require(len(live)<=64,'Bounded correction live dependency closure required')
    common._check(live);common._check(offline)
    return dict(loaded,pins=live,offline_export_proof_pins=offline,approach_plan=plan,recipe_pin=recipe_pin,
        pointer_observation_pin=pointer_pin,historical_source_pin=archive_pin,
        correction_retired_pins=retired,approach_baseline=baseline)


def prepare(p,loaded,*,marker_override=None):
    target=loaded['configured_contour']
    marker=marker_override or marker_path(p['expected_document_path'],p['expected_source_sha256'],target['native_id'])
    receipt=common._local_receipt(p['receipt_path'])
    protected={common._key(v['path']) for v in loaded['pins']+loaded['offline_export_proof_pins']}
    protected.add(common._key(p['expected_document_path']))
    require(not marker.exists() and not marker.is_symlink() and
        common._key(marker)!=common._key(receipt) and
        not protected.intersection({common._key(marker),common._key(receipt)}),'Fresh distinct receipt and once-marker required')
    context=deepcopy({k:v for k,v in loaded.items() if k not in
        ('approach_plan','approach_baseline','nc_observation','continuation_failed','continuation_before_context')})
    report=dict(schema_version=1,scope=SCOPE,status='prepared',phase='prepared',actions={},
        process_id=p['process_id'],source_path=p['expected_document_path'],initial_source_sha256=p['expected_source_sha256'],
        receipt_path=str(receipt),operation_native_id=target['native_id'],feature_native_id=target['feature_native_id'],
        tool_native_id=target['tool_native_id'],module_pin=common._pin(__file__),parent_pin=loaded['parent_pin'],
        nc_observation_pin=loaded['nc_observation_pin'],pointer_observation_pin=loaded['pointer_observation_pin'],
        historical_source_pin=loaded['historical_source_pin'],recipe_pin=loaded['recipe_pin'],
        plan=deepcopy(loaded['approach_plan']),loaded_context_before=context,
        live_pins=deepcopy(loaded['pins']),offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
        bootstrap_export_pins=deepcopy(loaded['bootstrap_export_pins']),phase_proofs_verified=False,
        protected_paths_equal_verified=False,full_tool_profile_capture_count=0,**{k:False for k in FORBIDDEN})
    return report,marker


def execute(sw,clsid,typelib,*,params,loaded,report,marker):
    target=loaded['configured_contour']
    args=dict(params,operation_native_id=target['native_id'],feature_native_id=target['feature_native_id'],
        tool_native_id=target['tool_native_id'])
    journal=Journal(report,params['receipt_path'],marker)
    _write_receipt(params['receipt_path'],report,create=True)
    backend=NativeBackend(loaded,args,sw,clsid,typelib,report,journal.persist)
    result=(run_continuation if loaded.get('continuation') else run_backend)(backend,journal,loaded)
    try:
        common._check(loaded['offline_export_proof_pins']);common._check(loaded['bootstrap_export_pins'])
        result['phase_proofs_verified']=True
        if result.get('readback_verified') is True:
            result['checkpoint']=validate_terminal(result);result['checkpoint_sha256']=_digest(result['checkpoint'])
            journal.persist();result['marker_pin']=common._pin(marker);journal.persist()
            require(result['marker_pin']['sha256']==_file_hash(marker),'Stable terminal marker required')
    except Exception as exc:
        result.update(status='uncertain',readback_verified=False,phase_proofs_verified=False,phase_proof_error=_error(exc))
    journal.persist();return result


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    """Flat saved authority; superseded source bytes are checked via their archive."""
    r,pin=read_pin(path,digest)
    require(r['module_pin']==common._pin(__file__) and r['process_id']==process_id
        and common._key(r['source_path'])==common._key(expected_document_path)
        and common._key(r['receipt_path'])==common._key(path)
        and r['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),
        'Current correction runtime/process/source differs')
    common._check(r['live_pins']);common._check(r['offline_proof_pins']);common._check(r['bootstrap_export_pins'])
    require(r['historical_source_pin']['sha256']==r['initial_source_sha256']
        and _file_hash(r['historical_source_pin']['path'])==r['initial_source_sha256'],'Original source archive differs')
    recipe,_=read_pin(r['recipe_pin']['path'],r['recipe_pin']['sha256'])
    require(group.exact(recipe,r['plan']),'Completed recipe changed')
    cp=validate_terminal(r)
    require(group.exact(cp,r['checkpoint']) and _digest(cp)==r['checkpoint_sha256'],'Flat checkpoint differs')
    marker=continuation_marker_path(r) if r.get('continuation') else marker_path(
        r['source_path'],r['initial_source_sha256'],r['operation_native_id'])
    mark,marker_pin=read_pin(str(marker),r['marker_pin']['sha256'])
    require(common._key(marker)==common._key(r['marker_pin']['path'])
        and group.exact(mark,Journal(r,path,marker).marker_state()),'Stable terminal marker differs')
    context=deepcopy(cp['context'])
    live=common._merge([v for v in r['live_pins'] if common._key(v['path'])!=common._key(r['parent_pin']['path'])],[pin])
    offline=common._merge(r['offline_proof_pins'],[r['parent_pin'],marker_pin])
    context.update(pins=live,offline_export_proof_pins=offline,parent_pin=pin,group_marker_pin=marker_pin,
        bootstrap_export_pins=deepcopy(r['bootstrap_export_pins']))
    exports.operation_contract(context);exports.validate_catalogue_authority(context)
    return context


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);continuing=request['action']=='continue_configured_contour_approach'
    loaded=load_continuation_inputs(p) if continuing else load_inputs(p)
    registration=common.discover_export_registration(loaded,p['addin_clsid'])
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    audit=audit_setters(typelib,loaded['generated_pin'],loaded['approach_plan'])
    report,marker=prepare_continuation(p,loaded) if continuing else prepare(p,loaded)
    report['setter_interface_audit']=audit
    if validate_only:
        return dict(status='validated_offline',native_called=False,interface_audit=audit,
            changes=loaded['approach_plan']['changes'],live_pin_count=len(loaded['pins']))
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return execute(sw,registration['clsid'],typelib,params=p,loaded=loaded,report=report,marker=marker)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true')
    options=parser.parse_args(argv)
    result=dispatch_request(json.loads(Path(options.request).read_text(encoding='utf-8-sig')),validate_only=options.validate_only)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','issue','native_called')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True or result.get('status')=='validated_offline' else 1


if __name__=='__main__':raise SystemExit(main())
