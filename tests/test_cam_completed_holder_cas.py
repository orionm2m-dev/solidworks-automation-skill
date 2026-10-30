"""使用真实单次状态机结果，验证完成后的只读证据加载器。"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts import sw_cam_completed_holder_cas as m
from test_cam_holder_shape_lifecycle import scenario, query_case, run


@pytest.fixture
def completed(query_case):
    case, query, load = query_case
    # 十七条独立合成线段，数量满足协议，不复制供应商或工程几何。
    case.loaded['holder']['records'] = [dict(kind='line', start_rz=[float(i),0.],
        end_rz=[float(i+1),0.]) for i in range(17)]
    loaded = load()
    case.loaded.update(loaded)
    result = run(case)
    assert result['readback_verified'] and result['mode_and_profile_verified'], result
    prior = dict(data=dict(new_tool_native_id=263, before_document=deepcopy(result['before_document']),
        tool=deepcopy(case.loaded['candidate']['tool'])),holder=case.loaded['holder'],
        pin=dict(sha256='a'*64),pins=[case.loaded['observation_pin']])
    cut = dict(tool_native_id=263,process_id=1234,expected_source_sha256=case.args['expected_source_sha256'],
        prior_receipt_pin=case.loaded['observation_pin'],immutable_pins=[case.loaded['observation_pin']])
    args = {k:case.args[k] for k in ('expected_candidate_tool_native_id','process_id',
                                   'expected_document_path','expected_source_sha256')}
    path = Path(case.args['receipt_path'])
    return SimpleNamespace(case=case,prior=prior,cut=cut,args=args,path=path,data=result)


def load(value):
    return m.load_completed_holder_cas(value.prior,value.cut,holder_shape_receipt_path=str(value.path),
        holder_shape_receipt_sha256=m._file_hash(value.path),**value.args)


def update_receipt(value,change):
    data=json.loads(value.path.read_text(encoding='utf-8-sig'))
    change(data)
    value.path.write_text(json.dumps(data),encoding='utf-8')


def test_actual_lifecycle_output_accepted_without_reopening_gate(completed,monkeypatch):
    import scripts.sw_cam_holder_shape_cas as writer
    monkeypatch.setattr(writer,'change_existing_holder_shape',lambda *a,**kw:pytest.fail('mutation called by loader'))
    before={str(p):p.read_bytes() for p in (completed.path,completed.case.loaded['marker'])}
    got=load(completed)
    assert got['holder_verification']['native_holder_shape_verified'] is True
    assert got['holder_snapshot']['GetHolderShape']=='User Defined'
    assert len(got['holder_profile']['chains'][0]['curves'])==17
    assert completed.case.calls==['SetHolderShape']
    assert all(Path(p).read_bytes()==content for p,content in before.items())


@pytest.mark.parametrize('change',[
    lambda d:d.update(native_dispatch_pending=True),
    lambda d:d.update(native_call_returned=False),
    lambda d:d.update(readback_verified=False),
    lambda d:d.update(holder_profile_verified=False),
    lambda d:d.update(tool_native_id=264),
    lambda d:d.update(tool_native_id=True),
    lambda d:d.update(process_id=5678),
    lambda d:d.update(source_sha256='0'*64),
    lambda d:d.update(setter_return_value=True),
    lambda d:d.update(setter_return_value=-1),
    lambda d:d.update(setter_return_type='NoneType'),
    lambda d:d.update(save_attempted=True),
    lambda d:d.update(production_qualified=True),
    lambda d:d['messages'].update(event_count=1),
    lambda d:d['guard_diagnostics'][0].update(invalid=True),
    lambda d:d['after_document'].update(title='other.sldprt'),
    lambda d:d['after_document'].update(needs_save=0),
    lambda d:d['after']['tool_parameters'].update(CutLength=20),
    lambda d:d['after']['holder'].update(GetProtrusion=26),
    lambda d:d['after']['holder'].update(GetHolderShape='Cylindrical'),
    lambda d:d['after']['holder_diagnostic'].update(capture_complete=False),
    lambda d:d['after']['holder_profile']['chains'][0]['curves'][0]['end_native'].__setitem__(0,99.),
])
def test_completed_loader_rejects_wrong_or_incomplete_proof(completed,change):
    update_receipt(completed,change)
    with pytest.raises(ValueError):load(completed)
    assert completed.case.calls==['SetHolderShape']


def test_receipt_hash_mismatch_rejected(completed):
    with pytest.raises(ValueError):
        m.load_completed_holder_cas(completed.prior,completed.cut,holder_shape_receipt_path=str(completed.path),
            holder_shape_receipt_sha256='0'*64,**completed.args)


def test_query_bytes_changed_rejected(completed):
    query=Path(completed.data['query_pin']['path'])
    query.write_text('{}')
    with pytest.raises(ValueError):load(completed)


def test_current_source_changed_rejected(completed):
    Path(completed.args['expected_document_path']).write_bytes(b'changed saved part')
    with pytest.raises(ValueError,match='Saved source changed'):load(completed)


def test_completed_marker_pending_rejected_without_rewrite(completed):
    marker=completed.case.loaded['marker']
    data=json.loads(marker.read_text(encoding='utf-8-sig'));data['native_dispatch_pending']=True
    marker.write_text(json.dumps(data),encoding='utf-8');before=marker.read_bytes()
    with pytest.raises(ValueError,match='marker differs'):load(completed)
    assert marker.read_bytes()==before


def test_prior_and_cut_identity_binding_is_not_inferred(completed):
    completed.cut['tool_native_id']=264
    with pytest.raises(ValueError,match='candidate/process/source'):load(completed)


def test_protected_asset_hash_is_checked(completed):
    p=Path(completed.prior['pins'][0]['path']);p.write_bytes(b'altered contract')
    with pytest.raises(ValueError):load(completed)
