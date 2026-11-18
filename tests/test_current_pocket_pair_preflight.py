import ast,copy,os,sys
from pathlib import Path
import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from typing import Literal
from enum import Enum
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_current_pocket_pair_read as core

def request(tmp_path):
    v=dict(process_id=123,expected_process_create_time=123.25,expected_document_path=str(tmp_path/'target.sldprt'),expected_source_sha256='a'*64,expected_feature_native_id=66,expected_operation_native_ids=[114,115],receipt_path=str(tmp_path/'read.json'),qualification_only=True,message_policy='vendor_default')
    for p in core.AUTHORITY_PREFIXES:v[p+'_path']=str(tmp_path/(p+'.json'));v[p+'_sha256']='b'*64
    return v

def schema():
    source=ROOT/'server.fragment.py'
    if not source.exists():source=RUNTIME/'mcp-server/server.py'
    tree=ast.parse(source.read_text(encoding='utf-8-sig'));node=next(x for x in tree.body if isinstance(x,ast.ClassDef)and x.name=='SolidWorksCamCurrentPocketPairReadInput')
    class ResponseFormat(str,Enum):JSON='json'
    class Target(BaseModel):
        model_config=ConfigDict(extra='forbid')
        addin_clsid:str
        expected_document_title:str|None=None
    env=dict(SolidWorksCamTargetInput=Target,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,Literal=Literal,ResponseFormat=ResponseFormat)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),env)
    return env['SolidWorksCamCurrentPocketPairReadInput']

def test_public_metadata_without_application():
    tlb=os.environ.get('SWMCP_CAM_TYPELIB_PATH')
    assert tlb,'Explicit installed public TLB path required for metadata test'
    result=core.preflight(tlb)
    assert result['native_calls']==result['application_connections']==0
    assert len(result['interface_names'])==25
    assert result['planes']['all_resolved']is True

@pytest.mark.parametrize('ids',[[114.0,115],[True,115],[114,114],[114,115,116]])
def test_schema_rejects_nonstrict_pair(tmp_path,ids):
    v=request(tmp_path);v.update(addin_clsid='{00000000-0000-0000-0000-000000000000}',expected_operation_native_ids=ids)
    with pytest.raises(ValueError):schema()(**v)

def test_schema_unknown_and_readonly_request(tmp_path):
    v=request(tmp_path);v['addin_clsid']='{00000000-0000-0000-0000-000000000000}'
    assert schema()(**v).expected_operation_native_ids==[114,115]
    with pytest.raises(ValueError):schema()(**v,action='apply')

def test_constructor_never_accesses_application(tmp_path):
    class NoApplication:
        def __getattr__(self,n):raise AssertionError(n)
    v=request(tmp_path);bundle={'context':{}}
    ctx=core.Context(NoApplication(),'clsid','tlb',v,bundle,{},lambda:None,lambda:None,{})
    assert ctx.session is None and ctx.closed is False

def test_real_parameter_rows_cache_dimensions_once(monkeypatch):
    from scripts import sw_cam_mill_current_parameters as p
    tool={'native_id':116,'is_mill_tool':True,'native_read_complete':True}
    targets=[dict(native_id=114+k,mill_operation_type=k,linked_feature_ids=[66],suppressed=False,toolpath_generated=False,toolpath_record_counts=[],assigned_tool=tool)for k in range(2)]
    class Obj:
        def __init__(self,id):self.id=id
    ops={114:Obj(114),115:Obj(115)};feature=Obj(66);doc=Obj(1)
    def read(obj,name,*args):
        if name=='QueryInterface':return obj
        if name=='GetCWObjectFromID':return ops[args[1]],True
        if name=='OpernType':return obj.id-114
        if name in ('Suppressed','GetIsToolpathGenerated'):return False
        if name=='IGetAllFeatures':return [feature]
        raise AssertionError(name)
    monkeypatch.setattr(p,'_object_id',lambda doc,obj,read:obj.id)
    monkeypatch.setattr(p,'_items',lambda value,*args:value)
    monkeypatch.setattr(p,'read_generic_tool',lambda *args:(copy.deepcopy(tool),Obj(116)))
    monkeypatch.setattr(p.pocket,'read_levels',lambda *a,**kw:{'raw':1})
    monkeypatch.setattr(p.pocket.rough,'read_rough_entry_parameters',lambda *a,**kw:{'raw':2})
    monkeypatch.setattr(p.pocket,'read_finish_parameters',lambda *a,**kw:{'raw':3})
    calls=[]
    def dimensions(*args):calls.append(args[0].id);return {'generic':copy.deepcopy(tool),'mill':{'EffCutlength':21}}
    monkeypatch.setattr(p,'read_tool_dimensions',dimensions)
    state={};native=dict(doc=doc,selected_feature=feature,operations=ops)
    p.capture_rows(state,native,targets,feature_id=66,read=read,typed=lambda o,n:o,boundary=lambda:None)
    assert calls==[116]
    assert state['operation_parameters'][0]['tool']==state['operation_parameters'][1]['tool']
    assert state['parameter_capture_complete']is True
