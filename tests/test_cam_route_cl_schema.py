"""真实服务器节点的离线输入模式测试；不加载或连接 CAD。"""
import ast
from cam_route_test_fixtures import REPO

def server_nodes(names):
    tree = ast.parse((REPO / 'mcp-server/server.py').read_text(encoding='utf-8-sig'))
    result = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names]
    assert {n.name for n in result} == set(names)
    return result
import ast
from enum import Enum
from pathlib import Path
from typing import Literal, Optional
import types
import sys
import pytest
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from scripts.sw_operation_guard import absolute_document_path

def ns():
    nodes = server_nodes(['ResponseFormat', 'BaseInput', 'SolidWorksCamGenericCLReadInput', 'solidworks_cam_read_generic_cl'])
    scope = dict(globals())
    scope['mcp'] = types.SimpleNamespace(tool=lambda **kwargs: lambda fn: fn)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'), 'exec'), scope)
    return scope

def args(tmp):
    return dict(export_receipt_path=str(tmp / 'export.json'), export_receipt_sha256='a' * 64, cl_path=str(tmp / 'output.cl'), cl_sha256='b' * 64, expected_operation_native_id=247, output_path=str(tmp / 'analysis.json'))

def test_schema(tmp_path):
    p = ns()['SolidWorksCamGenericCLReadInput'](**args(tmp_path))
    assert p.encoding == 'cp1251'

@pytest.mark.parametrize('change', [{'expected_operation_native_id': True}, {'expected_operation_native_id': 0}, {'cl_path': 'relative.cl'}, {'cl_sha256': 'bad'}, {'export_receipt_sha256': None}, {'encoding': 'guess'}, {'output_path': 'C:/file.nc'}, {'process_id': 23824}, {'generate': True}, {'apply_transform': True}, {'scale': 1000}])
def test_no_native_or_transform_inputs(tmp_path, change):
    with pytest.raises(ValueError):
        ns()['SolidWorksCamGenericCLReadInput'](**args(tmp_path) | change)

def test_alias_refused(tmp_path):
    a = args(tmp_path)
    a['output_path'] = a['export_receipt_path']
    with pytest.raises(ValueError):
        ns()['SolidWorksCamGenericCLReadInput'](**a)

def test_wrapper_has_no_cad_target_lookup(tmp_path, monkeypatch):
    scope = ns()
    p = scope['SolidWorksCamGenericCLReadInput'](**args(tmp_path))
    calls = []
    backend = types.ModuleType('scripts.sw_cam_generic_cl_reader')
    backend.analyze_exported_generic_cl = lambda **kw: calls.append(kw) or {'offline': True}
    monkeypatch.setitem(sys.modules, backend.__name__, backend)
    scope['_result'] = lambda value, fmt: value
    scope['_tool_error'] = lambda exc, fmt: (_ for _ in ()).throw(exc)
    assert scope['solidworks_cam_read_generic_cl'](p) == {'offline': True}
    assert calls == [p.model_dump(exclude={'response_format'})]

def export_ns():
    nodes = server_nodes(['ResponseFormat', 'BaseInput', 'ActiveDocumentInput', 'SolidWorksCamTargetInput', 'SolidWorksCamSelectedFeatureContextInput', 'SolidWorksCamMillGenericCLExportInput'])
    scope = dict(globals())
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'), 'exec'), scope)
    return scope

def export_args(tmp):
    return dict(process_id=23824, addin_clsid='{00000000-0000-0000-0000-000000000001}', expected_document_path=str(tmp / 'part.SLDPRT'), expected_source_sha256='a' * 64, expected_feature_native_id=244, expected_operation_native_id=248, expected_mill_operation_type=2, expected_toolpath_record_counts=[4], expected_ungenerated_operation_ids=[143], action='inspect', qualification_only=True, acknowledge_disposable_copy=True, acknowledge_machine_scope=True, expected_generated_operations=[dict(operation_native_id=247, toolpath_record_counts=[191]), dict(operation_native_id=248, toolpath_record_counts=[4])])

def test_export_schema_passes_ordered_contract(tmp_path):
    p = export_ns()['SolidWorksCamMillGenericCLExportInput'](**export_args(tmp_path))
    assert p.expected_generated_operations[0]['operation_native_id'] == 247

@pytest.mark.parametrize('change', ['bool_id', 'extra', 'duplicate', 'coercion', 'overlap'])
def test_export_schema_strict_contract(tmp_path, change):
    a = export_args(tmp_path)
    if change == 'bool_id':
        a['expected_generated_operations'][0]['operation_native_id'] = True
    elif change == 'extra':
        a['expected_generated_operations'][0]['label'] = 'not ID'
    elif change == 'duplicate':
        a['expected_generated_operations'][0]['operation_native_id'] = 248
    elif change == 'coercion':
        a['expected_generated_operations'][0]['toolpath_record_counts'] = ['191']
    elif change == 'overlap':
        a['expected_ungenerated_operation_ids'].append(247)
    with pytest.raises(ValueError):
        export_ns()['SolidWorksCamMillGenericCLExportInput'](**a)

@pytest.mark.parametrize('change', ['bool_id', 'coercion', 'missing_siblings', 'duplicate', 'extra'])
def test_reader_schema_strict_contract(tmp_path, change):
    a = args(tmp_path)
    a['expected_generated_operations'] = [dict(operation_native_id=247, toolpath_record_counts=[191])]
    a['expected_ungenerated_operation_ids'] = []
    if change == 'bool_id':
        a['expected_generated_operations'][0]['operation_native_id'] = True
    elif change == 'coercion':
        a['expected_generated_operations'][0]['toolpath_record_counts'] = ['191']
    elif change == 'missing_siblings':
        a.pop('expected_ungenerated_operation_ids')
    elif change == 'duplicate':
        a['expected_generated_operations'] *= 2
    elif change == 'extra':
        a['expected_generated_operations'][0]['label'] = 'not ID'
    with pytest.raises(ValueError):
        ns()['SolidWorksCamGenericCLReadInput'](**a)
