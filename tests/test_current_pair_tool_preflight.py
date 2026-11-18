import ast,copy,os,sys
from pathlib import Path
from enum import Enum
from typing import Literal
import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',ROOT));sys.path.insert(0,str(RUNTIME))
import scripts;scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_current_pair_tool as core

def model():
    source=ROOT/'server.fragment.py'
    if not source.exists():source=RUNTIME/'mcp-server/server.py'
    node=next(x for x in ast.parse(source.read_text(encoding='utf-8-sig')).body if isinstance(x,ast.ClassDef)and x.name=='SolidWorksCamCurrentPairToolInput')
    class Target(BaseModel):
        model_config=ConfigDict(extra='forbid')
        addin_clsid:str
        expected_document_title:str|None=None
    class ResponseFormat(str,Enum):JSON='json'
    env=dict(SolidWorksCamTargetInput=Target,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,Literal=Literal,ResponseFormat=ResponseFormat)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),env)
    return env['SolidWorksCamCurrentPairToolInput']

def inputs(tmp_path):
    v=dict(process_id=51,expected_process_create_time=123.5,expected_document_path=str(tmp_path/'work.sldprt'),expected_source_sha256='a'*64,expected_feature_native_id=77,expected_operation_native_ids=[501,502],selected_operation_native_id=501,receipt_path=str(tmp_path/'out.json'),qualification_only=True,acknowledge_one_tool_creation=True,message_policy='vendor_default')
    for prefix in ('current_context_receipt','recipe','holder_file','holder_recipe'):
        v[prefix+'_path']=str(tmp_path/(prefix+'.json'));v[prefix+'_sha256']='b'*64
    return v

def test_public_mutation_abi_only():
    tlb=os.environ.get('SWMCP_CAM_TYPELIB_PATH');assert tlb,'Public installed TLB path required'
    r=core.preflight(tlb)
    assert r['factory']['all_resolved']is True and r['assignment']['dispid']==8
    assert r['native_calls']==r['factory']['native_calls']==r['assignment']['native_calls']==0

@pytest.mark.parametrize('patch',[{'selected_operation_native_id':502},{'selected_operation_native_id':True},{'expected_operation_native_ids':[501.,502]},{'expected_operation_native_ids':[501,501]},{'acknowledge_one_tool_creation':False}])
def test_schema_rejects_wrong_mutation_scope(tmp_path,patch):
    v=inputs(tmp_path);v.update(patch);v['addin_clsid']='{00000000-0000-0000-0000-000000000000}'
    with pytest.raises(ValueError):model()(**v)

def test_schema_accepts_generic_ids_and_forbids_extra(tmp_path):
    v=inputs(tmp_path);v['addin_clsid']='{00000000-0000-0000-0000-000000000000}'
    assert model()(**v).selected_operation_native_id==501
    with pytest.raises(ValueError):model()(**v,GTP=True)

def test_factory_methods_are_reused_and_no_app_constructor(tmp_path):
    for name in ('create','created_classification','field','property','candidate'):
        assert getattr(core.Backend,name)is getattr(core.factory.NativeBackend,name)
    for name in ('attach_holder','batch','catalogue'):
        assert getattr(core.Backend,name)is getattr(core.prior.NativeBackend,name)
    class NoApplication:
        def __getattr__(self,name):raise AssertionError(name)
    data={'bundle':{'context':{'pins':[]}}}
    b=core.Backend(NoApplication(),'clsid','tlb',inputs(tmp_path),data,{},lambda:None,lambda:None,{'generated_pin':{}})
    assert b.new_id is None and b.session is None

def test_actual_assignment_binds_selected_and_new_ids_before_dispatch(tmp_path,monkeypatch):
    class Obj:
        def __init__(self,id):self.id=id
    op,feature,tool,doc=Obj(501),Obj(77),Obj(999),Obj(1)
    calls=[];pending=[]
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def typed(self,obj,name):calls.append(('typed',name));return obj
        def read(self,obj,name,*args):
            calls.append(('read',name))
            if name=='GetCWObjectFromID':assert args==(3,501);return op,True
            if name=='GetCWObjectID':return args[0].id,True
            if name=='OpernType':return 0
            if name in ('Suppressed','GetIsToolpathGenerated'):return False
            if name=='IGetAllFeatures':return [feature]
            if name=='ToolType':return 1
            if name=='CutDiameter':return 8.
            if name=='Protrusion':return 25.
            if name=='QueryInterface':return tool
            raise AssertionError(name)
        def dispatch_once(self,invoke,*,persist_pending):persist_pending();return invoke()
    b=object.__new__(core.Backend);b.args=inputs(tmp_path);b.doc=doc;b.new_tool=tool;b.new_id=999;b.data={'proposed':{'CutDiameter':8.,'Protrusion':25.}};b.guard=lambda:Guard()
    monkeypatch.setattr(core,'_items',lambda value,*a:value)
    def native(obj,name,*args):
        assert pending==[True] and obj is op and name=='SetTool' and args==(tool,)
        calls.append(('dispatch',name));return 0
    monkeypatch.setattr(core,'_member',native)
    assert b.assign_selected(lambda:pending.append(True))==0
    assert calls[-1]==('dispatch','SetTool')
    assert ('typed','ICWMillOperation')in calls
