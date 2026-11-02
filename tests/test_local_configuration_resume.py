from copy import deepcopy
from pathlib import Path
import ast
import pytest
from cam_public_test_support import add_runtime, required_module, required_test_module

R = add_runtime()
f = required_test_module('test_local_operation_group')
cl = required_module('sw_cam_local_configuration_cl')
m = required_module('sw_cam_local_configuration_resume')

def action(attempted=True):
    r=dict(attempted=attempted,returned=attempted,readback_verified=True,status='verified',observed=0)
    if attempted:r.update(native_dispatch_pending=False,native_return=dict(python_type='int',value_recorded=True,value=0))
    else:r['observed']=dict(already_satisfied=True,value=0)
    return r

@pytest.mark.parametrize('attempted',[True,False])
def test_completed_action_forms(attempted):m.verified_action(action(attempted))

@pytest.mark.parametrize('bad',['pending','unattempted_return','missing_pending','not_returned','wrong_hr','bool_hr','no_readback','unknown_skip'])
def test_invalid_action_outcomes(bad):
    r=action(False if bad in ('unattempted_return','unknown_skip')else True)
    if bad=='pending':r['native_dispatch_pending']=True
    elif bad=='unattempted_return':r['returned']=True
    elif bad=='missing_pending':r.pop('native_dispatch_pending')
    elif bad=='not_returned':r['returned']=False
    elif bad=='wrong_hr':r['native_return']['value']=1
    elif bad=='bool_hr':r['native_return']['value']=False
    elif bad=='no_readback':r['readback_verified']=False
    else:r['observed']['already_satisfied']=False
    with pytest.raises((ValueError,KeyError)):m.verified_action(r)


def workflow(tmp_path,monkeypatch,*,fail_at=None,bad_snapshot=False,bad_save=False):
    baseline,plan,param,old=f.fixture();ids=[344,346,348,350];targets=[];snapshot=deepcopy(baseline)
    for i,(t,oid)in enumerate(zip(plan['rows'],ids)):
        t.update(operation_native_id=oid,assigned_tool=deepcopy(plan['tool']),entry_point_native=[float(i),1.,0.])
        snapshot['binding']['operations'].append(dict(native_id=oid,setup_index=0,setup_native_id=93,operation_index=17+i,
            mill_operation_type=t['operation_type'],base_operation_type=1,suppressed=False,toolpath_generated=False,
            toolpath_record_counts=[],linked_feature_ids=[t['feature_native_id']],assigned_tool=deepcopy(plan['tool'])))
        snapshot['binding']['operation_setups'][0]['operation_count']+=1
        snapshot['parameters'].append(param(oid,t['feature_native_id'],plan['tool']));targets.append(deepcopy(t))
    adopted=m.expected_prefix(ids);field_values={}
    for t in targets:
        for spec in m.config.ROUGH_FIELDS if t['operation_type']==0 else m.config.FINISH_FIELDS:
            name=str(t['operation_native_id'])+':'+spec[0]
            field_values[name]=0 if name in adopted else 1
    report=dict(scope=m.SCOPE,source_path=str(tmp_path/'example.sldprt'),source_sha256='a'*64,
        adopted_receipt_pin=dict(path='partial.json',sha256='c'*64),adopted_marker_pin=dict(path='partial.marker',sha256='d'*64),
        writer_stop_pin=dict(path='stopped.json',sha256='e'*64),phase_proof_checks=[dict(phase=x,verified=True)for x in ('before_native_start','before_save','after_export_and_cleanup')])
    j=m.Journal(report,tmp_path/'receipt.json',tmp_path/'marker.json')
    partial=dict(after_tools=deepcopy(snapshot),nc_readbacks={'344':{}},entry_readbacks={'344':{}})
    loaded=dict(guide_parameters=dict(expected_parameters=baseline),local_plan=plan,
        configuration_resume_context=dict(targets=targets,expected_snapshot=deepcopy(snapshot),adopted_action_names=adopted),
        configuration_resume_partial=partial,generated=dict(saved_cl={'protected':14}),
        configuration_resume_pin=deepcopy(report['adopted_receipt_pin']),configuration_resume_marker_pin=deepcopy(report['adopted_marker_pin']),writer_stop_pin=deepcopy(report['writer_stop_pin']))
    class Backend(f.Backend):
        def field(self,t,spec):return field_values[str(t['operation_native_id'])+':'+spec[0]]
        def set_field(self,t,spec,wanted,pending):
            label=str(t['operation_native_id'])+':'+spec[0];pending();self.calls.append(label)
            if label==fail_at:raise RuntimeError('Unknown setter outcome')
            field_values[label]=deepcopy(wanted);return 0
        def save(self):self.calls.append('save');return 1 if bad_save else 0
        def saved_hash(self,stage):
            self.j.report['source_transition']=dict(source_before_sha256='a'*64,source_after_sha256='b'*64,strict_save_return=0,document=dict(needs_save=False));return 'b'*64
        def export(self,label,binding):self.calls.append('export');return dict(source_sha256='b'*64)
        def finish(self):
            self.calls.append('finish');self.j.report['messages']=dict(subscribed=True,disconnected=True,active=False,event_count=0)
    b=Backend(baseline,plan,param,old,j);b.value=deepcopy(snapshot)
    if bad_snapshot:b.value['parameters'][0]['nc']['feeds_compensation']['XYFeed']=999.
    def configure_nc(b,j,t,l):
        for key in ('GetSpndlSpeed','XYFeed'):
            label=str(t['operation_native_id'])+':NC:'+key
            def invoke(pending):pending();b.calls.append(label);return 0
            j.execute(label,invoke);j.verified(label,dict(readback={}))
        j.report.setdefault('nc_readbacks',{})[str(t['operation_native_id'])]={}
    def entry(b,j,t,point):
        for key in m.ENTRY_ACTIONS:
            label=str(t['operation_native_id'])+':entry:'+key
            def invoke(pending):pending();b.calls.append(label);return 0
            j.execute(label,invoke);j.verified(label,dict(point=point))
    def configured(before,after,targets,loaded):
        assert before['binding']==after['binding']
        for t in targets:
            for spec in m.config.ROUGH_FIELDS if t['operation_type']==0 else m.config.FINISH_FIELDS:
                assert field_values[str(t['operation_native_id'])+':'+spec[0]]==t['fields'][spec[0]]
    monkeypatch.setattr(m.prior.nc,'configure_nc',configure_nc)
    monkeypatch.setattr(m.prior.entry,'apply_entry',entry)
    monkeypatch.setattr(m.prior.recipe_hooks,'verify_configured',configured)
    monkeypatch.setattr(m.cl,'verify_saved',lambda *a:dict(protected_fourteen_cl_verified=True))
    monkeypatch.setattr(m.generation,'close_checked',lambda b,r:b.close())
    return b,j,loaded,field_values


def test_remaining_only_single_save_no_generation(tmp_path,monkeypatch):
    b,j,l,fields=workflow(tmp_path,monkeypatch);r=m.run_once(b,j,l)
    assert r['readback_verified'],r.get('issue')
    assert r['status']=='saved_local_configuration_review_required'
    assert set(r['actions'])==set(m.remaining_action_names(l['configuration_resume_context']['targets'],r['adopted_action_names']))
    assert not set(r['actions']).intersection(r['adopted_action_names'])
    assert b.calls.count('save')==b.calls.count('export')==1
    assert not any(x in b.calls for x in ('insert','assign','generate'))
    assert len(r['saved']['binding']['operations'])==21 and len(r['saved']['parameters'])==12
    assert not r['old_event_cleanup_confirmed']and not r['GTP_attempted']
    assert m.validate_completed(r,l)['saved_cl_streams']==14


def test_fresh_snapshot_mismatch_stops_all_writes(tmp_path,monkeypatch):
    b,j,l,_=workflow(tmp_path,monkeypatch,bad_snapshot=True);r=m.run_once(b,j,l)
    assert b.calls==['start','close']and not r['mutation_attempted']and r['actions']=={}


@pytest.mark.parametrize('label',['346:lead_in_type','348:entry_type','350:side_allowance'])
def test_unknown_setter_never_saves_or_replays(tmp_path,monkeypatch,label):
    b,j,l,_=workflow(tmp_path,monkeypatch,fail_at=label);r=m.run_once(b,j,l)
    assert not r['readback_verified']and 'save'not in b.calls and 'export'not in b.calls
    assert b.calls.count(label)==1 and r['actions'][label]['native_dispatch_pending']


def test_failed_save_not_replayed(tmp_path,monkeypatch):
    b,j,l,_=workflow(tmp_path,monkeypatch,bad_save=True);r=m.run_once(b,j,l)
    assert b.calls.count('save')==1 and 'export'not in b.calls and not r['readback_verified']


def test_second_entry_preserves_durable_evidence(tmp_path,monkeypatch):
    b,j,l,_=workflow(tmp_path,monkeypatch);m.run_once(b,j,l)
    before=deepcopy(j.report);receipt=j.receipt.read_bytes();marker=j.marker.read_bytes();calls=deepcopy(b.calls)
    with pytest.raises(ValueError):m.run_once(b,j,l)
    assert j.report==before and j.receipt.read_bytes()==receipt and j.marker.read_bytes()==marker and b.calls==calls


@pytest.mark.parametrize('action_name',['SetTool:348','insert:left_rough','GTP:344','346:perimeter'])
def test_journal_rejects_completed_and_forbidden_actions(tmp_path,monkeypatch,action_name):
    b,j,l,_=workflow(tmp_path,monkeypatch);j.report['adopted_action_names']=l['configuration_resume_context']['adopted_action_names'];j.report['actions']={}
    with pytest.raises(ValueError):j.entry(action_name)
    assert j.report['actions']=={}


@pytest.mark.parametrize('method',['insert','assign','generate'])
def test_native_adapter_forbids_out_of_scope_calls(method):
    with pytest.raises(ValueError):getattr(m.NativeBackend,method)(None)


@pytest.mark.parametrize('change',['old_path','new_generated','new_tool','new_feature','reorder'])
def test_cl_configuration_contract(tmp_path,monkeypatch,change):
    b,j,l,_=workflow(tmp_path,monkeypatch);value=deepcopy(b.value['binding']);base=l['guide_parameters']['expected_parameters']['binding'];targets=l['configuration_resume_context']['targets']
    assert len(m.cl.contract(value,base,targets))==14
    if change=='old_path':value['operations'][5]['toolpath_record_counts']=[99]
    elif change=='new_generated':value['operations'][-1].update(toolpath_generated=True,toolpath_record_counts=[1])
    elif change=='new_tool':value['operations'][-1]['assigned_tool']['native_id']+=1
    elif change=='new_feature':value['operations'][-1]['linked_feature_ids']=[1234]
    else:value['operations'][-2:]=reversed(value['operations'][-2:])
    with pytest.raises(ValueError):m.cl.contract(value,base,targets)


@pytest.mark.parametrize('bad',['replayed_action','old_cleanup','GTP','saved_snapshot','source','targets','lost_prefix'])
def test_terminal_rejects_false_authority(tmp_path,monkeypatch,bad):
    b,j,l,_=workflow(tmp_path,monkeypatch);r=m.run_once(b,j,l)
    if bad=='replayed_action':r['actions']['346:perimeter']=action()
    elif bad=='old_cleanup':r['old_event_cleanup_confirmed']=True
    elif bad=='GTP':r['GTP_attempted']=True
    elif bad=='saved_snapshot':r['saved']['parameters'][0]['nc']['feeds_compensation']['XYFeed']=99.
    elif bad=='source':r['source_transition']['source_after_sha256']='a'*64
    elif bad=='targets':r['learned_targets'][-1]['operation_native_id']+=1
    else:r['adopted_action_names'].pop()
    with pytest.raises((ValueError,AssertionError)):m.validate_completed(r,l)


def test_export_native_body_is_frozen_reuse():
    def body(path):
        return ast.dump(next(n for n in ast.parse(Path(path).read_text()).body if isinstance(n,ast.FunctionDef)and n.name=='export_current_cl'),include_attributes=False)
    assert body(cl.__file__)==body(cl.original.__file__)


def test_marker_does_not_change_with_pid_or_outputs(tmp_path):
    p=dict(expected_document_path=str(tmp_path/'source.sldprt'),expected_source_sha256='a'*64,partial_receipt_sha256='b'*64,process_id=1)
    assert m.marker_path(p)==m.marker_path(dict(p,process_id=99,receipt_path='different'))
    assert m.marker_path(p)!=m.marker_path(dict(p,partial_receipt_sha256='c'*64))



def synthetic_configuration_prefix():
    """Public synthetic saved-prefix schema; no document, source or receipt file."""
    baseline, plan, param, _ = f.fixture()
    ids = [344, 346, 348, 350]
    after = deepcopy(baseline)
    for index, (target, oid) in enumerate(zip(plan['rows'], ids)):
        target['entry_point_native'] = [float(index), 1.0, 0.0]
        after['parameters'].append(param(oid, target['feature_native_id'], plan['tool']))
        after['binding']['operations'].append(dict(native_id=oid, setup_index=0, setup_native_id=93,
            operation_index=17+index, mill_operation_type=target['operation_type'], base_operation_type=1,
            suppressed=False, toolpath_generated=False, toolpath_record_counts=[],
            linked_feature_ids=[target['feature_native_id']], assigned_tool=deepcopy(plan['tool'])))
        after['binding']['operation_setups'][0]['operation_count'] += 1
    byid = {row['operation_native_id']: row for row in after['parameters']}
    rough = byid[344]
    rough['rough'] = dict(entry={}, depth={}, boundary={})
    wanted = dict(entry_type=4, spiral_radius=0.1, spiral_pitch=0.02,
        first_depth=[False, 0.3], subsequent_depth=[False, 0.3], side_allowance=0.008,
        floor_allowance=0.0, side_step=[False, 0.008])
    plan['rows'][0]['fields'] = deepcopy(wanted)
    areas = {'entry_type':'entry', 'spiral_radius':'entry', 'spiral_pitch':'entry',
        'first_depth':'depth', 'subsequent_depth':'depth'}
    for spec in m.config.ROUGH_FIELDS:
        rough['rough'][areas.get(spec[0], 'boundary')][spec[2]] = {'raw': deepcopy(wanted[spec[0]])}
    rough['rough']['depth'].update(FirstDepthAmt={'raw':0.3}, SbsqDepthAmt={'raw':0.3})
    rough['rough']['entry'].update(GetHoleCentreEntry={'raw':True},
        GetEntryStartPtX={'raw':[0.0,0.0,0.0]}, GetEntryStartPtY={'raw':[0.0,0.0,0.0]})
    rough['startpoints'] = dict(read_complete=True, collection_interface_verified=True,
        list_is_null=False, entry_type=0, count=0, rows=[], hole_center_entry=True)
    rough['nc']['feeds_compensation'] = dict(GetTlpComp=1, GetCNCComp=0,
        GetRetractType=0, GetSpndlSpeed=1000.0, XYFeed=20.0)
    own = deepcopy(rough)
    own['startpoints'].update(entry_type=4, count=1,
        rows=[dict(type_raw=1,position_is_null=False,position_native=plan['rows'][0]['entry_point_native'])])
    own['rough']['entry']['GetEntryStartPtX']['raw'][0] = 0.0
    own['rough']['entry']['GetEntryStartPtY']['raw'][0] = 1.0
    own['nc']['feeds_compensation'].update(GetSpndlSpeed=7100.0, XYFeed=35.0)
    finish = byid[346]
    finish_values = dict(side_allowance=0.0, final_side=0.0, spring_passes=0,
        first_depth=[0.3,False], max_depth=[0.3,False], final_depth=0.0,
        side_step=[0.008,False], previous_allowance=0.008, override_previous=True, perimeter=2)
    plan['rows'][1]['fields'].update(deepcopy(finish_values))
    finish['finish_fields'] = dict(side_allowance=0.0, final_side=0.0, spring_passes=0,
        first_depth=[6.0,False], max_depth=[6.0,False], final_depth=0.0,
        side_step=[5.0,False], previous_allowance=0.5, override_previous=False, perimeter=1)
    finish['finish'] = {member:{'raw':deepcopy(finish['finish_fields'][key][0]
        if key in ('first_depth','max_depth','side_step') else finish['finish_fields'][key])}
        for key,member in m.config.finish.DEFAULT_FIELDS.items()}
    actions = {name:action() for name in m.expected_prefix(ids)}
    for spec in m.config.ROUGH_FIELDS:
        label='344:'+spec[0]; value=deepcopy(wanted[spec[0]])
        actions[label]=action(spec[0]!='floor_allowance')
        actions[label]['observed']=value if actions[label]['attempted'] else dict(already_satisfied=True,value=value)
    nc_before = deepcopy(rough['nc']['feeds_compensation'])
    for key in ('GetSpndlSpeed','XYFeed'):
        nc_after = deepcopy(nc_before); nc_after[key] = m.prior.micro.TARGET_VALUES[key]
        proof = m.prior.micro.verify_readback(nc_before,nc_after,key)
        actions['344:NC:'+key]['observed'] = dict(readback=nc_after,verification=proof)
        nc_before=nc_after
    point = plan['rows'][0]['entry_point_native']
    actions['344:entry:CreateStartPointInstance']['observed']=dict(type_raw=1,returned_nonnull=True)
    actions['344:entry:CreatePosition']['observed']=dict(coordinates=[0.0,0.0,0.0],returned_nonnull=True)
    for key in ('SetPointCoordinates','SetPointPosition'):actions['344:entry:'+key]['observed']=deepcopy(point)
    for key in ('AddStartPoint','SetStartPointList'):
        actions['344:entry:'+key]['observed']=dict(count=1,type_raw=1,position_native=deepcopy(point))
    for key,value in finish_values.items():
        actions['346:'+key]=action(key not in ('side_allowance','final_side','spring_passes','final_depth'))
        actions['346:'+key]['observed']=deepcopy(value) if actions['346:'+key]['attempted'] else dict(already_satisfied=True,value=deepcopy(value))
    return dict(actual_new_ids=ids,plan=plan,after_tools=after,actions=actions,
        captures=[dict(label='entry_after_344',parameters=[own],binding=deepcopy(after['binding']))],
        nc_readbacks={'344':dict(values=deepcopy(own['nc']['feeds_compensation']))},
        entry_readbacks={'344':deepcopy(own['startpoints'])})


def test_synthetic_verified_prefix():
    r=synthetic_configuration_prefix(); before=deepcopy(r); out=m.expected_partial_snapshot(r)
    assert r==before and len(out['parameters'])==12 and len(out['binding']['operations'])==21
    assert out['binding']==r['after_tools']['binding']
    byid={v['operation_native_id']:v for v in out['parameters']}
    assert all(byid[v['operation_native_id']]==v for v in r['after_tools']['parameters']
        if v['operation_native_id']not in r['actual_new_ids'][:2])
    finish=byid[346]
    assert finish['finish_fields']['first_depth']==[0.3,False]
    assert finish['finish']['FirstDepthCut']['raw']==0.3


@pytest.mark.parametrize('bad',['nc_value','nc_proof','point_factory','position_factory'])
def test_synthetic_prefix_rejects_inconsistent_observations(bad):
    r=synthetic_configuration_prefix()
    if bad=='nc_value':r['actions']['344:NC:XYFeed']['observed']['readback']['XYFeed']=36.0
    elif bad=='nc_proof':r['actions']['344:NC:GetSpndlSpeed']['observed']['verification']['raw_readback_verified']=False
    elif bad=='point_factory':r['actions']['344:entry:CreateStartPointInstance']['observed']['returned_nonnull']=False
    else:r['actions']['344:entry:CreatePosition']['observed']['coordinates'][2]=1.0
    with pytest.raises(ValueError):m.expected_partial_snapshot(r)
