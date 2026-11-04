from copy import deepcopy
import ast
from pathlib import Path
import pytest
from scripts import sw_cam_current_parameter_capture as c
from scripts import sw_cam_mill_current_parameters as p

def collection(rows):return dict(Count=len(rows),Item=lambda i:rows[i])

@pytest.fixture
def env(monkeypatch):
    calls=[];target=dict(_id=70);target['QueryInterface']=lambda cls:target
    tools={249:dict(_id=249,IsMillTool=True,ToolType=1,CutDiameter=8.,Protrusion=25.,Holder=19),252:dict(_id=252,IsMillTool=True,ToolType=1,CutDiameter=12.,Protrusion=50.,Holder=18)}
    ops={};rows=[];cribitems=list(tools.values());machine=dict(IGetToolcrib=dict(GetAllTools=collection(cribitems)))
    doc=dict(IGetMachine=machine,GetCWObjectID=lambda x:(x['_id'],True))
    def read(obj,name,*args):
        calls.append(name);value=obj[name];return value(*args) if callable(value) else value
    def typed(obj,name):
        assert obj is not None;return obj
    for index,(oid,kind,tid,generated) in enumerate([(248,1,249,True),(320,0,249,True),(356,0,252,False),(358,1,252,False)]):
        nc=dict(GetSpndlSpeed=float(1000+oid),XYFeed=float(100+oid),GetCNCComp=0,GetTlpComp=1)
        raw=dict(_id=oid,OpernType=kind,Suppressed=False,GetIsToolpathGenerated=generated,IGetAllFeatures=collection([target]),IGetTool=tools[tid],IGetNCParam=nc)
        ops[oid]=raw;generic,_=c.tool_generic(tools[tid],doc,read,typed)
        rows.append(dict(native_id=oid,setup_index=0,operation_index=index,setup_native_id=94,mill_operation_type=kind,linked_feature_ids=[70],suppressed=False,toolpath_generated=generated,toolpath_record_counts=[10] if generated else [],assigned_tool=generic))
    doc['GetCWObjectFromID']=lambda kind,oid:(ops[oid],True)
    state=dict(capture_complete=True,operations=rows,operation_count=4,operation_counts=[4],operation_setup_count=1,operation_setups=[dict(index=0,native_id=94,operation_count=4)])
    native=dict(doc=doc,machine=machine,selected_feature=target,operations=ops)
    def dimensions(tool,generic,batch):return dict(generic=deepcopy(generic),mill={'D':batch.read(tool,'CutDiameter')},holder={'id':batch.read(tool,'Holder')},dimension_read_complete=True,full_profiles_read=False)
    monkeypatch.setattr(c,'read_tool_dimensions',dimensions);monkeypatch.setattr(p,'read_tool_dimensions',dimensions)
    monkeypatch.setattr(p.pocket,'read_levels',lambda *a,**k:dict(depth=7.6))
    monkeypatch.setattr(p.pocket.rough,'read_rough_entry_parameters',lambda *a,**k:dict(SideAllow=1.))
    monkeypatch.setattr(p.pocket,'read_finish_parameters',lambda *a,**k:dict(SideAllow=1.))
    e=dict(state=state,native=native,tools=tools,ops=ops,rows=rows,calls=calls,cribitems=cribitems,read=read,typed=typed,boundary=lambda:None)
    def run(**extra):
        args=dict(feature_id=70,candidate_tool_native_id=249,expected_candidate_consumer_ids=[248,320],read=e['read'],typed=typed,boundary=e['boundary']);args.update(extra)
        return c.capture_parameter_batch(state,native,rows[-2:],**args)
    e['run']=run;calls.clear();return e

def test_real_own_lookup_crib_and_independent_consumer_nc(env):
    e=env;out=e['run']()
    assert out['read_complete'] and out['candidate_tool']['generic']['native_id']==249
    assert list(out['source_tools'])==['252'] and out['candidate_consumer_ids']==[248,320]
    assert list(out['target_nc'])==['356','358'] and list(out['candidate_consumers'])==['248','320']
    assert out['target_nc']['356']['feeds_compensation']['GetSpndlSpeed']==1356.
    assert out['candidate_consumers']['248']['feeds_compensation']['GetSpndlSpeed']==1248.
    assert not out['candidate_consumers']['248']['tool_defaults_read']
    assert not any(n.startswith(('Set','Generate','Save','Insert')) for n in e['calls'])
    assert e['state']['parameter_capture_complete'] and len(e['state']['operation_parameters'])==2

@pytest.mark.parametrize('ids',[[248],[320,248],[248,320,356],[True,320],None])
def test_usage_drift_or_bad_ids_fail_before_reads(env,ids):
    with pytest.raises(ValueError):env['run'](expected_candidate_consumer_ids=ids)
    assert not env['calls']

@pytest.mark.parametrize('bad',['duplicate_crib','missing_candidate','source_dimensions','consumer_alias','consumer_tool','consumer_flags','nc_bool','nc_nan'])
def test_binding_and_nc_type_fail_closed(env,bad):
    e=env
    if bad=='duplicate_crib':e['native']['machine']['IGetToolcrib']['GetAllTools']=collection([e['tools'][249],e['tools'][249],e['tools'][252]])
    elif bad=='missing_candidate':e['native']['machine']['IGetToolcrib']['GetAllTools']=collection([e['tools'][252]])
    elif bad=='source_dimensions':
        other=deepcopy(e['tools'][252]);other['Holder']=99;e['native']['machine']['IGetToolcrib']['GetAllTools']=collection([e['tools'][249],other])
    elif bad=='consumer_alias':e['native']['doc']['GetCWObjectFromID']=lambda kind,oid:(e['ops'][320] if oid==248 else e['ops'][oid],True)
    elif bad=='consumer_tool':e['ops'][248]['IGetTool']=e['tools'][252]
    elif bad=='consumer_flags':e['ops'][248]['Suppressed']=True
    elif bad=='nc_bool':e['ops'][356]['IGetNCParam']['GetCNCComp']=False
    else:e['ops'][358]['IGetNCParam']['XYFeed']=float('nan')
    with pytest.raises(ValueError):e['run']()
    assert not e['state']['parameter_batch']['read_complete']

def test_event_boundary_retains_last_nc_value_and_no_next_getter(env):
    e=env
    def boundary():
        if e['calls'] and e['calls'][-1]=='XYFeed':raise ValueError('event observed')
    e['boundary']=boundary
    with pytest.raises(ValueError,match='event observed'):e['run']()
    out=e['state']['parameter_batch'];assert not out['read_complete']
    assert out['target_nc']['356']['feeds_compensation']=={'GetSpndlSpeed':1356.,'XYFeed':456.}
    assert not out['target_nc']['356']['read_complete'] and e['calls'][-1]=='XYFeed'

def test_after_assignment_explicit_usage_and_source_tools(env):
    e=env;e['ops'][356]['IGetTool']=e['tools'][249];e['rows'][2]['assigned_tool']=deepcopy(e['rows'][0]['assigned_tool'])
    out=e['run'](expected_candidate_consumer_ids=[248,320,356])
    assert out['candidate_consumer_ids']==[248,320,356] and set(out['source_tools'])=={'249','252'}
    assert out['candidate_consumers']['356']['feeds_compensation']==out['target_nc']['356']['feeds_compensation']



def test_selected_feature_alias_rejected_before_parameter_reads(env):
    env['native']['selected_feature']=dict(_id=71)
    with pytest.raises(ValueError,match='Exact native parameter feature'):env['run']()
    assert 'operation_parameters' not in env['state']


def generated(e):
    e['rows'][2].update(toolpath_generated=True,toolpath_record_counts=[31]);e['ops'][356]['GetIsToolpathGenerated']=True


def test_explicit_generated_count_map_reads_same_complete_parameters(env):
    e=env;generated(e);out=e['run'](generation_observations={356:[31]})
    assert out['read_complete']and e['state']['parameter_capture_complete']
    assert out['target_nc']['356']['feeds_compensation']['GetSpndlSpeed']==1356.
    assert not any(x.startswith(('Set','Save','Generate','Insert'))for x in e['calls'])


def test_default_route_still_rejects_generated_target(env):
    generated(env)
    with pytest.raises(ValueError):env['run']()
    assert not env['calls']


@pytest.mark.parametrize('value',[{356:[30]},{356:[0]},{356:[True]},{356:[31,1]},{356:31},{True:[31]},{999:[31]},[],True,{358:[31]},None])
def test_generated_map_must_match_explicit_complete_row(env,value):
    generated(env)
    with pytest.raises(ValueError):env['run'](generation_observations=value)
    assert not env['calls']


def test_generated_native_flag_repeated_and_rejected_on_mismatch(env):
    generated(env);env['ops'][356]['GetIsToolpathGenerated']=False
    with pytest.raises(ValueError):env['run'](generation_observations={356:[31]})
    assert not env['state'].get('parameter_capture_complete')


def test_frozen_authority_and_default_entry_ast_unchanged():
    import json
    fixture=Path(__file__).resolve().parent/'fixtures/generation_parameter_authority_ast.json'
    old=json.loads(fixture.read_text(encoding='utf-8'))
    current=ast.parse(Path(p.__file__).read_text(encoding='utf-8'))
    new={n.name:ast.dump(n,include_attributes=False)for n in current.body if isinstance(n,ast.FunctionDef)and n.name in old}
    assert old==new
