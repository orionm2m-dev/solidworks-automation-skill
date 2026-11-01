import sys,ast
from pathlib import Path
from enum import Enum
from typing import Optional
from pydantic import BaseModel,ConfigDict,Field,model_validator,StrictInt
import pytest
from test_cam_inprocess_reader import fixture,m
from test_cam_inprocess_host_load import loader
sys.modules['scripts.sw_cam_inprocess_reader']=m
sys.modules['scripts.sw_cam_inprocess_host_load']=loader
class BaseInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
class ResponseFormat(str,Enum):JSON='json'
class FakeMcp:
    def tool(self,**kwargs):return lambda f:f
scope=dict(StrictInt=StrictInt,BaseInput=BaseInput,Field=Field,Optional=Optional,model_validator=model_validator,ResponseFormat=ResponseFormat,mcp=FakeMcp())
root=Path(__file__).parents[1]
tree=ast.parse((root/'mcp-server/server.py').read_text(encoding='utf-8'))
classes={'SolidWorksCamInprocessReaderInput','SolidWorksCamInprocessHostLoadInput'}
for node in tree.body:
    if isinstance(node,ast.ClassDef) and node.name in classes:
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<server-model>','exec'),scope)

def test_reader_mcp_model_preserves_strict_integer_boundary(fixture):
    p,_=fixture;cls=scope['SolidWorksCamInprocessReaderInput']
    cls(**dict(p,nc_operation_ids=[322]))
    for bad in ([True],['322'],[322,322]):
        with pytest.raises(ValueError):cls(**dict(p,nc_operation_ids=bad))

def test_loader_mcp_inherited_validation_accepts_only_explicit_load(fixture):
    p,_=fixture;cls=scope['SolidWorksCamInprocessHostLoadInput'];cls(**dict(p,acknowledge_host_load=True))
    for bad in (False,'true'):
        with pytest.raises(ValueError):cls(**dict(p,acknowledge_host_load=bad))
    with pytest.raises(ValueError):cls(**dict(p,acknowledge_host_load=True,nc_operation_ids=[322]))
