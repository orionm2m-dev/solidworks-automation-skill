"""Offline recovery refuses native failures, partial CL and altered history."""
from pathlib import Path
from copy import deepcopy
import json,os,sys
import pytest
STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE));sys.path.insert(0,str(ROOT))
import scripts
scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_pocket_rough_export_recovery as m


def receipt():
    return dict(scope=m.export.SCOPE,status='uncertain',phase='finished',native_hresult=0,
        native_call_attempted=True,native_call_returned=True,native_dispatch_pending=False,post_cleanup_document_file_verified=True,
        readback_verified=False,output_verified=False,protected_streams_verified=False,checkpoint_export_readback_verified=False,
        before={'state':'recorded'},after={'state':'recorded'},
        phase_proof_error={'type':'ValueError','hresult':None,'locations':[{'file':'sw_cam_pocket_rough_exports.py','function':'preserved_streams','line':96}]},
        messages={'subscribed':True,'disconnected':True,'active':False,'event_count':0,'overflow':False,'callback_errors':[],
          'callback_error_count':0,'subscription_error':None,'disconnect_errors':[]},**{k:False for k in m.FORBIDDEN})


def test_recorded_failure_scope_is_eligible():m.verify_export_receipt(receipt())


@pytest.mark.parametrize('key,value',[('native_hresult',False),('native_hresult',1),('native_dispatch_pending',True),
    ('GTP_attempted',True),('setter_attempted',True),('post_cleanup_document_file_verified',False),('automatic_replay',True)])
def test_native_or_replay_failure_rejected(key,value):
    r=receipt();r[key]=value
    with pytest.raises(ValueError):m.verify_export_receipt(r)


def test_changed_after_rejected():
    r=receipt();r['after']={'state':'changed'}
    with pytest.raises(ValueError):m.verify_export_receipt(r)


def test_other_verification_failure_rejected():
    r=receipt();r['phase_proof_error']['locations'][0]['line']=100
    with pytest.raises(ValueError):m.verify_export_receipt(r)


def five_blocks():
    return ('UNITS/ MM\n'+''.join('OPFEATSTART/op'+str(i)+'\nRAPID/\nGOTO/0,0,1\nOPFEATEND/op'+str(i)+'\n' for i in range(5))+'FINI\n').encode()


def test_balanced_exact_native_counts():
    rows=m.structural_blocks(five_blocks(),[2]*5)
    assert len(rows)==5 and [r['command_count'] for r in rows]==[2]*5


@pytest.mark.parametrize('old,new',[(b'FINI',b''),(b'OPFEATEND/op2',b'OPFEATEND/wrong'),(b'GOTO/0,0,1',b'UNKNOWN/1')])
def test_truncated_mismatched_or_unknown_cl_rejected(old,new):
    with pytest.raises(ValueError):m.structural_blocks(five_blocks().replace(old,new,1),[2]*5)


def test_invented_count_rejected():
    with pytest.raises(ValueError):m.structural_blocks(five_blocks(),[2,2,2,2,3])


def test_exact_historical_parser_retirement_only(tmp_path):
    old=tmp_path/'sw_cam_generic_cl_reader.py';old.write_bytes(b'old parser')
    original=m.common._pin(old);archive=tmp_path/'original_parser.py';archive.write_bytes(old.read_bytes())
    other=tmp_path/'guard.py';other.write_bytes(b'exact guard')
    r={'evidence_pins':[original,m.common._pin(other)],'offline_export_proof_pins':[],'bootstrap_export_pins':[]}
    old.write_bytes(b'new qualified parser')
    result=m.verify_phase_pins(r,str(archive))
    assert result['original_parser_pin']==original
    other.write_bytes(b'changed guard')
    with pytest.raises(ValueError):m.verify_phase_pins(r,str(archive))


def test_wrong_archive_cannot_replace_old_parser(tmp_path):
    old=tmp_path/'sw_cam_generic_cl_reader.py';old.write_bytes(b'old parser');archive=tmp_path/'archive.py';archive.write_bytes(b'other')
    r={'evidence_pins':[m.common._pin(old)],'offline_export_proof_pins':[],'bootstrap_export_pins':[]}
    with pytest.raises(ValueError):m.verify_phase_pins(r,str(archive))
