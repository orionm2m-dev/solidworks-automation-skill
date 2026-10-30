
"""Persist partial native observations and bound grouped prior-tool reads."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from test_taper_candidate_contract import m


class Batch:
    def __init__(self,env,limit,retained):
        self.env,self.limit,self.retained=env,limit,retained;self.calls=0
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def use(self,n=1):
        self.calls+=n
        if self.calls>self.limit:raise ValueError('budget exhausted')
    def typed(self,v,name):self.use();return v
    def read(self,obj,name,*args):
        self.use()
        if name=='ActiveDoc':return 'part'
        if name=='GetAllTools':return self.env.tools
        if name=='IGetMillToolHolder':return ('holder',obj['native_id'])
        if name=='profile_cost':self.use(args[0]);return None
        raise AssertionError(name)
    def require_complete(self):assert self.calls<=self.limit
    def summary(self):return dict(getter_calls=self.calls,query_interface_calls=0,max_native_calls=self.limit)
class Guard:
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,*args):return 'part'


@pytest.fixture
def environment(monkeypatch):
    env=SimpleNamespace(tools=[],batches=[],profile_cost=500,fail_id=None,persisted=[])
    units=dict(metric_document_scope_observed=True)
    route=dict(state=dict(operations=[],operation_counts=[],operation_setups=[]),settings={},units=units,binding={})
    b=object.__new__(m.NativeBackend)
    b.report={};b.new_id=None;b.old_holders={};b.loaded={'finish_payload':{'unit_record':units}}
    b.ctx=SimpleNamespace(guard=lambda:Guard(),app='app');b.sw='sw';b.crib='crib';b.native={'doc':'doc'}
    b.read_narrow=lambda label:deepcopy(route)
    b.persist=lambda:env.persisted.append(deepcopy(b.report))
    def batch(*extra,max_native_calls=m.PROFILE_BATCH_CALLS):
        value=Batch(env,max_native_calls,extra);env.batches.append(value);return value
    b.batch=batch
    monkeypatch.setattr(m,'read_document_cam_unit_scope',lambda *args,**kw:deepcopy(units))
    monkeypatch.setattr(m,'capture_local_tools',lambda *args:deepcopy(env.tools))
    monkeypatch.setattr(m,'_items',lambda values,*args:values)
    monkeypatch.setattr(m,'_object_id',lambda doc,tool,read:tool['native_id'])
    def full(tool,*,generic,read,typed,diagnostic):
        diagnostic['state']={'partial_id':tool['native_id']}
        read(tool,'profile_cost',env.profile_cost)
        if tool['native_id']==env.fail_id:raise ValueError('Injected decoder failure')
        diagnostic['capture_complete']=True
        return {'tool_native_id':tool['native_id'],'observed':True}
    monkeypatch.setattr(m,'read_full_mill_tool',full)
    env.backend=b
    return env


def rows(n):
    return [dict(native_id=i+1,tool_type_raw=1,CutDiameter=2.,Protrusion=20.,StnNo=float(i+1)) for i in range(n)]


def test_seventeen_tools_use_five_bounded_profile_batches(environment):
    e=environment;e.tools=rows(17)
    result=e.backend.snapshot('initial')
    assert len(result['protected_tools'])==17
    record=e.backend.report['protected_tool_observations'][0]
    assert record['catalogue']==e.tools and record['catalogue_complete'] is True
    assert record['budget']==m.profile_read_budget(17)
    assert len(record['batches'])==5 and all(v['max_native_calls']==5000 for v in record['batches'])
    assert [len(v.retained) for v in e.batches[2:]]==[4,4,4,4,1]
    assert len(e.batches)==7 and len(record['tool_reads'])==17
    assert all(v['read_complete'] is True for v in record['tool_reads'])
    first_full=next(v for v in e.persisted if v.get('protected_tool_observations',[{}])[0].get('tool_reads'))
    assert first_full['protected_tool_observations'][0]['catalogue_complete'] is True


def test_decoder_failure_persists_complete_catalogue_and_partial_current_tool(environment):
    e=environment;e.tools=rows(5);e.fail_id=3
    with pytest.raises(ValueError,match='decoder'):e.backend.snapshot('initial')
    record=e.persisted[-1]['protected_tool_observations'][0]
    assert record['catalogue']==e.tools
    assert list(record['partial_protected_tools'])==['1','2']
    assert record['tool_reads'][-1]['native_id']==3
    assert record['tool_reads'][-1]['tool_type_raw']==1
    assert record['tool_reads'][-1]['diagnostic']['state']=={'partial_id':3}
    assert record['tool_reads'][-1]['read_complete'] is False
    assert len(record['batches'])==1


def test_exhausted_chunk_budget_stops_without_partial_acceptance(environment):
    e=environment;e.tools=rows(17);e.profile_cost=2600
    with pytest.raises(ValueError,match='budget'):e.backend.snapshot('initial')
    record=e.persisted[-1]['protected_tool_observations'][0]
    assert record['catalogue']==e.tools and len(record['partial_protected_tools'])==1
    assert record['budget']['limit_is_stop_not_partial_acceptance'] is True
    assert len(e.batches)==3


@pytest.mark.parametrize('n,batches',[(0,0),(1,1),(4,1),(5,2),(17,5),(128,32)])
def test_explicit_count_derived_budget(n,batches):
    b=m.profile_read_budget(n)
    assert b['profile_batches']==batches and b['max_total_native_calls']==batches*5000+3000
    assert b['per_batch_limit']<=6000


@pytest.mark.parametrize('n',[True,-1,129,1.5])
def test_count_budget_rejects_unknown_or_unbounded_input(n):
    with pytest.raises(ValueError):m.profile_read_budget(n)
