"""原生适配器的边界与受保护路线测试；使用完全合成状态。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import importlib.util
import pytest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('grouped_face_boundaries_candidate',ROOT/'scripts/sw_cam_grouped_face_recipe.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)


def tool(native_id,diameter=8.,protrusion=25.):
    return dict(native_id=native_id,is_mill_tool=True,native_read_complete=True,
        tool_type_raw=1,units_verified=False,holder_geometry_verified=False,
        cut_diameter_native=diameter,protrusion_native=protrusion)


@pytest.fixture
def route(tmp_path):
    source=tmp_path/'SyntheticRoute.SLDPRT';source.write_bytes(b'synthetic saved part')
    rows=[]
    for index,oid in enumerate([143,144,195,196,267,247,248]):
        ids={247:263,248:249,267:252}
        summary=tool(ids.get(oid,oid+1000))
        if oid==267:summary=tool(252,12.,50.)
        rows.append(dict(native_id=oid,setup_native_id=93,setup_index=0,operation_index=index,
            linked_feature_ids=[265] if oid==267 else [79],mill_operation_type=20 if oid==267 else 1,
            suppressed=False,toolpath_generated=oid in (247,248),toolpath_record_counts=[191] if oid==247 else [74] if oid==248 else [],
            assigned_tool=summary))
    state=dict(document=dict(path=str(source),title=source.name,type=1,needs_save=False),
        saved_file_sha256='a'*64,features=[dict(native_id=i) for i in list(range(19))+[264,265]],
        feature_setups=[dict(native_id=i) for i in (69,70,71)],operation_setups=[dict(native_id=i) for i in (93,94,95)],
        operation_count=7,operation_counts=[7,0,0],operations=rows,sw_reference=dict(solids=[dict(name="SyntheticBody", mass_raw=[float(i) for i in range(12)])]))
    expected=tool(249)
    return state,expected


def configured(route,*,generated=False,dirty=False):
    before,wanted=route;after=deepcopy(before)
    target=next(row for row in after['operations'] if row['native_id']==267)
    target['assigned_tool']=deepcopy(wanted)
    target['toolpath_generated']=generated
    target['toolpath_record_counts']=[83] if generated else []
    after['document']['needs_save']=dirty
    return after


@pytest.mark.parametrize('dirty',[False,True])
@pytest.mark.parametrize('generated',[False,True])
def test_exact_target_assignment_and_only_new_path_are_allowed(route,dirty,generated):
    before,wanted=route;after=configured(route,generated=generated,dirty=dirty)
    raw=deepcopy((before,after))
    m.verify_route_delta(before,after,wanted,generated=generated)
    assert (before,after)==raw
    assert [r['toolpath_record_counts'] for r in after['operations'][-2:]]==[[191],[74]]


@pytest.mark.parametrize('kind',['rough_count','finish_count','rough_tool','finish_feature','order','extra_operation','source'])
def test_existing_operations_or_source_cannot_change_during_selected_generation(route,kind):
    before,wanted=route;after=configured(route,generated=True)
    by_id={row['native_id']:row for row in after['operations']}
    if kind=='rough_count':by_id[247]['toolpath_record_counts']=[190]
    elif kind=='finish_count':by_id[248]['toolpath_record_counts']=[73]
    elif kind=='rough_tool':by_id[247]['assigned_tool']['native_id']=999
    elif kind=='finish_feature':by_id[248]['linked_feature_ids']=[265]
    elif kind=='order':after['operations'][4],after['operations'][5]=after['operations'][5],after['operations'][4]
    elif kind=='extra_operation':after['operations'].append(deepcopy(by_id[267]));after['operation_count']=8
    elif kind=='source':after['saved_file_sha256']='b'*64
    with pytest.raises(ValueError):m.verify_route_delta(before,after,wanted,generated=True)


@pytest.mark.parametrize('counts',[[],[0],[-1],[True],[83,84]])
def test_generated_target_needs_exactly_one_positive_integer_path_container(route,counts):
    before,wanted=route;after=configured(route,generated=True)
    after['operations'][4]['toolpath_record_counts']=counts
    with pytest.raises(ValueError):m.verify_route_delta(before,after,wanted,generated=True)


def test_source_rebind_allows_only_explicit_saved_hash(route):
    before,wanted=route;after=configured(route,generated=True)
    after['saved_file_sha256']='b'*64
    m.verify_route_delta(before,after,wanted,generated=True,saved_sha='b'*64)
    with pytest.raises(ValueError):m.verify_route_delta(before,after,wanted,generated=True,saved_sha='c'*64)
    after['document']['path']+='other'
    with pytest.raises(ValueError):m.verify_route_delta(before,after,wanted,generated=True,saved_sha='b'*64)


@pytest.mark.parametrize('dirty',[0,1,None])
def test_native_dirty_observation_is_strict_boolean(route,dirty):
    before,wanted=route;after=configured(route,generated=True)
    after['document']['needs_save']=dirty
    with pytest.raises(ValueError):m.verify_route_delta(before,after,wanted,generated=True)


class Node:
    def __init__(self,native_id=None,**values):
        self.native_id=native_id
        self.values=values
    def QueryInterface(self,interface):return self


@pytest.fixture
def native_case(route,tmp_path,monkeypatch):
    from scripts import sw_cam_raw_mill_face_operation as capture
    from scripts import sw_cam_upper_cone_feature as cone
    from scripts import sw_cam_circle_lifecycle_evidence as identity_module
    from scripts import sw_cam_dispatch_guard as dispatch
    from scripts import sw_cam_route_read_batch as route_batch
    from scripts import sw_cam_raw_mill_face_observation_v2 as reader
    from scripts.sw_cam_mill_route_context import read_generic_tool
    before,wanted=route
    source=Path(before['document']['path'])
    digest=m._file_hash(source)
    before=deepcopy(before);before['saved_file_sha256']=digest
    dependency=tmp_path/'runtime.input';dependency.write_bytes(b'synthetic immutable dependency')
    dep_pin=dict(path=str(dependency),sha256=m._file_hash(dependency))
    from scripts import sw_cam_raw_mill_face_move as move
    loaded={key:None for key in move.CURRENT_KEYS}
    loaded.update(state=deepcopy(before),payload={'protected':'rough'},finish_payload={'protected':'finish'},
        cone_observation={'protected':'cone'},face_observation={'protected':'face'},
        source_sha256=digest,ids={},ownership=dict(create_time=100.,executable=str(tmp_path/'host.exe')),
        pins=[dep_pin],generated_pin=dep_pin)
    loaded['current_context_sha256']=m._digest(m.current_projection(loaded))
    document=deepcopy(before['document'])
    process=dict(process_id=4242,alive=True,create_time=100.,executable=loaded['ownership']['executable'])
    host=Node(GetProcessID=lambda:process['process_id'])
    events=Mock()
    args=dict(process_id=4242,expected_document_path=str(source),expected_source_sha256=digest)
    ctx=m.GroupContext(loaded,dict(args),host,'synthetic.tlb',None,events,before)
    calls=[];pending=Mock()
    settings=m.expected_settings()
    feature=Node(265)
    def collection(items):return Node(Count=len(items),Item=lambda index:items[index])
    old_tool=Node(252,IsMillTool=True,ToolType=1,CutDiameter=12.,Protrusion=50.)
    new_tool=Node(249,IsMillTool=True,ToolType=1,CutDiameter=8.,Protrusion=25.)
    nc=Node(**deepcopy(settings['nc']))
    state={}
    def operation(selected,label):
        values=deepcopy(settings['face'])
        values.update(Suppressed=False,IGetAllFeatures=collection([feature]),IGetTool=selected,IGetNCParam=nc,
            GetIsToolpathGenerated=False,OpernType=20)
        result=Node(267,**values);result.label=label
        def assign(value):
            pending.assert_called_once()
            assert value is new_tool
            calls.append(('mutation','SetTool',value.native_id))
            state['operation']=operation(value,'fresh_after_assignment')
            return 0
        result.values['SetTool']=assign
        return result
    state['operation']=operation(old_tool,'before_assignment')
    initial=state['operation']
    lookups=[]
    def lookup(kind,native_id):
        lookups.append((kind,native_id))
        if (kind,native_id)==(3,267):return state['operation'],True
        if (kind,native_id)==(1,265):return Node(265),True
        raise AssertionError((kind,native_id))
    doc=Node(GetCWObjectFromID=lookup,GetCWObjectID=lambda value:(value.native_id,True),GetDocType=1)
    machine=Node(MachType=1,IGetToolcrib=Node(GetAllTools=collection([old_tool,new_tool])))
    def member(obj,name,*values):
        calls.append((getattr(obj,'label','transport'),name,tuple(values)))
        value=obj.values[name]
        return value(*values) if callable(value) else deepcopy(value) if type(value) in (list,dict) else value
    for module in (cone,dispatch,route_batch,reader):
        monkeypatch.setattr(module,'_member',member)
    import scripts.sw_cam as native_methods
    monkeypatch.setattr(native_methods,'_member',member)
    for module in (dispatch,reader):monkeypatch.setattr(module,'_typed',lambda obj,*args:obj)
    monkeypatch.setattr(reader,'query_face_interface',lambda obj,*args,**kwargs:obj)
    monkeypatch.setattr(reader,'_is_comtypes_pointer',lambda obj:isinstance(obj,Node))
    monkeypatch.setattr(cone,'_process_identity',lambda pid:deepcopy(process))
    for module in (cone,dispatch,identity_module):monkeypatch.setattr(module,'raw_part_identity',lambda sw:deepcopy(document))
    backend=m.NativeBackend.__new__(m.NativeBackend)
    backend.capture=capture;backend.loaded=loaded;backend.args=dict(args);backend.sw=host;backend.ctx=ctx
    backend.clsid='synthetic';backend.typelib_path='synthetic.tlb';backend.report={};backend.persist=Mock()
    backend.current_state=deepcopy(before);backend.expected_tool=deepcopy(wanted)
    backend.native=dict(doc=doc,machine=machine,operations={267:initial})
    backend.events=events;backend.session_active=False
    units=dict(metric_document_scope_observed=True)
    backend._units=lambda:deepcopy(units)
    return SimpleNamespace(backend=backend,source=source,dependency=dependency,document=document,
        process=process,ctx=ctx,loaded=loaded,calls=calls,lookups=lookups,pending=pending,
        initial_operation=initial,state=state,source_sha=digest)


def test_assignment_reacquires_operation_and_feature_inside_real_read_batch(native_case):
    c=native_case;b=c.backend
    assert b.assign_tool(c.pending)==0
    assert b.native['operations'][267] is c.initial_operation
    c.calls.clear();c.lookups.clear()
    observed=b.read_settings('after_assignment')
    assert observed['binding']['native_id']==249
    assert b.native['operations'][267] is c.state['operation']
    assert b.native['operations'][267] is not c.initial_operation
    assert c.lookups.count((3,267))>=1 and c.lookups.count((1,265))>=2
    assert observed['settings']==m.expected_settings()
    batch=b.report['parameter_observations'][-1]['batch']
    assert batch['read_scope_complete'] is True and batch['read_only'] is True
    assert batch['getter_calls']>=40 and batch['binding_native_calls']>0
    assert not any(row[0]=='before_assignment' for row in c.calls)


@pytest.mark.parametrize('kind',['source','dependency','pid','reuse','dead'])
def test_native_boundary_stops_before_mutation_when_current_authority_changes(native_case,kind):
    c=native_case
    if kind=='source':c.source.write_bytes(b'outside saved file change')
    elif kind=='dependency':c.dependency.write_bytes(b'changed runtime')
    elif kind=='pid':c.process['process_id']=9001
    elif kind=='reuse':c.process['create_time']=200.
    elif kind=='dead':c.process['alive']=False
    with pytest.raises(ValueError):c.backend.assign_tool(c.pending)
    c.pending.assert_not_called()
    assert not any(row[:2]==('mutation','SetTool') for row in c.calls)


@pytest.mark.parametrize('value',[False,True,None,1,0.0])
def test_source_binding_cannot_advance_without_strict_save_hresult(native_case,value):
    c=native_case;c.source.write_bytes(b'new saved bytes')
    old=deepcopy(c.ctx.args)
    report=dict(native_call_returned=True,save_pending=False,native_return_type=type(value).__name__,native_return_value=value)
    with pytest.raises(ValueError):c.backend.saved_hash(report)
    assert c.ctx.args==old and 'source_transition' not in c.backend.report


def test_successful_save_records_transition_before_rebinding_source(native_case):
    c=native_case;c.source.write_bytes(b'new saved bytes');new_hash=m._file_hash(c.source)
    snapshots=[]
    c.backend.persist=lambda:snapshots.append((deepcopy(c.backend.report),deepcopy(c.ctx.args)))
    result=c.backend.saved_hash(dict(native_call_returned=True,save_pending=False,native_return_type='int',native_return_value=0))
    assert result==new_hash!=c.source_sha
    assert snapshots[-1][0]['source_transition']['source_after_sha256']==new_hash
    assert snapshots[-1][1]['expected_source_sha256']==c.source_sha
    assert c.ctx.args['expected_source_sha256']==new_hash
    assert c.backend.args['expected_source_sha256']==c.source_sha
    c.backend.boundary()


@pytest.mark.parametrize('kind',['dirty','different_document','pid_reuse'])
def test_save_success_code_alone_cannot_rebind_changed_identity(native_case,kind):
    c=native_case;c.source.write_bytes(b'new saved bytes')
    if kind=='dirty':c.document['needs_save']=True
    elif kind=='different_document':c.document['title']='other.SLDPRT'
    elif kind=='pid_reuse':c.process['create_time']=200.
    with pytest.raises(ValueError):c.backend.saved_hash(dict(native_call_returned=True,save_pending=False,native_return_type='int',native_return_value=0))
    assert c.ctx.args['expected_source_sha256']==c.source_sha


@pytest.mark.parametrize('kind',['rough','finish','cone','face'])
def test_final_full_proof_preserves_payload_and_both_feature_geometries(native_case,kind):
    c=native_case;b=c.backend
    route=(c.loaded['state'],b.expected_tool)
    after=configured(route,generated=True)
    observed=dict(state=after,binding=deepcopy(b.expected_tool),payload=dict(rough=deepcopy(c.loaded['payload']),
        finish=deepcopy(c.loaded['finish_payload'])),cone_observation=deepcopy(c.loaded['cone_observation']),
        face_observation=deepcopy(c.loaded['face_observation']))
    b.verify_final(observed)
    if kind in ('rough','finish'):observed['payload'][kind]['unexpected']=1
    else:observed[kind+'_observation']['unexpected']=1
    with pytest.raises(ValueError):b.verify_final(observed)


def test_selected_generation_dispatches_once_and_rejects_existing_generated_path(native_case):
    c=native_case;b=c.backend
    assert b.assign_tool(c.pending)==0
    c.pending.reset_mock();operation=c.state['operation']
    def generate():
        c.pending.assert_called_once()
        c.calls.append(('mutation','GenerateToolpath',267))
        operation.values['GetIsToolpathGenerated']=True
        return 0
    operation.values['GenerateToolpath']=generate
    assert b.generate(c.pending)==0
    c.pending.reset_mock()
    with pytest.raises(ValueError,match='already generated'):b.generate(c.pending)
    c.pending.assert_not_called()
    assert c.calls.count(('mutation','GenerateToolpath',267))==1


@pytest.mark.parametrize('value',[False,True])
def test_cam_dirty_refresh_preserves_actual_boolean(native_case,value):
    c=native_case;c.document['needs_save']=value
    c.backend.refresh_dirty()
    assert c.ctx.expected_document['needs_save'] is value
    assert c.backend.report['current_document']['needs_save'] is value
    assert c.ctx.args['expected_source_sha256']==c.source_sha
