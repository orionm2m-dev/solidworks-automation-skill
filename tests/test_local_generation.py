from copy import deepcopy
from pathlib import Path
import pytest
from cam_public_test_support import add_runtime, required_module, required_test_module

R = add_runtime()
f = required_test_module('test_local_operation_group')
context = required_module('sw_cam_local_saved_context')
m = required_module('sw_cam_local_generation')

def fixture():
    baseline,plan,param,old=f.fixture();snapshot=deepcopy(baseline);targets=[]
    for i,(row,oid)in enumerate(zip(plan['rows'],[344,346,348,350])):
        t=dict(deepcopy(row),operation_native_id=oid,assigned_tool=deepcopy(plan['tool']));targets.append(t)
        snapshot['binding']['operations'].append(dict(native_id=oid,setup_index=0,setup_native_id=93,operation_index=17+i,
            mill_operation_type=t['operation_type'],base_operation_type=1,suppressed=False,toolpath_generated=False,toolpath_record_counts=[],linked_feature_ids=[t['feature_native_id']],assigned_tool=deepcopy(plan['tool'])))
        snapshot['binding']['operation_setups'][0]['operation_count']+=1
        p=param(oid,t['feature_native_id'],plan['tool']);p['nc']['feeds_compensation'].update(GetSpndlSpeed=7100.,GetRetractType=0);snapshot['parameters'].append(p)
    nc={str(v['operation_native_id']):dict(values=deepcopy(v['nc']['feeds_compensation']))for v in snapshot['parameters'][8:]}
    return baseline,plan,param,old,snapshot,targets,nc


def workflow(tmp_path,monkeypatch,*,fail=None,drift=None,bad_snapshot=False):
    base,plan,param,old,snap,targets,nc=fixture()
    report=dict(scope=m.SCOPE,source_path=str(tmp_path/'part.sldprt'),source_sha256='a'*64,configuration_receipt_pin=dict(path='config',sha256='c'*64),phase_proof_checks=[dict(phase=k,verified=True)for k in ('before_native_start','before_save','after_export_and_cleanup')])
    journal=m.Journal(report,tmp_path/'receipt.json',tmp_path/'marker.json')
    loaded=dict(guide_parameters=dict(expected_parameters=base),configuration_generation=dict(snapshot=deepcopy(snap),targets=targets,nc_readbacks=nc),generated=dict(saved_cl={}),configuration_receipt_pin=deepcopy(report['configuration_receipt_pin']))
    class Backend(f.Backend):
        def outcome(self,t):return dict(operation_native_id=t['operation_native_id'],feature_native_id=t['feature_native_id'],background_over_before=False,background_over_after=False,generated=True,generated_for_feature=True,record_counts=[100])
        def generate(self,t,pending):
            result=super().generate(t,pending)
            if drift:
                v=next(x for x in self.value['parameters']if x['operation_native_id']==t['operation_native_id'])
                if drift=='feed':v['nc']['feeds_compensation']['XYFeed']=70.
                elif drift=='spindle':v['nc']['feeds_compensation']['GetSpndlSpeed']=8000.
                else:v['levels']['floor']=7.
            return result
        def saved_hash(self,stage):self.j.report['source_transition']=dict(source_before_sha256='a'*64,source_after_sha256='b'*64,strict_save_return=0,document=dict(needs_save=False));return 'b'*64
        def export(self,label,binding):self.calls.append('export');return dict(source_sha256='b'*64)
        def finish(self):self.calls.append('finish');self.j.report['messages']=dict(subscribed=True,disconnected=True,active=False,event_count=0)
    b=Backend(base,plan,param,old,journal,fail_at=fail);b.value=deepcopy(snap)
    if bad_snapshot:b.value['parameters'][-1]['nc']['feeds_compensation']['XYFeed']=36.
    monkeypatch.setattr(m.generation,'close_checked',lambda b,r:b.close())
    monkeypatch.setattr(m.prior.cl,'verify_saved',lambda *args:dict(protected14=True,new4=True))
    return b,journal,loaded


def test_complete_four_only_then_single_save(tmp_path,monkeypatch):
    b,j,l=workflow(tmp_path,monkeypatch);r=m.run_once(b,j,l)
    assert r['readback_verified'],r.get('issue')
    assert b.calls==['start']+['generate']*4+['save','export','finish','close']
    assert list(r['actions'])==['GTP:344','GTP:346','GTP:348','GTP:350','SaveActiveDocument']
    assert m.validate_completed(r,l)['new_generated_paths']==4
    assert not r['parameter_setter_attempted']and not r['tool_assignment_attempted']


@pytest.mark.parametrize('failure',[1,2,3,4])
def test_pending_generation_never_replayed_or_saved(tmp_path,monkeypatch,failure):
    b,j,l=workflow(tmp_path,monkeypatch,fail=failure);r=m.run_once(b,j,l)
    assert b.calls.count('generate')==failure and 'save'not in b.calls
    assert len(r['completed_gtp_counts'])==failure-1 and r['native_dispatch_pending']
    assert not r['readback_verified']


@pytest.mark.parametrize('drift',['feed','spindle','other'])
def test_unexpected_changes_preserve_all_paths_and_stop_before_save(tmp_path,monkeypatch,drift):
    b,j,l=workflow(tmp_path,monkeypatch,drift=drift);r=m.run_once(b,j,l)
    assert b.calls.count('generate')==4 and 'save'not in b.calls and 'export'not in b.calls
    assert len(r['completed_gtp_counts'])==4 and not r['native_dispatch_pending']
    candidate=r['nc_restore_candidate']
    assert candidate['status']==('NOT_PROVEN_NC_ONLY'if drift=='other'else'EXACT_NC_ONLY_DIFFERENCES_REVIEW_REQUIRED')
    assert not candidate['automatic_restore']and not candidate['GTP_replay_allowed']


def test_snapshot_mismatch_zero_mutations(tmp_path,monkeypatch):
    b,j,l=workflow(tmp_path,monkeypatch,bad_snapshot=True);r=m.run_once(b,j,l)
    assert b.calls==['start','close']and not r['mutation_attempted']and r['actions']=={}


def test_reentry_cannot_erase_old_receipt(tmp_path,monkeypatch):
    b,j,l=workflow(tmp_path,monkeypatch);m.run_once(b,j,l)
    old=deepcopy(j.report);files=[j.receipt.read_bytes(),j.marker.read_bytes()];calls=deepcopy(b.calls)
    with pytest.raises(ValueError):m.run_once(b,j,l)
    assert j.report==old and [j.receipt.read_bytes(),j.marker.read_bytes()]==files and b.calls==calls


@pytest.mark.parametrize('name',['insert:left_rough','SetTool:344','344:NC:XYFeed','GTP:100','GTP:1000'])
def test_journal_forbids_old_targets_and_setters(tmp_path,monkeypatch,name):
    b,j,l=workflow(tmp_path,monkeypatch);j.report.update(actual_new_ids=[344,346,348,350],actions={})
    with pytest.raises(ValueError):j.entry(name)
    assert j.report['actions']=={}


@pytest.mark.parametrize('name',['insert','assign','set_field','set_nc'])
def test_backend_forbids_non_generation_mutations(name):
    with pytest.raises(ValueError):getattr(m.NativeBackend,name)(None)


@pytest.mark.parametrize('bad',['extra_action','wrong_outcome','wrong_counts','saved_change','new_policy','production','wrong_target','wrong_source'])
def test_terminal_rejects_altered_authority(tmp_path,monkeypatch,bad):
    b,j,l=workflow(tmp_path,monkeypatch);r=m.run_once(b,j,l)
    if bad=='extra_action':r['actions']['GTP:100']=deepcopy(r['actions']['GTP:344'])
    elif bad=='wrong_outcome':r['actions']['GTP:344']['observed']['operation_native_id']=100
    elif bad=='wrong_counts':r['completed_gtp_counts'][344]=[101]
    elif bad=='saved_change':r['saved']['parameters'][-1]['nc']['feeds_compensation']['XYFeed']=70.
    elif bad=='new_policy':r['feed_policy']['left_rough']=[[35.,70.]]
    elif bad=='production':r['production_qualified']=True
    elif bad=='wrong_target':r['learned_targets'][0]['operation_native_id']=99
    else:r['source_transition']['source_after_sha256']='a'*64
    with pytest.raises(ValueError):m.validate_completed(r,l)


def test_marker_bound_to_source_not_receipt_or_process(tmp_path):
    p=dict(expected_document_path=str(tmp_path/'part.sldprt'),expected_source_sha256='a'*64)
    assert m.marker_path(p)==m.marker_path(dict(p,process_id=999,configuration_receipt_sha256='b'*64))
    assert m.marker_path(p)!=m.marker_path(dict(p,expected_source_sha256='b'*64))


def projection_fixture():
    base,plan,param,old,snap,targets,nc=fixture();doc=dict(path='C:/fixtures/part.sldprt',title='part.sldprt',type=1,needs_save=False)
    owner=dict(process_id=123,create_time=1.,alive=True);catalogue=[dict(native_id=i)for i in range(1,22)];dimensions={'profile':'actual'}
    loaded=dict(guide_parameters=dict(expected_parameters=base,document=deepcopy(doc)),ownership=owner,
        serial_flat_catalogue=catalogue,local_tool_dimensions=dimensions,generated=dict(saved_cl={}),state=dict(document=deepcopy(doc),saved_file_sha256='a'*64))
    r=dict(request=dict(process_id=123),source_path=doc['path'],saved_source_sha256='b'*64,ownership=deepcopy(owner),saved=snap,
        learned_targets=targets,nc_readbacks=nc,source_transition=dict(document=deepcopy(doc)),saved_cl={'current':14})
    r['saved_checkpoint']=dict(source_sha256='b'*64,document=deepcopy(doc),snapshot=deepcopy(snap),learned_targets=deepcopy(targets),saved_cl=deepcopy(r['saved_cl']),current_counts=dict(operations=21,parameters=12,paths=14,tools=21),GTP_complete=False,tool_catalogue=deepcopy(catalogue),tool_dimensions=deepcopy(dimensions))
    p=dict(process_id=123,expected_document_path=doc['path'],expected_source_sha256='b'*64)
    return r,loaded,dict(source_sha256='a'*64),p


def test_current_projection_uses_saved_source_and_full21_without_changing_protected_baseline():
    r,l,o,p=projection_fixture();before=deepcopy((r,l,o));current,outer=context.project_current(r,l,o,p)
    assert current['source_sha256']==outer['source_sha256']=='b'*64
    assert len(current['guide_parameters']['expected_parameters']['parameters'])==8
    assert len(current['configuration_generation']['snapshot']['parameters'])==12
    assert (r,l,o)==before


@pytest.mark.parametrize('bad',['source','pid','lifetime','saved_count','checkpoint','nc','target','catalogue','dirty'])
def test_current_projection_rejects_mixed_authorities(bad):
    r,l,o,p=projection_fixture()
    if bad=='source':p['expected_source_sha256']='c'*64
    elif bad=='pid':p['process_id']+=1
    elif bad=='lifetime':r['ownership']['create_time']=2.
    elif bad=='saved_count':r['saved_checkpoint']['current_counts']['paths']=18
    elif bad=='checkpoint':r['saved_checkpoint']['snapshot']['parameters'][0]['nc']['feeds_compensation']['XYFeed']=99.
    elif bad=='nc':r['nc_readbacks']['344']['values']['XYFeed']=70.
    elif bad=='target':r['learned_targets'][0]['operation_native_id']=999
    elif bad=='catalogue':r['saved_checkpoint']['tool_catalogue'].pop()
    else:r['saved_checkpoint']['document']['needs_save']=True
    with pytest.raises(ValueError):context.project_current(r,l,o,p)


def test_existing_generator_prebind_implementation_reused():
    import inspect
    assert m.NativeBackend.generate is m.prior.NativeBackend.generate
    src=inspect.getsource(m.generation.NativeBackend.generate)
    assert src.index("mill=guard.typed")<src.index('guard.dispatch_once')
    assert "type(guard.read(self.ctx.app,'IsBackgroundProcessForGTPOver'))is bool"in src
    assert 'is True'not in src

def test_real_inherited_constructor_has_no_shadowed_methods(tmp_path,monkeypatch):
    prior_tests=required_test_module('test_local_operation_packet')
    request,outer,loader,_,_=prior_tests._prepared(tmp_path,monkeypatch)
    p,loaded,_,reg,tlb,*_=m.prior.prepare_request(request,creation_loader=loader)
    b=m.NativeBackend(loaded,p,None,reg['clsid'],tlb,{},lambda:None,before_generate=m.prior.nc.before_generate,exporter=m.prior.cl.export_saved)
    assert len(b.protected_targets)==8 and b.ctx.expected_document==outer['state']['document']
    assert all(callable(getattr(b,k))for k in ('capture_snapshot','capture_binding','generate','outcome','save','export'))
    assert b.before_generate is m.prior.nc.before_generate


@pytest.mark.parametrize('pid',[True,False,0,-1,1.5,'123'])
def test_public_saved_loader_rejects_invalid_identity_before_read(pid,monkeypatch):
    monkeypatch.setattr(context.prior,'read_json_pin',lambda *a,**k:pytest.fail('Must reject identity before reading authority'))
    with pytest.raises(ValueError):context.load_completed('unused','a'*64,process_id=pid,expected_document_path='C:/fixtures/a.sldprt',expected_source_sha256='b'*64)


def test_public_loader_checks_current_source_and_preserves_historical_inputs(tmp_path,monkeypatch):
    r,l,o,p=projection_fixture();path=tmp_path/'part.sldprt';path.write_bytes(b'new saved source');sha=m.prior._file_hash(path)
    p.update(expected_document_path=str(path),expected_source_sha256=sha);r.update(source_path=str(path),saved_source_sha256=sha)
    r['source_transition']['document']['path']=str(path);r['saved_checkpoint']['document']['path']=str(path);r['saved_checkpoint']['source_sha256']=sha
    monkeypatch.setattr(context.prior,'read_json_pin',lambda *a,**k:(deepcopy(r),dict(path=str(tmp_path/'receipt.json'),sha256='c'*64)))
    monkeypatch.setattr(context,'reconstruct_configuration',lambda v:(deepcopy(l),deepcopy(o),dict(verified=True),[]))
    monkeypatch.setattr(context.common,'_check',lambda proofs:None)
    result=context.load_completed('unused','c'*64,**p)
    assert result[0]['source_sha256']==sha and result[0]['configuration_receipt_pin']['sha256']=='c'*64
    path.write_bytes(b'changed')
    with pytest.raises(ValueError):context.load_completed('unused','c'*64,**p)
    assert context.load_completed('unused','c'*64,check_current=False,**p)[0]['source_sha256']==sha

def test_current_projection_does_not_require_or_relabel_historical_state():
    r,l,o,p=projection_fixture();l.pop('state')
    current,_=context.project_current(r,l,o,p)
    assert current['state']==dict(document=r['saved_checkpoint']['document'],saved_file_sha256=r['saved_source_sha256'])
    assert 'operations'not in current['state']and len(current['configuration_generation']['snapshot']['binding']['operations'])==21
