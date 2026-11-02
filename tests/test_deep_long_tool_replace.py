from copy import deepcopy
from pathlib import Path
from types import ModuleType
import ast, importlib.util, inspect, json, os, sys
import pytest
R=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).resolve().parents[1]))).resolve();sys.path.insert(0,str(R))
P=Path(os.environ.get('SW_CAM_DEEP_REPLACEMENT_MODULE',str(Path(__file__).parents[1]/'scripts/sw_cam_deep_long_tool_replace.py')))
spec=importlib.util.spec_from_file_location('replacement_under_test',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.fixture
def loaded():
    f=json.loads((Path(__file__).parent/'fixtures/saved_deep_baseline.json').read_text(encoding='utf-8'))
    tool=deepcopy(f['snapshot']['parameters'][-1]['tool']);tool['generic'].update(native_id=400,protrusion_native=22.)
    for key,value in [('EffCutlength',6.),('OverallLen',40.),('ShoulderLength',7.5),('MillToolShankType',1),('ShoulderDia',2.),('ShankLength',11.2)]:tool['mill'][key]['raw']=value
    shallow=deepcopy(f['targets'])
    for row,oid,fid in zip(shallow,[322,324,326,328],[82,82,83,83]):row.update(operation_native_id=oid,feature_native_id=fid)
    return dict(guide_parameters=dict(document={},configuration={},expected_parameters=f['snapshot'],targets=shallow),deep_targets=f['targets'],configuration_tool=tool['generic'],replacement_tool_dimensions=tool,tool_catalogue_ids=[273,400],generated={'saved_cl':{'label':'prior'}},created_saved_cl={'label':'prior'})


def test_actual_constructor_keeps_bootstrap_module_and_callable_methods():
    b=m.NativeBackend({'guide_parameters':{'document':{}},'deep_targets':[]},{},object(),'metadata-only','metadata-only',{},lambda:None)
    assert isinstance(b.capture,ModuleType) and callable(b.capture.cone._bootstrap) and callable(b.capture_snapshot)
    tree=ast.parse(inspect.getsource(m.run_backend));names={n.func.attr for n in ast.walk(tree)if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and isinstance(n.func.value,ast.Name)and n.func.value.id=='backend'}
    assert 'capture'not in names and all(callable(getattr(b,n))for n in names)
    assert not [k for k,v in vars(b).items()if callable(getattr(type(b),k,None))and not callable(v)]


def test_exact_baseline_contract(loaded):assert m.baseline_contract(loaded)==loaded['guide_parameters']['expected_parameters']

@pytest.mark.parametrize('damage',['ID','feature','oldcount','tool','diameter','length','feed','catalogue'])
def test_rejects_wrong_creation_or_route(loaded,damage):
    b=loaded['guide_parameters']['expected_parameters']
    if damage=='ID':loaded['deep_targets'][0]['operation_native_id']=999
    elif damage=='feature':loaded['deep_targets'][0]['feature_native_id']=81
    elif damage=='oldcount':b['binding']['operations'].pop(0)
    elif damage=='tool':loaded['configuration_tool']['native_id']=273
    elif damage=='diameter':loaded['configuration_tool']['cut_diameter_native']=3.
    elif damage=='length':loaded['replacement_tool_dimensions']['mill']['EffCutlength']['raw']=3.
    elif damage=='feed':b['parameters'][-1]['nc']['feeds_compensation']['XYFeed']=777.
    elif damage=='catalogue':loaded['tool_catalogue_ids'].append(400)
    with pytest.raises(ValueError):m.baseline_contract(loaded)


def test_route_allows_selected_invalidation_but_never_protected_changes(loaded):
    old=loaded['guide_parameters']['expected_parameters']['binding'];new=deepcopy(old)
    row=new['operations'][13];row['assigned_tool']=loaded['configuration_tool'];row['toolpath_generated']=False;row['toolpath_record_counts']=[]
    m.verify_route(old,new,loaded['configuration_tool'],[330])
    new['operations'][4]['toolpath_record_counts']=[1]
    with pytest.raises(ValueError):m.verify_route(old,new,loaded['configuration_tool'],[330])


def test_route_rejects_unclaimed_new_generation(loaded):
    old=loaded['guide_parameters']['expected_parameters']['binding'];new=deepcopy(old);new['operations'][13]['assigned_tool']=loaded['configuration_tool'];new['operations'][13]['toolpath_record_counts']=[12]
    with pytest.raises(ValueError):m.verify_route(old,new,loaded['configuration_tool'],[330])


def test_postassignment_rejects_levels_and_feed_changes(loaded):
    old=loaded['guide_parameters']['expected_parameters']['parameters'][-1];new=deepcopy(old);new['tool']=loaded['replacement_tool_dimensions'];m.verify_restorable(old,new,loaded['replacement_tool_dimensions'])
    new['nc']['feeds_compensation']['XYFeed']=777.
    with pytest.raises(ValueError):m.verify_restorable(old,new,loaded['replacement_tool_dimensions'])


class FakeJournal:
    def __init__(self):self.report={'source_sha256':'a'*64,'request':{'process_id':99},'ownership':{},'tool_creation_pin':{}};self.created=False;self.claimed=False
    def create(self):assert not self.created;self.created=True
    def persist(self):pass
    def entry(self,n):assert n not in self.report['actions'];self.report['actions'][n]={'attempted':False}
    def pending(self,n):
        if n not in self.report['actions']:self.entry(n)
        assert not self.report['actions'][n]['attempted'];self.report['actions'][n]['attempted']=True;self.report['mutation_attempted']=True;self.claimed=True
    def execute(self,n,fn):
        self.entry(n);ret=fn(lambda:self.pending(n));assert type(ret)is int and ret==0;self.report['actions'][n]['returned']=True
    def verified(self,n,value):self.report['actions'][n].update(status='verified',readback_verified=True,observed=deepcopy(value))


class FakeBackend:
    def __init__(self,l,j,damage=None):self.loaded=l;self.j=j;self.report=j.report;self.learned=deepcopy(l['deep_targets']);self.snapshot=deepcopy(l['guide_parameters']['expected_parameters']);self.calls=[];self.damage=damage;self.closed=False
    def start(self):self.calls.append('start')
    def capture_snapshot(self,label,full=False,own=None):
        value=deepcopy(self.snapshot)
        if own is not None:value['parameters']=[r for r in value['parameters']if r['operation_native_id']==own['operation_native_id']]
        return value
    def export(self,label,binding):self.calls.append('CL:'+label);return {'label':label,'binding':deepcopy(binding)}
    def assign(self,t,pending):
        pending();oid=t['operation_native_id'];self.calls.append('SetTool:'+str(oid));next(x for x in self.snapshot['binding']['operations']if x['native_id']==oid)['assigned_tool']=deepcopy(self.loaded['configuration_tool']);own=next(x for x in self.snapshot['parameters']if x['operation_native_id']==oid);own['tool']=deepcopy(self.loaded['replacement_tool_dimensions'])
        if self.damage=='protected':self.snapshot['binding']['operations'][0]['suppressed']=True
        if self.damage=='feed':own['nc']['feeds_compensation']['XYFeed']=777.
        if self.damage in ('nc','nc_unconfirmed'):
            own['nc']['feeds_compensation']['GetCNCComp']=1
            if 'protected_finish' in own:own['protected_finish']['compensation'][1]=1
        return 0
    def refresh_dirty(self):pass
    def read_nc(self,t):return deepcopy(next(x for x in self.snapshot['parameters']if x['operation_native_id']==t['operation_native_id'])['nc']['feeds_compensation'])
    def set_nc(self,t,expected,pending):
        pending();self.calls.append('CNC0:'+str(t['operation_native_id']));row=next(x for x in self.snapshot['parameters']if x['operation_native_id']==t['operation_native_id'])
        if self.damage!='nc_unconfirmed':
            row['nc']['feeds_compensation']['GetCNCComp']=0
            if 'protected_finish' in row:row['protected_finish']['compensation'][1]=0
        return 0
    def generate(self,t,pending):
        pending();
        if self.damage=='gtp_unknown':raise RuntimeError('native completion unknown')
        oid=t['operation_native_id'];self.calls.append('GTP:'+str(oid));row=next(x for x in self.snapshot['binding']['operations']if x['native_id']==oid);row['toolpath_generated']=True;row['toolpath_record_counts']=[100+oid];return 0
    def outcome(self,t):return dict(operation_native_id=t['operation_native_id'],feature_native_id=t['feature_native_id'],record_counts=[100+t['operation_native_id']])
    def boundary(self):pass
    def save(self):self.calls.append('Save');return 0
    def saved_hash(self,stage):self.report['source_transition']={'document':{'path':'fixture.SLDPRT','type':1,'needs_save':False}};return 'b'*64
    def finish(self):self.calls.append('finish')
    def close(self):self.closed=True

@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(m.cl,'_verified',lambda a:{'parse_complete':True});monkeypatch.setattr(m,'verify_protected_cl',lambda a,b:{'protected_ten_complete_streams_verified':True});monkeypatch.setattr(m.cl,'verify_no_new_cutcom',lambda x:{'absent':True});monkeypatch.setattr(m.generation,'status_contract',lambda *a:None)
    def save_stage(report,**kw):
        old=kw['capture']('before');kw['verify'](old);kw['guard']();kw['claim']();assert kw['save']()==0;kw['saved_hash']();kw['verify'](kw['capture']('after'))
    monkeypatch.setattr(m.config.save_core,'run_one_existing_save',save_stage)


def test_four_existing_assignments_four_regenerations_one_save(loaded,engine):
    j=FakeJournal();b=FakeBackend(loaded,j);r=m.run_backend(b,j,loaded)
    assert r['readback_verified']is True and r['status']=='saved_replacement_review_required'
    assert b.calls==['start',*[f'SetTool:{i}'for i in m.IDS],*[f'GTP:{i}'for i in m.IDS],'Save','CL:saved','finish']
    assert not r['operation_creation_attempted']and not r['tool_creation_attempted']and not r['production_qualified'] and b.closed
    assert len(r['saved']['binding']['operations'])==17

@pytest.mark.parametrize('damage',['protected','feed'])
def test_unexpected_settool_effect_stops_before_any_gtp_or_save(loaded,engine,damage):
    j=FakeJournal();b=FakeBackend(loaded,j,damage);r=m.run_backend(b,j,loaded)
    assert r['status']=='uncertain'and not r['readback_verified'] and b.closed
    assert not any(x.startswith('GTP')or x=='Save'for x in b.calls)


def test_partial_attempt_cannot_replay(loaded,engine):
    j=FakeJournal();j.claimed=True;b=FakeBackend(loaded,j)
    with pytest.raises(ValueError):m.run_backend(b,j,loaded)
    assert b.calls==[]


def test_marker_cannot_be_bypassed_by_new_pid_receipt_or_tool(loaded,monkeypatch,tmp_path):
    monkeypatch.setattr(m.common,'local_evidence_root',lambda:tmp_path)
    p={'expected_document_path':str(tmp_path/'part.SLDPRT'),'expected_source_sha256':'a'*64,'process_id':99,'receipt_path':'first.json','tool_native_id':400}
    first=m.marker_path(p);first.write_text('pending')
    second=m.marker_path(dict(p,process_id=101,receipt_path='other.json',tool_native_id=999))
    assert first==second and second.exists()


def test_complete_protected_stream_change_or_reorder_rejected(monkeypatch):
    rows=[{'operation_native_id':i,'toolpath_record_counts':[i+1]}for i in [*m.cl.OLD,*m.IDS]]
    a={'expected_generated_operations':deepcopy(rows),'parsed':{'sig':list(range(14))}}
    b=deepcopy(a)
    monkeypatch.setattr(m.cl,'_verified',lambda v:v['parsed']);monkeypatch.setattr(m.cl,'_shared',lambda *a:None);monkeypatch.setattr(m.cl.review,'block_signature',lambda v,i:v['sig'][i])
    b['parsed']['sig'][10:]=[90,91,92,93]
    assert m.verify_protected_cl(a,b)['protected_ten_complete_streams_verified']
    b['parsed']['sig'][4]=99
    with pytest.raises(ValueError):m.verify_protected_cl(a,b)


def test_projection_uses_actual_created_dimensions_and_all_pins(loaded):
    wanted=deepcopy(loaded['replacement_tool_dimensions']);body={'geometry_read_complete':True,'profile_complete':True,'tool_native_id':400,'tool_type_raw':1,'cut_diameter_native':2.,'tool_protrusion_native':22.,
      'mill_tool':{v:wanted['mill'][k]['raw']for k,v in m.MILL_MAP.items()},'holder':{v:wanted['holder'][k]['raw']for k,v in m.HOLDER_MAP.items()}}
    checkpoint={'generic':{k:v for k,v in wanted['generic'].items()if k not in ['units_verified','holder_geometry_verified']},'catalogue':[{'native_id':273},{'native_id':400}],'saved_cl':{'label':'prior'}}
    context={'deep_loaded':loaded,'long_cut_tool_candidate':{'native_id':400,'full_tool':body},'long_cut_tool_checkpoint':checkpoint,'pins':[m.common._pin(R/'scripts'/name) for name in sorted(m.FACTORY_ONLY_NATIVE_PHASE)],'offline_export_proof_pins':[]}
    loaded['checkpoint_pins']=[]
    result=m.projection_from_creation(context)
    assert result['replacement_tool_dimensions']==wanted
    assert result['configuration_tool']['native_id']==400
    assert all(t['tool_native_id']==400 and t['assigned_tool']==wanted['generic']for t in result['deep_targets'])
    assert result['pins']==[m.common._pin(m.__file__)]


def test_actual_nc_and_target_members_are_callable_from_real_instance():
    b=m.NativeBackend({'guide_parameters':{'document':{}},'deep_targets':[]},{},object(),'metadata-only','metadata-only',{},lambda:None)
    for name in ['assign','nc_owner','read_nc','set_nc','generate','set_field','field','outcome','export','save','saved_hash','capture_snapshot']:
        assert callable(getattr(b,name))


def test_observed_cnc_change_is_restored_and_read_back_before_gtp(loaded,engine):
    j=FakeJournal();b=FakeBackend(loaded,j,'nc');r=m.run_backend(b,j,loaded)
    assert r['readback_verified'] and len([x for x in b.calls if x.startswith('CNC0:')])==4
    assert max(i for i,x in enumerate(b.calls)if x.startswith('CNC0:'))<min(i for i,x in enumerate(b.calls)if x.startswith('GTP:'))

@pytest.mark.parametrize('damage',['nc_unconfirmed','gtp_unknown'])
def test_unknown_or_unconfirmed_native_outcome_stops_without_save(loaded,engine,damage):
    j=FakeJournal();b=FakeBackend(loaded,j,damage);r=m.run_backend(b,j,loaded)
    assert r['status']=='uncertain' and not r['readback_verified'] and b.closed
    assert 'Save'not in b.calls and 'CL:saved'not in b.calls


def test_projected_creator_context_constructs_real_backend_and_accepts_newtool_outcome(loaded):
    wanted=deepcopy(loaded['replacement_tool_dimensions']);body={'geometry_read_complete':True,'profile_complete':True,'tool_native_id':400,'tool_type_raw':1,'cut_diameter_native':2.,'tool_protrusion_native':22.,
      'mill_tool':{v:wanted['mill'][k]['raw']for k,v in m.MILL_MAP.items()},'holder':{v:wanted['holder'][k]['raw']for k,v in m.HOLDER_MAP.items()}}
    loaded['checkpoint_pins']=[]
    context={'deep_loaded':loaded,'long_cut_tool_candidate':{'native_id':400,'full_tool':body},'long_cut_tool_checkpoint':{'generic':wanted['generic'],'catalogue':[{'native_id':273},{'native_id':400}],'saved_cl':{'label':'prior'}},'pins':[m.common._pin(R/'scripts'/name) for name in sorted(m.FACTORY_ONLY_NATIVE_PHASE)],'offline_export_proof_pins':[]}
    projected=m.projection_from_creation(context);m.baseline_contract(projected)
    backend=m.NativeBackend(projected,{},object(),'metadata-only','metadata-only',{},lambda:None)
    outcomes=json.loads((Path(__file__).parent/'fixtures/saved_deep_baseline.json').read_text(encoding='utf-8'))['outcomes']
    for target in backend.learned:
        assert target['assigned_tool']['native_id']==400
        assert target['reference_tool_dimensions']['mill']['EffCutlength']['raw']==6.
        m.generation.status_contract(outcomes[str(target['operation_native_id'])],target,True)
    assert isinstance(backend.capture,ModuleType) and callable(backend.capture_snapshot)


@pytest.fixture
def guard_context(tmp_path):
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'unchanged saved part fixture')
    names=sorted(m.FACTORY_ONLY_NATIVE_PHASE)+[f'active_{i}.py' for i in range(63)]
    pins=[]
    for name in names:
        p=tmp_path/name;p.write_text(name,encoding='utf-8');pins.append(m.common._pin(p))
    p=dict(process_id=99,expected_document_path=str(source),expected_source_sha256=m._file_hash(source))
    loaded=dict(pins=pins,checkpoint_pins=[],guide_parameters=dict(document=dict(path=str(source),type=1,needs_save=False)))
    return p,loaded


def test_real_guard_rejects_old66_accepts_split63_without_entering(guard_context,monkeypatch):
    from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
    p,loaded=guard_context
    def forbidden(*args,**kwargs):raise AssertionError('Offline preflight must never enter or access COM')
    monkeypatch.setattr(ScopedCamDispatchGuard,'__enter__',forbidden)
    with pytest.raises(ValueError,match='bounded complete evidence'):m.guard_constructor_preflight(p,loaded,'metadata-only')
    before=deepcopy(loaded['pins'])
    loaded['pins'],loaded['checkpoint_pins'],partition=m.partition_native_pins(loaded['pins'],loaded['checkpoint_pins'])
    result=m.guard_constructor_preflight(p,loaded,'metadata-only')
    assert result==dict(scope='REAL_SHARED_GUARD_CONSTRUCTOR_PREFLIGHT_V1',guard_type='ScopedCamDispatchGuard',native_calls=0,entered=False,live_pin_count=63,source_and_unique_files=64,constructor_verified=True)
    assert partition['input_count']==66 and partition['live_count']==63 and partition['shared_guard_maximum']==64 and not partition['shared_guard_modified']
    assert sorted(loaded['pins']+loaded['checkpoint_pins'],key=lambda x:x['path'])==sorted(before,key=lambda x:x['path'])
    m.common._check(loaded['pins']);m.common._check(loaded['checkpoint_pins'])


@pytest.mark.parametrize('damage',['missing_role','duplicate_role','still_over_limit'])
def test_partition_fails_closed_on_wrong_dependency_roles(guard_context,damage,tmp_path):
    p,loaded=guard_context;pins=loaded['pins']
    if damage=='missing_role':pins.pop(0)
    elif damage=='duplicate_role':pins.append(deepcopy(pins[0]))
    else:
        for i in range(2):
            path=tmp_path/f'extra_{i}.py';path.write_text('extra',encoding='utf-8');pins.append(m.common._pin(path))
    with pytest.raises(ValueError):m.partition_native_pins(pins,[])


def test_retired_dependency_content_remains_hash_checked(guard_context):
    p,loaded=guard_context
    live,proof,partition=m.partition_native_pins(loaded['pins'],[])
    Path(proof[0]['path']).write_text('changed completed factory',encoding='utf-8')
    with pytest.raises(ValueError):m.common._check(proof)
    m.common._check(live)


@pytest.mark.parametrize('damage',['document_path','missing_pin','pin_length','wrong_document_type'])
def test_real_guard_still_checks_actual_file_metadata_and_identity(guard_context,damage):
    p,loaded=guard_context
    loaded['pins'],loaded['checkpoint_pins'],_=m.partition_native_pins(loaded['pins'],[])
    if damage=='document_path':p['expected_document_path']=str(Path(p['expected_document_path']).with_name('other.SLDPRT'))
    elif damage=='missing_pin':loaded['pins'][0]['path']=str(Path(loaded['pins'][0]['path']).with_name('missing.py'))
    elif damage=='pin_length':loaded['pins'][0]['bytes']=Path(loaded['pins'][0]['path']).stat().st_size+1
    else:loaded['guide_parameters']['document']['type']=2
    with pytest.raises(ValueError):m.guard_constructor_preflight(p,loaded,'metadata-only')


def test_prepare_runs_actual_guard_preflight_after_abi_before_native_dispatch():
    tree=ast.parse(inspect.getsource(m.prepare_request))
    calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)]
    guard=[node for node in calls if node.func.id=='guard_constructor_preflight']
    abi=[node for node in calls if node.func.id=='audit_interfaces']
    assert len(guard)==len(abi)==1 and abi[0].lineno<guard[0].lineno
    assert not any(node.func.id in {'connect_solidworks','execute'} for node in calls)
