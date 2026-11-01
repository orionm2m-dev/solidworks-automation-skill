import importlib.util,os,sys,json
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import pytest
root=os.environ.get('SOLIDWORKS_SKILL_ROOT')
if root:sys.path.insert(0,root)
path=Path(__file__).parents[1]/'scripts/sw_cam_turn_bore_tool_initialize.py'
spec=importlib.util.spec_from_file_location('single_bore_init_test',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def events():return dict(subscribed=True,active=False,disconnected=True,event_count=0,overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])


def fixture(tmp_path):
    p=dict(process_id=7,expected_document_path=str(tmp_path/'part.SLDPRT'),expected_source_sha256='a'*64,crib_receipt_path=str(tmp_path/'crib.json'),crib_receipt_sha256='b'*64,operation_native_id=322,feature_native_id=76,tool_native_id=324,expected_included_angle_native=80.0,receipt_path=str(tmp_path/'result.json'),module_sha256=m._file_hash(m.__file__),qualification_only=True,acknowledge_ram_only=True)
    rs=m.partial.parent.roles.resolve_roles(SimpleNamespace(CW_TURN_OP_ROUGH_BORE=5,CW_TURN_OP_FINISH_BORE=6,CW_TURN_OP_ROUGH_TURN=1,CW_TURN_OP_FINISH_TURN=2),['rough_bore','finish_bore'])
    types=[7,8,1,2,14,9,3,4,13];counts=[[40],[19],[97],[43],[],[],[],[],[]]
    ops=[dict(setup_index=0,operation_index=i,native_id=100+i,turn_operation_type=k,linked_feature_ids=[76 if i==5 else 20+i],suppressed=False) for i,k in enumerate(types)]
    inv=dict(machine_type=3,feature_setup_count=1,feature_counts_by_setup=[5],feature_count=5,operation_setup_count=1,operation_count=9,operations=[dict(setup_index=0,operation_index=i,turn_operation_type=k,toolpath_generated=bool(counts[i]),toolpath_record_counts=counts[i]) for i,k in enumerate(types)],stock=dict(type=3))
    header=dict(turn_feature_type_raw=2,name='ID',attribute_id_raw=0,attribute_name='Drill')
    before=dict(document=dict(path=p['expected_document_path'],title='part',type=1,needs_save=False),saved_file_sha256='a'*64,inventory=inv,operations=ops,feature_ids=[dict(setup_index=0,native_ids=[20,21,22,76,24])],feature_header=header)
    pq=dict(process_id=7,expected_document_path=p['expected_document_path'],expected_source_sha256='a'*64,feature_native_id=76,anchor_operation_native_id=105,definitions=[dict(role='rough_bore',default_name='Default',default_operation_id=3),dict(role='finish_bore',default_name='Default',default_operation_id=4)])
    b=dict(operation_native_id=105,feature_native_id=76,operation_type=9,suppressed=False,generated=False,feature_header=deepcopy(header));obs=[];cats={}
    for role,kind,did in [('rough_bore',5,3),('finish_bore',6,4)]:
        x=next(x for x in rs if x['role']==role);obs.extend([dict(key=role+'_names',value=['Default'],returned_type='tuple'),dict(key=role+'_id_Default',value=did,returned_type='int')]);cats[role]=dict(x,operation_type=1,converted_python_type='tuple',entries=[dict(name='Default',default_operation_id=did)],unique_default_available=True,selected_default_operation_id=None,selection_performed=False)
    cat=dict(scope=m.partial.parent.roles.SCOPE,status='observed',phase='finished',readback_verified=True,read_only=True,source_path=p['expected_document_path'],source_sha256='a'*64,before=b,after=deepcopy(b),inventory_before=deepcopy(inv),inventory_after=deepcopy(inv),request=dict(process_id=7,setup_index=0,operation_index=5,roles=['rough_bore','finish_bore']),messages=events(),abi=dict(roles=rs),observations=obs,catalogues=cats)
    cat.update({k:False for k in ('mutation_attempted','GTP_attempted','model_saved','operation_inserted','assignment_attempted')})
    state=deepcopy(before);state['document']['needs_save']=True
    for x in state['operations'][6:]:x['operation_index']+=1
    row=dict(setup_index=0,operation_index=6,native_id=322,turn_operation_type=5,linked_feature_ids=[76],suppressed=False);state['operations'].insert(6,row)
    for x in state['inventory']['operations'][6:]:x['operation_index']+=1
    state['inventory']['operations'].insert(6,dict(setup_index=0,operation_index=6,turn_operation_type=5,toolpath_generated=False,toolpath_record_counts=[]));state['inventory']['operation_count']=10
    parent=dict(scope=m.partial.parent.SCOPE,status='uncertain',phase='finished',readback_verified=False,failed_phase='tool_reference_rough_bore',issue=dict(type='COMError',hresult=-2147220990),request=pq,before=before,mutation_attempted=True,native_dispatch_pending=False,actions={'InsertOperation_rough_bore':dict(attempted=True,returned=True,pending=False,readback_verified=False,new_native_id=322,resolved_native_value=5)},insertion_observations=[deepcopy(state)],new_operations=[deepcopy(row)],messages=events(),**{k:False for k in m.partial.parent.FORBIDDEN})
    tool=dict(complete=True,native_id=324,candidate=True,tool_type_raw=15,turn_tool_type_raw=1,insert_type_raw=1,holder_present=True,holder_type_raw=2,holder_id_raw=2,insert_dimensions_native=dict(IncludedAngle=80.0,NoseRadius=.4),holder_dimensions_native=dict(BoringBarDiameter=20.0,Protrusion=0.0))
    observed=dict(scope=m.partial.SCOPE,status='observed',phase='finished',readback_verified=True,read_only=True,request=dict(process_id=7,expected_document_path=p['expected_document_path'],expected_source_sha256='a'*64),source_path=p['expected_document_path'],source_sha256='a'*64,before=deepcopy(state),after=deepcopy(state),tools=[tool],tool_ids=[324],messages=events())
    observed.update({k:False for k in ('mutation_attempted','model_saved','GTP_attempted','operation_inserted','tool_assignment_attempted','operation_tool_lookup_attempted','persistence_qualified','physical_tool_qualified','production_qualified')})
    return p,parent,observed,dict(catalogue=cat,roles=rs)


def plan_fixture(tmp_path):
    p,parent,observed,loaded=fixture(tmp_path);state,tool,a=m.observed_crib(observed,p,parent,loaded)
    return p,dict(reference=state,candidate=tool,assignment=a,observed=observed,parent=parent,catalogue=loaded['catalogue'],roles=loaded['roles'])


def fake_run(tmp_path,*,failure=None,native_return=0):
    p,plan=plan_fixture(tmp_path);trace=[];saved=[];marker=tmp_path/'once.json'
    r=dict(scope=m.SCOPE,status='prepared',phase='prepared',request=p,source_path=p['expected_document_path'],source_sha256='a'*64,assignment=deepcopy(plan['assignment']),accepted_candidate=deepcopy(plan['candidate']),actions={},mutation_attempted=False,native_dispatch_pending=False,readback_verified=False,**{k:False for k in m.FORBIDDEN})
    def persist():saved.append(deepcopy(r))
    def claim():m._write_receipt(marker,m.claim_value(p),create=True)
    class Backend:
        def start(self):trace.append('start')
        def capture(self,label):
            trace.append(label);s=deepcopy(plan['reference'])
            if failure=='before_drift' and label=='before':s['saved_file_sha256']='c'*64
            if failure=='after_path_drift' and label=='after':s['inventory']['operations'][0]['toolpath_record_counts']=[39]
            if failure=='after_source_drift' and label=='after':s['saved_file_sha256']='c'*64
            return s
        def tool_snapshot(self,label):
            trace.append('tools_'+label);tools=deepcopy(plan['observed']['tools'])
            if failure=='tools_'+label:tools[0]['holder_dimensions_native']['Protrusion']=1.0
            return tools
        def assign(self,a,pending):
            assert a['operation_type']==5;pending();trace.append('assign')
            assert marker.exists() and saved[-1]['native_dispatch_pending'] is True
            if failure=='setter_exception':raise RuntimeError('server fault outcome unknown')
            return native_return
        def assigned(self,a):
            trace.append('reference')
            if failure=='getter_exception':raise RuntimeError('tool unavailable')
            value=m.binding.expected_reference(a,plan['candidate'])
            if failure=='wrong_tool':value['tool_native_id']=325
            if failure=='wrong_holder':value['holder_type_raw']=1
            return value
        def finish(self):trace.append('finish');r['messages']=events()
        def close(self):trace.append('close');r['messages']=events()
        def save(self):raise AssertionError('Save forbidden')
        def generate(self):raise AssertionError('GTP forbidden')
        def insert(self,*a):raise AssertionError('Insert forbidden')
    return lambda:m.run_backend(Backend(),p,plan,r,persist,claim),r,plan,trace,saved,marker


def test_actual_partial_lineage_and_bore_tool_selection(tmp_path):
    p,parent,observed,loaded=fixture(tmp_path);state,tool,a=m.observed_crib(observed,p,parent,loaded)
    assert state['inventory']['operation_count']==10 and a==dict(operation_native_id=322,operation_type=5,feature_native_id=76,tool_native_id=324)
    assert tool['insert_dimensions_native']['IncludedAngle']==80.0

@pytest.mark.parametrize('bad',['wrong_process','wrong_source','dirty_state','parent_wrong_type','parent_rpc','parent_second_insert','wrong_tool','wrong_angle','wrong_holder','incomplete','duplicate','lookup_performed'])
def test_observed_authority_rejects_wrong_or_incomplete_evidence(tmp_path,bad):
    p,parent,o,l=fixture(tmp_path)
    if bad=='wrong_process':o['request']['process_id']=8
    elif bad=='wrong_source':o['source_sha256']='c'*64
    elif bad=='dirty_state':o['after']['document']['needs_save']=False
    elif bad=='parent_wrong_type':parent['new_operations'][0]['turn_operation_type']=1
    elif bad=='parent_rpc':parent['issue']['hresult']=-2147417851
    elif bad=='parent_second_insert':parent['actions']['InsertOperation_finish_bore']={}
    elif bad=='wrong_tool':p['tool_native_id']=325
    elif bad=='wrong_angle':o['tools'][0]['insert_dimensions_native']['IncludedAngle']=55.0
    elif bad=='wrong_holder':o['tools'][0]['holder_type_raw']=1
    elif bad=='incomplete':o['tools'][0]['complete']=False
    elif bad=='duplicate':o['tools'].append(deepcopy(o['tools'][0]))
    elif bad=='lookup_performed':o['operation_tool_lookup_attempted']=True
    with pytest.raises((ValueError,KeyError)):m.observed_crib(o,p,parent,l)


def test_single_assignment_exact_readback_and_no_save(tmp_path):
    call,r,plan,trace,saved,marker=fake_run(tmp_path);call()
    assert trace==['start','before','tools_before','assign','reference','tools_after','after','finish','close']
    assert r['status']=='initialized_ram_no_save' and r['readback_verified'] and all(r[k] is False for k in m.FORBIDDEN)
    assert m.validate_initialized(r,plan)==r['after']
    assert [x['toolpath_record_counts'] for x in r['after']['inventory']['operations'][:4]]==[[40],[19],[97],[43]]

@pytest.mark.parametrize('failure,count',[('before_drift',0),('tools_before',0),('setter_exception',1),('getter_exception',1),('wrong_tool',1),('wrong_holder',1),('tools_after',1),('after_path_drift',1),('after_source_drift',1)])
def test_failure_never_retries_or_saves(tmp_path,failure,count):
    call,r,plan,trace,saved,marker=fake_run(tmp_path,failure=failure);call()
    assert trace.count('assign')==count and trace[-1]=='close' and not r['readback_verified']
    assert r['status']==('uncertain' if count else 'error') and not r['model_saved']
    with pytest.raises(ValueError):m.validate_initialized(r,plan)
    if failure=='setter_exception':assert r['actions']['SetTool_322']['pending'] and not r['actions']['SetTool_322']['returned'] and 'reference' not in trace

@pytest.mark.parametrize('value',[True,False,None,1,-1,'0'])
def test_nonzero_or_nonstrict_hresult_never_reads_or_reports_success(tmp_path,value):
    call,r,plan,trace,_,_=fake_run(tmp_path,native_return=value);call()
    assert trace.count('assign')==1 and 'reference' not in trace and not r['readback_verified']
    assert r['actions']['SetTool_322']['returned'] is True


def test_once_marker_prevents_same_target_replay(tmp_path):
    call,r,_,trace,_,marker=fake_run(tmp_path);marker.write_text('{}');call()
    assert 'assign' not in trace and r['status']=='error'


def test_changing_tool_or_output_does_not_bypass_attempt_marker(tmp_path):
    p,*_=fixture(tmp_path);old=m.marker_path(p);p['tool_native_id']=325;p['receipt_path']=str(tmp_path/'other.json');assert m.marker_path(p)==old

@pytest.mark.parametrize('key,value',[('operation_native_id',True),('tool_native_id',0),('process_id',False),('expected_included_angle_native',True),('expected_included_angle_native',float('nan')),('qualification_only',False),('module_sha256','0'*64)])
def test_request_rejects_bad_identity_angle_and_pin(tmp_path,key,value):
    p,*_=fixture(tmp_path);p[key]=value
    with pytest.raises(ValueError):m.validate_request(dict(action='initialize_single_turn_bore_tool',params=p))

@pytest.mark.parametrize('bad',['save','wrong_action','wrong_tool','source','tools','pending','false_hresult'])
def test_completed_validation_does_not_upgrade_uncertain_or_changed_state(tmp_path,bad):
    call,r,plan,_,_,_=fake_run(tmp_path);call()
    if bad=='save':r['model_saved']=True
    elif bad=='wrong_action':r['actions']['SetTool_999']=deepcopy(r['actions']['SetTool_322'])
    elif bad=='wrong_tool':r['reference_after']['tool_native_id']=325
    elif bad=='source':r['after']['saved_file_sha256']='c'*64
    elif bad=='tools':r['tools_after'][0]['holder_dimensions_native']['Protrusion']=1
    elif bad=='pending':r['native_dispatch_pending']=True
    elif bad=='false_hresult':r['actions']['SetTool_322']['native_return']=False
    with pytest.raises(ValueError):m.validate_initialized(r,plan)


def test_reuses_actual_native_assignment_and_capture_interfaces():
    assert m.NativeBackend is m.binding.NativeBackend
    assert all(callable(getattr(m.NativeBackend,k)) for k in ('start','capture','tool_snapshot','assign','assigned','finish','close'))
    assert callable(m.binding.reader._typed)



def test_boolean_candidate_subtype_is_not_an_integer_enum(tmp_path):
    p,parent,o,l=fixture(tmp_path);o['tools'][0]['turn_tool_type_raw']=True
    with pytest.raises(ValueError):m.observed_crib(o,p,parent,l)


def test_semantic_kind_comes_from_resolved_role_not_literal_five(tmp_path):
    p,parent,o,l=fixture(tmp_path)
    l['roles'][0]['resolved_native_value']=105
    l['catalogue']['catalogues']['rough_bore']['resolved_native_value']=105
    parent['actions']['InsertOperation_rough_bore']['resolved_native_value']=105
    parent['new_operations'][0]['turn_operation_type']=105
    for state in (parent['insertion_observations'][0],o['before'],o['after']):
        state['operations'][6]['turn_operation_type']=105;state['inventory']['operations'][6]['turn_operation_type']=105
    _,_,a=m.observed_crib(o,p,parent,l);assert a['operation_type']==105


def test_completed_loader_authority_is_ram_only(tmp_path,monkeypatch):
    call,r,plan,_,_,marker=fake_run(tmp_path);call()
    p=r['request'];plan['typelib_path']='typelib'
    r['runtime_and_evidence_pins']=[m.common._pin(m.__file__)];r['module_pin']=m.common._pin(m.__file__);r['marker_pin']=m.common._pin(marker)
    receipt=Path(p['receipt_path']);receipt.write_text(json.dumps(r));digest=m._file_hash(receipt)
    monkeypatch.setattr(m,'load_inputs',lambda actual:plan if actual==p else (_ for _ in ()).throw(AssertionError('different request')))
    monkeypatch.setattr(m,'marker_path',lambda _:marker)
    value=m.load_initialized(str(receipt),digest,process_id=p['process_id'],expected_document_path=p['expected_document_path'],expected_source_sha256=p['expected_source_sha256'])
    assert value['authority']=='single_rough_bore_tool_initialized_ram_no_save'
    assert value['persistence_qualified'] is False and value['GTP_authorized'] is False
    assert value['tool_reference']['tool_native_id']==324 and value['state']['inventory']['operation_count']==10
    with pytest.raises(ValueError):m.load_initialized(str(receipt),digest,process_id=8,expected_document_path=p['expected_document_path'],expected_source_sha256=p['expected_source_sha256'])
