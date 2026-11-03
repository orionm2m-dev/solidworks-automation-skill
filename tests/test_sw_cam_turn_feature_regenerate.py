"""Execute bounded recipe transaction/delta guards with synthetic native objects."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_turn_feature_regenerate as cam
REAL_CAPTURE = cam.capture


def policy_for(source, database, digest):
    return dict(protected_part_pins=[dict(path=str(source),sha256=digest)],techdb_path=str(database),
        techdb_sha256=cam._file_hash(database),current_attribute=dict(native_id=0,name="Drill"),
        requested_attribute_id=50,feature_spindle_type_raw=1,stock_attribute_raw=1,
        feature_diameters_native=dict(minimum=52.,maximum=61.),expected_operation_ids=[127,131,132,135],
        replaced_operation_ids=[131,132],expected_new_operation_types=[14,9,5,6],
        expected_default_operations=[dict(operation_type=5,name="Default",native_id=3),dict(operation_type=6,name="Default",native_id=4)],
        expected_new_tool_signatures=[None,None,{"tool_type_raw":15},{"tool_type_raw":15}])


def initial_state(path, digest):
    ops=[dict(setup_index=0,operation_index=i,native_id=oid,turn_operation_type=kind,linked_feature_ids=[fid])
         for i,(oid,kind,fid) in enumerate([(127,7,74),(131,14,76),(132,9,76),(135,13,78)])]
    inventory=[dict(setup_index=0,operation_index=i,turn_operation_type=x['turn_operation_type'],
        toolpath_generated=x['native_id'] in (127,132),toolpath_record_counts=[40] if x['native_id'] in (127,132) else [])
        for i,x in enumerate(ops)]
    return dict(document=dict(path=str(path),title=path.name,type=1,needs_save=False),source_sha256=digest,
        inventory=dict(operation_count=4,operation_setup_count=1,feature_count=3,operations=inventory),operations=ops,
        features=[dict(native_id=i,attribute_id_raw=0,attribute_name='Drill',name='feature'+str(i)) for i in (74,76,78)],
        current_attribute=dict(native_id=0,name='Drill'),current_attribute_lookup_id_raw=21,current_id_matches_lookup=False,
        catalog=dict(requested_id=50),feature_spindle_type_raw=1,stock_attribute_raw=1,
        feature_diameters_native=dict(minimum=52.,maximum=61.),
        own_operations=[dict(operation_native_id=x['native_id'],suppressed=False,tool_native_id=x['native_id']+100,
                             tool=dict(tool_type_raw=15)) for x in ops],
        nc=[dict(operation_native_id=x['native_id'],status='observed',feed_rate_ipm_native=1.) for x in ops],
        toolcrib=[dict(native_id=x['native_id']+100,complete=True,info_raw='tool') for x in ops])


def regenerate(state):
    old=deepcopy(state)
    fresh=[dict(setup_index=0,operation_index=i+1,native_id=400+i,turn_operation_type=k,linked_feature_ids=[76])
           for i,k in enumerate([14,9,5,6])]
    state['operations']=[old['operations'][0]]+fresh+[old['operations'][-1]]
    for i,row in enumerate(state['operations']): row['operation_index']=i
    state['inventory']['operation_count']=6
    state['inventory']['operations']=[old['inventory']['operations'][0]]+[
        dict(setup_index=0,operation_index=i+1,turn_operation_type=k,toolpath_generated=False,toolpath_record_counts=[])
        for i,k in enumerate([14,9,5,6])]+[old['inventory']['operations'][-1]]
    for i,row in enumerate(state['inventory']['operations']): row['operation_index']=i
    state['own_operations']=[old['own_operations'][0]]+[
        dict(operation_native_id=x['native_id'],suppressed=False,tool_native_id=x['native_id']+100,tool=dict(tool_type_raw=15))
        for x in fresh]+[old['own_operations'][-1]]
    state['nc']=[old['nc'][0]]+[dict(operation_native_id=x['native_id'],status='observed',feed_rate_ipm_native=2.)
                              for x in fresh]+[old['nc'][-1]]
    state['toolcrib'] += [dict(native_id=x['native_id']+100,complete=True,info_raw='tool') for x in fresh]


@pytest.fixture
def transaction(tmp_path, monkeypatch):
    source=tmp_path/'source.sldprt'; target=tmp_path/'copy.sldprt'; database=tmp_path/'db.mdb'
    source.write_bytes(b'saved');target.write_bytes(b'saved');database.write_bytes(b'recipe')
    digest=cam._file_hash(source);policy=policy_for(source,database,digest)
    config=dict(process_id=731,expected_process_create_time=1234.,expected_document_path=str(target),expected_source_sha256=digest,
                feature_setup_index=0,expected_feature_native_id=76,expected_turn_feature_type=2,attribute_name='Rough-Finish',
                max_features=64,max_operations=64)
    state=initial_state(target,digest);calls=[];fault={'mode':None};receipts=[]
    class Feature:
        @property
        def Attribute(self):return state['current_attribute']['native_id']
        @Attribute.setter
        def Attribute(self,value):
            calls.append('Attribute'); pending=json.loads(receipts[-1].read_text())
            assert pending['mutation_attempted'] and pending['native_dispatch_pending']
            assert pending['actions']['Attribute']==dict(attempted=True,returned=False)
            assert list(tmp_path.glob('turn_recipe_*.json'))
            if fault['mode']=='setter':raise RuntimeError('setter interrupted')
            state['current_attribute']=dict(native_id=value,name='Rough-Finish')
            state['current_attribute_lookup_id_raw']=value;state['current_id_matches_lookup']=True
            state['features'][1].update(attribute_id_raw=value,attribute_name='Rough-Finish')
            state['document']['needs_save']=True
            if fault['mode']=='attribute_drift':state['features'][0]['attribute_id_raw']=8
        def GenerateOpPlan(self, preference):
            assert preference==2; calls.append('GOP2')
            pending=json.loads(receipts[-1].read_text())
            assert pending['actions']['Attribute']['returned'] and pending['actions']['GenerateOpPlan']==dict(attempted=True,returned=False)
            if fault['mode']=='gop':raise RuntimeError('gop interrupted')
            regenerate(state)
            if fault['mode']=='protected_nc':state['nc'][0]['feed_rate_ipm_native']=9.
    feature=Feature()
    class Session:
        def __init__(self,*args):self.active=False;self.entered=False
        def __enter__(self):self.active=True;self.entered=True;return self
        def __exit__(self,*args):self.active=False
        def summary(self):return dict(active=self.active,subscribed=self.entered,disconnected=self.entered and not self.active,
            event_count=int(fault['mode']=='late_event' and self.entered and not self.active),overflow=False,
            callback_error_count=0,callback_errors=[],subscription_error=None,disconnect_errors=[])
    native=dict(app=N(),turn_feature=feature)
    def capture(*args,clean,check=lambda:None,**kwargs):
        check()
        if clean:assert not state['document']['needs_save']
        return deepcopy(state),native
    sw=N(GetDocuments=lambda:[N(GetPathName=lambda:str(target))],GetProcessID=lambda:731)
    monkeypatch.setattr(cam.recipe,'_context',lambda *args:(None,None,None,None,native['app']))
    monkeypatch.setattr(cam,'_process_identity',lambda _:dict(alive=True,process_id=731,create_time=1234.,executable='C:/bin/SLDWORKS.exe'))
    monkeypatch.setattr(cam,'capture',capture);monkeypatch.setattr(cam,'CamMessageSession',Session)
    monkeypatch.setattr(cam,'document_snapshot',lambda _:deepcopy(state['document']))
    monkeypatch.setattr(cam,'_typed',lambda obj,*_:obj);monkeypatch.setattr(cam,'local_evidence_root',lambda:tmp_path)
    def invoke(action='prepare',**changes):
        params=dict(config,policy=policy,action=action)
        if action=='apply':
            receipt=tmp_path/('receipt'+str(len(receipts))+'.json');receipts.append(receipt)
            params.update(expected_state_sha256=prepared['prepared_state_sha256'],receipt_path=str(receipt))
        params.update(changes)
        return cam.qualify_turn_feature_recipe(sw,'clsid','tlb',**params)
    prepared=invoke()
    assert prepared['status']=='prepared',prepared
    return N(**locals())


def test_prepare_then_apply_exact_sequence_and_scope(transaction):
    t=transaction;assert not t.calls and not list(t.tmp_path.glob('turn_recipe_*.json'))
    result=t.invoke('apply')
    assert result['status']=='review_required' and result['readback_verified']
    assert t.calls==['Attribute','GOP2'] and result['native_recipe_ram_verified']
    assert result['delta']['protected_operation_ids']==[127,135]
    assert not any(result[x] for x in ('GTP_attempted','model_saved','tool_assignment_attempted',
        'persistence_verified','production_qualified','toolpath_coordinates_verified','all_nc_parameters_verified'))
    assert json.loads(t.receipts[-1].read_text())==result


@pytest.mark.parametrize('mode,expected_calls',[('setter',['Attribute']),('attribute_drift',['Attribute']),
    ('gop',['Attribute','GOP2']),('protected_nc',['Attribute','GOP2']),('late_event',['Attribute','GOP2'])])
def test_partial_failure_keeps_marker_and_rejects_new_receipt(transaction,mode,expected_calls):
    t=transaction;t.fault['mode']=mode;result=t.invoke('apply')
    assert result['status']=='uncertain' and not result['readback_verified'] and t.calls==expected_calls
    second=t.invoke('apply');assert second['status']=='error' and second['issue']['type']=='ValueError'
    assert t.calls==expected_calls


@pytest.mark.parametrize('mutation',['source','copy','database','wrong_digest','old_op_order','raw_current','condition'])
def test_prewrite_guard_stops_without_marker(transaction,mutation):
    t=transaction;args={}
    if mutation=='source':t.source.write_bytes(b'changed')
    elif mutation=='copy':t.target.write_bytes(b'changed')
    elif mutation=='database':t.database.write_bytes(b'changed')
    elif mutation=='wrong_digest':args['expected_state_sha256']='0'*64
    elif mutation=='old_op_order':t.state['operations'].reverse()
    elif mutation=='raw_current':t.state['current_attribute']['native_id']=21
    else:t.state['stock_attribute_raw']=2
    result=t.invoke('apply',**args)
    assert result['status']=='error' and not result['mutation_attempted'] and not t.calls
    assert not list(t.tmp_path.glob('turn_recipe_*.json'))


@pytest.mark.parametrize('change',['new_type','old_id','new_link','outside_feature','protected_tool','protected_count',
    'generated','crib_changed','unexplained_tool','ordering','new_suppressed','new_tool_signature'])
def test_full_delta_rejects_unapproved_change(transaction,change):
    t=transaction;before=deepcopy(t.state);after=deepcopy(before);regenerate(after)
    if change=='new_type':after['operations'][1]['turn_operation_type']=1
    elif change=='old_id':after['operations'][1]['native_id']=131
    elif change=='new_link':after['operations'][1]['linked_feature_ids']=[74]
    elif change=='outside_feature':after['features'][0]['attribute_id_raw']=1
    elif change=='protected_tool':after['own_operations'][0]['tool_native_id']=999
    elif change=='protected_count':after['inventory']['operations'][0]['toolpath_record_counts']=[41]
    elif change=='generated':after['inventory']['operations'][1]['toolpath_generated']=True
    elif change=='crib_changed':after['toolcrib'][0]['info_raw']='other'
    elif change=='unexplained_tool':after['toolcrib'].append(dict(native_id=999))
    elif change=='ordering':after['operations'].reverse()
    elif change=='new_suppressed':after['own_operations'][1]['suppressed']=True
    else:after['own_operations'][3]['tool']['tool_type_raw']=1
    with pytest.raises(ValueError):cam.verify_delta(before,after,t.config,t.policy)


def test_protected_alias_and_multiple_documents(transaction):
    t=transaction
    with pytest.raises(ValueError):cam.files(dict(t.config,expected_document_path=str(t.source)),t.policy)
    t.sw.GetDocuments=lambda:[N(GetPathName=lambda:str(t.target)),N(GetPathName=lambda:str(t.source))]
    with pytest.raises(ValueError):cam.isolated(t.sw,t.config,lambda:None)


def test_receipt_write_error_does_not_claim_success(transaction,monkeypatch):
    t=transaction;original=cam._write_receipt
    def write(path,value,**kw):
        if value.get('phase')=='GenerateOpPlan_returned':raise OSError('receipt unavailable')
        return original(path,value,**kw)
    monkeypatch.setattr(cam,'_write_receipt',write)
    result=t.invoke('apply')
    assert result['status']=='uncertain' and not result['readback_verified'] and t.calls==['Attribute','GOP2']


def test_final_receipt_failure_revokes_ram_verified(transaction,monkeypatch):
    t=transaction;original=cam._write_receipt
    def write(path,value,**kw):
        if value.get('status')=='review_required':raise OSError('terminal write unavailable')
        return original(path,value,**kw)
    monkeypatch.setattr(cam,'_write_receipt',write)
    result=t.invoke('apply')
    assert result['status']=='uncertain' and not result['readback_verified'] and not result['native_recipe_ram_verified']


def test_process_creation_time_changed_before_mutation(transaction,monkeypatch):
    t=transaction
    monkeypatch.setattr(cam,'_process_identity',lambda _:dict(alive=True,process_id=731,create_time=9999.,executable='C:/bin/SLDWORKS.exe'))
    result=t.invoke('apply')
    assert result['status']=='error' and not result['mutation_attempted'] and not t.calls


@pytest.fixture
def actual_capture(transaction,monkeypatch):
    from test_sw_cam_turn_feature_recipe import Collection
    t=transaction;calls=[];broken={'nc':False};tools=[];operations={}
    for row in t.state['operations']:
        ident=row['native_id'];tool=N(native_id=ident+100,ToolType=1,GetToolInfoString=lambda:'generic')
        tools.append(tool)
        def nc_read(ident=ident):
            calls.append(ident)
            if broken['nc']:raise RuntimeError('own NC unavailable')
            return N(GetSpndlSpeed=lambda:500.,GetFeedRateIPM=lambda:35.)
        operations[ident]=N(Suppressed=False,IGetTool=lambda tool=tool:tool,IGetTurnNCParam=nc_read)
    native=dict(operations=operations,doc=N(GetCWObjectID=lambda obj:(obj.native_id,True)),
        machine=N(IGetToolcrib=lambda:N(GetAllTools=lambda:Collection(tools))),
        turn_feature=N(IGetAllDefaultOperations=lambda kind:('Default',),GetTdbIdForDefaultOperation=lambda kind,name:{5:3,6:4}[kind]))
    def recipe_capture(*args,native_out,**kw):
        native_out.update(native);args[4]['snapshots'].append({})
        state=deepcopy(t.state);state['techdb_path_raw']=str(t.database);return state
    monkeypatch.setattr(cam.recipe,'_capture',recipe_capture)
    monkeypatch.setattr(cam.profile,'_typed',lambda obj,*args:obj)
    monkeypatch.setattr(cam,'_items',lambda raw,typelib,read,limit:[read(raw,'Item',i) for i in range(read(raw,'Count'))])
    real_capture=REAL_CAPTURE
    report=dict(snapshots=[],guarded_member_reads=0)
    return N(**locals())


def test_capture_reads_own_tools_and_each_nc_before_accepting(actual_capture):
    c=actual_capture;t=c.t
    result,_=c.real_capture(t.sw,'clsid','tlb',t.config,t.policy,c.report,clean=True)
    assert c.calls==[127,131,132,135]
    assert [x['tool_native_id'] for x in result['own_operations']]==[227,231,232,235]
    assert all(x['status']=='observed' and x['feed_rate_ipm_native']==35. for x in result['nc'])
    assert [x['native_id'] for x in result['default_operations']]==[3,4]


def test_first_own_nc_exception_stops_further_operations(actual_capture):
    c=actual_capture;t=c.t;c.broken['nc']=True
    with pytest.raises(ValueError):c.real_capture(t.sw,'clsid','tlb',t.config,t.policy,c.report,clean=True)
    assert c.calls==[127] and c.report['snapshots'][0]['nc'][0]['status']=='error'


@pytest.mark.parametrize('field,value',[('receipt_path','C:/evidence/unused.json'),('expected_state_sha256','a'*64)])
def test_prepare_rejects_apply_fields(transaction,field,value):
    result=transaction.invoke(**{field:value})
    assert result['status']=='error' and not transaction.calls


@pytest.mark.parametrize('changed',['orientation','angle'])
def test_nested_boring_signature_rejects_wrong_geometry(transaction,changed):
    t=transaction;before=deepcopy(t.state);after=deepcopy(before);regenerate(after)
    signature=dict(tool_type_raw=15,dimensions_native=dict(IncludedAngle=80.0),
                   holder=dict(orientation_for_operation_raw=5))
    t.policy['expected_new_tool_signatures'][2]=deepcopy(signature)
    after['own_operations'][3]['tool']=deepcopy(signature)
    if changed=='orientation':after['own_operations'][3]['tool']['holder']['orientation_for_operation_raw']=4
    else:after['own_operations'][3]['tool']['dimensions_native']['IncludedAngle']=55.0
    with pytest.raises(ValueError):cam.verify_delta(before,after,t.config,t.policy)
