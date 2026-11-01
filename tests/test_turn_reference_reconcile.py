import importlib.util,os,sys
from pathlib import Path
from copy import deepcopy
import pytest
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).parents[1])))
sys.path.insert(0,str(ROOT))
P=Path(__file__).parents[1]/'scripts/sw_cam_turn_reference_reconcile.py'
spec=importlib.util.spec_from_file_location('reconcile_under_test',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class NativeError(Exception):
    def __init__(self,hresult):self.hresult=hresult


def read_case(ident=31,error=None,null=False):
    op,doc,tool=object(),object(),object();calls=[];records=[]
    def read(obj,name,*args):
        calls.append(name)
        if name=='IGetTool':
            assert obj is op
            if error is not None:raise NativeError(error)
            return None if null else tool
        if name=='GetCWObjectID':assert obj is doc and args==(tool,);return ident,True
        if name=='ToolType':return 15
        if name=='GetToolInfoString':return 'observed'
        raise AssertionError(name)
    result=m.read_reference(op,doc,31,read=read,typed=lambda obj,name:obj,publish=lambda value:records.append(deepcopy(value)))
    return result,calls,records

@pytest.mark.parametrize('ident,outcome',[(31,'desired_tool_reference_observed'),(32,'different_tool_reference_observed')])
def test_exact_native_id_observation(ident,outcome):
    r,calls,records=read_case(ident)
    assert r['outcome']==outcome and r['tool_native_id']==ident and r['binding_determined']
    assert calls.count('IGetTool')==1 and len(calls)==4
    assert records[0]['getter_attempted'] and not records[0]['getter_returned']


def test_null_tool_is_only_claimed_after_actual_null():
    r,calls,_=read_case(null=True)
    assert r['outcome']=='null_tool_reference_observed' and r['present'] is False
    assert calls==['IGetTool']


def test_known_unavailable_is_not_null_or_absent():
    r,calls,records=read_case(error=m.KNOWN_UNAVAILABLE)
    assert r['outcome']=='tool_reference_unavailable' and not r['binding_determined']
    assert 'present' not in r and not r['getter_returned']
    assert r['issue']['hresult']==m.KNOWN_UNAVAILABLE and calls==['IGetTool'] and records[-1]==r

@pytest.mark.parametrize('error',[-2147417851,-2147467262,-1])
def test_other_fault_stops_instead_of_more_tool_probes(error):
    with pytest.raises(NativeError):read_case(error=error)


def failed():
    p={'assignments':[dict(operation_native_id=10,operation_type=1,feature_native_id=6,tool_native_id=31),dict(operation_native_id=11,operation_type=2,feature_native_id=6,tool_native_id=32)]}
    return dict(scope=m.repair.SCOPE,status='uncertain',phase='finished',mutation_attempted=True,readback_verified=False,issue={'type':'COMError','hresult':-2147417851},model_saved=False,GTP_attempted=False,GOP_attempted=False,tool_geometry_changed=False,operation_inserted=False,automatic_retry=False,automatic_replay=False,persistence_qualified=False,messages={'subscribed':True,'disconnected':True,'active':False,'event_count':0},request=p,actions={'SetTool_10':dict(attempted=True,pending=True,returned=False,readback_verified=False)})


def test_only_attempted_first_operation_selected():
    f=failed();assert m.pending_assignment(f)==f['request']['assignments'][0]

@pytest.mark.parametrize('change',[lambda f:f.update(status='repaired_ram_no_save'),lambda f:f.update(model_saved=True),lambda f:f['actions']['SetTool_10'].update(returned=True),lambda f:f['actions'].update(SetTool_11=dict(attempted=True)),lambda f:f['issue'].update(hresult=-1),lambda f:f['messages'].update(active=True)])
def test_reconciliation_requires_exact_failed_attempt(change):
    f=failed();change(f)
    with pytest.raises(ValueError):m.pending_assignment(f)


class Fake:
    def __init__(self,reference,fail=None):self.reference=reference;self.fail=fail;self.calls=[]
    def step(self,n):
        self.calls.append(n)
        if self.fail==n:raise ValueError(n)
    def start(self):self.step('start')
    def capture(self,n):
        self.step(n);v=deepcopy(self.reference);v['document']['needs_save']=True
        if self.fail=='drift_'+n:v['inventory']['count']=12
        return v
    def observe_reference(self,a):self.step('one_reference');return {'outcome':'tool_reference_unavailable','binding_determined':False}
    def finish(self):self.step('finish')
    def close(self):self.step('close')


def run(fail=None):
    ref={'document':{'needs_save':False},'saved_file_sha256':'a'*64,'inventory':{'count':11}}
    plan={'reference':ref,'assignment':{'operation_native_id':10}};r={'phase':'prepared','mutation_attempted':False}
    b=Fake(ref,fail);m.run_backend(b,plan,r,lambda:None);return r,b


def test_changed_dirty_is_observed_without_write():
    r,b=run();assert r['status']=='observed' and r['protected_route_unchanged']
    assert r['before']['document']['needs_save'] and r['before']==r['after']
    assert not r['mutation_attempted'] and b.calls.count('one_reference')==1

@pytest.mark.parametrize('fail',['start','before','drift_before','one_reference','after','drift_after','finish','close'])
def test_read_failure_stops_and_closes(fail):
    r,b=run(fail);assert r['status']=='error' and not r['readback_verified']
    assert b.calls[-1]=='close' and b.calls.count('one_reference')<=1
    if fail in ('start','before','drift_before'):assert 'one_reference' not in b.calls
    assert not {'assign','Save','GTP','InsertOperation'} & set(b.calls)
