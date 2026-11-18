"""Recovery contracts; synthetic backends only, no application/COM."""
from copy import deepcopy
import os,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
RT=Path(os.environ.get('SWMCP_RUNTIME_ROOT',ROOT))
sys.path.insert(0,str(RT));sys.path.insert(0,str(RT/'tests'))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_current_pair_tool_recovery as core
from test_current_pair_tool_contract import snapshot,assigned,FakeBackend,data_and_report,flow


def request(tmp_path):
    v=dict(process_id=10,expected_process_create_time=123.,expected_document_path=str(tmp_path/'part.SLDPRT'),expected_source_sha256='b'*64,expected_feature_native_id=66,expected_operation_native_ids=[114,115],selected_operation_native_id=114,expected_tool_native_id=202,qualification_only=True,acknowledge_existing_tool_recovery=True,message_policy='vendor_default')
    for k in ('partial_receipt','original_marker','cli_result','executor_exit'):v.update({k+'_path':str(tmp_path/(k+'.json')),k+'_sha256':'a'*64})
    v['receipt_path']=str(tmp_path/'recovery.json');return v


def raw_and_request(tmp_path,monkeypatch):
    data,r=data_and_report(tmp_path);v=request(tmp_path)
    old={k:v[k]for k in core.current.IDENTITY_KEYS};old['selected_operation_native_id']=114
    for k in ('current_context_receipt','recipe','holder_file','holder_recipe'):old.update({k+'_path':str(tmp_path/(k+'.json')),k+'_sha256':'a'*64})
    old.update(receipt_path=v['partial_receipt_path'],qualification_only=True,acknowledge_one_tool_creation=True,message_policy='vendor_default')
    done=dict(attempted=True,returned=True,pending=False,native_return_type='int',native_return_value=0)
    raw=dict(scope=core.tool.SCOPE,status='prepared',phase='before',mutation_attempted=True,assignment_attempted=True,Save_attempted=False,model_saved=False,request=old,new_tool_native_id=202,initial_source_sha256='b'*64,recipe=data['recipe'],holder_recipe=data['holder'],configured_candidate={'full_tool':{'id':202},'identity':data['recipe']['identity']},duplicate_policy={'new_definition_permitted_by_duplicate_policy':True},factory_classification={'MillToolType':1,'MillToolSubType':3,'EndRadius':0.},messages={'test_clean':True},before=snapshot(),after_assignment=assigned(),captures=[{'label':'configured_unassigned','observation':snapshot()}],source_path=old['expected_document_path'],receipt_path=old['receipt_path'],protected_tools_before={'116':{'native_id':116,'profile':'original','holder':'original'}},initial_catalogue=[{'native_id':116,'tool_type_raw':1,'CutDiameter':20.,'Protrusion':60.}])
    for k in ('GOP_attempted','GTP_attempted','Import_attempted','operation_parameter_setters_attempted','TechDB_write_attempted','automatic_replay','production_qualified'):raw[k]=False
    raw['actions']={'AddNewTool3':dict(attempted=True,returned=True,pending=False,returned_interface_pointer=True),'SetTool':deepcopy(done),'SetFilePathForUserDefinedHolder':deepcopy(done)}
    raw['field_readbacks']=[dict(property=k,requested=data['proposed'][k],actual=data['proposed'][k],readback_verified=True)for k in core.tool.factory.FIELD_ORDER]
    monkeypatch.setattr(core.tool.serial,'validate_recipe',lambda recipe:dict(recipe['target'],**recipe['identity']))
    monkeypatch.setattr(core.tool.geometry,'verify_candidate',lambda *a:dict(profile_verified=True))
    monkeypatch.setattr(core.tool.reader.shared,'event_health',lambda m,active=False:0 if m.get('test_clean') else 1)
    return raw,v


def saved(raw,v):
    raw=deepcopy(raw);v=deepcopy(v);v['expected_source_sha256']='c'*64
    raw.update(Save_attempted=True,model_saved=True,saved_file_sha256_after_native_return='c'*64,native_save=dict(save_pending=False,native_call_returned=True,native_return_type='int',native_return_value=0),save_snapshots={'before':deepcopy(raw['after_assignment'])})
    raw['actions']['SaveActiveDocument']=dict(attempted=True,returned=True,pending=False,native_return_type='int',native_return_value=0)
    return raw,v


def test_both_exact_admissible_branches(tmp_path,monkeypatch):
    raw,v=raw_and_request(tmp_path,monkeypatch);core.shape(v);assert core.validate_partial(raw,v)=='save_once'
    raw,v=saved(raw,v);assert core.validate_partial(raw,v)=='read_saved'


@pytest.mark.parametrize('fault',['pending_assign','assign_bool','assign_missing','pending_create','pending_save','saved_bool','save_not_returned','model_not_saved','save_without_hash','wrong_source','wrong_tool','wrong_pid','wrong_lifetime','wrong_path','field_missing','field_not_verified','field_wrong','GTP','message','runtime','configured_drift','assignment_depth','assignment_dirty_missing'])
def test_authority_misuse_rejected_before_backend(tmp_path,monkeypatch,fault):
    raw,v=raw_and_request(tmp_path,monkeypatch)
    if fault in {'pending_save','saved_bool','save_not_returned','model_not_saved','save_without_hash'}:raw,v=saved(raw,v)
    if fault=='pending_assign':raw['actions']['SetTool']['pending']=True
    elif fault=='assign_bool':raw['actions']['SetTool']['native_return_value']=False
    elif fault=='assign_missing':del raw['actions']['SetTool']
    elif fault=='pending_create':raw['actions']['AddNewTool3']['returned']=False
    elif fault=='pending_save':raw['native_save']['save_pending']=True
    elif fault=='saved_bool':raw['native_save']['native_return_value']=False
    elif fault=='save_not_returned':raw['actions']['SaveActiveDocument']['returned']=False
    elif fault=='model_not_saved':raw['model_saved']=False
    elif fault=='save_without_hash':del raw['saved_file_sha256_after_native_return']
    elif fault=='wrong_source':v['expected_source_sha256']='d'*64
    elif fault=='wrong_tool':v['expected_tool_native_id']=203
    elif fault=='wrong_pid':v['process_id']=11
    elif fault=='wrong_lifetime':v['expected_process_create_time']=124.
    elif fault=='wrong_path':v['expected_document_path']=str(tmp_path/'other.SLDPRT')
    elif fault=='field_missing':raw['field_readbacks'].pop()
    elif fault=='field_not_verified':raw['field_readbacks'][0]['readback_verified']=False
    elif fault=='field_wrong':raw['field_readbacks'][0]['actual']=999.
    elif fault=='GTP':raw['GTP_attempted']=True
    elif fault=='message':raw['messages']={}
    elif fault=='runtime':raw['runtime_error']={'error':'changed'}
    elif fault=='configured_drift':raw['captures'][0]['observation']['parameters'][1]['nc']['S']=1.
    elif fault=='assignment_depth':raw['after_assignment']['parameters'][0]['levels']['depth']=0.
    elif fault=='assignment_dirty_missing':del raw['after_assignment']
    with pytest.raises(Exception):core.validate_partial(raw,v)


def interruption(raw,v):
    marker=dict(scope=core.tool.SCOPE,actions=deepcopy(raw['actions']),new_tool_native_id=202,receipt_path=v['partial_receipt_path'],source_path=raw['source_path'],initial_source_sha256='b'*64,automatic_replay=False)
    v['original_marker_path']=str(core.tool.marker_path(raw['request']))
    ex=dict(scope='CURRENT_PAIR_TOOL_EXECUTOR_EXIT_V1',status='observed',all_executors_absent=True,process_id=v['process_id'],expected_process_create_time=v['expected_process_create_time'],expected_document_path=v['expected_document_path'],executor_processes=[dict(process_id=100,creation_time=1.,alive=False,role='client'),dict(process_id=101,creation_time=2.,alive=False,role='backend')])
    for prefix in ('partial_receipt','original_marker','cli_result'):ex[prefix+'_pin']=dict(path=v[prefix+'_path'],sha256=v[prefix+'_sha256'])
    return marker,{'status':'timeout','current_request':{'name':'solidworks_cam_create_assign_current_pocket_tool'}},ex


@pytest.mark.parametrize('fault',[None,'cli_pending','still_alive','pin','once','pid_reuse_live','target_pid'])
def test_interruption_lineage_gate(tmp_path,monkeypatch,fault):
    raw,v=raw_and_request(tmp_path,monkeypatch);marker,cli,ex=interruption(raw,v)
    if fault=='cli_pending':cli['status']='running'
    elif fault=='still_alive':ex['executor_processes'][1]['alive']=True
    elif fault=='pin':ex['partial_receipt_pin']['sha256']='f'*64
    elif fault=='once':marker['actions']['SetTool']['pending']=True
    elif fault=='pid_reuse_live':ex['executor_processes'][0]['process_id']=101
    elif fault=='target_pid':ex['executor_processes'][0]['process_id']=v['process_id']
    if fault:
        with pytest.raises(Exception):core.validate_interruption(v,raw,marker,cli,ex)
    else:core.validate_interruption(v,raw,marker,cli,ex)


def test_exit_rechecks_lifetime_allows_unrelated_reused_pid_and_logs_console():
    ex={'executor_processes':[dict(process_id=10,creation_time=1.,role='backend'),dict(process_id=11,creation_time=2.,role='client'),dict(process_id=12,creation_time=3.,role='console')]}
    observed=core.check_executors(ex,creation_time=lambda pid:{10:20.,11:None,12:3.}[pid])
    assert [x['original_alive']for x in observed]==[False,False,True]
    with pytest.raises(Exception):core.check_executors(ex,creation_time=lambda pid:{10:1.,11:None,12:None}[pid])


class RecoveryBackend(FakeBackend):
    def __init__(self,data,r,fault=None):
        super().__init__(data,r,fault);self.created=self.assigned=True;self.fields=deepcopy(data['proposed']);self.saved=data['branch']=='read_saved'
        if self.saved:self.d['expected_source_sha256']='c'*64
    def bind_existing(self):self.calls.append('bind_existing');return self.catalogue()
    def capture_current(self,label):
        s=super().capture_current(label)
        if self.fault=='fresh_pair':s['parameters'][1]['nc']['S']=1.
        if self.fault=='dirty':s['inventory']['document']['needs_save']=True
        return s
    def candidate(self,label):
        v=super().candidate(label)
        if self.fault=='candidate':v['full_tool']['id']=203
        return v
    def full_existing(self,tid,label):
        v=super().full_existing(tid,label)
        if self.fault=='protected':v['profile']='wrong'
        return v
    def create(self,*a):pytest.fail('No new creation')
    def assign_selected(self,*a):pytest.fail('No assignment replay')
    def property(self,*a):pytest.fail('No field replay')
    def attach_holder(self,*a):pytest.fail('No holder replay')


def setup_flow(flow,tmp_path,monkeypatch):
    data,r=flow;raw,v=raw_and_request(tmp_path,monkeypatch)
    data.update(raw=raw,branch='save_once',request=v)
    r.update(scope=core.SCOPE,branch='save_once',partial_receipt_pin=dict(path=v['partial_receipt_path'],sha256=v['partial_receipt_sha256']),current_baseline_receipt_pin=data['bundle']['receipt_pin'])
    return data,r


def test_exact_existing_tool_one_save_no_replayed_setters(flow,tmp_path,monkeypatch):
    data,r=setup_flow(flow,tmp_path,monkeypatch);b=RecoveryBackend(data,r);j=core.Journal(r,data['receipt'],data['marker'])
    raw_before=deepcopy(data['raw']);result=core.run_backend(b,j,data)
    assert result['status']=='review_required',result
    assert b.calls.count('save')==1 and set(result['actions'])=={'SaveActiveDocument'}
    assert all(result[k]for k in core.tool.ACCEPTANCE) and data['marker'].exists()
    assert data['raw']==raw_before
    with pytest.raises(Exception):core.Journal(deepcopy(r),tmp_path/'other.json',data['marker']).claim()


@pytest.mark.parametrize('fault',['fresh_pair','dirty','candidate','protected','classification','cleanup','runtime','final_files'])
def test_fresh_negative_stops_no_replay(flow,tmp_path,monkeypatch,fault):
    data,r=setup_flow(flow,tmp_path,monkeypatch);b=RecoveryBackend(data,r,fault);j=core.Journal(r,data['receipt'],data['marker']);old=deepcopy(data['raw'])
    result=core.run_backend(b,j,data)
    assert result['status']=='uncertain' and not any(result[k]for k in core.tool.ACCEPTANCE)
    assert b.calls.count('save')<=1 and data['marker'].exists() and data['raw']==old
    if fault in {'fresh_pair','dirty','candidate','protected','classification'}:assert 'save'not in b.calls


def test_native_recovery_backend_mutators_are_unreachable():
    b=object.__new__(core.Backend)
    for name in ('create','assign_selected','property','attach_holder'):
        with pytest.raises(ValueError):getattr(b,name)()


def test_saved_branch_cannot_dispatch_save(tmp_path):
    r=dict(scope=core.SCOPE,branch='read_saved',phase='prepared',source_path=str(tmp_path/'part'),initial_source_sha256='c'*64,partial_receipt_pin={'path':'raw','sha256':'a'*64},actions={},mutation_attempted=False)
    j=core.Journal(r,tmp_path/'out.json',tmp_path/'once.json')
    with pytest.raises(Exception):j.pending('SaveActiveDocument')
    assert not j.marker.exists()


def test_request_rejects_extra_mutation_option(tmp_path):
    v=request(tmp_path);v['recreate_tool']=True
    with pytest.raises(Exception):core.shape(v)


from test_current_pocket_context import probe,run as save_probe,terminal


def test_default_executor_probe_uses_existing_win32_helper_and_fails_on_denial(monkeypatch):
    ex={'executor_processes':[dict(process_id=10,creation_time=1.,role='backend')]}
    monkeypatch.setattr(core.definition,'_process_identity',lambda pid:dict(process_id=pid,create_time=2.,alive=True))
    assert core.check_executors(ex)[0]['original_alive']is False
    class Win32Failure(Exception):
        def __init__(self,code):self.winerror=code
    def absent(pid):raise Win32Failure(87)
    monkeypatch.setattr(core.definition,'_process_identity',absent)
    assert core.check_executors(ex)[0]['actual_creation_time']is None
    def denied(pid):raise Win32Failure(5)
    monkeypatch.setattr(core.definition,'_process_identity',denied)
    with pytest.raises(Win32Failure):core.check_executors(ex)


def test_read_saved_reconstruction_roundtrips_current_loader_without_Save(probe):
    p=probe;original=save_probe(p);raw=deepcopy(p['report']);old=deepcopy(raw)
    raw['request']={'expected_source_sha256':p['bundle']['context']['expected_source_sha256']}
    bundle=deepcopy(p['bundle']);bundle['context']=deepcopy(original['context'])
    data={'raw':raw,'bundle':bundle,'request':deepcopy(original['payload']['identity'])}
    r={'scope':core.SCOPE,'partial_receipt_pin':p['bundle']['receipt_pin'],'current_baseline_receipt_pin':p['bundle']['receipt_pin']}
    calls_before=list(p['calls']);core.restore_saved_context(r,data,original['payload']['snapshot'],lambda:None)
    assert p['calls']==calls_before and raw['native_save']==old['native_save']
    p['report']=r;v=terminal(p,original,'recovered.json')
    loaded=core.current.load_current_baseline(v)
    assert loaded['state']==original['state'] and r['save_provenance']['kind']=='original_returned_save_then_fresh_readback'


def test_full_read_saved_flow_performs_zero_Save(flow,tmp_path,monkeypatch,probe):
    data,r=setup_flow(flow,tmp_path,monkeypatch);data['raw'],data['request']=saved(data['raw'],data['request']);data['branch']=r['branch']='read_saved'
    data['bundle']['context']=deepcopy(probe['bundle']['context']);data['bundle']['context']['expected_source_sha256']='c'*64
    data['bundle']['context']['current_sketch_baseline']['saved_file_sha256']='c'*64
    data['bundle']['root_pins']=deepcopy(probe['bundle']['root_pins'])
    b=RecoveryBackend(data,r);j=core.Journal(r,data['receipt'],data['marker']);old=deepcopy(data['raw'])
    result=core.run_backend(b,j,data)
    assert result['status']=='review_required',result
    assert 'save'not in b.calls and result['actions']=={} and result['Save_attempted']is False
    assert result['save_readback_verified'] and result['model_saved'] and data['raw']==old


def test_save_exception_retains_pending_and_consumes_attempt(flow,tmp_path,monkeypatch):
    data,r=setup_flow(flow,tmp_path,monkeypatch);b=RecoveryBackend(data,r)
    def fail():b.calls.append('save');raise RuntimeError('Save has unknown outcome')
    b.save=fail;j=core.Journal(r,data['receipt'],data['marker']);result=core.run_backend(b,j,data)
    assert result['status']=='uncertain' and b.calls.count('save')==1
    assert result['actions']['SaveActiveDocument']['pending']is True and data['marker'].exists()
    with pytest.raises(Exception):j.pending('SaveActiveDocument')


@pytest.mark.parametrize('record',[{}, {'phase':'before_capture'}])
def test_preSave_capture_record_is_unattempted(tmp_path,monkeypatch,record):
    raw,v=raw_and_request(tmp_path,monkeypatch);raw['native_save']=record
    assert core.validate_partial(raw,v)=='save_once'


@pytest.mark.parametrize('record',[{'phase':'SaveActiveDocument'}, {'phase':'before_capture','save_attempted':True}, {'phase':'before_capture','native_call_returned':True}, {'phase':'before_capture','save_pending':True}])
def test_uncertain_native_Save_state_never_admitted_as_unattempted(tmp_path,monkeypatch,record):
    raw,v=raw_and_request(tmp_path,monkeypatch);raw['native_save']=record
    with pytest.raises(Exception):core.validate_partial(raw,v)



def test_evidence_merge_removes_only_identical_duplicate_pins_and_keeps_limit(tmp_path):
    pins=[dict(path=str(tmp_path/(str(i)+'.json')),sha256='a'*64)for i in range(40)]
    assert len(core.merged_pins(pins,pins))==40
    with pytest.raises(Exception):core.merged_pins(pins,[dict(pins[0],sha256='b'*64)])
    extra=[dict(path=str(tmp_path/('extra'+str(i)+'.json')),sha256='a'*64)for i in range(25)]
    with pytest.raises(Exception):core.merged_pins(pins,extra)


@pytest.mark.parametrize('flag',['mutation_attempted','Save_attempted','GOP_attempted','GTP_attempted','Import_attempted','tool_creation_attempted','tool_assignment_attempted','automatic_replay','physical_tool_qualified','native_units_verified','cutting_conditions_qualified','island_geometry_verified','production_qualified'])
def test_historical_pair_never_promotes_unexpected_action(tmp_path,monkeypatch,flag):
    raw,v=raw_and_request(tmp_path,monkeypatch)
    pair=dict(scope=core.tool.reader.SCOPE,status='observed',phase='finished',read_only=True,**{k:True for k in core.tool.reader.FLAGS})
    for k in ('mutation_attempted','Save_attempted','GOP_attempted','GTP_attempted','Import_attempted','tool_creation_attempted','tool_assignment_attempted','automatic_replay','physical_tool_qualified','native_units_verified','cutting_conditions_qualified','island_geometry_verified','production_qualified'):pair[k]=False
    pair[flag]=True;monkeypatch.setattr(core.definition,'read_pin',lambda *a:(pair,{}))
    with pytest.raises(Exception,match='Original pair action/qualification'):core.historical_bundle(raw,v)


def test_save_input_dedup_preserves_all_root_authority_and_bound(probe):
    p=probe;bundle=p['bundle'];original=deepcopy(bundle)
    # Forty root pins repeated in the full context must not become eighty.
    extras=[]
    for i in range(40):
        path=p['target'].parent/('extra'+str(i)+'.json');path.write_text('{}',encoding='utf-8')
        extras.append(dict(path=str(path),sha256=core._file_hash(path)))
    bundle['root_pins']+=extras;bundle['context']['pins']+=extras
    reduced=core.save_bundle_without_duplicate_roots(bundle)
    assert len(reduced['root_pins'])==1 and reduced['context']['pins']==bundle['context']['pins']
    p['bundle']=reduced;result=save_probe(p);v=terminal(p,result,'manyroots.json')
    loaded=core.current.load_current_baseline(v)
    assert len(loaded['root_pins'])==42 and loaded['state']==result['state']



def test_save_input_missing_guard_pin_rejected(probe):
    b=probe['bundle'];b['context']['pins']=b['context']['pins'][1:]
    with pytest.raises(Exception,match='omitted a root pin'):core.save_bundle_without_duplicate_roots(b)
