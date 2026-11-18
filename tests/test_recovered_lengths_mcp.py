"""MCP delivery boundaries for the saved pocket length reader."""
import ast
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from enum import Enum
from typing import Optional, Literal
import pytest
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

RT = Path(os.environ.get('SWMCP_RUNTIME_ROOT', Path(__file__).resolve().parents[1]))
if str(RT) not in sys.path: sys.path.insert(0, str(RT))
from scripts.sw_operation_guard import absolute_document_path
from scripts import sw_cam_qualify_recovered_pocket_read as parent
import scripts


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    server = Path(os.environ.get('SWMCP_LENGTH_SERVER_CANDIDATE', RT/'mcp-server/server.py'))
    names = {'ResponseFormat', 'BaseInput', 'ActiveDocumentInput', 'SolidWorksCamTargetInput',
             'SolidWorksCamRecoveredPocketReadQualificationInput', 'SolidWorksCamRecoveredPocketLengthsInput',
             'solidworks_cam_read_recovered_pocket_lengths'}
    nodes = [n for n in ast.parse(server.read_text(encoding='utf-8-sig')).body
             if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names]
    assert {n.name for n in nodes} == names
    trace = []
    control = {'failure': None}
    def current():
        trace.append('runtime')
        if control['failure'] == 'outer' and trace.count('runtime') == 2:
            raise ValueError('late runtime change')
    def prepare(values):
        trace.append('prepare')
        assert set(values) == parent.KEYS
        if control['failure'] == 'authority': raise ValueError('changed authority')
        return dict(request=values, consumed=False)
    def run(sw, clsid, tlb, values, *, prepared, runtime_check):
        trace.append('read')
        assert set(values) == parent.KEYS and prepared['request'] == values
        assert prepared['consumed'] is False and sw is control['sw']
        assert clsid == control['values']['addin_clsid'] and Path(tlb).name == 'camworks.tlb'
        return dict(status='error' if control['failure'] == 'native' else 'observed',
                    read_only=True, mutation_attempted=False, native_length_observation={'complete': False})
    def revoke(result, error):
        trace.append('revoke')
        assert str(error) == 'late runtime change' and result['mutation_attempted'] is False
        return dict(result, status='error', runtime_error=str(error))
    backend = SimpleNamespace(prepare=prepare, run_read=run, revoke=revoke)
    monkeypatch.setitem(sys.modules, 'scripts.sw_cam_recovered_pocket_lengths', backend)
    monkeypatch.setattr(scripts, 'sw_cam_recovered_pocket_lengths', backend, raising=False)
    control['sw'] = object()
    def target(params):
        trace.append('target')
        return control['sw'], dict(clsid=params.addin_clsid, addin_path=str(tmp_path/'addin.dll'))
    def tool(**metadata):
        assert metadata['name'] == 'solidworks_cam_read_recovered_pocket_lengths'
        assert metadata['annotations']['readOnlyHint'] is True
        assert metadata['annotations']['destructiveHint'] is False
        return lambda function: function
    ns = dict(BaseModel=BaseModel, Field=Field, ConfigDict=ConfigDict,
              field_validator=field_validator, model_validator=model_validator,
              Optional=Optional, Literal=Literal, Enum=Enum, Path=Path,
              absolute_document_path=absolute_document_path, mcp=SimpleNamespace(tool=tool),
              _runtime_identity=SimpleNamespace(assert_current=current), _selected_process_id=123,
              _cam_target=target, _run_locked=lambda invoke, fmt: invoke())
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(server), 'exec'), ns)
    values = dict(process_id=123, expected_process_create_time=1000.25,
                  expected_document_path=str(tmp_path/'sample.SLDPRT'), expected_source_sha256='a'*64,
                  expected_feature_native_id=66, expected_operation_native_ids=[69, 70],
                  recovered_receipt_path=str(tmp_path/'recovery.json'), recovered_receipt_sha256='b'*64,
                  receipt_path=str(tmp_path/'lengths.json'),
                  addin_clsid='{11111111-2222-3333-4444-555555555555}', response_format='json')
    control['values'] = values
    return ns, values, trace, control


def invoke(delivery):
    ns, values, trace, control = delivery
    model = ns['SolidWorksCamRecoveredPocketLengthsInput'].model_validate(values)
    return ns['solidworks_cam_read_recovered_pocket_lengths'](model)


def test_native_delivery_uses_exact_prepared_readonly_request(delivery):
    result = invoke(delivery)
    assert result['status'] == 'observed' and result['mutation_attempted'] is False
    assert delivery[2] == ['runtime', 'prepare', 'target', 'read', 'runtime']
    assert result['native_length_observation']['complete'] is False


@pytest.mark.parametrize('key,value', [
    ('process_id', True), ('expected_operation_native_ids', [69, True]),
    ('expected_operation_native_ids', [69, 69]), ('expected_document_title', 'sample'),
    ('receipt_path', 'relative.json'), ('expected_source_sha256', 'bad'),
    ('recovered_receipt_sha256', 'bad'), ('Save_attempted', True),
])
def test_invalid_schema_never_resolves_application(delivery, key, value):
    delivery[1][key] = value
    with pytest.raises(ValueError): invoke(delivery)
    assert not delivery[2]


def test_other_process_rejected_before_authority_or_application(delivery):
    delivery[0]['_selected_process_id'] = 124
    with pytest.raises(ValueError, match='process'): invoke(delivery)
    assert delivery[2] == ['runtime']


def test_changed_authority_never_connects_to_application(delivery):
    delivery[3]['failure'] = 'authority'
    with pytest.raises(ValueError, match='authority'): invoke(delivery)
    assert delivery[2] == ['runtime', 'prepare']


def test_outer_runtime_failure_is_revoked(delivery):
    delivery[3]['failure'] = 'outer'
    result = invoke(delivery)
    assert result['status'] == 'error' and result['runtime_error'] == 'late runtime change'
    assert delivery[2][-1] == 'revoke'


def test_native_error_is_not_promoted(delivery):
    delivery[3]['failure'] = 'native'
    result = invoke(delivery)
    assert result['status'] == 'error' and result['native_length_observation']['complete'] is False