from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace,ModuleType
import importlib.util,os,sys,json,ast,inspect
import pytest
from cam_public_test_support import add_runtime, required_module
R=add_runtime()
m=required_module('sw_cam_deep_long_tool_replace_current')
path=R/'tests/test_deep_long_tool_replace.py'
if not path.is_file():raise RuntimeError('Required public replacement fixture is missing')
spec=importlib.util.spec_from_file_location('prior_test_fixtures',path);prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)


@pytest.fixture
def loaded():return prior.loaded.__wrapped__()

@pytest.mark.parametrize('background',[False,True])
def test_actual_generate_real_guard_binds_before_claim_and_calls_once(tmp_path,monkeypatch,loaded,background):
    from scripts import sw_cam_dispatch_guard as gm
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'part');proof=tmp_path/'proof.py';proof.write_text('proof')
    calls=[];monkeypatch.setattr(gm.ScopedCamDispatchGuard,'_identity',lambda self:None)
    def typed(raw,name,path):calls.append('QI');return raw
    monkeypatch.setattr(gm,'_typed',typed)
    guard=gm.ScopedCamDispatchGuard(None,'metadata',process_id=1,expected_document={'path':str(source),'title':source.name,'type':1,'needs_save':False},source_sha256=m.historical._file_hash(source),evidence_pins=[m.common._pin(proof)],verify_evidence=lambda:None,verify_owned_process=lambda:None,check_events=lambda:None)
    b=m.NativeBackend(loaded,{},object(),'metadata','metadata',{},lambda:None);raw=object();b.ctx=SimpleNamespace(guard=lambda:guard);b.doc=object()
    b.read_nc=lambda t:deepcopy(t['reference_nc']);b.target=lambda g,t:(raw,None)
    b.outcome=lambda t:dict(operation_native_id=t['operation_native_id'],feature_native_id=t['feature_native_id'],background_over_before=background,background_over_after=background,generated=True,generated_for_feature=True,record_counts=[17118])
    monkeypatch.setattr(m,'read_generic_tool',lambda *a:(loaded['configuration_tool'],raw));monkeypatch.setattr(m,'_member',lambda obj,name:calls.append(name)or 0)
    assert b.generate(b.learned[0],lambda:calls.append('pending'))==0
    assert calls==['QI','pending','GenerateToolpath']
    with pytest.raises(ValueError):guard.dispatch_once(lambda:m._member(raw,'GenerateToolpath'),persist_pending=lambda:None)
    assert calls.count('GenerateToolpath')==1

@pytest.mark.parametrize('damage',['not_bool','nc_changed','tool_changed'])
def test_generate_rejects_bad_preconditions_before_pending(loaded,monkeypatch,damage):
    b=m.NativeBackend(loaded,{},object(),'metadata','metadata',{},lambda:None);t=b.learned[0]
    b.read_nc=lambda _:dict(t['reference_nc'],XYFeed=777)if damage=='nc_changed'else deepcopy(t['reference_nc'])
    b.outcome=lambda _:dict(operation_native_id=t['operation_native_id'],feature_native_id=t['feature_native_id'],background_over_before=0 if damage=='not_bool'else False,background_over_after=False,generated=True,generated_for_feature=True,record_counts=[17118])
    class G:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,*a):return None
        def typed(self,*a):raise AssertionError('must reject before interface binding')
    b.ctx=SimpleNamespace(guard=lambda:G());b.doc=object();b.target=lambda *a:(object(),None)
    monkeypatch.setattr(m,'read_generic_tool',lambda *a:({'native_id':999},None))
    with pytest.raises(ValueError):b.generate(t,lambda:(_ for _ in()).throw(AssertionError('no pending')))

def test_marker_is_identical_across_versions_pid_and_receipt(tmp_path,monkeypatch):
    monkeypatch.setattr(m.common,'local_evidence_root',lambda:tmp_path)
    p=dict(expected_document_path=str(tmp_path/'part.SLDPRT'),expected_source_sha256='a'*64,process_id=1,receipt_path='one',module_sha256='b'*64)
    old=m.historical.marker_path(p);old.write_text('pending')
    assert m.marker_path(dict(p,process_id=2,receipt_path='two',module_sha256='c'*64))==old

def test_actual_constructor_keeps_reader_and_native_action_reuse(loaded):
    b=m.NativeBackend(loaded,{},object(),'metadata','metadata',{},lambda:None)
    assert isinstance(b.capture,ModuleType)and callable(b.capture_snapshot)
    assert m.NativeBackend.assign is m.historical.NativeBackend.assign
    assert m.NativeBackend.save is m.historical.NativeBackend.save
    assert m.marker_path is m.historical.marker_path
    assert m.historical.NativeBackend.generate is not m.NativeBackend.generate


def configured(loaded):
    value=deepcopy(loaded['guide_parameters']['expected_parameters']['parameters'])
    for row in value:
        if row['operation_native_id']in m.IDS:row['tool']=deepcopy(loaded['replacement_tool_dimensions'])
    return value


def policy(loaded,ids=None,after=1000.):
    return {'mode':'nominal_geometry_only','source_sha256':'a'*64,'tool_native_id':loaded['configuration_tool']['native_id'],
        'operations':[{'operation_native_id':oid,'xy_feed_pairs':[{'before':500.,'after':after}]}for oid in (ids or m.IDS)]}


def checked(before,after,loaded,p=None):
    return m.verify_post_generation_parameters(before,after,selected_ids=m.IDS,policy=p,source_sha256='a'*64,tool_native_id=loaded['configuration_tool']['native_id'])


def test_default_exact_and_explicit_unchanged_are_accepted(loaded):
    rows=configured(loaded);original=deepcopy(rows)
    assert checked(rows,rows,loaded)['permitted_changes']==[]
    assert checked(rows,rows,loaded,policy(loaded))['permitted_changes']==[]
    assert rows==original


def test_only_four_predeclared_xy_pairs_accepted_without_normalization(loaded):
    old=configured(loaded);new=deepcopy(old)
    for row in new[4:]:row['nc']['feeds_compensation']['XYFeed']=1000.
    original=deepcopy(new);result=checked(old,new,loaded,policy(loaded))
    assert len(result['permitted_changes'])==4 and new==original
    assert not result['production_qualified']and not result['physical_cutting_conditions_qualified']
    with pytest.raises(ValueError):checked(old,new,loaded)


@pytest.mark.parametrize('damage',['unlisted_op','unlisted_positive','spindle','CNC','Z_recipe','protected_feed','tool','row_order','duplicate','row_missing','extra_field'])
def test_all_unlisted_changes_rejected(loaded,damage):
    old=configured(loaded);new=deepcopy(old)
    if damage=='unlisted_op':new[-1]['nc']['feeds_compensation']['XYFeed']=1000.;p=policy(loaded,ids=[330])
    else:
        p=policy(loaded)
        if damage=='unlisted_positive':new[-1]['nc']['feeds_compensation']['XYFeed']=1234.
        elif damage=='spindle':new[-1]['nc']['feeds_compensation']['GetSpndlSpeed']=8000.
        elif damage=='CNC':new[-1]['nc']['feeds_compensation']['GetCNCComp']=1
        elif damage=='Z_recipe':new[-1]['start_point']={'unrequested':1}
        elif damage=='protected_feed':new[0]['nc']['feeds_compensation']['XYFeed']=1000.
        elif damage=='tool':new[-1]['tool']['generic']['native_id']=999
        elif damage=='row_order':new[0],new[1]=new[1],new[0]
        elif damage=='duplicate':new[-1]=deepcopy(new[-2])
        elif damage=='row_missing':new.pop()
        else:new[-1]['unlisted']=True
    with pytest.raises(ValueError):checked(old,new,loaded,p)


@pytest.mark.parametrize('damage',['wrong_source','wrong_tool','protected_id','duplicate_id','empty_pairs','too_many_pairs','duplicate_pair','wrong_before','zero','negative','nan','inf','bool','unknown_mode','extra_permission','empty_ops'])
def test_policy_is_bounded_source_bound_and_finite(loaded,damage):
    p=policy(loaded);pair=p['operations'][0]['xy_feed_pairs'][0]
    if damage=='wrong_source':p['source_sha256']='b'*64
    elif damage=='wrong_tool':p['tool_native_id']=999
    elif damage=='protected_id':p['operations'][0]['operation_native_id']=322
    elif damage=='duplicate_id':p['operations'].append(deepcopy(p['operations'][0]))
    elif damage=='empty_pairs':p['operations'][0]['xy_feed_pairs']=[]
    elif damage=='too_many_pairs':p['operations'][0]['xy_feed_pairs']*=9
    elif damage=='duplicate_pair':p['operations'][0]['xy_feed_pairs']*=2
    elif damage=='wrong_before':pair['before']=250.
    elif damage=='zero':pair['after']=0.
    elif damage=='negative':pair['after']=-1.
    elif damage=='nan':pair['after']=float('nan')
    elif damage=='inf':pair['after']=float('inf')
    elif damage=='bool':pair['after']=True
    elif damage=='unknown_mode':p['mode']='any_positive'
    elif damage=='extra_permission':p['anything']=True
    else:p['operations']=[]
    with pytest.raises(ValueError):checked(configured(loaded),configured(loaded),loaded,p)


def test_baseline_uses_exact_authority_values_not_500_or_4000(loaded):
    for t,row in zip(loaded['deep_targets'],loaded['guide_parameters']['expected_parameters']['parameters'][4:]):
        row['nc']['feeds_compensation'].update(XYFeed=640.,GetSpndlSpeed=3200.)
        t['reference_nc']=deepcopy(row['nc']['feeds_compensation'])
    assert m.baseline_contract(loaded)==loaded['guide_parameters']['expected_parameters']
    loaded['deep_targets'][0]['reference_nc']['XYFeed']=500.
    with pytest.raises(ValueError,match='Authoritative'):m.baseline_contract(loaded)


def test_pure_delta_contract_supports_arbitrary_ids_and_group_count():
    old=[{'operation_native_id':7,'nc':{'feeds_compensation':{'XYFeed':80.}},'kept':'raw'},
         {'operation_native_id':91,'nc':{'feeds_compensation':{'XYFeed':120.}},'kept':'protected'}]
    new=deepcopy(old);new[0]['nc']['feeds_compensation']['XYFeed']=90.
    p={'mode':'nominal_geometry_only','source_sha256':'c'*64,'tool_native_id':28,'operations':[{'operation_native_id':7,'xy_feed_pairs':[{'before':80.,'after':90.}]}]}
    result=m.verify_post_generation_parameters(old,new,selected_ids=[7],policy=p,source_sha256='c'*64,tool_native_id=28)
    assert len(result['permitted_changes'])==1


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(m.cl,'_verified',lambda a:{'parse_complete':True})
    monkeypatch.setattr(m.DeepGuideHooks,'verify_protected_cl',staticmethod(lambda a,b:{'protected_ten_complete_streams_verified':True}))
    monkeypatch.setattr(m.cl,'verify_no_new_cutcom',lambda x:{'absent':True})
    def save_stage(report,**kw):
        before=kw['capture']('before');kw['verify'](before);kw['guard']();kw['claim']();assert kw['save']()==0;kw['saved_hash']();kw['verify'](kw['capture']('after'))
    monkeypatch.setattr(m.config.save_core,'run_one_existing_save',save_stage)


class Backend(prior.FakeBackend):
    def __init__(self,loaded,journal,feed=None,damage=None):super().__init__(loaded,journal,damage);self.feed=feed
    def generate(self,t,pending):
        result=super().generate(t,pending)
        if self.feed is not None:
            next(r for r in self.snapshot['parameters']if r['operation_native_id']==t['operation_native_id'])['nc']['feeds_compensation']['XYFeed']=self.feed
        return result
    def outcome(self,t):return dict(operation_native_id=t['operation_native_id'],feature_native_id=t['feature_native_id'],background_over_before=False,background_over_after=False,generated=True,generated_for_feature=True,record_counts=[100+t['operation_native_id']])


@pytest.mark.parametrize('feed',[None,1000.])
def test_full_fresh_group_preserves_order_saves_once_and_exports_actual_checkpoint(loaded,engine,feed):
    j=prior.FakeJournal()
    if feed is not None:j.report['request'][m.POLICY_KEY]=policy(loaded)
    b=Backend(loaded,j,feed);r=m.run_replacement_group(b,j,loaded,m.DeepGuideHooks())
    assert r['readback_verified'],r.get('issue')
    assert b.calls==['start',*[f'SetTool:{i}'for i in m.IDS],*[f'GTP:{i}'for i in m.IDS],'Save','CL:saved','finish']
    checkpoint=r['replacement_checkpoint_context']
    assert len(checkpoint['operation_order'])==17 and len(checkpoint['generated_ids'])==14
    assert all(t['reference_nc']['XYFeed']==(feed or 500.)for t in checkpoint['learned_targets'])
    assert all(row['nc']['feeds_compensation']['XYFeed']==500. for row in r['configured']['parameters'][4:])
    assert r['saved']==r['generated']and not r['production_qualified'] and b.closed


@pytest.mark.parametrize('feed,allow',[(1000.,False),(1234.,True)])
def test_unknown_feed_preserves_all_completed_gtp_and_stops_before_save(loaded,engine,feed,allow):
    j=prior.FakeJournal()
    if allow:j.report['request'][m.POLICY_KEY]=policy(loaded)
    b=Backend(loaded,j,feed);r=m.run_replacement_group(b,j,loaded,m.DeepGuideHooks())
    assert r['status']=='uncertain'and not r['readback_verified']
    assert all(r['actions']['GTP:'+str(i)]['readback_verified'] for i in m.IDS)
    assert r['failed_phase']=='post_generation_parameter_validation' and r['completed_gtp_ids']==list(m.IDS)
    assert r['post_generation_validation']['native_regeneration_must_not_replay']
    assert not r['post_generation_validation']['verified']and 'Save'not in b.calls and 'CL:saved'not in b.calls
    assert [x for x in b.calls if x.startswith('GTP')]==['GTP:'+str(i)for i in m.IDS]
    assert all(row['nc']['feeds_compensation']['XYFeed']==feed for row in r['generated']['parameters'][4:])
    with pytest.raises(ValueError):m.run_replacement_group(b,j,loaded,m.DeepGuideHooks())


@pytest.mark.parametrize('damage',['protected','feed','gtp_unknown','nc_unconfirmed'])
def test_assignment_or_unknown_native_failure_never_saves(loaded,engine,damage):
    j=prior.FakeJournal();b=Backend(loaded,j,damage=damage);r=m.run_replacement_group(b,j,loaded,m.DeepGuideHooks())
    assert r['status']=='uncertain'and 'Save'not in b.calls and b.closed


def test_historical_producer_never_mutated():
    assert m.historical._file_hash(m.historical.__file__)=='fd7986e4bb13646f89f1d3f263906508005b3085a8527af0eb3955fddf6d4487'
    assert 'is True' in inspect.getsource(m.historical.NativeBackend.generate)
    source=inspect.getsource(m.run_replacement_group)
    assert '330'not in source and 'IDS'not in source and 'Z:/'not in source


@pytest.fixture
def preflight(tmp_path,monkeypatch,loaded):
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'unchanged source')
    metadata=tmp_path/'camworks.tlb';metadata.write_bytes(b'ABI fixture')
    pins=[m.common._pin(m.historical.__file__),m.common._pin(metadata)]
    for i in range(61):
        path=tmp_path/f'live{i}.py';path.write_bytes(b'evidence');pins.append(m.common._pin(path))
    loaded.update(pins=pins,checkpoint_pins=[],generated_pin=pins[-1])
    loaded['guide_parameters'].update(document={'path':str(source),'title':source.name,'type':1,'needs_save':False},configuration={'sw_configuration_name':'fixture'})
    p={key:'unused'for key in m.PARAMS}
    p.update(process_id=9,expected_document_path=str(source),expected_source_sha256=m.historical._file_hash(source),
        module_sha256=m.historical._file_hash(m.__file__),tool_creation_receipt_path=str(tmp_path/'creator.json'),tool_creation_receipt_sha256='c'*64,
        receipt_path=str(tmp_path/'receipt.json'),progress_path=str(tmp_path/'progress.json'),saved_cl_path=str(tmp_path/'route.cl'),
        acknowledgement='assign_existing_four_only_geometric_feeds_not_production_qualified')
    Path(p['tool_creation_receipt_path']).write_text('{}')
    context={'long_cut_tool_checkpoint':{'registration':{'clsid':'fixture'}}}
    calls=[]
    def loader(*a,**kw):calls.append((a,kw));return context
    monkeypatch.setattr(m.historical,'projection_from_creation',lambda x:deepcopy(loaded))
    monkeypatch.setattr(m.authority,'read_pin',lambda *a:({'saved_source_sha256':p['expected_source_sha256'],'process_id':9},m.common._pin(p['tool_creation_receipt_path'])))
    monkeypatch.setattr(m.common,'discover_export_registration',lambda *a:{'addin_path':str(tmp_path/'CAMWorks.dll')})
    monkeypatch.setattr(m.historical,'audit_interfaces',lambda *a:{'metadata_only':True})
    monkeypatch.setattr(m.common,'local_evidence_root',lambda:tmp_path)
    monkeypatch.setattr(m.common,'_local_receipt',lambda x:Path(x))
    monkeypatch.setattr(m.cl,'_fresh_path',lambda x:Path(x))
    return {'action':m.ACTION,'params':p},loaded,loader,calls


@pytest.mark.parametrize('explicit',[False,True])
def test_actual_prepare_real_guard64_sealed_policy_and_source_marker(preflight,monkeypatch,explicit):
    from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
    request,loaded,loader,calls=preflight
    if explicit:
        request['params'][m.POLICY_KEY]=policy(loaded)
        request['params'][m.POLICY_KEY]['source_sha256']=request['params']['expected_source_sha256']
    original=deepcopy(request)
    monkeypatch.setattr(ScopedCamDispatchGuard,'__enter__',lambda *a:(_ for _ in()).throw(AssertionError('offline must not enter')))
    p,new,*rest=m.prepare_request(request,creation_loader=loader)
    assert request==original and len(calls)==1
    assert len(new['pins'])==64 and new['native_guard_preflight']['constructor_verified']
    assert rest[-2]==m.historical.marker_path(p)
    assert p['module_sha256']==m.historical._file_hash(m.__file__)
    assert p.get(m.POLICY_KEY)==original['params'].get(m.POLICY_KEY)
    assert new['historical_engine_pin']==m.common._pin(m.historical.__file__)


@pytest.mark.parametrize('damage',['unknown_policy','wrong_module','existing_marker','live65'])
def test_prepare_rejects_before_native(preflight,damage,tmp_path):
    request,loaded,loader,calls=preflight
    if damage=='unknown_policy':request['params'][m.POLICY_KEY]={'mode':'any_positive'}
    elif damage=='wrong_module':request['params']['module_sha256']='f'*64
    elif damage=='existing_marker':m.marker_path(request['params']).write_text('claimed')
    else:
        p=tmp_path/'overflow.py';p.write_bytes(b'overflow');loaded['pins'].append(m.common._pin(p))
    with pytest.raises(ValueError):m.prepare_request(request,creation_loader=loader)
    if damage=='wrong_module':assert calls==[]


def test_source_marker_cannot_be_bypassed_with_new_feed_permission(preflight):
    request,loaded,loader,calls=preflight;marker=m.marker_path(request['params']);marker.write_text('claimed')
    request['params'][m.POLICY_KEY]=policy(loaded)
    request['params'][m.POLICY_KEY]['source_sha256']=request['params']['expected_source_sha256']
    with pytest.raises(ValueError,match='once marker'):m.prepare_request(request,creation_loader=loader)



def test_generic_runner_accepts_one_authorized_operation_without_deep_ids(loaded,engine):
    original=330;replacement_id=7
    baseline=loaded['guide_parameters']['expected_parameters']
    next(r for r in baseline['binding']['operations']if r['native_id']==original)['native_id']=replacement_id
    row=next(r for r in baseline['parameters']if r['operation_native_id']==original);row['operation_native_id']=replacement_id
    target=deepcopy(loaded['deep_targets'][0]);target['operation_native_id']=replacement_id;loaded['deep_targets']=[target]
    class Hooks:
        baseline=staticmethod(lambda value:value['guide_parameters']['expected_parameters'])
        fields=staticmethod(lambda target:m.config.ROUGH_FIELDS)
        verify_restorable=staticmethod(m.historical.verify_restorable)
        verify_protected_cl=staticmethod(lambda a,b:{'generic_protected_streams':True})
        @staticmethod
        def verify_route(before,after,wanted,changed,generated=None):
            expected=deepcopy(before)
            for entry in expected['operations']:
                if entry['native_id']in changed:
                    entry['assigned_tool']=deepcopy(wanted)
                    if generated is not None:entry['toolpath_generated']=True;entry['toolpath_record_counts']=generated[entry['native_id']]
            assert expected==after
        @staticmethod
        def verify_configured(before,after,wanted):
            expected=deepcopy(before)
            next(r for r in expected if r['operation_native_id']==replacement_id)['tool']=deepcopy(wanted)
            assert expected==after
    j=prior.FakeJournal();b=Backend(loaded,j);r=m.run_replacement_group(b,j,loaded,Hooks())
    assert r['readback_verified'],r.get('issue')
    assert b.calls==['start','SetTool:7','GTP:7','Save','CL:saved','finish']
    assert [t['operation_native_id']for t in r['replacement_checkpoint_context']['learned_targets']]==[7]
    assert r['completed_gtp_ids']==[7]
