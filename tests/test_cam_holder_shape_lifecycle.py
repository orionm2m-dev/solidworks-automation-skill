"""现有刀柄单次形状选择：合成数据、真实状态机和负向回读检查。"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts import sw_cam_holder_shape_cas as m
from cam_mutation_test_fixtures import NativeBoundary, EventSession

REAL_LOAD_SHAPE = m.load_shape_change


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    source = tmp_path / 'fixture.sldprt'
    source.write_bytes(b'synthetic part')
    evidence = tmp_path / 'contract.json'
    evidence.write_text('{}')
    doc = dict(path=str(source), title=source.name, document_type=1, needs_save=False)
    pin = dict(path=str(evidence), sha256=m._file_hash(evidence))
    holder = {k: 1.0 for k in m.HOLDER_FIELDS}
    holder.update(GetHolderShape='Cylindrical', GetHolderId=17, GetHolderNumber='fixture',
                  GetName=str(tmp_path / 'holder.mh'), GetProtrusion=25.0)
    tool = dict(m.FIELDS)
    tool.update(ToolType=14, IsMillTool=True, GetToolName=str(tmp_path / 'tool.mt'),
                IGetMillToolHolder=holder, native_id=263)
    crib = dict(GetAllTools=[tool])
    native = dict(doc=object(), machine=dict(IGetToolcrib=crib), operations={})
    anchor = SimpleNamespace(pins=[], check_files=lambda: None, check_runtime_identity=lambda: None)
    recipe = dict(file_path=holder['GetName'], records=[dict(kind='line', start_rz=[0.,0.], end_rz=[1.,0.])])
    loaded = dict(anchor=anchor, pins=[pin], marker=tmp_path / 'attempt.json', query_pin=pin,
        observation_pin=pin, query=dict(after_document=deepcopy(doc), after_holder=deepcopy(holder)),
        prior={}, holder=recipe, candidate=dict(tool=dict(mt_path_raw=tool['GetToolName'], parameters=dict(m.FIELDS))))
    args = dict(holder_query_receipt_path=str(evidence), holder_query_receipt_sha256=pin['sha256'],
        expected_candidate_tool_native_id=263, expected_holder_shape_raw='Cylindrical',
        desired_holder_shape='User Defined', process_id=1234, expected_document_path=str(source),
        expected_source_sha256=m._file_hash(source), receipt_path=str(tmp_path / 'result.json'),
        qualification_only=True, acknowledge_disposable_copy=True, message_policy='vendor_default')
    controls = dict(result=0, exception=False, drift=None, dirty=False)
    calls = []
    monkeypatch.setattr(m, 'load_shape_change', lambda **kwargs: loaded)
    monkeypatch.setattr(m, '_bootstrap', lambda *args: object())
    monkeypatch.setattr(m, 'raw_part_identity', lambda sw: deepcopy(doc))
    monkeypatch.setattr(m, 'resolve_existing_context', lambda *args: native)
    monkeypatch.setattr(m, '_object_id', lambda doc, obj, read: obj['native_id'])
    monkeypatch.setattr(m, 'holder_objects', lambda *args: {263: holder})
    monkeypatch.setattr(m, 'com_identity', lambda obj, read: id(obj))
    monkeypatch.setattr(m, 'ScopedCamDispatchGuard', NativeBoundary)
    import scripts.sw_cam_events as events
    monkeypatch.setattr(events, 'CamMessageSession', EventSession)
    def profile(*args, diagnostic, **kwargs):
        curves = [dict(read_complete=True, curve_type=0,
            start_native=[record['start_rz'][0],0.,record['start_rz'][1]+25.],
            end_native=[record['end_rz'][0],0.,record['end_rz'][1]+25.]) for record in recipe['records']]
        diagnostic['state'].update(status='observed', declared_chain_count=1, chains=[dict(
            read_complete=True, declared_curve_count=len(curves), curves=curves)])
        diagnostic.update(capture_complete=True, stage='complete')
    monkeypatch.setattr(m, 'read_segment_chains', profile)
    def member(obj, name, *values):
        if name == 'GetProcessID':
            return 1234
        assert obj is holder and name == 'SetHolderShape' and values == ('User Defined',)
        pending = json.loads(Path(args['receipt_path']).read_text(encoding='utf-8-sig'))
        marker = json.loads(loaded['marker'].read_text(encoding='utf-8-sig'))
        assert pending['native_dispatch_pending'] and pending['setter_attempted']
        assert marker['native_dispatch_pending'] and marker['automatic_replay'] is False
        calls.append(name)
        if controls['exception']:
            raise RuntimeError('synthetic native outcome unknown')
        holder['GetHolderShape'] = 'User Defined'
        doc['needs_save'] = controls['dirty']
        if controls['drift'] == 'protrusion': holder['GetProtrusion'] = 26.0
        if controls['drift'] == 'tool': tool['CutLength'] = 20.0
        if controls['drift'] == 'source': source.write_bytes(b'changed source')
        if controls['drift'] == 'evidence': evidence.write_text('{"changed": true}')
        return controls['result']
    monkeypatch.setattr(m, '_member', member)
    return SimpleNamespace(args=args, loaded=loaded, controls=controls, calls=calls, doc=doc)


def run(case):
    return m.change_existing_holder_shape(object(), 'fixture', 'fixture.tlb', **case.args)


@pytest.mark.parametrize('dirty', [False, True])
def test_one_setter_and_raw_dirty_preserved(scenario, dirty):
    scenario.controls['dirty'] = dirty
    result = run(scenario)
    assert result['readback_verified'], result
    assert result['holder_profile_verified'] and result['mode_changed']
    assert result['after_document']['needs_save'] is dirty
    assert scenario.calls == ['SetHolderShape']
    assert result['production_qualified'] is False and result['full_context_rechecked'] is False
    assert all(result[k] is False for k in ('GTP_attempted','save_attempted','assignment_attempted','export_attempted'))


@pytest.mark.parametrize('value', [True, False, None, 0.0, '0', -1, 2**31])
def test_unexpected_return_is_once_and_uncertain(scenario, value):
    scenario.controls['result'] = value
    result = run(scenario)
    assert result['status'] == 'uncertain' and not result['readback_verified']
    assert result['native_call_returned'] and not result['native_dispatch_pending']
    assert type(result['setter_return_value']) is type(value) and result['setter_return_value'] == value
    assert 'after' not in result and scenario.calls == ['SetHolderShape']


def test_unknown_exception_keeps_pending_evidence(scenario):
    scenario.controls['exception'] = True
    result = run(scenario)
    assert result['status'] == 'uncertain' and result['native_dispatch_pending']
    assert not result['native_call_returned'] and scenario.calls == ['SetHolderShape']
    marker = json.loads(scenario.loaded['marker'].read_text(encoding='utf-8-sig'))
    assert marker['native_dispatch_pending'] and marker['automatic_replay'] is False


@pytest.mark.parametrize('drift', ['protrusion', 'tool', 'source', 'evidence'])
def test_post_setter_invariant_change_is_not_success(scenario, drift):
    scenario.controls['drift'] = drift
    result = run(scenario)
    assert result['status'] == 'uncertain' and not result['readback_verified']
    assert scenario.calls == ['SetHolderShape']
    disk = json.loads(Path(scenario.args['receipt_path']).read_text(encoding='utf-8-sig'))
    assert disk['setter_attempted'] and disk['readback_verified'] is False
    if drift == 'protrusion':
        assert disk['after']['holder']['GetProtrusion'] == 26.0


def test_same_attempt_marker_stops_second_native_call(scenario, tmp_path):
    first = run(scenario)
    assert first['readback_verified']
    marker = scenario.loaded['marker'].read_bytes()
    scenario.args['receipt_path'] = str(tmp_path / 'second.json')
    result = run(scenario)
    assert not result['setter_attempted'] and not result['readback_verified']
    assert scenario.calls == ['SetHolderShape']
    assert scenario.loaded['marker'].read_bytes() == marker


def test_existing_receipt_is_not_overwritten(scenario):
    output = Path(scenario.args['receipt_path'])
    output.write_bytes(b'previous immutable report')
    result = run(scenario)
    assert result['status'] == 'error' and not result['mutation_attempted']
    assert scenario.calls == [] and output.read_bytes() == b'previous immutable report'


@pytest.fixture
def query_case(scenario, monkeypatch, tmp_path):
    parent = dict(scenario.loaded)
    parent["data"] = dict(before_document=deepcopy(scenario.doc), prior_receipt_pin=dict(sha256="a"*64))
    query = dict(scope=m.QUERY_SCOPE, status="observed", phase="finished", readback_verified=True,
        raw_dimensions=True, tool_native_id=263, process_id=1234,
        source_sha256=scenario.args["expected_source_sha256"],
        expected_document_path=scenario.args["expected_document_path"],
        observation_pin=scenario.loaded["observation_pin"],
        before_document=deepcopy(scenario.doc), after_document=deepcopy(scenario.doc),
        before_tool_parameters=dict(m.FIELDS), after_tool_parameters=dict(m.FIELDS),
        holder=deepcopy(scenario.loaded["query"]["after_holder"]),
        after_holder=deepcopy(scenario.loaded["query"]["after_holder"]),
        guard_diagnostic=dict(invalid=False,native_call_attempted=False),
        messages=dict(subscribed=True,active=False,disconnected=True,event_count=0))
    for name in ("mutation_attempted","export_attempted","save_attempted","assignment_attempted",
        "GTP_attempted","profile_read_attempted","manufacturing_qualified","may_mutate",
        "full_context_rechecked","units_verified"):
        query[name]=False
    monkeypatch.setattr(m, "load_holder_query", lambda **kwargs: parent)
    target=tmp_path/"query.json"
    def load():
        target.write_text(json.dumps(query),encoding="utf-8")
        args=dict(scenario.args,holder_query_receipt_path=str(target),holder_query_receipt_sha256=m._file_hash(target))
        return REAL_LOAD_SHAPE(**args)
    return scenario,query,load


def test_synthetic_query_accepted_by_real_loader(query_case):
    case,query,load=query_case
    result=load()
    assert result["query"]["holder"]["GetHolderShape"]=="Cylindrical"
    assert result["marker"]==m.shape_marker(case.args["expected_document_path"],"a"*64,263)


@pytest.mark.parametrize("change",[
    lambda q:q.update(readback_verified=False),
    lambda q:q.update(process_id=5678),
    lambda q:q.update(source_sha256="0"*64),
    lambda q:q.update(mutation_attempted=True),
    lambda q:q["messages"].update(event_count=1),
    lambda q:q["guard_diagnostic"].update(invalid=True),
    lambda q:q["after_tool_parameters"].update(CutLength=20),
    lambda q:q["after_holder"].update(GetProtrusion=26.0),
])
def test_real_loader_rejects_changed_query(query_case,change):
    case,query,load=query_case
    change(query)
    with pytest.raises(ValueError):load()
    assert case.calls==[]


def test_real_loader_preserves_existing_marker(query_case):
    case,query,load=query_case
    marker=m.shape_marker(case.args["expected_document_path"],"a"*64,263)
    marker.write_bytes(b"previous uncertain attempt")
    with pytest.raises(ValueError,match="never replay"):load()
    assert marker.read_bytes()==b"previous uncertain attempt" and case.calls==[]
