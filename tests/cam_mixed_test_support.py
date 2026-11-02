"""Shared offline test inputs; no application connection or private default path."""
from copy import deepcopy
import ast,json,math,os,sys
from pathlib import Path
import pytest

def repository_root():
    supplied=os.environ.get('SOLIDWORKS_SKILL_ROOT')
    root=Path(__file__).resolve().parents[1] if supplied is None else Path(supplied)
    if supplied is not None and (not supplied.strip()or not root.is_absolute()):
        raise ValueError('SOLIDWORKS_SKILL_ROOT must be an existing absolute repository root')
    if not (root/'scripts').is_dir()or not (root/'mcp-server/server.py').is_file():
        raise ValueError('Required repository scripts and mcp-server/server.py are missing')
    return root
ROOT=repository_root()
sys.path.insert(0,str(ROOT))
SCRIPTS=ROOT/'scripts'

def evidence_file(env,relative):
    value=os.environ.get(env)
    if value is None:pytest.skip(env+' is not supplied; actual evidence check is optional')
    root=Path(value)
    if not value.strip()or not root.is_absolute()or not root.is_dir():
        raise ValueError(env+' must name an existing absolute evidence directory')
    path=root/relative
    if not path.is_file():raise ValueError(env+' is supplied but required evidence is missing: '+relative)
    return path

def evidence_json(env,relative):
    return json.loads(evidence_file(env,relative).read_text(encoding='utf-8-sig'))

def server_nodes(*names):
    tree=ast.parse((ROOT/'mcp-server/server.py').read_text(encoding='utf-8-sig'))
    result=[n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name in names]
    if len(result)!=len(names):raise ValueError('Installed sealed wrapper is missing or duplicated: '+','.join(names))
    return result

def synthetic_specs():
    start=[1.,0.,10.9];end=[0.,1.,10.9];origin=[0.,0.,10.9]
    arc=dict(kind='arc',start_model_mm=start,end_model_mm=end,mid_model_mm=[math.sqrt(.5),math.sqrt(.5),10.9],center_model_mm=origin,radius_mm=1.,sweep_radians=math.pi/2)
    segments=[arc]+[dict(kind='line',start_model_mm=a,end_model_mm=b,mid_model_mm=[(x+y)/2 for x,y in zip(a,b)])for a,b in [(end,origin),(origin,start)]]
    result=[]
    for i in range(2):
        profile=deepcopy(segments)
        for seg in profile:
            for key,value in seg.items():
                if key.endswith('_model_mm'):seg[key]=[value[0]+4*i,*value[1:]]
        result.append(dict(plane_axis='Z',plane_offset_mm=10.9,sketch_name='RootRestProfile'+str(i+1),plane_name='RootRestPlane'+str(i+1),profile=dict(kind='closed_mixed',segments=profile)))
    return result

def synthetic_context(specs):
    from scripts import sw_cam_deep_long_tool_replace as base
    document=dict(path='part',type=1,title='part',needs_save=False)
    baseline=dict(binding={'operations':[dict(native_id=i,suppressed=False)for i in base.OLD+base.IDS]},parameters=[dict(operation_native_id=i,feature_native_id=80)for i in [322,324,326,328,*base.IDS]])
    return dict(guide_parameters=dict(document=document,expected_parameters=baseline),deep_targets=[],root_pocket_specs=deepcopy(specs),root_pocket_saved_document=deepcopy(document),source_sha256='a'*64,tool_catalogue_ids=[273,338],generated={'saved_cl':{'synthetic':True}},ownership=dict(process_id=123,create_time=1.,executable='test-process',alive=True))
