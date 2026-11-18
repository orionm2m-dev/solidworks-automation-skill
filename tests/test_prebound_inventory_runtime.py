"""Static extraction and full inventory parity; synthetic native graph only."""
from pathlib import Path
from copy import deepcopy
import ast,hashlib,json,os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
RT=Path(os.environ['SWMCP_RUNTIME_ROOT']);sys.path.insert(0,str(RT))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_prebound_inventory as candidate
parent=candidate.parent

class Node:
    def __init__(self,role,native_id=0,rows=None,interface=''):
        self.role,self.native_id,self.rows,self.interface=role,native_id,rows,interface

class Graph:
    def __init__(self,generated=False,change=None):
        self.app=Node('app');self.doc=Node('doc');self.machine=Node('machine')
        self.setup=Node('feature_setup',201);self.feature=Node('feature',202)
        self.opsetup=Node('operation_setup',301);self.ops=[Node('operation',401),Node('operation',402)]
        self.tools=[Node('tool',501),Node('tool',502)];self.generated=generated;self.change=change
        self.trace=[];self.calls=0
        if change=='cross_kind_id':self.tools[0].native_id=202
        if change=='duplicate_operation':self.ops[1].native_id=401
    def typed(self,obj,name):
        self.trace.append(('qi',obj.role,name))
        return Node(obj.role,obj.native_id,obj.rows,name)
    def read(self,obj,name,*args):
        self.calls+=1;self.trace.append(('read',obj.role,name,tuple(x.native_id if isinstance(x,Node)else x for x in args)))
        if self.change=='getter_failure' and name=='GetIsToolpathGenerated':raise RuntimeError('injected')
        i=0 if obj.native_id in(401,501)else 1
        if name=='IGetActiveDoc':return self.doc
        if name=='IGetMachine':return self.machine
        if name=='GetDocType':return 3 if self.change=='wrong_document'else 1
        if name=='GetActiveConfigurationName':return 'configuration'
        if name=='GetActiveConfiguration':return Node('configuration')
        if name=='SWConfigurationName':return 'Default'
        if name=='ConfigurationName':return 'other'if self.change=='wrong_configuration'else 'configuration'
        if name=='MachType':return 3 if self.change=='wrong_machine'else 1
        if name=='IGetEnumSetups':return Node('collection',rows=[self.setup])
        if name=='IGetEnumFeatures':return Node('collection',rows=[self.feature])
        if name=='IGetEnumOpSetups':return Node('collection',rows=[self.opsetup])
        if name=='IGetEnumOperations':return Node('collection',rows=self.ops)
        if name=='Count':return True if self.change=='bool_count'else len(obj.rows)
        if name=='Item':return obj.rows[args[0]]
        if name=='GetCWObjectID':return args[0].native_id,True
        if name=='Axis':return [0,0,-1]
        if name=='GetReferencePosition':return [0,0,0]
        if name=='Suppressed':return False
        if name=='FeatureName':return 'Pocket'
        if name in('VolumeType','SubType'):return 2
        if name=='OpernType':return i if obj.interface=='ICWMillOperation'else 0
        if name=='GetIsToolpathGenerated':return bool(self.generated and i==0)
        if name=='IGetAllFeatures':return Node('collection',rows=[self.feature]* (2 if self.change=='duplicate_links'else 1))
        if name=='IGetEnumToolpaths':return Node('collection',rows=[Node('path')] if self.generated and i==0 else [])
        if name=='RecordCount':return True if self.change=='bool_record_count'else 17
        if name=='IGetTool':return self.tools[i]
        if name=='IsMillTool':return True
        if name=='ToolType':return 1
        if name=='CutDiameter':return 8.0 if i==0 else 20.0
        if name=='Protrusion':return 25.0 if i==0 else 60.0
        raise AssertionError((obj.role,name))

def run(graph,prebound):
    diagnostic={};updates=[]
    if prebound:result=candidate.capture_bound_inventory(graph.doc,graph.machine,graph,diagnostic,lambda d:updates.append(deepcopy(d)))
    else:result=parent.capture_import_inventory(graph.app,None,graph,diagnostic,lambda d:updates.append(deepcopy(d)))
    return result,diagnostic,updates

def test_parent_static_body_identical_after_only_three_bootstrap_assignments():
    source=Path(parent.__file__)
    assert hashlib.sha256(source.read_bytes()).hexdigest()=='8f6b538720154be00497bef5ea489f80c7e2a31f5f900750512d775fb69efaab'
    old=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef)and n.name=='capture_import_inventory')
    new=next(n for n in ast.parse(Path(candidate.__file__).read_text()).body if isinstance(n,ast.FunctionDef)and n.name=='capture_bound_inventory')
    removed=[n for n in old.body if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id in('active','doc','machine')for t in n.targets)]
    assert len(removed)==3
    old.body=[n for n in old.body if n not in removed]
    assert ast.dump(ast.Module(body=old.body,type_ignores=[]))==ast.dump(ast.Module(body=new.body,type_ignores=[]))
    assert [x.arg for x in new.args.args]==['doc','machine','guard','diagnostic','progress']

@pytest.mark.parametrize('generated',[False,True])
def test_full_payload_trace_and_progress_parity(generated):
    a=Graph(generated);b=Graph(generated)
    old,od,ou=run(a,False);new,nd,nu=run(b,True)
    assert new==old and new['capture_complete'] is True
    excluded={('qi','doc','ICWDoc3'),('qi','doc','ICWPartDoc'),('qi','machine','ICWMachine'),('read','app','IGetActiveDoc',()),('read','doc','IGetMachine',())}
    assert [r for r in a.trace if r not in excluded]==b.trace
    assert od['native_read_count']==nd['native_read_count']+2
    assert len(ou)==len(nu)
    for x,y in zip(ou,nu):
        x['native_read_count']-=2;assert x==y
    assert not any(r[0]=='read'and r[2]in('IGetActiveDoc','IGetMachine')for r in b.trace)

@pytest.mark.parametrize('change',['cross_kind_id','duplicate_operation','wrong_document','wrong_configuration','wrong_machine','bool_count','bool_record_count','duplicate_links','getter_failure'])
def test_negative_observation_stops_with_same_parent_error(change):
    errors=[]
    for prebound in(False,True):
        g=Graph(True,change)
        with pytest.raises((ValueError,RuntimeError))as e:run(g,prebound)
        errors.append((type(e.value),str(e.value)))
    assert errors[0]==errors[1]

def test_getter_failure_is_not_retried():
    g=Graph(True,'getter_failure')
    with pytest.raises(RuntimeError):run(g,True)
    assert sum(r[0]=='read'and r[2]=='GetIsToolpathGenerated'for r in g.trace)==1
