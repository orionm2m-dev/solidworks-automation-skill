"""Reconfigure one verified FACE lead, regenerate once and preserve a flat checkpoint."""
from copy import deepcopy
from pathlib import Path
import json
import re
from scripts import sw_cam_grouped_face_recipe as group
from scripts import sw_cam_checkpoint_exports as exports
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_ud14_save import run_one_existing_save

SCOPE = 'SAVED_FACE_LEAD_RECONFIGURATION_V1'
MEMBER, GETTER = 'SetLeadInClearance', 'GetLeadInClearance'
OLD, TARGET = [2.0, False], [8.0, False]
ACTIONS = (MEMBER, 'GenerateToolpath', 'SaveActiveDocument')
key, pin, check, merge = exports._key, exports._pin, exports._check, exports._merge


def marker_path(source, source_sha256):
    value = _digest(dict(scope=SCOPE, source=key(source), source_sha256=source_sha256,
                         operation_native_id=267))
    return exports.local_evidence_root() / ('face_reconfigure_' + value + '.json')


def verify_settings(actual, baseline, *, changed=False, generated_count=None):
    expected = deepcopy(baseline)
    require(group.exact(expected['face'][GETTER], OLD), 'Initial lead must equal2mm absolute')
    if changed: expected['face'][GETTER] = deepcopy(TARGET)
    if generated_count is not None:
        require(changed and type(generated_count) is int and 0 < generated_count < 2**31
                and expected['face']['CutMethod'] == 1, 'Strict automatic LONG count required')
        expected['face']['NumberOfCuts'] = generated_count
    require(group.exact(actual, expected), 'Unexpected FACE/NC parameter change')


def verify_route(reference, observed, *, phase, saved_sha=None):
    require(phase in ('baseline', 'configured', 'generated'), 'Unknown route phase')
    old = next(row for row in reference['operations'] if row['native_id'] == 267)
    actual = next(row for row in observed['operations'] if row['native_id'] == 267)
    if phase == 'baseline':
        from scripts.sw_cam_upper_cone_feature import require_state_equivalent
        require_state_equivalent(reference, observed)
        return
    require(type(actual['toolpath_generated']) is bool, 'Strict generated flag required')
    if phase == 'configured':
        require((actual['toolpath_generated'] is True and group.exact(actual['toolpath_record_counts'], old['toolpath_record_counts']))
            or (actual['toolpath_generated'] is False and actual['toolpath_record_counts'] == []),
            'Only unchanged stale path or complete invalidation allowed after setter')
    else:
        require(actual['toolpath_generated'] is True, 'Newly generated FACE path required')
    group.verify_route_delta(reference, observed, old['assigned_tool'],
        generated=actual['toolpath_generated'], saved_sha=saved_sha)


def verify_observed(loaded, observed, *, phase, changed=False, generated_count=None, saved_sha=None, full=False):
    verify_route(loaded['state'], observed['state'], phase=phase, saved_sha=saved_sha)
    verify_settings(observed['settings'], loaded['settings'], changed=changed, generated_count=generated_count)
    tool = next(v['assigned_tool'] for v in loaded['state']['operations'] if v['native_id'] == 267)
    require(group.exact(observed['binding'], tool)
        and group.exact(observed['units'], loaded['finish_payload']['unit_record']), 'Tool or unit scope changed')
    if full:
        require(group.exact(observed['payload'], dict(rough=loaded['payload'], finish=loaded['finish_payload']))
            and group.exact(observed['cone_observation'], loaded['cone_observation'])
            and group.exact(observed['face_observation'], loaded['face_observation']), 'Protected payload/geometry changed')


def validate_plan(plan, loaded):
    require(plan.get('scope') == 'FACE267_SINGLE_PARAMETER_LEADIN_CORRECTION_V1'
        and plan.get('operation_native_id') == 267 and plan.get('feature_native_id') == 265
        and plan.get('assigned_tool_native_id') == 249 and plan.get('all_other_settings_protected') is True,
        'Exact single-parameter correction plan required')
    c = plan['only_parameter_change']
    require(c['interface'] == 'ICWFaceMillOp' and c['setter'] == MEMBER and c['getter'] == GETTER
        and group.exact(c['expected_old'], OLD) and group.exact(c['target'], TARGET), 'Unsupported correction')
    require(group.exact(plan['baseline_settings'], loaded['settings'])
        and plan['source_sha256'] == loaded['source_sha256']
        and key(plan['source_authority']['path']) == key(loaded['parent_pin']['path'])
        and plan['source_authority']['sha256'] == loaded['parent_pin']['sha256'], 'Plan source/settings differ')
    verify_settings(loaded['settings'], plan['baseline_settings'])
    require(plan['protected_operations'] == {'247':[191], '248':[74]}, 'Protected counts differ')
    check(plan['source_evidence'])


class Journal(group.GroupJournal):
    """Local durable once-marker; readonly observations do not rewrite an unchanged marker."""
    def __init__(self, report, receipt, marker):
        super().__init__(report, receipt, marker)
        self.marker_signature = None

    def _marker_state(self):
        r = self.report
        actions = {name:{k:deepcopy(row[k]) for k in ('status','attempted','returned','native_dispatch_pending','readback_verified','native_return') if k in row}
                   for name,row in r.get('actions',{}).items()}
        return dict(scope=SCOPE, source_path=r['source_path'], source_sha256=r['source_sha256'],
            operation_native_id=267, receipt_path=str(self.receipt), recipe_sha256=r['recipe_sha256'],
            status=r['status'], actions=actions, native_dispatch_pending=r.get('native_dispatch_pending',False),
            readback_verified=r.get('readback_verified',False), automatic_replay=False)

    def persist(self):
        if not self.created: return
        if self.claimed:
            require(_file_hash(self.marker) == self.marker_digest, 'Once-marker changed externally')
            state = self._marker_state(); signature = _digest(state)
            if signature != self.marker_signature:
                _write_receipt(self.marker, state)
                self.marker_digest = _file_hash(self.marker); self.marker_signature = signature
        _write_receipt(self.receipt, self.report)


class NativeBackend(group.NativeBackend):
    def write_lead(self, pending):
        from scripts.sw_cam import _member
        with self.ctx.guard() as guard:
            op, feature = self._resolve(guard); face = self._face(guard, op)
            dispatch = self._feature_dispatch(guard, feature)
            old = guard.read(face, GETTER, dispatch)
            old = list(old) if type(old) is tuple else old
            require(group.exact(old, OLD), 'Lead changed immediately before setter')
            return guard.dispatch_once(lambda:_member(face, MEMBER, dispatch, *TARGET), persist_pending=pending)

    def generate(self, pending):
        from scripts.sw_cam import _member
        from scripts.sw_cam_mill_route_context import read_generic_tool
        require(self.report['actions'][MEMBER].get('readback_verified') is True
            and group.exact(self.report['actions'][MEMBER].get('observed'), TARGET), 'Confirmed new setting required')
        with self.ctx.guard() as guard:
            op, feature = self._resolve(guard); face = self._face(guard, op)
            value = guard.read(face, GETTER, self._feature_dispatch(guard, feature))
            value = list(value) if type(value) is tuple else value
            require(group.exact(value, TARGET), 'New lead changed before intentional generation')
            tool,_ = read_generic_tool(op,self.native['doc'],guard.read,guard.typed)
            require(group.exact(tool,self.expected_tool), 'Selected tool changed before GTP')
            mill=guard.typed(op,'ICWMillOperation')
            return guard.dispatch_once(lambda:_member(mill,'GenerateToolpath'),persist_pending=pending)


def run_backend(backend, journal, loaded):
    r = journal.report
    r.update(status='error',phase='preflight',actions={},mutation_attempted=False,native_call_attempted=False,
        native_call_returned=False,native_dispatch_pending=False,readback_verified=False,model_saved=False,
        full_capture_count=0,automatic_replay=False,automatic_retry=False,automatic_rollback=False,
        physical_geometry_verified=False,cutting_conditions_qualified=False,production_qualified=False)
    try:
        journal.create(); backend.start()
        r['phase']='baseline'; journal.persist()
        baseline=backend.capture_full('baseline');r['full_capture_count']+=1;r['baseline']=deepcopy(baseline);journal.persist()
        verify_observed(loaded,baseline,phase='baseline',full=True)
        journal.execute(MEMBER,backend.write_lead)
        backend.refresh_dirty();actual=backend.read_field(GETTER)
        r['immediate_lead_readback']=deepcopy(actual);journal.persist()
        require(group.exact(actual,TARGET),'Immediate lead readback differs')
        journal.verified(MEMBER,actual)
        configured=backend.read_narrow('configured');r['configured']=deepcopy(configured);journal.persist()
        verify_observed(loaded,configured,phase='configured',changed=True)
        journal.execute('GenerateToolpath',backend.generate)
        backend.refresh_dirty();generated=backend.read_narrow('generated');r['generated']=deepcopy(generated);journal.persist()
        n=generated['settings']['face']['NumberOfCuts'];r['automatic_count_observation']=dict(before=loaded['settings']['face']['NumberOfCuts'],after=n,physical_pass_count_verified=False)
        verify_observed(loaded,generated,phase='generated',changed=True,generated_count=n)
        journal.verified('GenerateToolpath',dict(toolpath_record_counts=next(v['toolpath_record_counts'] for v in generated['state']['operations'] if v['native_id']==267)))
        expected=backend.save_projection(generated)
        save_report=dict(phase='prepared',native_call_returned=False,save_pending=False);r['save_stage']=save_report;journal.entry('SaveActiveDocument')
        def persist_save():
            if save_report.get('native_call_returned') is True:
                entry=r['actions']['SaveActiveDocument'];value=group.return_observation(save_report['native_return_value'])
                if value['python_type'] != save_report['native_return_type']:
                    value=dict(python_type=save_report['native_return_type'],value_recorded=False,value=None,limit_reason='native_nonprimitive_return_not_serialized')
                entry.update(returned=True,native_dispatch_pending=False,status='returned',native_return=value)
                if not value['value_recorded']:save_report['native_return_value']=None
                r.update(native_dispatch_pending=False,native_call_returned=True)
            journal.persist()
        def capture(label):
            if label=='before':
                value=backend.read_narrow('before_save');r['before_save']=deepcopy(value);journal.persist()
                verify_observed(loaded,value,phase='generated',changed=True,generated_count=n)
            else:
                value=backend.capture_full('final');r['full_capture_count']+=1;r['final']=deepcopy(value);journal.persist()
                verify_observed(loaded,value,phase='generated',changed=True,generated_count=n,saved_sha=save_report['saved_file_sha256'],full=True)
            return backend.save_projection(value)
        def saved_hash():
            digest=backend.saved_hash(save_report)
            require(digest!=r['source_sha256'],'Changed CAM settings were not proven in saved file bytes')
            return digest
        run_one_existing_save(save_report,capture=capture,
            verify=lambda v:require(group.exact(v,expected),'Route/settings changed during Save'),
            guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=persist_save,
            save=backend.save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',dict(source_sha256=save_report['saved_file_sha256']))
        backend.finish();require(r['full_capture_count']==2,'Exactly two full captures required')
        cp=backend.checkpoint(r['final'])
        r.update(status='review_required',phase='finished',model_saved=True,readback_verified=True,
            saved_source_sha256=save_report['saved_file_sha256'],checkpoint=cp,checkpoint_sha256=_digest(cp),
            reason='LEAD_RECONFIGURED_GENERATED_SAVED_CL_WIP_REVIEW_REQUIRED')
        journal.persist()
    except Exception as exc:
        from scripts.sw_cam import _error
        r.update(status='uncertain' if r['mutation_attempted'] else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
        try:journal.persist()
        except Exception as failure:r['receipt_write_error']=_error(failure)
    finally:
        try:backend.close()
        except Exception as failure:
            from scripts.sw_cam import _error
            r.update(status='uncertain',cleanup_issue=_error(failure),readback_verified=False)
        try:journal.persist()
        except Exception as failure:
            from scripts.sw_cam import _error
            r.update(status='uncertain',receipt_write_error=_error(failure),readback_verified=False)
    return r


def _retirements(loaded):
    root=Path(group.__file__).resolve().parent
    wanted={key(root/'sw_cam_mill_stock_export_evidence.py'),key(root/'sw_cam_installation.py')}
    recipe=[p for p in loaded['holder_recipe']['pins'] if Path(p['path']).suffix.casefold()=='.json']
    require(len(recipe)==1,'One previously parsed holder recipe required');wanted.add(key(recipe[0]['path']))
    retired=[p for p in loaded['pins'] if key(p['path']) in wanted]
    require(len(retired)==3,'Exact phase-specific retirement required')
    return retired


def load_parent(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    loaded=exports.load_completed_reconciliation(path,digest,process_id=process_id,
        expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256)
    exports.operation_contract(loaded);check(loaded['pins']);retired=_retirements(loaded);keys={key(p['path']) for p in retired}
    live=merge([p for p in loaded['pins'] if key(p['path']) not in keys],
        [pin(__file__),pin(Path(group.__file__).parent/'sw_cam_ud14_save.py')])
    require(len(live)==63,'Expected63 phase-specific live dependencies')
    loaded.update(pins=live,reconfigure_retired_pins=retired,
        bootstrap_export_pins=[p for p in retired if Path(p['path']).name=='sw_cam_installation.py'],
        offline_export_proof_pins=[p for p in retired if Path(p['path']).name!='sw_cam_installation.py'])
    return loaded


def _fresh(loaded,receipt,marker):
    exports._local_receipt(receipt)
    require(not Path(receipt).exists() and not Path(receipt).is_symlink()
        and not marker.exists() and not marker.is_symlink(),'Fresh local receipt and once-marker required')
    protected={key(p['path']) for p in loaded['pins']+loaded['reconfigure_retired_pins']}
    protected.add(key(loaded['state']['document']['path']))
    require(key(receipt) not in protected and key(marker) not in protected and key(receipt)!=key(marker),'Evidence alias')


def prepare(params):
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    identity={k:params[k] for k in ('process_id','expected_document_path','expected_source_sha256')}
    loaded=load_parent(params['checkpoint_receipt_path'],params['checkpoint_receipt_sha256'],**identity)
    plan,planpin=read_pin(params['plan_path'],params['plan_sha256']);validate_plan(plan,loaded)
    marker=marker_path(params['expected_document_path'],params['expected_source_sha256']);_fresh(loaded,params['receipt_path'],marker)
    report=dict(schema_version=1,scope=SCOPE,module_pin=pin(__file__),process_id=params['process_id'],
        source_path=params['expected_document_path'],source_sha256=params['expected_source_sha256'],
        receipt_path=params['receipt_path'],recipe_sha256=params['plan_sha256'],recipe_pin=planpin,plan=deepcopy(plan),
        parent_pin=deepcopy(loaded['parent_pin']),previous_group_marker_pin=deepcopy(loaded['group_marker_pin']),
        previous_recovery_marker_pin=deepcopy(loaded['recovery_marker_pin']),historical_move_marker_pin=deepcopy(loaded['historical_move_marker_pin']),
        current_before=group.current_projection(loaded),current_before_sha256=loaded['current_context_sha256'],
        settings_before=deepcopy(loaded['settings']),live_pins=deepcopy(loaded['pins']),retired_offline=deepcopy(loaded['reconfigure_retired_pins']))
    return loaded,report,marker


def execute(sw,clsid,typelib,*,params,loaded,report,marker):
    journal=Journal(report,params['receipt_path'],marker)
    backend=NativeBackend(loaded,params,sw,clsid,typelib,report,journal.persist)
    result=run_backend(backend,journal,loaded)
    if result.get('readback_verified') is True:
        result['marker_pin']=pin(marker);journal.persist()
        require(result['marker_pin']['sha256']==_file_hash(marker),'Terminal marker changed')
    return result


def validate_terminal(data):
    require(data.get('scope')==SCOPE and data.get('status')=='review_required' and data.get('phase')=='finished'
        and data.get('readback_verified') is True and data.get('model_saved') is True
        and data.get('native_dispatch_pending') is False and data.get('full_capture_count')==2,
        'Completed reconfiguration, generation and save required')
    require(not any(k in data for k in ('issue','failed_phase','receipt_write_error','cleanup_issue'))
        and all(data.get(k) is False for k in ('automatic_retry','automatic_replay','automatic_rollback',
              'physical_geometry_verified','cutting_conditions_qualified','production_qualified')), 'Uncertain terminal evidence')
    require(set(data['actions'])==set(ACTIONS),'Exactly setter, generation and save required')
    for name in ACTIONS:
        row=data['actions'][name];ret=row['native_return']
        require(row.get('status')=='verified' and row.get('attempted') is True and row.get('returned') is True
            and row.get('readback_verified') is True and row.get('native_dispatch_pending') is False
            and ret.get('value_recorded') is True and ret.get('python_type')=='int'
            and type(ret.get('value')) is int and ret['value']==0,'Exact terminal native action required')
    before=data['current_before'];require(set(before)==set(group.CURRENT_KEYS)
        and _digest(before)==data['current_before_sha256'],'Initial checkpoint differs')
    loaded=dict(before,settings=data['settings_before'])
    verify_observed(loaded,data['baseline'],phase='baseline',full=True)
    verify_observed(loaded,data['configured'],phase='configured',changed=True)
    require(group.exact(data['immediate_lead_readback'],TARGET)
        and group.exact(data['actions'][MEMBER]['observed'],TARGET),'Setter readback differs')
    n=data['automatic_count_observation']['after']
    require(group.exact(data['automatic_count_observation']['before'],loaded['settings']['face']['NumberOfCuts'])
        and data['automatic_count_observation']['physical_pass_count_verified'] is False,'Count provenance differs')
    verify_observed(loaded,data['generated'],phase='generated',changed=True,generated_count=n)
    verify_observed(loaded,data['before_save'],phase='generated',changed=True,generated_count=n)
    save=data['save_stage'];saved=data['saved_source_sha256'];transition=data['source_transition']
    require(save.get('save_readback_verified') is True and save.get('native_call_returned') is True
        and save.get('save_pending') is False and save.get('native_return_type')=='int'
        and type(save.get('native_return_value')) is int and save['native_return_value']==0
        and save['saved_file_sha256']==saved==transition['source_after_sha256'] and saved!=data['source_sha256']
        and transition['source_before_sha256']==data['source_sha256']==before['source_sha256']
        and type(transition['strict_save_return']) is int and transition['strict_save_return']==0,'Exact Save transition required')
    verify_observed(loaded,data['final'],phase='generated',changed=True,generated_count=n,saved_sha=saved,full=True)
    require(group.exact(group.NativeBackend.save_projection(None,data['generated']),
        group.NativeBackend.save_projection(None,data['final'])),'Save changed route projection')
    current=deepcopy(before);current.update(state=deepcopy(data['final']['state']),source_sha256=saved)
    selected=next(v for v in current['state']['operations'] if v['native_id']==267)
    cp=dict(current=current,settings=deepcopy(data['final']['settings']),generated_face_operation_id=267,
            toolpath_record_counts=deepcopy(selected['toolpath_record_counts']))
    require(group.exact(cp,data['checkpoint']) and _digest(cp)==data['checkpoint_sha256'], 'Final flat checkpoint differs')
    return cp


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    """Validate immutable history without requiring the superseded source file bytes."""
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
    data,receiptpin=read_pin(path,digest);cp=validate_terminal(data);clean_events(data)
    require(data['module_pin']==pin(__file__) and type(process_id) is int and data['process_id']==process_id
        and key(data['source_path'])==key(expected_document_path) and key(data['receipt_path'])==key(path)
        and data['saved_source_sha256']==expected_source_sha256==cp['current']['source_sha256']
        and _file_hash(expected_document_path)==expected_source_sha256,'Current runtime/process/source differs')
    parent,parentpin=read_pin(data['parent_pin']['path'],data['parent_pin']['sha256'])
    require(parent.get('scope')==exports.RECOVERY_SCOPE and parent.get('status')=='observed'
        and parent.get('phase')=='finished' and parent.get('read_only') is True and parent.get('read_pending') is False
        and parent.get('full_capture_count')==1 and type(parent.get('native_mutation_calls')) is int and parent['native_mutation_calls']==0
        and parent['module_pin']==pin(exports.__file__) and parent['process_id']==process_id
        and key(parent['source_path'])==key(expected_document_path) and parent['source_sha256']==data['source_sha256']
        and all(parent.get(k) is False for k in ('GTP_attempted','model_saved','setter_attempted','automatic_replay'))
        and not any(k in parent for k in ('issue','failed_phase','cleanup_issue','receipt_write_error'))
        and parent.get('readback_verified') is True
        and parent.get('state_reconciled') is True and parent.get('original_group_completion_claimed') is False
        and group.exact(parent['checkpoint']['current'],data['current_before'])
        and group.exact(parent['checkpoint']['settings'],data['settings_before'])
        and parent['checkpoint_sha256']==_digest(parent['checkpoint']),'Previous verified authority differs')
    clean_events(parent)
    plan,planpin=read_pin(data['recipe_pin']['path'],data['recipe_pin']['sha256'])
    require(plan==data['plan'],'Correction plan differs')
    validate_plan(plan,dict(data['current_before'],settings=data['settings_before'],parent_pin=parentpin))
    retired=data['retired_offline'];require(len(retired)==3,'Exact original phase proof required')
    check(retired);check(data['live_pins'])
    require(len(data['live_pins'])==63 and not any(key(p['path'])==key(expected_document_path) for p in data['live_pins']),
        'Exact bounded immutable closure required')
    parent_live=merge([p for p in parent['live_pins'] if key(p['path'])!=key(parent['failed_group_pin']['path'])],[parentpin])
    require(len(parent_live)==64,'Previous recovery closure differs')
    expected_retired=_retirements(dict(data['current_before'],pins=parent_live))
    require(expected_retired==retired,'Dependency phase roles differ')
    retired_keys={key(p['path']) for p in retired}
    expected_live=merge([p for p in parent_live if key(p['path']) not in retired_keys],
        [pin(__file__),pin(Path(group.__file__).parent/'sw_cam_ud14_save.py')])
    require(data['live_pins']==expected_live,'Exact derived reconfiguration closure differs')
    marker=marker_path(data['source_path'],data['source_sha256'])
    mark,markpin=read_pin(str(marker),data['marker_pin']['sha256'])
    require(key(data['marker_pin']['path'])==key(marker)
        and mark==Journal(data,data['receipt_path'],marker)._marker_state(),'Stable local terminal marker differs')
    # Completed read-only recovery marker remains exact historical evidence; uncertain mutation markers stay live.
    check([data['previous_recovery_marker_pin']])
    live=merge([p for p in data['live_pins'] if key(p['path'])!=key(parentpin['path'])],[receiptpin,markpin])
    require(len(live)==64,'Terminal closure must remain64')
    for protected in ('historical_move_marker_pin','previous_group_marker_pin'):
        require(any(key(p['path'])==key(data[protected]['path']) and p['sha256']==data[protected]['sha256'] for p in live),
                'Original uncertain mutation marker must remain live')
    generated=[p for p in live if Path(p['path']).name.startswith('_FE488661_')]
    require(len(generated)==1,'Generated library binding missing')
    result=dict(cp['current'],pins=live,current_context_sha256=_digest(cp['current']),parent_pin=receiptpin,
        group_marker_pin=markpin,generated_pin=generated[0],settings=deepcopy(cp['settings']),
        generated_face_operation_id=267,toolpath_record_counts=deepcopy(cp['toolpath_record_counts']),
        reconfigure_retired_pins=retired,historical_parent_pin=parentpin,reconfigure_receipt=data,
        authority_kind='reconfigured_saved_group',bootstrap_export_pins=[p for p in retired if Path(p['path']).name=='sw_cam_installation.py'],
        offline_export_proof_pins=[p for p in retired if Path(p['path']).name!='sw_cam_installation.py'])
    exports.operation_contract(result);return result


COMMON=exports.COMMON
PARAMS=COMMON|{'plan_path','plan_sha256'}


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'}
        and request['action'] in {'reconfigure','export_cl','export_wip'},'Supported checkpoint action required')
    action=request['action'];params=request['params']
    wanted=PARAMS if action=='reconfigure' else COMMON|({'output_path'} if action=='export_cl' else {'output_dir','project_root'})
    require(type(params) is dict and set(params)==wanted,'Exact checkpoint request fields required')
    require(type(params['process_id']) is int and 0<params['process_id']<2**32,'Exact owned PID required')
    for name,value in params.items():
        if name.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA256 required')
        if name.endswith('path') or name in ('output_dir','project_root'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
    require(params['module_sha256']==_file_hash(__file__) and params['qualification_only'] is True
        and params['acknowledge_disposable_copy'] is True and params['acknowledge_machine_scope'] is True
        and params['message_policy']=='vendor_default','Explicit qualification binding required')
    require(type(params['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',params['addin_clsid']), 'Exact CAM CLSID required')
    return action,dict(params)


def ownership_proof(loaded):
    """A completed launch record is offline provenance; current process checks remain live."""
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    found=[]
    for entry in loaded['pins']:
        if Path(entry['path']).suffix.casefold()!='.json':continue
        value,_=read_pin(entry['path'],entry['sha256'])
        if value.get('status')=='ok' and value.get('phase')=='connected' and value.get('new_process_verified') is True:
            require(value.get('process_identity')==loaded['ownership']
                and value.get('process_id')==loaded['ownership']['process_id'], 'Completed ownership record differs')
            found.append(entry)
    require(len(found)==1,'One exact completed launch provenance record required')
    return found[0]


def load_export(path,digest,*,action,process_id,expected_document_path,expected_source_sha256):
    require(action in exports.EXPORT_ACTIONS,'Only readonly exports allowed')
    loaded=load_completed(path,digest,process_id=process_id,expected_document_path=expected_document_path,
                          expected_source_sha256=expected_source_sha256)
    root=Path(group.__file__).resolve().parent
    wanted={key(root/'sw_cam_ud14_save.py'),key(loaded['group_marker_pin']['path'])}
    if action=='export_cl':
        wanted.add(key(root/'sw_cam_shared_holder_geometry.py'));wanted.add(key(ownership_proof(loaded)['path']))
    retired=[p for p in loaded['pins'] if key(p['path']) in wanted]
    require(len(retired)==(4 if action=='export_cl' else 2),'Exact completed export phase proofs required')
    live=merge([p for p in loaded['pins'] if key(p['path']) not in wanted],exports.export_runtime_pins(action))
    require(len(live)<=64 and any(key(p['path'])==key(__file__) for p in live)
        and any(key(p['path'])==key(loaded['parent_pin']['path']) for p in live),'Active code and authority must stay live')
    require(all(Path(p['path']).suffix.casefold() not in ('.mt','.mh','.stl') for p in retired),'Native assets cannot retire')
    loaded.update(pins=live,export_action=action,export_parent_pins=deepcopy(loaded['pins']),
        offline_export_proof_pins=merge(loaded['offline_export_proof_pins'],retired),
        export_retired_pins=retired)
    check(live);check(loaded['offline_export_proof_pins']);return loaded


def dispatch_request(request):
    action,params=validate_request(request)
    identity={k:params[k] for k in ('process_id','expected_document_path','expected_source_sha256')}
    if action=='reconfigure':loaded,report,marker=prepare(params)
    else:
        loaded=load_export(params['checkpoint_receipt_path'],params['checkpoint_receipt_sha256'],action=action,**identity)
        exports.fresh_paths(loaded,params,action)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=params['process_id']):
        check(loaded['pins']);check(loaded['offline_export_proof_pins'])
        registration=exports.discover_export_registration(loaded,params['addin_clsid'])
        sw,_=connect_solidworks(process_id=params['process_id'],launch_new_instance=False,wait_seconds=1)
        typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
        if action=='reconfigure':
            report['bootstrap_validation']=deepcopy(loaded['bootstrap_validation'])
            return execute(sw,registration['clsid'],typelib,params=params,loaded=loaded,report=report,marker=marker)
        if action=='export_cl':
            result=exports.export_cl(sw,registration['clsid'],typelib,loaded=loaded,args=params,output_path=params['output_path'])
        else:
            result=exports.export_wip(sw,registration['clsid'],typelib,loaded=loaded,args=params,
                project_root=params['project_root'],output_dir=params['output_dir'])
        try:
            check(loaded['offline_export_proof_pins']);check(loaded['bootstrap_export_pins'])
            result['phase_proofs_verified_after_export']=True
        except Exception as exc:
            from scripts.sw_cam import _error
            result.update(status='uncertain',readback_verified=False,checkpoint_export_readback_verified=False,phase_proofs_verified_after_export=False,post_export_proof_error=_error(exc))
        _write_receipt(params['receipt_path'],result)
        return result


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    options=parser.parse_args(argv);result=dispatch_request(json.loads(Path(options.request).read_text(encoding='utf-8-sig')))
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','issue')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True else 1


if __name__=='__main__':raise SystemExit(main())
