import importlib.util,os,sys
from copy import deepcopy
from pathlib import Path
import pytest
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(ROOT))
P=Path(__file__).parents[1]/'scripts'/'sw_cam_turn_toolcrib_diagnostic.py'
spec=importlib.util.spec_from_file_location('toolcrib_diagnostic_under_test',P)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Obj:
    def __init__(self,**values):self.values=values


def tool(ident=10,kind=15,turn=1,insert=1,holder_kind=2):
    holder=None if holder_kind is None else Obj(GetHolderType=holder_kind,GetHolderId=7,HolderShape=0,**{x:25.0 for x in m.BORING_FIELDS if x!='HolderShape'})
    turning=Obj(ToolType=turn,InsertType=insert,IGetTurnToolHolder=holder,Thickness=3.97,IncludedAngle=80.,NoseRadius=.2,InscribedCircle=9.525)
    return Obj(native_id=ident,ToolType=kind,GetToolInfoString='sample',turning=turning)


def inspect(tools):
    log=[];rows=[];published=[];crib=Obj(GetAllTools=tools);machine=Obj(IGetToolcrib=crib);doc=Obj()
    def typed(obj,name):
        log.append(('QI',name))
        return obj.values['turning'] if name=='ICWTurnTool' else obj
    def read(obj,name,*args):
        log.append(('get',name))
        if name=='GetCWObjectID':return args[0].values['native_id'],True
        return obj.values[name]
    result=m.read_tools(machine,doc,read=read,typed=typed,items=lambda r,n:r,rows=rows,publish=lambda:published.append(deepcopy(rows)))
    return rows,log,result,published


def test_candidate_reads_boring_dimensions_without_operation_lookup():
    rows,log,(_,ids),published=inspect([tool()])
    assert ids==[10] and rows[0]['candidate'] and rows[0]['complete']
    assert rows[0]['holder_dimensions_native']['BoringBarDiameter']==25.
    assert rows[0]['insert_dimensions_native']['NoseRadius']==.2
    assert all(name!='IGetTool' for _,name in log) and published

@pytest.mark.parametrize('kind,turn,insert,holder_kind,reason',[(1,1,1,2,'not_turn_tool'),(15,2,1,2,'not_insert_holder_no_subtype_probe'),(15,1,1,None,'holder_absent'),(15,1,1,1,'not_diamond_boring_bar'),(15,1,2,2,'not_diamond_boring_bar')])
def test_skips_inapplicable_geometry(kind,turn,insert,holder_kind,reason):
    rows,log,_,_=inspect([tool(kind=kind,turn=turn,insert=insert,holder_kind=holder_kind)])
    assert rows[0]['reason']==reason and rows[0]['candidate'] is False
    assert not any(n in ('BoringBarDiameter','NoseRadius','ICWDrillTool') for _,n in log)


def test_duplicate_tool_id_rejected():
    with pytest.raises(ValueError,match='Duplicate'):inspect([tool(),tool()])


def test_tool_bound():
    with pytest.raises(ValueError,match='exceeds'):inspect([tool(i+1) for i in range(33)])

@pytest.mark.parametrize('value',[True,'15',None])
def test_strict_tool_type(value):
    with pytest.raises(ValueError):inspect([tool(kind=value)])

@pytest.mark.parametrize('value',[float('nan'),float('inf'),True])
def test_invalid_dimension(value):
    t=tool();t.values['turning'].values['NoseRadius']=value
    with pytest.raises(ValueError):inspect([t])


def test_tool_failure_keeps_previous_rows():
    first=tool();bad=tool(11);bad.values['turning'].values['NoseRadius']=float('nan')
    rows=[];machine=Obj(IGetToolcrib=Obj(GetAllTools=[first,bad]));doc=Obj()
    def read(o,n,*a):return (a[0].values['native_id'],True) if n=='GetCWObjectID' else o.values[n]
    with pytest.raises(ValueError):m.read_tools(machine,doc,read=read,typed=lambda o,n:o.values['turning'] if n=='ICWTurnTool' else o,items=lambda v,n:v,rows=rows,publish=lambda:None)
    assert rows[0]['complete'] and rows[1]['complete'] is False and rows[1]['native_id']==11


class Fake:
    def __init__(self,reference,fail=None):self.reference=reference;self.fail=fail;self.calls=[]
    def step(self,n):
        self.calls.append(n)
        if n==self.fail:raise ValueError('injected '+n)
    def start(self):self.step('start')
    def capture(self,n):
        self.step(n);v=deepcopy(self.reference)
        if self.fail==n+'_mismatch':v['extra']=1
        return v
    def tools(self):self.step('tools');return [10]
    def finish(self):self.step('finish')
    def close(self):self.step('close')


def run(fail=None):
    reference={'document':{'needs_save':False},'inventory':{'operation_count':11}}
    b=Fake(reference,fail);r={'phase':'prepared','tools':[],'mutation_attempted':False,'persistence_qualified':False};snapshots=[]
    m.run_backend(b,{'reference':reference},r,lambda:snapshots.append(deepcopy(r)))
    return b,r,snapshots


def test_success_stays_diagnostic():
    b,r,_=run();assert r['status']=='observed' and r['readback_verified']
    assert not r['mutation_attempted'] and not r['persistence_qualified']
    assert b.calls==['start','before','tools','after','finish','close']

@pytest.mark.parametrize('fail',['start','before','tools','after','finish','close','before_mismatch','after_mismatch'])
def test_failure_always_attempts_cleanup(fail):
    b,r,records=run(fail);assert r['status']=='error' and not r['readback_verified']
    assert b.calls[-1]=='close' and records
    if fail in ('start','before','before_mismatch'):assert 'tools' not in b.calls


def test_forbidden_mutators_and_broken_lookup_absent():
    assert not {'IGetTool','SetTool','InsertOperation','GenerateToolpath','SaveActiveDocument','AddNewTurnTool3'} & m.GETTERS
    assert 'ICWDrillTool' not in m.INTERFACES


def test_empty_crib_is_valid_observation():
    rows,_,(_,ids),_=inspect([]);assert rows==[] and ids==[]
