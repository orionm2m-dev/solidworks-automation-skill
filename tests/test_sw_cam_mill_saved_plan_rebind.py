from copy import deepcopy
from pathlib import Path
import hashlib
import json
import pytest
from scripts import sw_cam_mill_saved_plan_tools as old
from scripts import sw_cam_mill_saved_plan_rebind as m

@pytest.fixture
def case(tmp_path):
    part=tmp_path/'Qualification'/'model.SLDPRT';part.parent.mkdir();part.write_bytes(b'new-saved-model')
    stock=tmp_path/'stock.stl';stock.write_bytes(b'synthetic-stock-file')
    saved=digest_file(part)
    features=[dict(setup_index=0,feature_index=i,setup_native_id=69,
        geometry=dict(native_id=79+i,volume_type=2,shape_raw=2,suppressed=False)) for i in range(18)]
    tool=dict(native_id=145,is_mill_tool=True,native_read_complete=True,
              units_verified=False,holder_geometry_verified=False,tool_type_raw=1,
              cut_diameter_native=20.0,protrusion_native=60.0)
    ops=[dict(setup_index=0,setup_native_id=93,operation_index=i,native_id=143+i,
        mill_operation_type=i,base_operation_type=0,suppressed=False,toolpath_generated=False,
        linked_feature_ids=[79],toolpath_record_counts=[],assigned_tool=deepcopy(tool)) for i in range(2)]
    state=dict(document=dict(path=str(part),title=part.name,type=1,needs_save=False),
        saved_file_sha256=saved,features=features,operations=ops,operation_count=2,
        sw_reference=dict(solids=[],feature_tree=[]),
        operation_setup_count=1,operation_counts=[2],operation_setups=[dict(native_id=93,index=0,operation_count=2)],
        stock=dict(stl_path=str(stock),stl_sha256=digest_file(stock)),
        selected_profile_headers={'island_count':5})
    data=dict(scope=old.PLAN_SCOPE,action='save_checked',status='review_required',phase='finished',
        process_id=16516,native_hresult=0,expected_operation_setup_native_id=93,
        selected=dict(feature_native_id=79,owner_setup_native_id=69,volume_type=2,shape=2,
                      island_count=5,include_contours=False),
        before=deepcopy(state),after=state,source_before_sha256='a'*64,
        source_after_sha256=saved,saved_file_sha256=saved,state_sha256=old._digest(state),
        anchor=dict(scope=old.PLAN_SCOPE,pins=[dict(path='old-unavailable-receipt.json',sha256='b'*64)]),
        plan_receipt=dict(path='old-unavailable-plan.json',sha256='c'*64),
        messages=dict(subscribed=True,disconnected=True,active=False,event_count=0,overflow=0,
                      callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[]))
    for key in ('mutation_attempted','native_call_attempted','native_call_returned','save_attempted',
                'readback_verified','save_readback_verified','model_saved'):data[key]=True
    for key in ('native_dispatch_pending','GOP_attempted','GTP_attempted','AFR_attempted',
                'tool_assignment_attempted','stock_edit_attempted','geometry_edit_attempted',
                'TechDB_write_attempted','full_inventory_verified','world_geometry_verified',
                'production_qualified','post_cleanup_CAM_getters'):data[key]=False
    data['before']['saved_file_sha256']='a'*64
    data['before']['document']['needs_save']=True
    pin=tmp_path/'saved.json'
    args=dict(process_id=16516,expected_document_path=str(part),expected_source_sha256=saved,
        expected_feature_native_id=79,expected_operation_native_ids=[143,144],
        expected_operation_setup_native_id=93,expected_tool_native_id=145)
    def write():
        pin.write_text(json.dumps(data),encoding='utf-8')
        return digest_file(pin)
    return dict(data=data,args=args,pin=pin,part=part,stock=stock,write=write)

def digest_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def binding(case):
    c=case
    saved_sha=c['write']()
    original=old.load_saved_plan_tools_evidence(str(c['pin']),saved_sha,**c['args'])
    full=dict(tool_native_id=145,geometry_read_complete=True,profile_complete=True,
              mill_tool={'overall_length_native':100.0},profiles={'holder':'synthetic-full'})
    details=dict(items=[dict(operation_native_id=i,full_tool=deepcopy(full)) for i in (143,144)],
        metadata_read_complete=True,profile_complete=True,
        generic_operation_context_unchanged=True,canonical_state_changed=False)
    tool=dict(scope=old.SCOPE,status='review_required',phase='finished',process_id=16516,
        read_only=True,anchor=original.summary(),saved_file_sha256=c['args']['expected_source_sha256'],
        before=deepcopy(original.state),after=deepcopy(original.state),
        before_tool_details=deepcopy(details),after_tool_details=deepcopy(details),
        state_sha256=m._digest(original.state),tool_details_sha256=m._digest(details),
        messages=deepcopy(c['data']['messages']))
    tool.update({k:False for k in m.FALSE_FLAGS})
    tool.update({k:True for k in m.TRUE_FLAGS})
    tool_path=c['pin'].with_name('tool.json')
    owner=dict(status='ok',phase='connected',launch_mode='executable',
        launch_attempted=True,new_process_verified=True,user_control_verified=True,
        automatic_retry=False,termination_attempted=False,process_id=13484,
        executable=str(c['pin'].with_name('SLDWORKS.exe')),
        known_process_ids_before=[16516,43920],
        process_identity=dict(process_id=13484,create_time=1000.25,alive=True,
                              executable=str(c['pin'].with_name('SLDWORKS.exe'))))
    owner_path=c['pin'].with_name('startup.json')
    args=dict(c['args'],process_id=13484,previous_process_id=16516,
        saved_plan_receipt_path=str(c['pin']),saved_plan_receipt_sha256=saved_sha,
        tool_receipt_path=str(tool_path),tool_receipt_sha256=None,
        owned_startup_receipt_path=str(owner_path),owned_startup_receipt_sha256=None)
    def write():
        tool_path.write_text(json.dumps(tool),encoding='utf-8')
        owner_path.write_text(json.dumps(owner),encoding='utf-8')
        args['tool_receipt_sha256']=digest_file(tool_path)
        args['owned_startup_receipt_sha256']=digest_file(owner_path)
    write()
    return dict(case=c,tool=tool,tool_path=tool_path,details=details,owner=owner,
                owner_path=owner_path,args=args,write=write)


class FakeSession:
    last=None
    def __init__(self,*args):
        self.active=False;self.closed=False;self.event=False;self.close_error=False
        FakeSession.last=self
    def __enter__(self):self.active=True;return self
    def __exit__(self,*args):self.active=False;self.closed=True
    def summary(self):
        return dict(subscribed=True,active=self.active,disconnected=self.closed,
                    event_count=int(self.event),disconnect_errors=['bad'] if self.close_error else [])


def run_case(b,monkeypatch,mode='ok'):
    import scripts.sw_cam_events as events
    monkeypatch.setattr(events,'CamMessageSession',FakeSession)
    c=b['case'];calls=[]
    monkeypatch.setattr(m,'_member',lambda *a:43920 if mode=='wrong_pid' else 13484)
    monkeypatch.setattr(m,'raw_part_identity',lambda sw:deepcopy(c['data']['after']['document']))
    def process(pid):
        row=deepcopy(b['owner']['process_identity'])
        if mode=='pid_reuse':row['create_time']+=1
        return row
    monkeypatch.setattr(m,'_process_identity',process)
    monkeypatch.setattr(m,'_bootstrap',lambda *a:'app')
    def capture(*args,**kw):
        calls.append(1);kw['check']()
        assert kw['process_id']==13484 and kw['evidence'].historical_process_id==16516
        state=deepcopy(c['data']['after']);details=deepcopy(b['details'])
        if mode=='neighbor':state['features'][-1]['geometry']['shape_raw']=999
        if mode=='stock':state['stock']['stl_sha256']='d'*64
        if mode=='operation':state['operations'][0]['linked_feature_ids']=[80]
        if mode=='full_tool':details['items'][0]['full_tool']['mill_tool']['overall_length_native']=39
        if mode=='partial':details['profile_complete']=False
        if mode=='shared_user':details['items'].pop()
        if mode=='file':c['part'].write_bytes(b'drift')
        if mode=='evidence':b['tool_path'].write_text('{}')
        if mode=='event':FakeSession.last.event=True
        if mode=='cleanup':FakeSession.last.close_error=True
        if mode=='capture_error':raise RuntimeError('synthetic transport failure')
        if mode=='second_capture' and len(calls)==2:state['features'][0]['geometry']['shape_raw']=7
        kw['diagnostic']['operation_details']={'selected_tool_details':details}
        return state,{}
    monkeypatch.setattr(m,'capture_selected_plan',capture)
    path=c['pin'].with_name('rebind.json')
    result=m.verify_saved_plan_session('sw','clsid','tlb',**b['args'],
        qualification_only=True,acknowledge_disposable_copy=True,receipt_path=str(path))
    return result,calls,path


def test_explicit_new_session_success_and_consumer(binding,monkeypatch):
    oldbytes=binding['case']['pin'].read_bytes();toolbytes=binding['tool_path'].read_bytes()
    report,calls,path=run_case(binding,monkeypatch)
    assert report['session_rebind_verified'] is True,report
    assert len(calls)==2 and FakeSession.last.closed
    assert binding['case']['pin'].read_bytes()==oldbytes and binding['tool_path'].read_bytes()==toolbytes
    args=dict(binding['case']['args'],process_id=13484)
    e=old.load_saved_plan_tools_evidence(str(binding['case']['pin']),
        binding['args']['saved_plan_receipt_sha256'],**args,
        session_rebind_receipt_path=str(path),session_rebind_receipt_sha256=digest_file(path))
    assert e.bound_process_id==13484 and e.historical_process_id==16516
    assert e.data['process_id']==16516 and e.historical_summary()==binding['tool']['anchor']
    assert e.baseline_tool_details==binding['details'] and len(e.pins)==5
    e.check_runtime_identity()
    assert all(report[k] is False for k in m.FALSE_FLAGS)


@pytest.mark.parametrize('mode',['wrong_pid','pid_reuse','neighbor','stock','operation','full_tool',
    'partial','shared_user','file','evidence','event','cleanup','capture_error','second_capture'])
def test_fail_closed(binding,monkeypatch,mode):
    FakeSession.last=None
    report,calls,path=run_case(binding,monkeypatch,mode)
    assert report['status']=='error' and report['session_rebind_verified'] is False
    assert report['readback_verified'] is False and report['tool_profile_complete'] is False
    assert all(report[k] is False for k in m.FALSE_FLAGS)
    if FakeSession.last is not None:assert FakeSession.last.closed


@pytest.mark.parametrize('field,value',[('process_id',13484),('read_only',False),
    ('tool_profile_complete',False),('mutation_attempted',True),('state_sha256','c'*64)])
def test_bad_historical_tool_rejected(binding,field,value):
    binding['tool'][field]=value;binding['write']()
    with pytest.raises(ValueError):m._load_baseline(**binding['args'])


@pytest.mark.parametrize('field,value',[('process_id',True),('new_process_verified',False),
    ('automatic_retry',True),('known_process_ids_before',[13484]),('phase','waiting')])
def test_bad_ownership_rejected(binding,field,value):
    binding['owner'][field]=value;binding['write']()
    with pytest.raises(ValueError):m._load_baseline(**binding['args'])


def test_default_old_loader_remains_strict(binding):
    a=dict(binding['case']['args'],process_id=13484)
    with pytest.raises(ValueError):
        old.load_saved_plan_tools_evidence(str(binding['case']['pin']),
            binding['args']['saved_plan_receipt_sha256'],**a)


@pytest.mark.parametrize('pair',[{'session_rebind_receipt_path':'missing.json'},
                                  {'session_rebind_receipt_sha256':'a'*64}])
def test_no_partial_optional_pair(binding,pair):
    with pytest.raises(ValueError):
        old.load_saved_plan_tools_evidence(str(binding['case']['pin']),
            binding['args']['saved_plan_receipt_sha256'],**binding['case']['args'],**pair)


def test_finished_write_failure_revokes_success(binding,monkeypatch):
    write=m._write_receipt
    def fail(path,data,*args,**kwargs):
        if data.get('session_rebind_verified') is True:raise OSError('disk full')
        return write(path,data,*args,**kwargs)
    monkeypatch.setattr(m,'_write_receipt',fail)
    report,calls,path=run_case(binding,monkeypatch)
    assert len(calls)==2 and report['status']=='error'
    assert report['session_rebind_verified'] is False and 'receipt_write_error' in report


def test_rebind_does_not_authorize_another_current_pid(binding,monkeypatch):
    report,calls,path=run_case(binding,monkeypatch)
    a=dict(binding['case']['args'],process_id=43920)
    with pytest.raises(ValueError):
        old.load_saved_plan_tools_evidence(str(binding['case']['pin']),
            binding['args']['saved_plan_receipt_sha256'],**a,
            session_rebind_receipt_path=str(path),session_rebind_receipt_sha256=digest_file(path))


def test_changed_pin_rejected_on_consumer_recheck(binding,monkeypatch):
    report,calls,path=run_case(binding,monkeypatch)
    a=dict(binding['case']['args'],process_id=13484)
    e=old.load_saved_plan_tools_evidence(str(binding['case']['pin']),
        binding['args']['saved_plan_receipt_sha256'],**a,
        session_rebind_receipt_path=str(path),session_rebind_receipt_sha256=digest_file(path))
    path.write_text('{}')
    with pytest.raises(ValueError):e.check_files()


def test_no_mutating_native_calls():
    import ast
    p=Path(__file__).resolve().parents[1]/'scripts/sw_cam_mill_saved_plan_rebind.py'
    tree=ast.parse(p.read_text(encoding='utf-8'))
    forbidden={'Save','Save3','SaveAs','SetTool','GenerateOperationPlan','GenerateToolpath','EMF','GOP','GTP'}
    for n in ast.walk(tree):
        if isinstance(n,ast.Call):
            name=n.func.attr if isinstance(n.func,ast.Attribute) else n.func.id if isinstance(n.func,ast.Name) else ''
            assert name not in forbidden
