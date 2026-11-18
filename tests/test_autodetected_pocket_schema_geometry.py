import ast
from copy import deepcopy
import importlib
import math
import os
from pathlib import Path
import sys
from typing import Any, Dict, Literal, Optional

import pytest
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',STAGE))
sys.path.insert(0,str(RUNTIME))
import scripts
if str(STAGE/'scripts') not in scripts.__path__:scripts.__path__.insert(0,str(STAGE/'scripts'))
core=importlib.import_module('scripts.sw_cam_autodetected_pocket')
geo=importlib.import_module('scripts.sw_cam_four_island_geometry')


def loops():
    answer=[]
    for degrees in (20,150,210,340):
        angle=math.radians(degrees)
        def xy(u,v):return [u*math.cos(angle)-v*math.sin(angle),u*math.sin(angle)+v*math.cos(angle)]
        inner,outer,w=12.,16.,2.
        ai,ao=math.sqrt(inner**2-w**2),math.sqrt(outer**2-w**2)
        p=[xy(ai,-w),xy(ao,-w),xy(ao,w),xy(ai,w)]
        answer.append([dict(kind='LINE',start_xy_mm=p[0],end_xy_mm=p[1]),
            dict(kind='ARC',start_xy_mm=p[1],end_xy_mm=p[2],centre_xy_mm=[0.,0.],mid_xy_mm=xy(outer,0),radius_mm=outer),
            dict(kind='LINE',start_xy_mm=p[2],end_xy_mm=p[3]),
            dict(kind='ARC',start_xy_mm=p[3],end_xy_mm=p[0],centre_xy_mm=[0.,0.],mid_xy_mm=xy(inner,0),radius_mm=inner)])
    return answer


def test_analytic_loop_order_is_irrelevant_without_losing_scope():
    expected=loops();observed=[]
    for loop in reversed(deepcopy(expected)):
        reverse=[]
        for c in reversed(loop):
            c['start_xy_mm'],c['end_xy_mm']=c['end_xy_mm'],c['start_xy_mm'];reverse.append(c)
        observed.append(reverse[1:]+reverse[:1])
    proof=geo.verify_four_loops(expected,observed,tolerance_mm=1e-6)
    assert proof['four_planar_islands_verified'] and not proof['world_depth_verified']
    assert not proof['production_qualified']


@pytest.mark.parametrize('damage',['missing','duplicate','shift','arc','opening'])
def test_changed_analytic_geometry_is_rejected(damage):
    expected=loops();actual=deepcopy(expected)
    if damage=='missing':actual.pop()
    elif damage=='duplicate':actual[1]=deepcopy(actual[0])
    elif damage=='shift':
        for c in actual[0]:
            for k in ('start_xy_mm','end_xy_mm','mid_xy_mm','centre_xy_mm'):
                if k in c:c[k][0]+=.02
    elif damage=='arc':actual[0][1]['radius_mm']+=.01
    else:actual[0][0]['end_xy_mm'][0]+=.01
    with pytest.raises(ValueError):geo.verify_four_loops(expected,actual,tolerance_mm=1e-6)


def test_public_factory_metadata_without_application():
    tlb=os.environ.get('SWMCP_CAM_TYPELIB_PATH') or os.environ.get('SWMCP_CAM_TYPELIB')
    if not tlb:pytest.skip('Set public CAM typelib path for installed metadata test')
    result=core.preflight(tlb)
    assert result['dispid']==8 and result['auto_detect_islands'] is True and result['application_calls']==0


def schema():
    source=STAGE/'server.fragment.py'
    if not source.exists():source=RUNTIME/'mcp-server/server.py'
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    selected=[node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='SolidWorksCamAutodetectedPocketInput']
    assert len(selected)==1
    class Target(BaseModel):
        model_config=ConfigDict(extra='forbid')
        addin_clsid:str
        expected_document_title:Optional[str]=None
    class ResponseFormat:
        JSON='json'
    namespace=dict(SolidWorksCamTargetInput=Target,ConfigDict=ConfigDict,Field=Field,Dict=Dict,Any=Any,
                   Literal=Literal,Optional=Optional,model_validator=model_validator,field_validator=field_validator,ResponseFormat=str)
    # Annotation is string; the default value follows the actual server constant.
    selected[0]=deepcopy(selected[0])
    for node in ast.walk(selected[0]):
        if isinstance(node,ast.Attribute) and isinstance(node.value,ast.Name) and node.value.id=='ResponseFormat' and node.attr=='JSON':
            node.value.id='_ResponseValues'
    namespace['_ResponseValues']=ResponseFormat
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected,type_ignores=[])),str(source),'exec'),namespace)
    return namespace['SolidWorksCamAutodetectedPocketInput']


def request(tmp_path):
    value=dict(process_id=731,expected_process_create_time=1234.25,owner_setup_native_id=408,
               expected_sw_configuration='Model',expected_cam_configuration='Mill0',depth_native=13.2,
               qualification_only=True,acknowledge_definition_only=True,message_policy='vendor_default',
               expected_axis_native=[0.,0.,-1.],expected_origin_native=[0.,0.,0.],
               sketch_spec=dict(plane_axis='Z',plane_offset_mm=25.8,sketch_name='ScopeCircle',plane_name='ScopePlane',
                                profile=dict(kind='circle',center_model_mm=[0.,0.,25.8],radius_mm=23.35)))
    for key in core.KEYS:
        if key.endswith('_sha256'):value[key]='1'*64
        if key.endswith('_path'):value[key]=str(tmp_path/(key+('.SLDPRT' if key in ('expected_document_path','original_document_path') else '.json')))
    return value


def test_schema_exact_generic_request(tmp_path):
    model=schema();v=request(tmp_path);result=model(addin_clsid='{00000000-0000-0000-0000-000000000001}',**v)
    assert result.owner_setup_native_id==408


@pytest.mark.parametrize('field,value',[('process_id',731.0),('owner_setup_native_id',True),('acknowledge_definition_only',1),('depth_native',True),('unexpected',1)])
def test_schema_rejects_coercion_and_unknown_keys(tmp_path,field,value):
    v=request(tmp_path);v[field]=value
    with pytest.raises((ValueError,TypeError)):schema()(addin_clsid='synthetic',**v)


def test_schema_installed_runtime_symbol_names():
    source=STAGE/'server.fragment.py'
    if not source.exists():source=RUNTIME/'mcp-server/server.py'
    fragment=ast.parse(source.read_text(encoding='utf-8-sig'))
    installed=ast.parse((RUNTIME/'mcp-server/server.py').read_text(encoding='utf-8-sig'))
    assert any(isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_runtime_identity' for t in node.targets) for node in ast.walk(installed))
    calls=[node.func for node in ast.walk(fragment) if isinstance(node,ast.Call)]
    assert not any(isinstance(fn,ast.Name) and fn.id=='_assert_runtime_unchanged' for fn in calls)

def test_installed_schema_fallback_without_staging_fragment(tmp_path,monkeypatch):
    candidate=STAGE/'candidate02'
    installed=candidate if (candidate/'mcp-server/server.py').exists() else RUNTIME
    module=sys.modules[__name__]
    monkeypatch.setattr(module,'STAGE',tmp_path)
    monkeypatch.setattr(module,'RUNTIME',installed)
    v=request(tmp_path)
    assert schema()(addin_clsid='synthetic',**v).owner_setup_native_id==408
    test_schema_installed_runtime_symbol_names()