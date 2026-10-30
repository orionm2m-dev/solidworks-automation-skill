"""Synthetic saved-plan contract and lifecycle tests; never connect to SOLIDWORKS."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import pytest
from scripts import sw_cam_mill_saved_plan_tools as m


def digest_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    data=dict(scope=m.PLAN_SCOPE,action='save_checked',status='review_required',phase='finished',
        process_id=16516,native_hresult=0,expected_operation_setup_native_id=93,
        selected=dict(feature_native_id=79,owner_setup_native_id=69,volume_type=2,shape=2,
                      island_count=5,include_contours=False),
        before=deepcopy(state),after=state,source_before_sha256='a'*64,
        source_after_sha256=saved,saved_file_sha256=saved,state_sha256=m._digest(state),
        anchor=dict(scope=m.PLAN_SCOPE,pins=[dict(path='old-unavailable-receipt.json',sha256='b'*64)]),
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


def load(c):
    return m.load_saved_plan_tools_evidence(str(c['pin']),c['write'](),**c['args'])


def test_saved_anchor_never_replays_older_receipts(case):
    e=load(case)
    assert e.operation_ids==[143,144] and e.tool_id==145
    assert e.summary()['previous_anchor_replayed'] is False
    assert len(e.pins)==2
    assert e.verify(deepcopy(case['data']['after']))
    assert e.summary()['original_source_sha256']=='a'*64


@pytest.mark.parametrize('key,value',[
    ('process_id',49032),('process_id',True),('native_hresult',False),('scope','full'),
    ('save_readback_verified',False),('model_saved',False),('GOP_attempted',True),
    ('production_qualified',True),('state_sha256','e'*64),('source_after_sha256','e'*64),
    ('expected_operation_setup_native_id',69),('receipt_write_error',{}),
])
def test_invalid_saved_receipt(case,key,value):
    case['data'][key]=value
    with pytest.raises(ValueError):load(case)


@pytest.mark.parametrize('key,value',[
    ('expected_source_sha256','d'*64),('process_id',49032),('expected_operation_native_ids',[144,143]),
    ('expected_operation_native_ids',[143]),('expected_operation_native_ids',[143,143]),
    ('expected_operation_native_ids',[143,True]),('expected_operation_native_ids',(143,144)),
    ('expected_tool_native_id',146),('expected_feature_native_id',80),('expected_operation_setup_native_id',69)
])
def test_request_binding_rejected(case,key,value):
    case['args'][key]=value
    with pytest.raises(ValueError):load(case)


def test_wrong_sha_rejected(case):
    case['write']()
    with pytest.raises(ValueError):
        m.load_saved_plan_tools_evidence(str(case['pin']),'e'*64,**case['args'])


def test_dirty_saved_or_wrong_path_rejected(case):
    case['data']['after']['document']['needs_save']=True
    case['data']['state_sha256']=m._digest(case['data']['after'])
    with pytest.raises(ValueError):load(case)


@pytest.mark.parametrize('field,value',[('setup_native_id',69),('linked_feature_ids',[80]),
    ('toolpath_generated',True),('toolpath_record_counts',[8]),('suppressed',True)])
def test_wrong_operation_membership(case,field,value):
    for label in ('before','after'):case['data'][label]['operations'][0][field]=value
    case['data']['state_sha256']=m._digest(case['data']['after'])
    with pytest.raises(ValueError):load(case)


def test_extra_shared_tool_user_rejected(case):
    for label in ('before','after'):
        x=case['data'][label]; row=deepcopy(x['operations'][0]);row.update(native_id=999,linked_feature_ids=[80])
        x['operations'].append(row);x['operation_count']=3
    case['data']['state_sha256']=m._digest(case['data']['after'])
    with pytest.raises(ValueError):load(case)


@pytest.mark.parametrize('target',['pin','stock'])
def test_file_replacement_rejected(case,target):
    e=load(case);case[target].write_bytes(b'changed')
    with pytest.raises(ValueError):e.check_files()


def test_stock_sha_mismatch(case):
    case['stock'].write_bytes(b'changed')
    with pytest.raises(ValueError):load(case)


def test_saved_context_change_rejected(case):
    case['data']['after']['operations'][0]['assigned_tool']['cut_diameter_native']=2
    case['data']['state_sha256']=m._digest(case['data']['after'])
    with pytest.raises(ValueError):load(case)


def test_clean_event_guard(case):
    case['data']['messages']['event_count']=1
    with pytest.raises(ValueError):load(case)


def test_neighbor_readback_change(case):
    e=load(case); state=deepcopy(e.state);state['features'][-1]['geometry']['shape_raw']=5
    with pytest.raises(ValueError):e.verify(state)


def test_stock_reader_reads_native_then_compares(case,monkeypatch):
    e=load(case);calls=[]
    def stock_reader(*args):
        calls.append(args);return deepcopy(e.state['stock']),'native'
    monkeypatch.setattr(m,'_export_stock',stock_reader)
    assert e.read_stock('wp','tlb','read',{})[1]=='native' and len(calls)==1
    monkeypatch.setattr(m,'_export_stock',lambda *a: ({'wrong':True},'native'))
    with pytest.raises(ValueError):e.read_stock('wp','tlb','read',{})


class FakeSession:
    last=None
    def __init__(self,*args):
        self.active=False;self.closed=False;self.event=False;self.close_error=False
        FakeSession.last=self
    def __enter__(self):self.active=True;return self
    def __exit__(self,*args):self.active=False;self.closed=True
    def summary(self):
        return dict(subscribed=True,active=self.active,disconnected=self.closed,event_count=int(self.event),
                    disconnect_errors=['fail'] if self.close_error else [])


def run_fake(c,monkeypatch,mode='complete'):
    import scripts.sw_cam_events as events
    monkeypatch.setattr(events,'CamMessageSession',FakeSession)
    monkeypatch.setattr(m,'validate_inventory_request',lambda **kwargs:None)
    monkeypatch.setattr(m,'_member',lambda obj,name:16516)
    monkeypatch.setattr(m,'raw_part_identity',lambda sw:deepcopy(c['data']['after']['document']))
    monkeypatch.setattr(m,'_bootstrap',lambda *a:'app')
    count=[]
    def capture(*args,**kwargs):
        count.append(1);kwargs['check']()
        assert kwargs['operation_details_reader'].func is m.read_selected_operation_tool_details
        state=deepcopy(c['data']['after'])
        full=dict(tool_native_id=145,geometry_read_complete=mode!='partial',profile_complete=False,mill_tool={'shank':20})
        items=[dict(operation_native_id=i,full_tool=deepcopy(full),tool_metadata_complete=mode!='partial') for i in (143,144)]
        details=dict(items=items,metadata_read_complete=mode!='partial',profile_complete=False,
                     generic_operation_context_unchanged=True,canonical_state_changed=False)
        kwargs['diagnostic']['operation_details']={'selected_tool_details':details}
        if mode=='change_tool' and len(count)==2:items[0]['full_tool']['mill_tool']['shank']=3
        if mode=='disagree_shared':items[1]['full_tool']['mill_tool']['shank']=3
        if mode=='neighbor' and len(count)==2:state['features'][-1]['geometry']['shape_raw']=9
        if mode=='event':FakeSession.last.event=True
        if mode=='cleanup':FakeSession.last.close_error=True
        if mode=='dirty':state['document']['needs_save']=True
        if mode=='exception':raise RuntimeError('guard failure')
        if mode=='file':c['part'].write_bytes(b'changed')
        if mode=='missing_item':items.pop()
        return state,{}
    monkeypatch.setattr(m,'capture_selected_plan',capture)
    return m.inspect_saved_plan_tools('sw','clsid','tlb',**c['args'],
        saved_plan_receipt_path=str(c['pin']),saved_plan_receipt_sha256=c['write'](),
        qualification_only=True,acknowledge_disposable_copy=True,
        receipt_path=str(c['pin'].with_name('output.json'))),count


@pytest.mark.parametrize('mode',['complete','partial'])
def test_two_read_scope_stable(case,monkeypatch,mode):
    report,count=run_fake(case,monkeypatch,mode)
    assert len(count)==2 and report['readback_verified'] is True
    assert report['tools_readback_verified'] is (mode=='complete')
    assert report['tool_profile_complete'] is False and report['production_qualified'] is False
    assert report['full_inventory_verified'] is False
    for key in ('mutation_attempted','GOP_attempted','GTP_attempted','model_saved','save_attempted','tool_assignment_attempted'):
        assert report[key] is False
    assert FakeSession.last.closed


@pytest.mark.parametrize('mode',['change_tool','disagree_shared','neighbor','event','cleanup','dirty',
                                  'exception','file','missing_item'])
def test_readback_failure_is_never_complete(case,monkeypatch,mode):
    report,count=run_fake(case,monkeypatch,mode)
    assert report['status']=='error',report
    assert report['readback_verified'] is False and report['tools_readback_verified'] is False
    assert FakeSession.last.closed

def test_boolean_document_type_is_not_part(case):
    for label in ('before','after'):case['data'][label]['document']['type']=True
    case['data']['state_sha256']=m._digest(case['data']['after'])
    with pytest.raises(ValueError):load(case)


def test_full_server_import_and_registered_schema(case):
    import ast
    import os
    import subprocess
    import sys
    import scripts
    root=Path(__file__).resolve().parents[1]
    server=root/'mcp-server'/'server.py'
    # Read the actual staged/installed server; never depend on merge snippet files.
    tree=ast.parse(server.read_text(encoding='utf-8'))
    classes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SolidWorksCamSavedMillPlanToolsInput']
    assert len(classes)==1
    payload=dict(**case['args'],addin_clsid='{00000000-0000-0000-0000-000000000001}',saved_plan_receipt_path=str(case['pin']),
        saved_plan_receipt_sha256=case['write'](),qualification_only=True,
        acknowledge_disposable_copy=True,receipt_path=str(case['pin'].with_name('schema_output.json')))
    code="""import sys,runpy,json
sys.path[:]=json.loads(sys.argv[2])
import scripts
scripts.__path__[:]=json.loads(sys.argv[3])
n=runpy.run_path(sys.argv[1],run_name='saved_plan_tool_import_smoke')
assert n['_automation_loaded'] is False and n['_selected_process_id'] is None
assert 'solidworks_cam_inspect_saved_mill_plan_tools' in n['mcp']._tool_manager._tools
schema=n['SolidWorksCamSavedMillPlanToolsInput']
p=json.loads(sys.argv[4])
schema.model_validate(p)
for key,value in [('expected_operation_native_ids',[True,144]),('expected_operation_native_ids',['143',144]),('expected_operation_native_ids',[143,143]),('expected_operation_native_ids',[]),('expected_tool_native_id',True),('qualification_only',False),('process_id',True)]:
    bad=dict(p);bad[key]=value
    try:schema.model_validate(bad)
    except ValueError:pass
    else:raise AssertionError('schema accepted '+key+repr(value))
print('SERVER_IMPORT_AND_SCHEMA_PASS')
"""
    result=subprocess.run([sys.executable,'-c',code,str(server),json.dumps(sys.path),
        json.dumps(list(scripts.__path__)),json.dumps(payload)],capture_output=True,text=True,
        timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert 'SERVER_IMPORT_AND_SCHEMA_PASS' in result.stdout


def test_new_backend_has_no_native_mutation_calls():
    import ast
    root=Path(__file__).resolve().parents[1]
    forbidden={'Save','Save3','SaveAs','SetTool','GenerateOperationPlan','GenerateToolpath','EMF','GOP','GTP'}
    for name in ('sw_cam_mill_saved_plan_tools.py','sw_cam_mill_selected_tool_details.py'):
        tree=ast.parse((root/'scripts'/name).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.Call):
                target=node.func
                name=target.attr if isinstance(target,ast.Attribute) else target.id if isinstance(target,ast.Name) else ''
                assert name not in forbidden
                if name in ('_member','read'):
                    assert not any(isinstance(a,ast.Constant) and a.value in forbidden for a in node.args if isinstance(a,ast.Constant) and isinstance(a.value,str))
