"""Full completed-packet authority regression with saved read-only fixture."""
from copy import deepcopy
from pathlib import Path
import importlib.util,os,sys
import pytest
R=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).resolve().parents[1]))).resolve()
sys.path.insert(0,str(R));import scripts
scripts.__path__.insert(0,os.environ.get('SW_CAM_DEEP_CHECKPOINT_MODULE_ROOT',str(R/'scripts')))
from scripts import sw_cam_deep_guide_checkpoint as m

@pytest.fixture(scope='session')
def fixture_source():
    evidence=os.environ.get('SW_CAM_DEEP_GUIDE_EVIDENCE_ROOT')
    if not evidence:pytest.skip('Optional historical reader fixture requires SW_CAM_DEEP_GUIDE_EVIDENCE_ROOT')
    spec=importlib.util.spec_from_file_location('writer_test_fixture',R/'tests/test_deep_writer.py')
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    return old,old.saved.__wrapped__()


def full_report(fixture_source,tmp_path,monkeypatch):
    old,l=fixture_source;l=deepcopy(l)
    original=l['guide_parameters'];r=dict(scope=m.writer.SCOPE,module_pin=m.common._pin(m.writer.__file__),source_path=original['document']['path'],source_sha256='a'*64,
      request=dict(process_id=123,source_backup_path='independent_backup.SLDPRT',source_backup_sha256='a'*64,choices={}),ownership={'process_id':123},
      inspect_receipt_pin={'path':'inspect.json','sha256':'c'*64},live_pins=[],checkpoint_pins=[],zero_attempt_predecessor={'confirmed':True})
    class Recorded(old.FakeBackend):
        def capture_snapshot(self,label,**kw):
            value=super().capture_snapshot(label,**kw)
            self.report.setdefault('captures',[]).append(dict(label=label,**deepcopy(value)))
            return value
    b=Recorded(l,r);j=m.writer.Journal(r,tmp_path/'writer.json',tmp_path/'marker.json')
    # Persistence/no-replay are covered by writer tests; this fixture tests only
    # the terminal authority and must not rewrite a large report at every field.
    j.persist=lambda:None
    monkeypatch.setattr(m.cl,'_verified',lambda a:{'operation_blocks':[{}]*14})
    monkeypatch.setattr(m.cl.review,'block_signature',lambda p,i:['signature',i])
    monkeypatch.setattr(m.cl,'verify_protected',lambda *a:True)
    monkeypatch.setattr(m.cl,'verify_no_new_cutcom',lambda *a:True)
    monkeypatch.setattr(m.cl,'verify_all',lambda *a:True)
    m.writer.run_backend(b,j,l)
    assert r['status']=='saved_deep_guides_review_required',r.get('issue')
    r['messages']={'active':False,'subscribed':True,'disconnected':True};r['cleanup_session_active']=False
    r['source_transition']['strict_save_return']=0
    # Independent files/read-only historical authority are substituted; the full
    # new completed-packet checks and its actual action/snapshot shapes remain real.
    observed={'request':dict(process_id=123,expected_document_path=r['source_path'],expected_source_sha256='a'*64,
      corrected_receipt_path='prior.json',corrected_receipt_sha256='d'*64),'before':deepcopy(original['expected_parameters']),
      'deep_headers_before':deepcopy(l['deep_headers'])}
    prior={'saved_cl':deepcopy(r['before_cl'])}
    def read(path,sha):return (deepcopy(observed),deepcopy(r['inspect_receipt_pin']))if path=='inspect.json'else(deepcopy(prior),{'path':path,'sha256':sha})
    monkeypatch.setattr(m,'read_pin',read)
    monkeypatch.setattr(m.authority,'completed_corrected',lambda *a:(deepcopy(original),'test-clsid'))
    monkeypatch.setattr(m.authority.cl,'verify_all',lambda *a:True)
    monkeypatch.setattr(m.inspect,'compile_definition_plan',lambda *a:deepcopy(l['deep_plan']))
    monkeypatch.setattr(m.writer,'load_zero_attempt',lambda *a:([],{'confirmed':True}))
    real_pin=m.common._pin
    monkeypatch.setattr(m.common,'_pin',lambda path:deepcopy(l['source_backup_pin'])if path=='independent_backup.SLDPRT'else real_pin(path))
    return r,dict(process_id=123,expected_document_path=r['source_path'],expected_source_sha256='b'*64)


def test_complete_actual_shaped_packet_selects17_14(fixture_source,tmp_path,monkeypatch):
    r,p=full_report(fixture_source,tmp_path,monkeypatch);selected,addin=m.completed_packet(r,p)
    assert addin=='test-clsid'and selected['expected_parameters']==r['saved']
    assert len(selected['baseline']['operations'])==17 and len(selected['expected_parameters']['parameters'])==8
    assert [x['operation_native_id']for x in selected['targets']]==[322,324,326,328]


@pytest.mark.parametrize('bad',['saved_source','backup_alias','backup_sha','zero_lineage','target_id','target_depth','protected_parameter','saved_parameter','saved_route','saved_signature','snapshot_hash','prior_source','save_return','definition_observation','new_nc','count_after_gtp'])
def test_completed_packet_rejects_false_continuation_authority(fixture_source,tmp_path,monkeypatch,bad):
    r,p=full_report(fixture_source,tmp_path,monkeypatch)
    if bad=='saved_source':p['expected_source_sha256']='e'*64
    elif bad=='backup_alias':r['request']['source_backup_path']=r['source_path']
    elif bad=='backup_sha':r['request']['source_backup_sha256']='e'*64
    elif bad=='zero_lineage':r['zero_attempt_predecessor']={}
    elif bad=='target_id':r['saved_checkpoint_context']['learned_targets'][0]['operation_native_id']=999
    elif bad=='target_depth':r['learned_targets'][0]['expected_levels']['levels']['machining_depth_native']=2.
    elif bad=='protected_parameter':r['after_tools']['parameters'][0]['nc']['feeds_compensation']['XYFeed']+=1
    elif bad=='saved_parameter':r['saved']['parameters'][-1]['nc']['feeds_compensation']['GetTlpComp']=0
    elif bad=='saved_route':r['saved']['binding']['operations'][0]['toolpath_generated']=True
    elif bad=='saved_signature':r['saved_checkpoint_context']['saved_CL_block_signature_sha256'][13]='e'*64
    elif bad=='snapshot_hash':r['saved_checkpoint_context']['snapshot_sha256']='e'*64
    elif bad=='prior_source':r['saved_checkpoint_context']['prior_source_sha256']='e'*64
    elif bad=='save_return':r['source_transition']['strict_save_return']=False
    elif bad=='definition_observation':r['actions']['insert:guide80_rough']['observed']['native_id']=999
    elif bad=='new_nc':r['configured']['parameters'][-1]['nc']['feeds_compensation']['GetCNCComp']=1
    elif bad=='count_after_gtp':r['actions']['GTP:407']['observed']['record_counts']=[1]
    with pytest.raises(ValueError):m.completed_packet(r,p)
