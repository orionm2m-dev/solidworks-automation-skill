from pathlib import Path
from copy import deepcopy
import importlib.util,os,sys,json,math
import pytest
from cam_public_test_support import add_runtime, required_module, required_test_module
R=add_runtime()
m=required_module('sw_cam_local_operation_continue')
f=required_test_module('test_local_operation_group')


def levels(depth=3.4):
    return dict(levels=dict(machining_depth_native=depth,override_machining_depth=False),setup=dict(origin=[0.,0.,26.],axis=[0.,0.,-1.]))

@pytest.mark.parametrize('count',range(5))
@pytest.mark.parametrize('direction',[-math.inf,math.inf])
def test_only_four_representable_steps(count,direction):
    b=3.4
    for _ in range(count):b=math.nextafter(b,direction)
    a,proof=m.adopt_levels(levels(),levels(b))
    assert a==levels(b)and proof['absolute_delta_mm']<=1e-12
    assert not proof['geometric_allowance_changed']

@pytest.mark.parametrize('bad',[3.4001,3.3999,0.,-3.4,float('nan'),float('inf'),3,True])
def test_bad_depth_is_rejected(bad):
    with pytest.raises((ValueError,KeyError)):m.adopt_levels(levels(),levels(bad))

def test_fifth_ulp_rejected():
    b=3.4
    for _ in range(5):b=math.nextafter(b,math.inf)
    with pytest.raises(ValueError):m.adopt_levels(levels(),levels(b))

def test_absolute_cap_not_only_ulp():
    with pytest.raises(ValueError):m.adopt_levels(levels(1e8),levels(math.nextafter(1e8,math.inf)))

@pytest.mark.parametrize('field',['axis','origin','flag','extra'])
def test_other_levels_remain_exact(field):
    b=levels(math.nextafter(3.4,math.inf))
    if field=='axis':b['setup']['axis'][2]=1.
    elif field=='origin':b['setup']['origin'][2]=math.nextafter(26.,math.inf)
    elif field=='flag':b['levels']['override_machining_depth']=True
    else:b['levels']['extra']=0.
    with pytest.raises(ValueError):m.adopt_levels(levels(),b)

def synthetic_definition_stop(monkeypatch):
    baseline,plan,param,old_tool=f.fixture()
    def native_levels(depth=3.4):
        value=levels(depth)
        value['setup']['axis_native']=value['setup'].pop('axis')
        value['setup']['origin_native']=value['setup'].pop('origin')
        return value
    for row in plan['rows']:
        row['expected_levels']=native_levels()
    definitions=deepcopy(baseline)
    actions={}
    for i,(row,oid) in enumerate(zip(plan['rows'],[344,346,348,350])):
        definition=dict(native_id=oid,setup_index=0,setup_native_id=93,operation_index=17+i,
            mill_operation_type=row['operation_type'],base_operation_type=1,suppressed=False,
            toolpath_generated=False,toolpath_record_counts=[],linked_feature_ids=[row['feature_native_id']],
            assigned_tool=deepcopy(old_tool))
        definitions['binding']['operations'].append(definition)
        definitions['binding']['operation_setups'][0]['operation_count']+=1
        own=param(oid,row['feature_native_id'],old_tool)
        own['levels']=native_levels(math.nextafter(3.4,math.inf))
        definitions['parameters'].append(own)
        actions['insert:'+row['key']]=dict(actual_native_id=oid,attempted=True,returned=True,
            readback_verified=True,native_dispatch_pending=False,observed=deepcopy(definition))
    document=dict(path='C:/fixtures/example.sldprt',title='example.sldprt',type=1,needs_save=False)
    owner=dict(process_id=123,create_time=1.,executable='C:/fixtures/cad.exe',alive=True)
    raw=dict(scope=m.prior.SCOPE,status='uncertain',phase='finished',failed_phase='insert:right_finish',
        module_pin=dict(sha256=m.PARENT_PRODUCER_SHA),ownership=owner,source_sha256='a'*64,
        issue=dict(type='ValueError',locations=[dict(file='sw_cam_local_operation_group.py',function='run_backend',line=164),
            dict(file='sw_cam_rough_firstcut.py',function='require',line=38)]),
        mutation_attempted=True,model_saved=False,readback_verified=False,native_dispatch_pending=False,
        cleanup_session_active=False,current_document=document,
        messages=dict(subscribed=True,disconnected=True,active=False,event_count=0),
        before=baseline,definitions=definitions,plan=plan,actions=actions,actual_new_ids=[344,346,348,350],
        actual_default_catalogues={},request=dict(choices={r['key']:dict(name=r['default_operation_name'],
            default_operation_id=r['default_operation_id'])for r in plan['rows']},feed_policy=deepcopy(plan['feed_policy'])))
    loaded=dict(ownership=deepcopy(owner),source_sha256='a'*64,
        guide_parameters=dict(document=deepcopy(document),expected_parameters=deepcopy(baseline)),
        local_verified_context={},local_recipe={})
    # Only projection input is synthetic. The adoption contract and frozen producer digest check are real.
    monkeypatch.setattr(m.prior.projection,'project_context',lambda *a,**k:dict(local_plan=deepcopy(raw['plan'])))
    return raw,loaded


def test_synthetic_four_definition_depths(monkeypatch):
    raw,loaded=synthetic_definition_stop(monkeypatch);before=deepcopy(raw)
    out=m.partial_contract(raw,loaded)
    assert [t['operation_native_id']for t in out['targets']]==[344,346,348,350]
    assert all(p['absolute_delta_mm']==math.ulp(3.4)for p in out['depth_adoption'])
    assert all(t['expected_levels']['levels']['machining_depth_native']==3.4000000000000004 for t in out['targets'])
    assert raw==before

@pytest.mark.parametrize('bad',['depth','otherlevel','extraaction','pending','save','lifetime','insertid','definition','later'])
def test_synthetic_partial_contract_rejects_bad_adoption(monkeypatch,bad):
    raw,loaded=synthetic_definition_stop(monkeypatch)
    if bad=='depth':raw['definitions']['parameters'][8]['levels']['levels']['machining_depth_native']=3.4001
    elif bad=='otherlevel':raw['definitions']['parameters'][8]['levels']['setup']['axis_native'][2]=1.
    elif bad=='extraaction':raw['actions']['SetTool:344']={}
    elif bad=='pending':raw['native_dispatch_pending']=True
    elif bad=='save':raw['model_saved']=True
    elif bad=='lifetime':loaded['ownership']['process_id']+=1
    elif bad=='insertid':raw['actions']['insert:left_rough']['actual_native_id']=999
    elif bad=='definition':raw['definitions']['binding']['operations'][-1]['assigned_tool']['native_id']=999
    elif bad=='later':raw['after_tools']={}
    with pytest.raises((ValueError,KeyError)):m.partial_contract(raw,loaded)

def workflow(tmp_path,monkeypatch,*,bad_snapshot=False,feed=False,fail=None):
    baseline,plan,param,old=f.fixture()
    for row in plan['rows']:row['expected_levels']=levels(math.nextafter(3.4,math.inf))
    original_param=param
    def param(oid,fid,tool):
        row=original_param(oid,fid,tool);row['levels']=levels(math.nextafter(3.4,math.inf));return row
    definitions=deepcopy(baseline);targets=[]
    for i,row in enumerate(plan['rows']):
        oid=1000+i
        definition=dict(native_id=oid,setup_index=0,setup_native_id=93,operation_index=17+i,mill_operation_type=row['operation_type'],base_operation_type=1,suppressed=False,toolpath_generated=False,toolpath_record_counts=[],linked_feature_ids=[row['feature_native_id']],assigned_tool=deepcopy(old))
        definitions['binding']['operations'].append(definition)
        definitions['binding']['operation_setups'][0]['operation_count']+=1
        definitions['parameters'].append(param(oid,row['feature_native_id'],old))
        targets.append(dict(deepcopy(row),operation_native_id=oid,assigned_tool=deepcopy(old)))
    report=dict(source_path=str(tmp_path/'part.sldprt'),source_sha256='a'*64,adopted_receipt_pin=dict(path='parent',sha256='c'*64),adopted_marker_pin=dict(path='marker',sha256='d'*64))
    journal=m.Journal(report,tmp_path/'receipt.json',tmp_path/'marker.json')
    loaded=dict(guide_parameters=dict(expected_parameters=baseline),local_plan=plan,generated=dict(saved_cl=dict(saved14=True)),
        adopted_definition_context=dict(plan=plan,targets=targets,definitions=definitions,depth_adoption=[]))
    backend=f.Backend(baseline,plan,param,old,journal,feed_delta=feed,fail_at=fail);backend.value=deepcopy(definitions)
    if bad_snapshot:backend.value['parameters'][-1]['levels']['levels']['machining_depth_native']=3.4001
    backend.outcome=lambda t:dict(operation_native_id=t['operation_native_id'],feature_native_id=t['feature_native_id'],background_over_before=False,background_over_after=False,generated=True,generated_for_feature=True,record_counts=[100])
    monkeypatch.setattr(m.config,'verify_automatic_target',lambda *a:None)
    monkeypatch.setattr(m.generation,'close_checked',lambda b,r:b.close())
    return backend,journal,loaded

def test_complete_tail_never_inserts(tmp_path,monkeypatch):
    b,j,loaded=workflow(tmp_path,monkeypatch)
    r=m.run_once(b,j,loaded,hooks=f.hooks())
    assert r['readback_verified'],r.get('issue')
    assert b.calls==['start']+['assign']*4+['generate']*4+['save','export','finish','close']
    assert not any(k.startswith('insert:')for k in r['actions'])
    assert not r['operation_creation_attempted']and r['status']=='saved_existing_local_group_review_required'

def test_fresh_mismatch_stops_before_any_assignment(tmp_path,monkeypatch):
    b,j,l=workflow(tmp_path,monkeypatch,bad_snapshot=True)
    r=m.run_once(b,j,l,hooks=f.hooks())
    assert b.calls==['start','close']and not r['mutation_attempted']and r['status']=='error'

@pytest.mark.parametrize('failure',[1,2,3,4])
def test_unknown_gtp_stops_without_save_or_replay(tmp_path,monkeypatch,failure):
    b,j,l=workflow(tmp_path,monkeypatch,fail=failure)
    r=m.run_once(b,j,l,hooks=f.hooks())
    assert r['status']=='uncertain'and b.calls.count('generate')==failure and 'save'not in b.calls
    receipt=j.receipt.read_bytes();marker=j.marker.read_bytes();snapshot=deepcopy(r);calls=deepcopy(b.calls)
    with pytest.raises(ValueError):m.run_once(b,j,l,hooks=f.hooks())
    assert receipt==j.receipt.read_bytes()and marker==j.marker.read_bytes()and snapshot==r and calls==b.calls

def test_feed_drift_preserves_completed_four_and_stops_save(tmp_path,monkeypatch):
    b,j,l=workflow(tmp_path,monkeypatch,feed=True)
    r=m.run_once(b,j,l,hooks=f.hooks())
    assert r['status']=='uncertain'and len(r['completed_gtp_counts'])==4 and 'save'not in b.calls

def test_native_adapter_explicitly_forbids_insert():
    with pytest.raises(ValueError,match='forbidden'):m.NativeBackend.insert(object(),{},0,None,None)

def test_marker_does_not_depend_on_pid_or_output_names(tmp_path,monkeypatch):
    monkeypatch.setattr(m.common,'local_evidence_root',lambda:tmp_path)
    p=dict(expected_document_path=str(tmp_path/'part'),expected_source_sha256='a'*64,failed_receipt_sha256='b'*64,process_id=1)
    q=dict(p,process_id=2,receipt_path='new')
    assert m.marker_path(p)==m.marker_path(q)
    q['failed_receipt_sha256']='c'*64;assert m.marker_path(p)!=m.marker_path(q)

def test_prior_marker_not_touched_by_new_journal(tmp_path,monkeypatch):
    parent=tmp_path/'parent_marker.json';parent.write_bytes(b'archived')
    b,j,l=workflow(tmp_path,monkeypatch);m.run_once(b,j,l,hooks=f.hooks())
    assert parent.read_bytes()==b'archived'


def terminal_fixture(tmp_path,monkeypatch):
    b,j,l=workflow(tmp_path,monkeypatch);r=m.run_once(b,j,l,hooks=f.hooks())
    l.update(configuration_tool=deepcopy(r['plan']['tool']),sealed_feed_policy=deepcopy(r['plan']['feed_policy']),
        adopted_receipt_pin=deepcopy(r['adopted_receipt_pin']),adopted_marker_pin=deepcopy(r['adopted_marker_pin']))
    r['messages']=dict(subscribed=True,disconnected=True,active=False,event_count=0)
    r['source_transition']=dict(source_before_sha256='a'*64,source_after_sha256='b'*64,strict_save_return=0,document=dict(needs_save=False))
    r['phase_proof_checks']=[dict(phase=x,verified=True)for x in ('before_native_start','before_save','after_export_and_cleanup')]
    r['saved_cl']['source_sha256']='b'*64
    def skipped():return dict(status='verified',attempted=False,returned=False,readback_verified=True,observed=dict(already_satisfied=True))
    def executed():return dict(status='verified',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,observed={'typed_readback':True})
    for target in r['learned_targets']:
        oid=str(target['operation_native_id']);rough=target['operation_type']==0
        for spec in (m.config.ROUGH_FIELDS if rough else m.config.FINISH_FIELDS):r['actions'][oid+':'+spec[0]]=skipped()
        for key in ('GetSpndlSpeed','XYFeed'):r['actions'][oid+':NC:'+key]=skipped()
        if rough:
            for key in ('CreateStartPointInstance','CreatePosition','SetPointCoordinates','SetPointPosition','AddStartPoint','SetStartPointList'):r['actions'][oid+':entry:'+key]=executed()
    monkeypatch.setattr(m.prior.recipe_hooks,'verify_configured',lambda *a:None)
    monkeypatch.setattr(m.prior.cl,'verify_saved',lambda *a:dict(protected_count=14))
    return r,l

def test_completed_continuation_authority(tmp_path,monkeypatch):
    r,l=terminal_fixture(tmp_path,monkeypatch)
    result=m.validate_completed(r,l)
    assert result['saved_operations']==21 and result['saved_parameters']==12 and result['saved_cl_streams']==18

@pytest.mark.parametrize('problem',['definitions','insert_action','parent_pin','normalization','empty_targets','assignment_observed','gtp_count','source','dirty','production'])
def test_terminal_rejects_false_authority(tmp_path,monkeypatch,problem):
    r,l=terminal_fixture(tmp_path,monkeypatch)
    if problem=='definitions':r['definitions']['parameters'][-1]['nc']['feeds_compensation']['XYFeed']=99.
    elif problem=='insert_action':r['actions']['insert:left_rough']=deepcopy(r['actions']['SetTool:1000'])
    elif problem=='parent_pin':r['adopted_receipt_pin']['sha256']='f'*64
    elif problem=='normalization':r['depth_adoption'].append({'unexpected':True})
    elif problem=='empty_targets':r['learned_targets']=[]
    elif problem=='assignment_observed':r['actions']['SetTool:1000']['observed']['feature_native_id']=999
    elif problem=='gtp_count':r['actions']['GTP:1000']['observed']['record_counts']=[101]
    elif problem=='source':r['saved_source_sha256']='a'*64
    elif problem=='dirty':r['source_transition']['document']['needs_save']=True
    else:r['production_qualified']=True
    with pytest.raises((ValueError,KeyError)):m.validate_completed(r,l)

