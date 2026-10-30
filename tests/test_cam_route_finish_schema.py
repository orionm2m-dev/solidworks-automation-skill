"""真实服务器节点的离线输入模式测试；不加载或连接 CAD。"""
import ast
from cam_route_test_fixtures import REPO

def server_nodes(names):
    tree = ast.parse((REPO / 'mcp-server/server.py').read_text(encoding='utf-8-sig'))
    result = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names]
    assert {n.name for n in result} == set(names)
    return result
from copy import deepcopy
from pathlib import Path
from typing import Literal, Optional
import json, sys, types
import pytest
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from scripts import sw_cam_finish_continuation_evidence as ev
from scripts import sw_cam_finish_continuation as sut
from test_cam_route_finish_continuation import data

def schema():

    class Base(BaseModel):
        model_config = ConfigDict(extra='forbid')
        addin_clsid: str = 'clsid'
        expected_document_title: Optional[str] = None
        response_format: str = 'json'

    class Tools:

        def tool(self, **kw):
            return lambda f: f
    from scripts.sw_operation_guard import absolute_document_path
    ns = dict(SolidWorksCamTargetInput=Base, Field=Field, Literal=Literal, Optional=Optional, field_validator=field_validator, model_validator=model_validator, Path=Path, absolute_document_path=absolute_document_path, mcp=Tools())
    exec(compile(ast.Module(body=server_nodes(['_finish_continuation_call', 'SolidWorksCamFinishContinuationInput', 'SolidWorksCamFinishSaveInput', 'SolidWorksCamFinishCLInput', 'solidworks_cam_generate_finish_recipe', 'solidworks_cam_save_finish_progress', 'solidworks_cam_export_finish_generic_cl']), type_ignores=[]), str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'), 'exec'), ns)
    return ns

def request(tmp_path):
    (l, a) = data(tmp_path)
    a.update(checkpoint_receipt_path=l['pin']['path'], checkpoint_receipt_sha256=l['pin']['sha256'])
    return a

@pytest.mark.parametrize('key,value', [('process_id', True), ('target_operation_native_id', '247'), ('qualification_only', False), ('software_only_experiment', 1), ('software_only_experiment', False), ('expected_document_title', 'title'), ('checkpoint_receipt_sha256', 'BAD'), ('checkpoint_receipt_path', 'relative.json'), ('expected_document_path', 'relative.SLDPRT'), ('message_policy', 'ignore'), ('read_mode', 'fast')])
def test_schema_rejects_inexact_inputs(tmp_path, key, value):
    a = request(tmp_path)
    a[key] = value
    with pytest.raises(ValueError):
        schema()['SolidWorksCamFinishContinuationInput'](**a)

def test_schema_save_and_cl_are_explicit(tmp_path):
    ns = schema()
    a = request(tmp_path)
    with pytest.raises(ValueError):
        ns['SolidWorksCamFinishSaveInput'](**a)
    assert ns['SolidWorksCamFinishSaveInput'](**dict(a, checkpoint_action='gtp')).checkpoint_action == 'gtp'
    with pytest.raises(ValueError):
        ns['SolidWorksCamFinishSaveInput'](**dict(a, checkpoint_action='entry'))
    with pytest.raises(ValueError):
        ns['SolidWorksCamFinishCLInput'](**dict(a, project_root=str(tmp_path), output_path=str(tmp_path / 'x.cl'), acknowledge_machine_scope=False))

@pytest.mark.parametrize('name,cls,backend,extra', [('solidworks_cam_generate_finish_recipe', 'SolidWorksCamFinishContinuationInput', 'generate_finish_after_recipe', {}), ('solidworks_cam_save_finish_progress', 'SolidWorksCamFinishSaveInput', 'save_finish_progress', {'checkpoint_action': 'cl'}), ('solidworks_cam_export_finish_generic_cl', 'SolidWorksCamFinishCLInput', 'export_finish_generic_cl', {'acknowledge_machine_scope': True})])
def test_each_wrapper_forwards_only_its_action(tmp_path, monkeypatch, name, cls, backend, extra):
    ns = schema()
    a = request(tmp_path)
    a.update(extra)
    if cls.endswith('CLInput'):
        a.update(project_root=str(tmp_path), output_path=str(tmp_path / 'x.cl'))
    params = ns[cls](**a)
    calls = []
    monkeypatch.setattr(sut, backend, lambda *x, **kw: calls.append((x, kw)) or {'ok': True})
    ns.update(_selected_process_id=23824, _run_locked=lambda op, fmt: op(), _cam_target=lambda p: ('sw', {'clsid': 'clsid', 'addin_path': str(tmp_path / 'addin.dll')}))
    assert ns[name](params) == {'ok': True} and len(calls) == 1
    assert calls[0][1] == dict(params.model_dump(exclude={'addin_clsid', 'expected_document_title', 'response_format'}), typelib_path=str(tmp_path / 'camworks.tlb'))
    ns['_selected_process_id'] = 1
    with pytest.raises(ValueError):
        ns[name](params)
    assert len(calls) == 1

