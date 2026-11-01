"""Corrected checkpoint authority and reused Close/Open path; no live CAD."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace,ModuleType
import importlib.util,json,os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1];RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME));import scripts
for path in (ROOT.parent/'guide_finish_cnc_none_20261102/scripts',ROOT.parent/'guide_finish_cnc_none_fix_20261102/scripts',ROOT/'scripts'):
    if path.is_dir():scripts.__path__.insert(0,str(path))
from scripts import sw_cam_guide_corrected_reopen as m
F=json.loads((RUNTIME/'tests/guide_configuration_shapes.json').read_text())
spec=importlib.util.spec_from_file_location('prior_reopen_tests',RUNTIME/'tests/test_guide_group_reopen.py')
oldtests=importlib.util.module_from_spec(spec);spec.loader.exec_module(oldtests)


def fixture(monkeypatch):
    before=deepcopy(F['initial']);targets=[dict(v,assigned_tool=deepcopy(F['wanted']))for v in F['recipe']['rows']]
    for row,oid in zip(before['binding']['operations'],m.reopen.ORDER):
        row['native_id']=oid
        row['toolpath_generated']=oid not in (195,196,144)
        row['toolpath_record_counts']=[oid+5]if row['toolpath_generated']else[]
    for row in before['parameters']:
        if row['operation_native_id']in m.correction.IDS:
            row['nc']['feeds_compensation'].update(GetCNCComp=1,GetTlpComp=1)
            row['protected_finish']['compensation']=[1,1]
    saved=deepcopy(before);saved['parameters']=m.correction.expected_parameters(before,m.correction.IDS)
    counts={324:[91],328:[93]}
    for row in saved['binding']['operations']:
        if row['native_id']in counts:row['toolpath_record_counts']=counts[row['native_id']]
    parent={'saved':before,'ownership':{'process_id':52},'saved_cl':{'label':'parent'}}
    parentpin={'path':'synthetic_parent.json','sha256':'c'*64};warnings=[{'path':'w1','sha256':'1'*64},{'path':'w2','sha256':'2'*64}]
    selected=dict(expected_parameters=before,baseline=before['binding'],targets=targets,configuration=deepcopy(oldtests.CONFIG))
    monkeypatch.setattr(m,'read_pin',lambda *a:(deepcopy(parent),deepcopy(parentpin)))
    monkeypatch.setattr(m.correction.saved_loader,'completed_generated',lambda *a:(deepcopy(selected),'synthetic-clsid'))
    monkeypatch.setattr(m.correction,'load_warnings',lambda *a:deepcopy(warnings))
    monkeypatch.setattr(m.correction.finish_cl,'verify_protected_eight',lambda *a:True)
    monkeypatch.setattr(m.correction.finish_cl,'verify_finish_without_cutcom',lambda *a:True)
    monkeypatch.setattr(m.cl,'verify_all',lambda *a:True)
    doc=dict(path='synthetic.SLDPRT',title='synthetic.SLDPRT',type=1,needs_save=False)
    r=dict(scope=m.correction.SCOPE,module_pin=m.common._pin(m.correction.__file__),status='saved_finish_cnc_candidate_review_required',phase='finished',
        readback_verified=True,generation_readback_verified=True,protected_cl_verified=True,saved_cl_verified=True,model_saved=True,
        continuation_ready=True,GTP_attempted=True,save_attempted=True,setter_attempted=True,empirical_finish_cutcom_absence_verified=True,
        native_dispatch_pending=False,automatic_retry=False,SetTool_attempted=False,operation_creation_attempted=False,persistence_after_reopen_verified=False,
        messages=deepcopy(oldtests.MESSAGES),changed_operation_ids=[324,328],regenerated_operation_ids=[324,328],actions={},
        generated_checkpoint_pin=deepcopy(parentpin),warning_receipt_pins=warnings,candidate_readbacks=[],
        before=before,generated=deepcopy(saved),saved=saved,recipe=targets,ownership={'process_id':52},request={'process_id':52},
        source_path=doc['path'],source_sha256='a'*64,saved_source_sha256='b'*64,before_cl=deepcopy(parent['saved_cl']),generated_cl={},saved_cl={})
    for target in [v for v in targets if v['operation_native_id']in m.correction.IDS]:
        oid=target['operation_native_id'];old=m.correction.nc_row(before,oid)['nc']['feeds_compensation'];new=m.correction.nc_row(saved,oid)['nc']['feeds_compensation']
        r['candidate_readbacks'].append(dict(operation_native_id=oid,before=deepcopy(old),after=deepcopy(new),proof=m.correction.candidate.verify_candidate_readback(old,new)))
        action=dict(status='verified',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,native_return=m.group.return_observation(0))
        r['actions']['SetCNCComp:'+str(oid)]=deepcopy(action)
        r['actions']['GenerateToolpath:'+str(oid)]=dict(action,observed=dict(operation_native_id=oid,feature_native_id=target['feature_native_id'],generated=True,
            generated_for_feature=True,record_counts=counts[oid],background_over_before=False,background_over_after=False))
    r['actions']['SaveActiveDocument']=deepcopy(action)
    r['source_transition']=dict(strict_save_return=0,source_before_sha256='a'*64,source_after_sha256='b'*64,document=doc)
    r['saved_checkpoint_context']=dict(process_id=52,ownership={'process_id':52},document=doc,source_sha256='b'*64,prior_source_sha256='a'*64,
        snapshot_key='saved',snapshot_sha256=m.group._digest(saved),prior_generated_checkpoint_pin=parentpin,persistence_after_reopen_verified=False,configuration=oldtests.CONFIG)
    return r,dict(process_id=52,expected_document_path=doc['path'],expected_source_sha256='b'*64)


def test_corrected_authority_retains_all_ten_saved_paths(monkeypatch):
    r,p=fixture(monkeypatch);selected,addin=m.completed_corrected(r,p)
    assert selected['expected_parameters']==r['saved']and addin=='synthetic-clsid'
    assert sum(v['toolpath_generated']for v in selected['baseline']['operations'])==10
    assert [v['native_id']for v in selected['baseline']['operations']]==m.reopen.ORDER


@pytest.mark.parametrize('bad',['scope','module','save','setter','cutcom_proof','pending','repeat','source','dirty','hash','parameter','path','history','before_cl','warnings','candidate','offset','candidate_proof','save_transition','wrong_pid','cl','cutcom','protected_cl'])
def test_corrected_authority_rejects_incomplete_or_rebound_state(monkeypatch,bad):
    r,p=fixture(monkeypatch)
    if bad=='scope':r['scope']=m.reopen.SCOPE
    if bad=='module':r['module_pin']['sha256']='f'*64
    if bad=='save':r['model_saved']=False
    if bad=='setter':r['setter_attempted']=False
    if bad=='cutcom_proof':r['empirical_finish_cutcom_absence_verified']=False
    if bad=='pending':r['actions']['GenerateToolpath:324']['native_dispatch_pending']=True
    if bad=='repeat':r['actions']['GenerateToolpath:322']=deepcopy(r['actions']['GenerateToolpath:324'])
    if bad=='source':p['expected_source_sha256']='e'*64
    if bad=='dirty':r['saved_checkpoint_context']['document']['needs_save']=True
    if bad=='hash':r['saved_checkpoint_context']['snapshot_sha256']='e'*64
    if bad=='parameter':r['saved']['parameters'][0]['nc']['extra']=1
    if bad=='path':r['saved']['binding']['operations'][2]['toolpath_record_counts']=[999]
    if bad=='history':r['generated_checkpoint_pin']['sha256']='e'*64
    if bad=='before_cl':r['before_cl']['label']='unrelated'
    if bad=='warnings':r['warning_receipt_pins']=[]
    if bad=='candidate':r['candidate_readbacks'][0]['after']['GetCNCComp']=1
    if bad=='offset':m.correction.nc_row(r['saved'],324)['nc']['feeds_compensation']['GetTlpComp']=0
    if bad=='candidate_proof':r['candidate_readbacks'][0]['proof']['raw_zero_readback_verified']=False
    if bad=='save_transition':r['source_transition']['strict_save_return']=True
    if bad=='wrong_pid':p['process_id']=53
    fail=lambda *a:(_ for _ in()).throw(ValueError('CL changed'))
    if bad=='cl':monkeypatch.setattr(m.cl,'verify_all',fail)
    if bad=='cutcom':monkeypatch.setattr(m.correction.finish_cl,'verify_finish_without_cutcom',fail)
    if bad=='protected_cl':monkeypatch.setattr(m.correction.finish_cl,'verify_protected_eight',fail)
    with pytest.raises(ValueError):m.completed_corrected(r,p)


@pytest.mark.parametrize('failed',[False,True])
def test_reused_lifecycle_never_saves_or_generates_and_rejects_changed_cl(tmp_path,monkeypatch,failed):
    b,oldjournal,loaded=oldtests.setup(tmp_path)
    report=dict(scope=m.SCOPE,source_path='synthetic.SLDPRT',source_sha256='b'*64,corrected_checkpoint_pin={'path':'corrected.json','sha256':'e'*64})
    journal=m.Journal(report,tmp_path/'corrected_reopen.json',tmp_path/'corrected_marker.json')
    def finish():
        b.trace.append('export')
        if failed:raise ValueError('CL mismatch')
        report['cl_persistence_verified']=True;b.trace.append('finish')
    b.finish=finish
    result=m.reopen.run_backend(b,journal,loaded)
    assert b.trace.count('native_close')==b.trace.count('native_open')==1
    assert result['persistence_after_reopen_verified']is(not failed)
    assert not result['GTP_attempted']and not result['save_attempted']
    before=(journal.receipt.read_bytes(),journal.marker.read_bytes())
    with pytest.raises(ValueError):m.reopen.run_backend(b,journal,loaded)
    assert before==(journal.receipt.read_bytes(),journal.marker.read_bytes())


def test_parameter_backend_has_read_only_behavior():
    for name in ('generate','regenerate','save','assign','set_candidate'):
        assert not hasattr(m.ParameterBackend,name)
    assert m.ParameterBackend.batch is m.generation.NativeBackend.batch
    assert m.ParameterBackend.capture_binding is m.generation.NativeBackend.capture_binding


def test_native_readers_are_reused_without_reimplementation():
    assert m.ParameterBackend is m.correction.saved_loader.ParameterBackend
    assert m.NativeBackend is m.correction.saved_loader.NativeBackend


def test_zero_attempt_lineage_is_rechecked(monkeypatch):
    r,p=fixture(monkeypatch);pin={'path':'failed.json','sha256':'d'*64}
    r['zero_attempt_predecessor_pin']=pin;r['request'].update(zero_attempt_receipt_path=pin['path'],zero_attempt_receipt_sha256=pin['sha256'])
    seen=[]
    def load(request,loaded):
        seen.append((request,loaded));return {},deepcopy(pin),[],''
    monkeypatch.setattr(m.correction,'load_zero_attempt',load)
    m.completed_corrected(r,p);assert len(seen)==1 and seen[0][1]['generated']['saved']==r['before']
    r['zero_attempt_predecessor_pin']=dict(pin,sha256='f'*64)
    with pytest.raises(ValueError):m.completed_corrected(r,p)


def test_missing_zero_attempt_pin_rejected(monkeypatch):
    r,p=fixture(monkeypatch);r['request']['zero_attempt_receipt_path']='failed.json'
    with pytest.raises(ValueError):m.completed_corrected(r,p)
