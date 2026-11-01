from copy import deepcopy
from pathlib import Path
import ast
import json
from types import SimpleNamespace
import pytest

from scripts import sw_cam_guide_group_reader as r

MODULE = Path(r.__file__).resolve()
REPO = MODULE.parents[1]
FIXTURE = Path(__file__).resolve().parent / 'fixtures/guide_group_R122.json'

@pytest.fixture
def loaded():
    return {'state': json.loads(FIXTURE.read_text(encoding='utf-8'))}

class Node:
    def __init__(self, oid, **fields): self.oid, self.fields = oid, fields

class Graph:
    def __init__(self, loaded):
        self.nodes = {}; self.calls = []; self.state = deepcopy(loaded['state'])
        for row in self.state['features']:
            h=row['geometry']; self.nodes[h['native_id']] = Node(h['native_id'],
                VolumeType=h['volume_type'], SubType=h['subtype_raw'], Shape=h['shape_raw'],
                Suppressed=h['suppressed'], FeatureName=h['name'], Axis=h['axis_native'],
                Depth=h['depth_native'], GetBoundParams=h['bounds_native'], GetStartPosition=h['start_native'],
                GetOwner=Node(row['setup_native_id']))
        self.setups=[]
        for setup in self.state['operation_setups']:
            ops=[]
            for row in self.state['operations']:
                if row['setup_native_id'] != setup['native_id']: continue
                tool=row['assigned_tool']
                node=Node(row['native_id'], base_type=row['base_operation_type'], mill_type=row['mill_operation_type'],
                    Suppressed=row['suppressed'], GetIsToolpathGenerated=row['toolpath_generated'],
                    IGetAllFeatures=[self.nodes[fid] for fid in row['linked_feature_ids']],
                    IGetEnumToolpaths=[Node(10000+i,RecordCount=count) for i,count in enumerate(row['toolpath_record_counts'])],
                    IGetTool=Node(tool['native_id'], IsMillTool=tool['is_mill_tool'], ToolType=tool['tool_type_raw'],
                        CutDiameter=tool['cut_diameter_native'], Protrusion=tool['protrusion_native']))
                self.nodes[node.oid]=node;ops.append(node)
            self.setups.append(Node(setup['native_id'], IGetEnumOperations=ops))
        self.machine=Node(0,MachType=1,IGetEnumOpSetups=self.setups)
        self.doc=Node(-1,GetDocType=1,IGetMachine=self.machine)
    def typed(self,obj,interface): return (obj,interface)
    def read(self,obj,name,*args):
        interface=''
        if isinstance(obj,tuple):obj,interface=obj
        self.calls.append(name)
        if name=='Count':return len(obj)
        if name=='Item':return obj[args[0]]
        if name=='GetCWObjectID':
            raw=args[0][0] if isinstance(args[0],tuple) else args[0]
            return (raw.oid,True)
        if name=='GetCWObjectFromID':return (self.nodes[args[1]],True)
        if name=='OpernType':return obj.fields['mill_type' if interface=='ICWMillOperation' else 'base_type']
        return obj.fields[name]


def test_saved_real_r122_baseline(loaded):
    graph=Graph(loaded)
    actual,handles=r.read_binding(graph.doc,loaded,read=graph.read,typed=graph.typed)
    assert actual==r.expected(loaded)
    assert tuple(v['native_id'] for v in actual['operations'])==r.ORDER
    assert set(handles)==set(r.ORDER)|{'feature79','feature82','feature83'}
    assert len(graph.calls)<400

@pytest.mark.parametrize('change',[ 'reorder','counts','tool','bool','guide_header','reference_header','duplicate','setup','new_guide_operation'])
def test_read_binding_rejects_drift(loaded,change):
    graph=Graph(loaded)
    if change=='reorder':graph.setups[0].fields['IGetEnumOperations'].reverse()
    elif change=='counts':graph.nodes[320].fields['IGetEnumToolpaths'][0].fields['RecordCount']+=1
    elif change=='tool':graph.nodes[320].fields['IGetTool'].oid=999
    elif change=='bool':graph.nodes[320].fields['GetIsToolpathGenerated']=1
    elif change=='guide_header':graph.nodes[82].fields['Depth']=2.0
    elif change=='reference_header':graph.nodes[79].fields['Depth']=2.0
    elif change=='duplicate':graph.nodes[320].oid=144
    elif change=='setup':graph.setups[1].oid=96
    else:graph.nodes[320].fields['IGetAllFeatures']=[graph.nodes[82]]
    with pytest.raises(ValueError):r.read_binding(graph.doc,loaded,read=graph.read,typed=graph.typed)

@pytest.mark.parametrize('bad',[True,0,-1,1.5,'1'])
def test_bad_catalogue_ids(bad):
    def read(obj,name,*args):return ['default'] if name=='IGetAllDefaultOperations' else bad
    with pytest.raises(ValueError):r.read_catalogues(object(),read=read,typed=lambda o,n:o)

def test_catalogue_both_operation_types_no_selection():
    calls=[]
    def read(obj,name,*args):
        calls.append((name,args))
        return ['rough' if args[0]==0 else 'finish'] if name=='IGetAllDefaultOperations' else 102+args[0]
    rows=r.read_catalogues(object(),read=read,typed=lambda o,n:o)
    assert [v['operation_type'] for v in rows]==[0,1]
    assert [v['entries'][0]['default_operation_id'] for v in rows]==[102,103]
    assert all(v['selection_performed'] is False for v in rows)
    assert len(calls)==4

@pytest.mark.parametrize('names',[[],['a']*2,['x']*33,['\0'],['x'*1001]])
def test_catalogue_bounds(names):
    with pytest.raises(ValueError):r.read_catalogues(object(),read=lambda *a:names,typed=lambda o,n:o)

@pytest.mark.parametrize('name',['SetStartPosition','InsertOperation','GenerateToolpath','Save3','IGetDefaultOperationParameters'])
def test_group_batch_rejects_mutation_and_invented_getters(name):
    batch=r.GroupReadBatch.__new__(r.GroupReadBatch);batch._known_objects=set()
    with pytest.raises(ValueError):batch.read(object(),name)
    assert batch._invalid is True

def test_group_batch_dispatch_disabled():
    batch=r.GroupReadBatch.__new__(r.GroupReadBatch)
    with pytest.raises(ValueError):batch.dispatch_once(lambda:None,persist_pending=lambda:None)

def test_missing_defaults_not_reference_claim():
    gap=r.missing_defaults()
    assert gap['getter_available'] is gap['observed'] is gap['native_call_attempted'] is False
    assert 'names and IDs only' in gap['reason']

def request():
    directory=str(MODULE.parent)
    return dict(action='read_shallow_guide_group',params=dict(process_id=47168,
        expected_document_path=directory+'/part.SLDPRT',expected_source_sha256='a'*64,
        expected_configuration='Default',addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}',
        checkpoint_receipt_path=directory+'/saved.json',checkpoint_receipt_sha256='b'*64,
        module_sha256=r._file_hash(MODULE),receipt_path=directory+'/new.json',progress_path=directory+'/progress.json'))

@pytest.mark.parametrize('field,value',[('process_id',True),('process_id',0),('expected_configuration',''),
    ('expected_configuration','Default\0'),('module_sha256','a'*64),('expected_source_sha256','a'),
    ('expected_document_path','relative'),('addin_clsid','x')])
def test_request_rejects_wrong_identity(field,value):
    value_request=request();value_request['params'][field]=value
    with pytest.raises(ValueError):r.validate_request(value_request)

def test_request_no_write_flags_or_extra_features():
    value=request();r.validate_request(value);value['params']['feature_native_ids']=[80,81]
    with pytest.raises(ValueError):r.validate_request(value)

@pytest.mark.parametrize('stage',['start','observe','finish','close'])
def test_lifecycle_failure_never_success(stage):
    report={'phase':'test'};calls=[]
    class Backend:
        ctx=SimpleNamespace(identity=lambda:dict(path='part',needs_save=False))
        def action(self,name):
            calls.append(name)
            if name==stage:raise ValueError('guard changed')
        def start(self):self.action('start')
        def observe(self):self.action('observe')
        def finish(self):self.action('finish')
        def close(self):self.action('close')
    out=r.run_backend(Backend(),report,lambda:None)
    assert out['readback_verified'] is False and out['status']=='error'
    assert calls[-1]=='close'

def test_configuration_guard_without_com():
    backend=r.NativeBackend.__new__(r.NativeBackend)
    backend.boundary=lambda:None;backend.sw=object();backend.args={'expected_configuration':'Default'}
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,obj,name):return 'Other' if name=='Name' else object()
    backend.ctx=SimpleNamespace(guard=lambda:Guard())
    with pytest.raises(ValueError,match='configuration'):backend.configuration()

def test_catalogue_abi_source_contract_without_com_import():
    import ast
    source=Path(r.start.common.__file__).parents[1]/'.venv/Lib/site-packages/comtypes/gen/_FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    methods=next(n.value.elts for n in tree.body if isinstance(n,ast.Assign)
        and any(ast.unparse(t)=='ICWMillFeature._methods_' for t in n.targets))
    rows={v.args[2].value:ast.unparse(v) for v in methods if isinstance(v.args[2],ast.Constant)}
    assert 'dispid(42)' in rows['IGetAllDefaultOperations'] and 'POINTER(VARIANT)' in rows['IGetAllDefaultOperations']
    assert 'dispid(43)' in rows['GetTdbIdForDefaultOperation'] and 'BSTR' in rows['GetTdbIdForDefaultOperation']
    assert "['out', 'retval'], POINTER(c_int)" in rows['GetTdbIdForDefaultOperation']

@pytest.fixture
def snippet(monkeypatch):
    from enum import Enum
    from pydantic import BaseModel,ConfigDict,Field,model_validator
    class Format(str,Enum):JSON='json'
    class FakeMcp:
        def tool(self,**kwargs):return lambda f:f
    env=dict(BaseInput=BaseModel, ConfigDict=ConfigDict, Field=Field, model_validator=model_validator,
        ResponseFormat=Format, mcp=FakeMcp(), _selected_process_id=47168)
    server = REPO / 'mcp-server/server.py'
    tree = ast.parse(server.read_text(encoding='utf-8-sig'))
    wanted = {'SolidWorksCamShallowGuideGroupInput', 'solidworks_cam_read_shallow_guide_group'}
    nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in wanted]
    assert len(nodes) == 2, 'Installed MCP group model/tool pair required'
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(server), 'exec'), env)
    return env

def test_mcp_one_group_dispatch_with_desktop_guard(snippet,monkeypatch):
    seen=[]
    def dispatch(req):seen.append(req);return {'status':'fake-only'}
    def run(op,fmt,**kwargs):
        assert kwargs==dict(load_automation=False,desktop_guard=True)
        return op()
    monkeypatch.setattr(r,'dispatch_request',dispatch)
    snippet['_run_locked']=run
    params=snippet['SolidWorksCamShallowGuideGroupInput'](**request()['params'])
    assert snippet['solidworks_cam_read_shallow_guide_group'](params)=={'status':'fake-only'}
    assert len(seen)==1 and seen[0]==request()

def test_mcp_refuses_other_selected_pid(snippet):
    snippet['_selected_process_id']=123
    snippet['_run_locked']=lambda op,*a,**k:op()
    params=snippet['SolidWorksCamShallowGuideGroupInput'](**request()['params'])
    with pytest.raises(ValueError,match='owned process'):
        snippet['solidworks_cam_read_shallow_guide_group'](params)

@pytest.mark.parametrize('change',[{'process_id':True},{'process_id':'47168'},{'expected_configuration':None},
    {'save':True},{'feature_native_ids':[82]},{'expected_source_sha256':'no'}])
def test_mcp_strict_schema(snippet,change):
    from pydantic import ValidationError
    with pytest.raises((ValidationError,ValueError)):
        snippet['SolidWorksCamShallowGuideGroupInput'](**dict(request()['params'],**change))

def test_mcp_exact_configuration_whitespace_preserved(snippet):
    params=snippet['SolidWorksCamShallowGuideGroupInput'](**dict(request()['params'],expected_configuration=' Default '))
    assert params.expected_configuration==' Default '


def test_cam_name_can_differ_from_sw_name():
    doc, config = object(), object()
    values={'GetActiveConfigurationName':'CAM setup 1','GetActiveConfiguration':config,
        'ConfigurationName':'CAM setup 1','SWConfigurationName':'По умолчанию'}
    row=r.configuration_binding.config_binding(doc,'По умолчанию',read=lambda o,n:values[n],typed=lambda o,n:o)
    r.configuration_binding.require_binding(row)
    assert row['cam_configuration_name'] != row['sw_configuration_name']
    assert row['associated_sw_configuration_matches'] is True

@pytest.mark.parametrize('wrong',[{'ConfigurationName':'CAM other'},{'SWConfigurationName':'Other SW'}])
def test_config_helper_rejects_actual_mapping_change(wrong):
    values=dict(GetActiveConfigurationName='CAM setup 1',GetActiveConfiguration=object(),
        ConfigurationName='CAM setup 1',SWConfigurationName='Default',**{})
    values.update(wrong)
    row=r.configuration_binding.config_binding(object(),'Default',read=lambda o,n:values[n],typed=lambda o,n:o)
    with pytest.raises(ValueError):r.configuration_binding.require_binding(row)
