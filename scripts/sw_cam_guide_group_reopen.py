"""Verify persisted guide parameters by closing and reopening one clean owned part.

Uses the completed saved group receipt as the new source authority. The four
operations are never recreated. No Save, setters, GTP, application exit or UI.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts import sw_cam_guide_group_configuration as configuration
from scripts import sw_cam_lifecycle as lifecycle
from scripts import sw_connect
from scripts import sw_cam_installation as installation
from scripts import sw_cam_raw_mill_face_operation as capture_module
from scripts.sw_cam_upper_cone_feature import UpperConeContext
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam import _member, _error
from scripts.sw_cam_rough_firstcut import require

reader, guide, group, common = configuration.reader, configuration.guide, configuration.group, configuration.common
SCOPE = 'SAVED_GUIDE_FOUR_SAME_SESSION_REOPEN_V1'
ORDER = [195, 196, 267, 247, 248, 271, 143, 144, 320, 322, 324, 326, 328]
TARGETS = [(322,82,0), (324,82,1), (326,83,0), (328,83,1)]
PARAMS = {'process_id','expected_document_path','expected_source_sha256','configuration_receipt_path',
    'configuration_receipt_sha256','module_sha256','receipt_path','progress_path','acknowledgement'}


RESUME_SCOPE = 'GUIDE_CONFIGURATION_REMAINDER_SAVE_V1'


def resolve_resume_history(r):
    """Resolve the immutable prefix/preparation; never rewrite or replay history."""
    from scripts import sw_cam_guide_group_resume as resume
    require(r.get('scope') == RESUME_SCOPE == resume.SCOPE and r.get('module_pin') == common._pin(resume.__file__),
        'Exact executed remainder writer required')
    require(r.get('SetTool_attempted') is False and r.get('automatic_retry') is False,
        'Remainder must not assign tools or replay')
    resolved = {}
    for key in ('source_partial_receipt_pin','writer_exit_pin','prepared_receipt_pin'):
        expected = r[key]
        require(type(expected) is dict and {'path','sha256'} <= set(expected) <= {'path','sha256','canonical_path','bytes','identity'}, 'Exact immutable history pin required')
        value,pin = read_pin(expected['path'],expected['sha256'])
        require(group.exact(pin,expected), 'Historical receipt pin differs')
        resolved[key] = value
    partial = resolved['source_partial_receipt_pin']; prepared = resolved['prepared_receipt_pin']
    remaining_names = resume.validate_partial(partial,resolved['writer_exit_pin'],r['source_partial_receipt_pin'])
    require(group.exact(r['source_after_tools_reference'],dict(receipt_pin=r['source_partial_receipt_pin'],
        key='after_tools',sha256=group._digest(partial['after_tools']))), 'Historical after-tools reference differs')
    require(prepared.get('scope') == resume.PREPARE_SCOPE and prepared.get('module_pin') == common._pin(resume.__file__)
        and prepared.get('status') == 'observed' and prepared.get('phase') == 'finished'
        and prepared.get('readback_verified') is True and prepared.get('continuation_ready') is True
        and prepared.get('read_only') is True, 'Completed read-only reconciliation required')
    require(not any(key in prepared for key in ('issue','failed_phase','cleanup_issue','receipt_write_error'))
        and all(prepared.get(key) is False for key in ('mutation_attempted','save_attempted','GTP_attempted')),
        'Uncertain or modifying reconciliation cannot authorize continuation')
    clean_events(prepared)
    require(prepared['source_partial_receipt_pin'] == r['source_partial_receipt_pin']
        and prepared['writer_exit_pin'] == r['writer_exit_pin'], 'Reconciliation references differ')
    require(group.exact(r['ownership'],partial['ownership']) and group.exact(r['ownership'],prepared['ownership'])
        and group.exact(prepared['document'],partial['current_document']), 'Historical owner/document differs')
    require(r['source_sha256'] == r['request']['expected_source_sha256'] == partial['source_sha256'] == prepared['source_sha256']
        and r['recipe_sha256'] == partial['recipe_sha256'] and group.exact(r['recipe'],partial['recipe'])
        and group.exact(r['configuration_pins'],partial['configuration_pins']), 'Historical source/recipe differs')
    for key in ('process_id','expected_configuration','addin_clsid'):
        require(group.exact(r['request'][key],partial['request'][key])
            and group.exact(r['request'][key],prepared['request'][key]), 'Resume request lineage differs: '+key)
    for candidate in (partial,prepared):
        require(common._key(candidate['source_path']) == common._key(r['source_path']), 'Historical source path differs')
    for pathkey,hashkey,pinkey in (('partial_receipt_path','partial_receipt_sha256','source_partial_receipt_pin'),
            ('writer_exit_path','writer_exit_sha256','writer_exit_pin'),('prepared_receipt_path','prepared_receipt_sha256','prepared_receipt_pin')):
        require(common._key(r['request'][pathkey]) == common._key(r[pinkey]['path'])
            and r['request'][hashkey] == r[pinkey]['sha256'], 'Resume request history pin differs')
    wanted = partial['after_tools']['parameters'][0]['tool']['generic']
    remaining = resume.reconcile(partial,prepared['actual'],wanted)
    require(group.exact(remaining,prepared['remaining']) and [v['action'] for v in remaining] == remaining_names,
        'Prepared untouched remainder differs')
    require(r['inherited_verified_action_names'] == list(partial['actions'])
        and list(r['actions']) == remaining_names + ['SaveActiveDocument']
        and not (set(partial['actions']) & set(r['actions'])), 'Remainder replays or omits a historical action')
    for name,action in r['actions'].items():
        require(action.get('status') == 'verified' and action.get('readback_verified') is True
            and not action.get('native_dispatch_pending'), 'Incomplete resumed action: '+name)
        if action.get('attempted') is True:
            ret = action.get('native_return',{})
            require(action.get('returned') is True and ret.get('python_type') == 'int'
                and ret.get('value_recorded') is True and type(ret.get('value')) is int and ret['value'] == 0,
                'Resumed native return is not confirmed S_OK')
        else:
            require(name != 'SaveActiveDocument' and action.get('attempted') is False and action.get('returned') is False
                and action.get('observed',{}).get('already_satisfied') is True, 'Unsupported resumed skip')
    pins = [r[key] for key in ('source_partial_receipt_pin','writer_exit_pin','prepared_receipt_pin')]
    pins += [common._pin(resume.__file__),common._pin(resume.fields.__file__)]
    return dict(after_tools=partial['after_tools'],prior_parameter_pin=r['prepared_receipt_pin'],pins=pins)

def completed_checkpoint(r, p):
    require(r.get('scope') in (configuration.SCOPE,RESUME_SCOPE) and r.get('status') == 'saved_configuration_no_toolpath'
        and r.get('phase') == 'finished', 'Completed saved configuration required')
    for key in ('readback_verified','configuration_readback_verified','model_saved','continuation_ready'):
        require(r.get(key) is True, 'Completed save proof required: '+key)
    require(not any(key in r for key in ('issue','failed_phase','cleanup_issue','receipt_write_error')),
        'Uncertain configuration cannot authorize close')
    require(r.get('GTP_attempted') is False and r.get('native_dispatch_pending') is False
        and r.get('persistence_after_reopen_verified') is False, 'Unexpected prior execution state')
    clean_events(r)
    checkpoint = r['saved_checkpoint_context']
    require(checkpoint['process_id'] == p['process_id'] == r['request']['process_id']
        and type(p['process_id']) is int and checkpoint['ownership']['process_id'] == p['process_id'], 'Exact owned PID required')
    require(group.exact(checkpoint['ownership'],r['ownership']), 'Saved owner differs')
    document = checkpoint['document']
    require(document.get('needs_save') is False and document.get('type') == 1
        and common._key(document['path']) == common._key(p['expected_document_path'])
        and common._key(r['source_path']) == common._key(p['expected_document_path']), 'Exact clean saved part required')
    require(checkpoint['source_sha256'] == p['expected_source_sha256'] == r['saved_source_sha256']
        and checkpoint['prior_source_sha256'] == r['source_sha256']
        and checkpoint['source_sha256'] != checkpoint['prior_source_sha256'], 'Exact new Save source transition required')
    require(checkpoint['snapshot_key'] == 'saved' and checkpoint['snapshot_sha256'] == group._digest(r['saved'])
        and checkpoint['persistence_after_reopen_verified'] is False, 'Exact saved parameter snapshot required')
    require(group.exact(document,r['source_transition']['document']) and group.exact(r['saved'],r['configured']),
        'Saved readback differs from configured state')
    history = resolve_resume_history(r) if r['scope'] == RESUME_SCOPE else None
    prior_pin = history['prior_parameter_pin'] if history else r['configuration_pins'][0]
    require(checkpoint['prior_parameter_receipt_pin'] == prior_pin, 'Parameter lineage differs')
    guide.configuration_binding.require_binding(checkpoint['configuration'])
    require(r['configuration_pins'][1]['sha256'] == r['recipe_sha256'], 'Explicit recipe pin differs')
    rows = r['recipe']['rows']
    require([(v['operation_native_id'],v['feature_native_id'],v['operation_type']) for v in rows] == TARGETS,
        'Exact four saved guide identities required')
    require(r['configured_operation_ids'] == [v[0] for v in TARGETS], 'Four verified configurations required')
    ops = r['saved']['binding']['operations']
    require([v['native_id'] for v in ops] == ORDER, 'Exact thirteen-operation order required')
    selected = {v['native_id']:v for v in ops if v['native_id'] in r['configured_operation_ids']}
    wanted = selected[322]['assigned_tool']
    require(wanted['native_id'] == 273 and wanted['cut_diameter_native'] == 2.0, 'Qualified existing D2 tool required')
    for oid,fid,kind in TARGETS:
        row = selected[oid]
        require(row['linked_feature_ids'] == [fid] and row['mill_operation_type'] == kind
            and row['setup_native_id'] == 93 and row['suppressed'] is False
            and row['toolpath_generated'] is False and row['toolpath_record_counts'] == []
            and group.exact(row['assigned_tool'],wanted), 'Saved guide binding differs')
    if history is None:configuration.verify_capture_links(r)
    after_tools = history['after_tools'] if history else r['after_tools']
    configuration.verify_configured(after_tools,r['saved'],r['recipe'],wanted)
    if history:
        for before,after in zip(after_tools['parameters'],r['saved']['parameters']):
            require(group.exact(configuration.protected_parameters(before),configuration.protected_parameters(after)), 'Saved resume changed unselected parameters')
    action = r['actions']['SaveActiveDocument']
    require(action.get('status') == 'verified' and action.get('readback_verified') is True
        and action.get('attempted') is True and action.get('returned') is True
        and action.get('native_dispatch_pending') is False, 'One completed native Save required')
    return dict(document=deepcopy(document), configuration=deepcopy(checkpoint['configuration']),
        baseline=deepcopy(r['saved']['binding']), expected_parameters=deepcopy(r['saved']),
        targets=[dict(row,assigned_tool=deepcopy(wanted)) for row in rows],
        history_pins=deepcopy(history['pins']) if history else [])


class CheckpointContext(UpperConeContext):
    def files(self):
        super().files()
        common._check(self.loaded['checkpoint_pins'])


class ParameterBackend:
    """Reuse the existing reader methods without the historical source loader."""
    events = group.NativeBackend.events
    start = group.NativeBackend.start
    boundary = group.NativeBackend.boundary
    finish = group.NativeBackend.finish
    close = group.NativeBackend.close
    batch = configuration.NativeBackend.batch
    capture_parameters = configuration.NativeBackend.capture_parameters
    configuration = guide.NativeBackend.configuration

    def __init__(self,loaded,args,sw,clsid,typelib_path,report,persist):
        self.loaded,self.args,self.sw = loaded,dict(args),sw
        self.clsid,self.typelib_path,self.report,self.persist = clsid,typelib_path,report,persist
        self.capture = capture_module
        self.session,self.session_active,self.doc,self.save_app = None,False,None,None
        self.ctx = CheckpointContext(loaded,self.args,sw,typelib_path,None,self.events,
            {'document':loaded['guide_parameters']['document']})


class NativeBackend:
    def __init__(self,loaded,args,sw,clsid,typelib_path,report,persist):
        self.loaded,self.args,self.sw,self.clsid,self.typelib_path = loaded,args,sw,clsid,typelib_path
        self.report,self.persist,self.parameter_reader = report,persist,None

    def start(self):
        require(self.parameter_reader is None, 'Fresh parameter reader required')
        self.parameter_reader = ParameterBackend(self.loaded,self.args,self.sw,self.clsid,self.typelib_path,self.report,self.persist)
        self.parameter_reader.start()

    def capture_parameters(self,label):
        return self.parameter_reader.capture_parameters(label)

    def capture_binding(self):
        backend = self.parameter_reader
        backend.boundary()
        with backend.ctx.guard() as guard:
            doc = guard.typed(guard.read(backend.ctx.app,'IGetActiveDoc'),'ICWDoc3')
        expected = self.loaded['guide_parameters']['configuration']
        def binding():require(group.exact(backend.configuration(doc),expected),'Saved configuration changed')
        binding(); state = dict(member='',returned=False,read_index=0)
        progress_path = str(Path(self.args['progress_path']).with_name(Path(self.args['progress_path']).stem+'.before_close.json'))
        protected = [self.args['expected_document_path'],self.args['receipt_path']] + [v['path'] for v in self.loaded['pins']+self.loaded['checkpoint_pins']]
        with reader.pocket.journal.ReadProgressJournal(full_persist=self.persist,progress_path=progress_path,
                describe=lambda:dict(state,phase='before_close_binding'),max_updates=4096,protected_paths=protected) as progress:
            batch = backend.batch(doc,progress.read,state,binding)
            try:
                with batch:
                    observed,_ = configuration.definitions.read_current_binding(doc,read=batch.read,typed=batch.typed)
                batch.require_complete();progress.complete()
            finally:self.report['preclose_read_batch'] = batch.summary();self.persist()
        binding();backend.boundary()
        return observed

    def check_clean(self):
        backend = self.parameter_reader
        backend.boundary()
        require(backend.ctx.identity()['needs_save'] is False, 'Never close unsaved document')
        require(_member(self.sw,'UserControl') is True, 'Native close requires UserControl=true')
        backend.boundary()

    def close_target(self,pending):
        self.check_clean(); backend = self.parameter_reader
        with backend.ctx.guard() as guard:
            app = guard.typed(backend.ctx.app,'ICWApp')
        backend.doc = None
        pending(); self.check_clean()
        value = _member(app,'CloseActiveDocument')
        backend.events()
        return value

    def _closed_boundary(self):
        require(self.parameter_reader is not None, 'Original owner verifier required')
        self.parameter_reader.ctx.files(); self.parameter_reader.ctx.owned()
        require(_member(self.sw,'GetProcessID') == self.args['process_id'], 'Owned application differs')
        require(_file_hash(self.args['expected_document_path']) == self.args['expected_source_sha256'], 'Saved source changed')

    def verify_closed(self):
        self._closed_boundary()
        documents = lifecycle._open_documents(self.sw,self.args['expected_document_path'],check=self._closed_boundary)
        self.report['open_documents_after_close'] = documents
        self.parameter_reader.events()
        return documents

    def disconnect_closed(self):
        backend = self.parameter_reader
        backend.close(); backend.events(False)
        backend.doc = backend.save_app = backend.ctx.app = None
        self.report.setdefault('event_sessions',[]).append(deepcopy(self.report['messages']))
        self._closed_boundary()

    def open_target(self,pending):
        self._closed_boundary()
        lifecycle._open_documents(self.sw,self.args['expected_document_path'],check=self._closed_boundary)
        pending(); self._closed_boundary()
        model = sw_connect.open_document(self.sw,self.args['expected_document_path'],read_only=False,silent=True,raise_on_error=True)
        require(model is not None, 'OpenDoc6 returned no model')
        # No cached CAM handles are used after OpenDoc6. The next start creates
        # a new reader and establishes the documented CAM-to-SW binding again.
        self.parameter_reader.ctx.identity()
        self.parameter_reader = None
        return True

    def finish(self):
        self.parameter_reader.finish()
        self.report.setdefault('event_sessions',[]).append(deepcopy(self.report['messages']))

    def close(self):
        if self.parameter_reader is not None:
            self.parameter_reader.close()
            if self.parameter_reader.session is not None:
                self.parameter_reader.events(False)
                self.report['cleanup_session_active'] = self.parameter_reader.session_active


class ReopenJournal(group.GroupJournal):
    def _marker_state(self):
        r = self.report
        return dict(scope=SCOPE,source_path=r['source_path'],source_sha256=r['source_sha256'],
            receipt_path=str(self.receipt),phase=r['phase'],status=r['status'],actions=deepcopy(r['actions']),
            native_dispatch_pending=r.get('native_dispatch_pending',False),automatic_replay=False)


def run_backend(backend,journal,loaded):
    r = journal.report
    require(not journal.created and not journal.claimed, 'Existing reopen attempt cannot replay')
    r.update(status='prepared',phase='prepared',actions={},mutation_attempted=False,native_call_attempted=False,
        native_call_returned=False,native_dispatch_pending=False,save_attempted=False,GTP_attempted=False,
        close_verified=False,reopen_verified=False,persistence_after_reopen_verified=False,
        readback_verified=False,automatic_retry=False,production_qualified=False)
    journal.create()
    try:
        backend.start()
        r['before_close_binding'] = backend.capture_binding();journal.persist()
        require(group.exact(r['before_close_binding'],loaded['guide_parameters']['baseline']), 'Current saved CAM binding differs')
        r['preclose_parameters_reused_from_saved_receipt'] = True
        r['preclose_parameter_changes_independently_excluded'] = False
        r['cam_dirty_state'] = 'not independently exposed; immediate owned Save continuation required'
        journal.persist()
        backend.check_clean()
        journal.execute('CloseActiveDocument',backend.close_target)
        backend.verify_closed();r['close_verified'] = True;journal.verified('CloseActiveDocument',True)
        backend.disconnect_closed()
        journal.entry('OpenDoc6')
        opened = backend.open_target(lambda:journal.pending('OpenDoc6'))
        entry = r['actions']['OpenDoc6']
        require(opened is True and entry.get('native_dispatch_pending') is True, 'Native Open bypassed pending')
        entry.update(returned=True,native_dispatch_pending=False,status='returned',native_return=dict(model_returned=True))
        r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist()
        backend.start()
        r['reopened'] = backend.capture_parameters('reopened');journal.persist()
        require(group.exact(r['reopened'],loaded['guide_parameters']['expected_parameters']), 'Reopened CAM parameters or route differ')
        backend.check_clean();backend.finish()
        journal.verified('OpenDoc6',True)
        r.update(status='reopen_verified',phase='finished',reopen_verified=True,
            persistence_after_reopen_verified=True,readback_verified=True)
    except Exception as exc:
        r.update(status='uncertain' if r['mutation_attempted'] else 'error',failed_phase=r['phase'],phase='finished',
            issue=_error(exc),readback_verified=False,persistence_after_reopen_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False,persistence_after_reopen_verified=False)
        journal.persist()
    return r


def prepare_request(request):
    require(type(request) is dict and set(request) == {'action','params'} and request['action'] == 'verify_guide_saved_reopen', 'Exact reopen action required')
    p = deepcopy(request['params'])
    require(type(p) is dict and set(p) == PARAMS, 'Exact reopen parameter keys required')
    require(p['acknowledgement'] == 'immediate_saved_continuation_no_intervening_cam_or_user_changes', 'Immediate saved continuation acknowledgement required')
    require(type(p['process_id']) is int and 0 < p['process_id'] < 2**31, 'Strict positive owned PID required')
    for key,value in p.items():
        if key.endswith('_path'): require(type(value) is str and Path(value).is_absolute(), 'Absolute path required')
        if key.endswith('_sha256'): require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value), 'Exact SHA required')
    require(p['module_sha256'] == _file_hash(__file__), 'Reopen module changed')
    r,pin = read_pin(p['configuration_receipt_path'],p['configuration_receipt_sha256'])
    recipe, _ = read_pin(r['configuration_pins'][1]['path'], r['recipe_sha256'])
    require(group.exact(recipe,r['recipe']), 'Pinned explicit recipe differs')
    selected = completed_checkpoint(r,p)
    if r['scope'] == configuration.SCOPE:
        require(r['module_pin'] == common._pin(configuration.__file__), 'Executed configuration module changed')
    require(_file_hash(p['expected_document_path']) == p['expected_source_sha256'], 'Saved source changed')
    pins = deepcopy(r['live_pins'])
    require(1 <= len(pins) <= 64, 'Existing bounded reader closure required')
    generated = [v for v in pins if Path(v['path']).name.startswith('_FE488661_0BD8_11D6_2012_2018CE99E55F_') and Path(v['path']).suffix == '.py']
    require(len(generated) == 1, 'Exact generated CAM metadata pin required')
    loaded = dict(pins=pins,ownership=deepcopy(r['ownership']),guide_parameters=selected,generated_pin=generated[0],
        configuration_pins=deepcopy(r['configuration_pins']),bootstrap_export_pins=[common._pin(installation.__file__)],
        checkpoint_pins=common._merge(r['configuration_pins'],[pin]+selected['history_pins']+[common._pin(v) for v in (__file__,lifecycle.__file__,sw_connect.__file__)]))
    common._check(loaded['pins']);common._check(loaded['checkpoint_pins'])
    registration = common.discover_export_registration(loaded,r['request']['addin_clsid'])
    typelib = str(Path(registration['addin_path']).parent/'camworks.tlb')
    require(common._pin(typelib) in pins, 'Installed TLB differs from saved reader')
    audit = reader.pocket.audit_interfaces(typelib,loaded['generated_pin'])
    p.update(expected_configuration=selected['configuration']['sw_configuration_name'])
    receipt,progress = common._local_receipt(p['receipt_path']),Path(p['progress_path'])
    marker = receipt.with_name('guide_reopen_'+group._digest(dict(scope=SCOPE,pid=p['process_id'],source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.json')
    forbidden = {common._key(v['path']) for v in pins+loaded['checkpoint_pins']} | {common._key(p['expected_document_path'])}
    for path in (receipt,progress,marker):
        require(path.parent.is_dir() and not path.exists() and not path.is_symlink() and common._key(path) not in forbidden, 'Fresh nonaliased output required')
    require(len({common._key(x) for x in (receipt,progress,marker)}) == 3, 'Distinct outputs required')
    return p,loaded,registration,typelib,audit,receipt,marker


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,audit,receipt,marker = prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,selected_ids=[v[0] for v in TARGETS],source_sha256=p['expected_source_sha256'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['checkpoint_pins'])
        sw,_ = sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report = dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),source_path=p['expected_document_path'],
            source_sha256=p['expected_source_sha256'],ownership=loaded['ownership'],interface_audit=audit)
        journal = ReopenJournal(report,receipt,marker)
        backend = NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        return run_backend(backend,journal,loaded)





