from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import importlib.util
import pytest
S=Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location('saved_configuration_staged',S/'scripts/sw_cam_saved_wall_configuration.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.fixture
def report():
    return dict(scope=m.writer.SCOPE,status='saved_configuration_no_toolpath',phase='finished',model_saved=True,readback_verified=True,phase_proofs_verified=True,
        actions={'SaveActiveDocument':{}},setter_attempted=False,assignment_attempted=False,GTP_attempted=False,automatic_replay=False,geometry_acceptance_complete=False,production_qualified=False,generated_record_counts=[],
        loaded_context_before={'neck_tool_checkpoint':{},'generated_pocket_finish':{'stale':True}},latest_status={},before={},final={'state':{'saved':True},'parameters':{'new':True},'startpoints':[1],'catalogue':[2]},
        saved_source_sha256='b'*64,initial_source_sha256='a'*64,save_stage={'save_readback_verified':True,'saved_file_sha256':'b'*64},source_transition={'strict_save_return':0,'source_before_sha256':'a'*64,'source_after_sha256':'b'*64})

@pytest.fixture
def boundaries():
    with patch.object(m.parent,'qualify_scope'),patch.object(m.parent,'no_output'),patch.object(m.parent,'verify_capture') as capture,patch.object(m.parent.wall,'save_projection',side_effect=lambda x:x),patch.object(m.parent.wall,'equivalent_projection'),patch.object(m.parent.wall.history,'verified_action'),patch.object(m.parent.original,'projected',side_effect=deepcopy),patch.object(m.group,'current_projection',side_effect=deepcopy),patch.object(m,'clean_events'):
        yield capture


def test_saved_configuration_uses_final_state_without_path(report,boundaries):
    got=m.validate_saved(report)
    assert got['state']==report['final']['state'] and got['pocket_parameters']==report['final']['parameters']
    assert got['source_sha256']=='b'*64 and 'generated_pocket_finish' not in got
    assert boundaries.call_args_list[0].kwargs==dict(corrected=True,generated=False)
    assert boundaries.call_args_list[1].kwargs==dict(corrected=True,generated=False,saved_sha='b'*64)
    assert 'generated_pocket_finish' in report['loaded_context_before']

@pytest.mark.parametrize('key,value',[('readback_verified',False),('phase_proofs_verified',False),('status','uncertain'),('model_saved',False),('generated_record_counts',[1]),('GTP_attempted',True),('setter_attempted',True),('production_qualified',True),('actions',{'GenerateToolpath':{}}),('issue',{})])
def test_non_authoritative_receipt_rejected(report,boundaries,key,value):
    report[key]=value
    with pytest.raises(ValueError):m.validate_saved(report)

@pytest.mark.parametrize('delta',[{'strict_save_return':True},{'source_after_sha256':'c'*64},{'source_before_sha256':'b'*64}])
def test_save_transition_is_strict(report,boundaries,delta):
    report['source_transition'].update(delta)
    with pytest.raises(ValueError):m.validate_saved(report)

@pytest.mark.parametrize('change',['process','source','digest','writer'])
def test_loader_binds_process_source_and_writer(tmp_path,report,boundaries,change):
    source=tmp_path/'part.sldprt';source.write_bytes(b'saved');sha=m._file_hash(source);pin={'path':'receipt','sha256':'d'*64};writer={'path':'writer','sha256':'e'*64}
    report.update(module_pin=writer,process_id=123,source_path=str(source),saved_source_sha256=sha,live_pins=[],offline_proof_pins=[],bootstrap_export_pins=[])
    if change=='process':report['process_id']=124
    if change=='source':report['source_path']=str(tmp_path/'other.sldprt')
    if change=='digest':report['saved_source_sha256']='0'*64
    if change=='writer':report['module_pin']={}
    with patch.object(m,'read_pin',return_value=(report,pin)),patch.object(m.common,'_pin',return_value=writer):
        with pytest.raises(ValueError):m.load_completed('receipt','d'*64,process_id=123,expected_document_path=str(source),expected_source_sha256=sha)
