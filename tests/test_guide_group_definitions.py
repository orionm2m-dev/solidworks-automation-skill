import json,importlib.util,os,sys
from pathlib import Path
from copy import deepcopy
import pytest
root=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).resolve().parents[1])))
sys.path.insert(0,str(root))
spec=importlib.util.spec_from_file_location('guide_definitions',root/'scripts/sw_cam_guide_group_definitions.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.fixture
def observation():
    ops=[dict(native_id=oid,setup_index=0,setup_native_id=93,operation_index=i,mill_operation_type=1,base_operation_type=9,suppressed=False,toolpath_generated=(i>1),toolpath_record_counts=[40+i] if i>1 else [],linked_feature_ids=[79],assigned_tool=dict(native_id=273,native_read_complete=True)) for i,oid in enumerate(m.ORDER)]
    features={str(fid):dict(native_id=fid,depth_native=.999999,name='guide'+str(fid)) for fid in (82,83)}
    before=dict(operations=ops,operation_setups=[dict(index=0,native_id=93,operation_count=9)],features=features)
    config=dict(sw_configuration_name='Default',cam_sw_configuration_name='Default')
    guides=[dict(feature_native_id=fid,header=features[str(fid)],defaults_catalogue=[dict(operation_type=kind,entries=[dict(name='Named default',default_operation_id=800+fid+kind)]) for kind in (0,1)]) for fid in (82,83)]
    return dict(scope=m.rebind.SCOPE,session_rebind_verified=True,status='observed',phase='finished',readback_verified=True,group_baseline_read_complete=True,read_only=True,mutation_attempted=False,save_attempted=False,GTP_attempted=False,before=before,after=deepcopy(before),configuration_before=config,configuration_after=deepcopy(config),request=dict(expected_configuration='Default'),guides=guides)

@pytest.fixture
def plan(observation):
    choices={key:dict(name='Named default',default_operation_id=800+fid+kind) for key,fid,kind in m.ROWS}
    return m.compile_definition_plan(observation,choices)


def added(before,row,oid,anchor):
    after=deepcopy(before);old=after['operations'][-1]
    after['operations'].append(dict(native_id=oid,setup_index=old['setup_index'],setup_native_id=93,operation_index=old['operation_index']+1,mill_operation_type=row['operation_type'],base_operation_type=9,suppressed=False,toolpath_generated=False,toolpath_record_counts=[],linked_feature_ids=[row['feature_native_id']],assigned_tool=dict(native_id=273,native_read_complete=True)))
    after['operation_setups'][0]['operation_count']+=1;return after

class Backend:
    def __init__(self,plan,journal):self.plan=plan;self.journal=journal;self.current=deepcopy(plan['baseline']);self.calls=[];self.closed=False;self.finished=False;self.fail_on=None;self.bad_nc_on=None;self.mutate_old_on=None
    def start(self):pass
    def capture_binding(self,label,new_id=None):
        if new_id is not None and new_id==self.bad_nc_on:raise RuntimeError('IGetNCParam RPC error')
        if new_id is not None and new_id==self.mutate_old_on:self.current['operations'][0]['toolpath_record_counts']=[999]
        return deepcopy(self.current),None if new_id is None else dict(read_complete=True,spindle_speed_native=1000.,xy_feed_native=500.)
    def insert(self,row,anchor,pending,returned):
        assert anchor==self.current['operations'][-1]['native_id'];pending()
        disk=json.loads(self.journal.marker.read_text());assert disk['native_dispatch_pending'] and disk['actions'][row['key']]['attempted']
        self.calls.append((row['key'],anchor));oid=900+len(self.calls)
        if len(self.calls)==self.fail_on:raise RuntimeError('InsertOperation failure after pending')
        returned(object());self.current=added(self.current,row,oid,anchor);return oid
    def finish(self):self.finished=True
    def close(self):self.closed=True

@pytest.fixture
def run(tmp_path,plan):
    report=dict(plan=plan,source_path=str(tmp_path/'source.SLDPRT'),source_sha256='1'*64,recipe_sha256='2'*64)
    journal=m.DefinitionJournal(report,tmp_path/'receipt.json',tmp_path/'once.json')
    return Backend(plan,journal),journal


def test_four_definitions_use_actual_returned_anchor_ids_and_one_durable_group(run):
    b,j=run;r=m.run_backend(b,j)
    assert r['status']=='observed' and r['readback_verified'] and r['actual_new_ids']==[901,902,903,904]
    assert [anchor for _,anchor in b.calls]==[320,901,902,903]
    assert b.finished and b.closed
    assert not any(r[k] for k in ('save_attempted','GTP_attempted','tool_assignment_attempted','parameter_setter_attempted'))
    assert all(x['readback_verified'] for x in r['actions'].values())


def test_catalogue_ids_are_not_hardcoded(plan):
    assert [v['default_operation_id'] for v in plan['rows']]==[882,883,883,884]

@pytest.mark.parametrize('kind',['unknown_default','bool_id','ambiguous','old_scope','wrong_configuration','old_route_changed','already_planned'])
def test_bad_authority_or_default_is_rejected(observation,kind):
    choices={key:dict(name='Named default',default_operation_id=800+fid+native) for key,fid,native in m.ROWS}
    if kind=='unknown_default':choices['guide82_rough']['default_operation_id']=79
    if kind=='bool_id':choices['guide82_rough']['default_operation_id']=True
    if kind=='ambiguous':observation['guides'][0]['defaults_catalogue'][0]['entries']*=2
    if kind=='old_scope':observation['scope']=m.READ_SCOPE
    if kind=='wrong_configuration':observation['configuration_after']['sw_configuration_name']='Other'
    if kind=='old_route_changed':observation['after']['operations'][0]['toolpath_record_counts']=[9]
    if kind=='already_planned':observation['before']['operations'][0]['linked_feature_ids']=[82];observation['after']=deepcopy(observation['before'])
    with pytest.raises(ValueError):m.compile_definition_plan(observation,choices)

@pytest.mark.parametrize('change',[
 lambda x:x['operations'][0].update(toolpath_record_counts=[99]),lambda x:x['operations'][0].update(assigned_tool={'native_id':999,'native_read_complete':True}),
 lambda x:x['operations'][-1].update(mill_operation_type=True),lambda x:x['operations'][-1].update(linked_feature_ids=[83]),
 lambda x:x['operations'][-1].update(toolpath_generated=True),lambda x:x['operations'][-1].update(toolpath_record_counts=[1]),
 lambda x:x['operations'][-1].update(operation_index=0),lambda x:x['operations'][-1].update(setup_native_id=69),
 lambda x:x['features']['82'].update(depth_native=2),lambda x:x['operation_setups'][0].update(operation_count=11),
 lambda x:x['operations'][-1]['assigned_tool'].update(native_read_complete=False),
])
def test_every_protected_or_invalid_added_delta_rejected(plan,change):
    before=plan['baseline'];row=plan['rows'][0];after=added(before,row,901,320);change(after)
    with pytest.raises(ValueError):m.verify_one_addition(before,after,row,901,320)


def test_finish_same_feature_after_rough_is_allowed(plan):
    current=plan['baseline'];anchor=320
    for i,row in enumerate(plan['rows']):
        oid=901+i;after=added(current,row,oid,anchor);m.verify_one_addition(current,after,row,oid,anchor);current=after;anchor=oid

@pytest.mark.parametrize('stage',[1,2,3,4])
def test_insert_failure_stops_at_attempt_and_never_replays_prefix(run,stage):
    b,j=run;b.fail_on=stage;r=m.run_backend(b,j)
    assert r['status']=='uncertain' and not r['readback_verified'] and len(b.calls)==stage and b.closed and not b.finished
    assert r['actual_new_ids']==list(range(901,900+stage))
    assert r['native_dispatch_pending'] is True
    calls=list(b.calls);marker_before=j.marker.read_bytes();receipt_before=j.receipt.read_bytes()
    with pytest.raises(ValueError):m.run_backend(b,j)
    assert b.calls==calls and j.marker.read_bytes()==marker_before and j.receipt.read_bytes()==receipt_before


def test_own_nc_failure_stops_before_next_insert(run):
    b,j=run;b.bad_nc_on=902;r=m.run_backend(b,j)
    assert r['status']=='uncertain' and len(b.calls)==2 and r['actual_new_ids']==[901,902]
    assert r['actions']['guide82_rough']['readback_verified'] is True and r['actions']['guide82_finish']['returned'] is True
    assert not r['actions']['guide82_finish']['readback_verified']


def test_protected_path_change_stops_before_next_insert(run):
    b,j=run;b.mutate_old_on=901;r=m.run_backend(b,j)
    assert r['status']=='uncertain' and len(b.calls)==1 and not r['readback_verified']


def test_minimal_nc_reader_is_mill_not_turn_and_keeps_raw_values():
    calls=[]
    def typed(obj,interface):calls.append(('QI',interface));return interface
    def read(obj,member):
        calls.append((obj,member));return {'IGetNCParam':'nc','GetSpndlSpeed':548.64,'XYFeed':1016.5010978924302}[member]
    result=m.read_own_nc('operation',read=read,typed=typed)
    assert result['read_complete'] and result['xy_feed_native']==1016.5010978924302 and not result['physical_units_qualified']
    assert calls==[('QI','ICWMillOperation'),('ICWMillOperation','IGetNCParam'),('QI','ICWNCParam'),('QI','ICWNCParam2'),('ICWNCParam','GetSpndlSpeed'),('ICWNCParam2','XYFeed')]


def test_return_without_durable_pending_is_rejected(run):
    b,j=run
    def insert(row,anchor,pending,returned):
        b.calls.append((row['key'],anchor));returned(object());return 901
    b.insert=insert;r=m.run_backend(b,j)
    assert r['status']=='error' and not r['readback_verified'] and len(b.calls)==1 and not j.marker.exists()
    assert r['actions']['guide82_rough']['returned'] is False


@pytest.mark.parametrize('failure',[None,'default','header','anchor'])
def test_native_insert_helper_checks_exact_default_header_anchor_then_pending(plan,monkeypatch,failure):
    from scripts import sw_cam_comtypes
    row=plan['rows'][0];header=plan['baseline']['features']['82'];calls=[]
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,obj,name,*args):
            if name=='GetCWObjectFromID':return ('feature' if args[0]==1 else 'anchor',True)
            if name=='QueryInterface':return 'dispatch_anchor'
            if name=='GetTdbIdForDefaultOperation':return row['default_operation_id']+(1 if failure=='default' else 0)
            raise AssertionError(name)
        def typed(self,obj,name):assert name=='ICWMillFeature';return obj
        def dispatch_once(self,invoke,*,persist_pending):persist_pending();return invoke()
    class Context:
        def guard(self):return Guard()
    monkeypatch.setattr(m,'read_header',lambda *a:(dict(header,depth_native=9) if failure=='header' else header,None))
    monkeypatch.setattr(m,'_object_id',lambda *a:999 if failure=='anchor' else 320)
    monkeypatch.setattr(sw_cam_comtypes,'_is_comtypes_pointer',lambda value:value=='actual_pointer')
    def call(obj,name,*args):calls.append((obj,name,args));return 'actual_pointer'
    monkeypatch.setattr(m,'_member',call)
    pending=lambda:calls.append('pending')
    if failure:
        with pytest.raises(ValueError):m.insert_selected_once(Context(),'doc',row,320,header,pending)
        assert calls==[]
    else:
        assert m.insert_selected_once(Context(),'doc',row,320,header,pending)=='actual_pointer'
        assert calls==['pending',('feature','InsertOperation',(0,row['default_operation_id'],'dispatch_anchor'))]


def test_nc_nonfinite_is_rejected():
    with pytest.raises(ValueError):m.read_own_nc('op',typed=lambda obj,name:obj,read=lambda obj,name: object() if name=='IGetNCParam' else float('nan'))


def test_mcp_model_and_owned_pid_binding(tmp_path):
    from pydantic import BaseModel,ConfigDict,Field,model_validator
    from enum import Enum
    class BaseInput(BaseModel):model_config=ConfigDict(extra='forbid')
    class ResponseFormat(str,Enum):JSON='json'
    class Decorator:
        def tool(self,**kwargs):return lambda f:f
    sys.modules['scripts.sw_cam_guide_group_definitions']=m
    ns=dict(BaseInput=BaseInput,Field=Field,model_validator=model_validator,ResponseFormat=ResponseFormat,mcp=Decorator())
    fixture=Path(__file__).with_name('mcp_guide_definitions_fixture.py');exec(compile(fixture.read_text(),str(fixture),'exec'),ns)
    p=dict(process_id=123,expected_document_path=str(tmp_path/'part.SLDPRT'),expected_source_sha256='1'*64,expected_configuration='Default',addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}',checkpoint_receipt_path=str(tmp_path/'old.json'),checkpoint_receipt_sha256='2'*64,session_rebind_receipt_path=str(tmp_path/'new.json'),session_rebind_receipt_sha256='3'*64,choices={label:dict(name='Default',default_operation_id=79 if kind==0 else 87) for label,fid,kind in m.ROWS},module_sha256=m._file_hash(m.__file__),receipt_path=str(tmp_path/'output.json'),acknowledge_definition_only_group=True)
    cls=ns['SolidWorksShallowGuideDefinitionsInput'];cls(**p)
    for key,value in [('process_id',True),('acknowledge_definition_only_group',False),('choices',{})]:
        with pytest.raises(ValueError):cls(**dict(p,**{key:value}))
    ns.update(_selected_process_id=999,_run_locked=lambda op,*a,**kw:op())
    with pytest.raises(ValueError):ns['solidworks_cam_insert_shallow_guide_definitions'](cls(**p))


def test_native_backend_constructs_real_inherited_group_batch_without_any_native_call(tmp_path):
    from types import SimpleNamespace
    from scripts.sw_cam_guide_group_reader import GroupReadBatch
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'source')
    dependency=tmp_path/'dependency.py';dependency.write_text('pass')
    doc=dict(path=str(source),title=source.name,type=1,needs_save=False)
    def forbidden():raise AssertionError('Constructor must not enter native/guard callbacks')
    class NativeTrap:
        def __getattr__(self,name):raise AssertionError('Native access during constructor: '+name)
    backend=m.NativeBackend.__new__(m.NativeBackend)
    backend.sw=NativeTrap();backend.typelib_path=str(tmp_path/'camworks.tlb')
    backend.args=dict(process_id=123,expected_source_sha256=m._file_hash(source))
    backend.loaded=dict(generated_pin=dict(path=str(dependency),sha256=m._file_hash(dependency)),pins=[dict(path=str(dependency),sha256=m._file_hash(dependency))])
    backend.ctx=SimpleNamespace(identity=lambda:deepcopy(doc),files=forbidden,owned=forbidden)
    backend.events=forbidden;retained=NativeTrap();state=dict(member='',returned=False,read_index=0)
    callback=lambda:None
    batch=backend.make_read_batch(retained,forbidden,state,callback)
    assert type(batch) is GroupReadBatch and batch.progress is callback and batch.progress_state is state
    assert batch.generated_pin==backend.loaded['generated_pin'] and batch._retained==[retained]
    assert not batch._entered and not batch._active and batch._budget==1200
    assert len(batch._rows)==2
