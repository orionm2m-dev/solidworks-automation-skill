"""Portable offline regression; all identities and documents are synthetic."""
from pathlib import Path
import hashlib,os,sys
import pytest
from scripts import sw_cam_wip_complete_dispatch_guard as m

def args(tmp_path,count):
 source=tmp_path/'source.sldprt';source.write_bytes(b'saved')
 pins=[]
 for n in range(count):
  p=tmp_path/f'pin{n:03}.bin';b=f'pin{n:03}'.encode();p.write_bytes(b);pins.append(dict(path=str(p),sha256=hashlib.sha256(b).hexdigest(),bytes=len(b)))
 return dict(process_id=42,expected_document=dict(path=str(source),title='source',type=1,needs_save=False),source_sha256=hashlib.sha256(b'saved').hexdigest(),evidence_pins=pins,verify_evidence=lambda:None,verify_owned_process=lambda:None,check_events=lambda:None)

class NoApplication:
 def __getattribute__(self,name):raise AssertionError('No application access: '+name)

@pytest.mark.parametrize('count',[1,64,65,128,129,192,193,256])
def test_all_unique_pins_retained_and_no_native_access(tmp_path,count):
 a=args(tmp_path,count);g=m.WipCompleteDispatchGuard(NoApplication(),'metadata-only',**a)
 assert len(g._rows)==count+1
 assert {x[2]for x in g._rows}=={str(Path(p['path']).resolve()).casefold()for p in a['evidence_pins']}|{str(Path(a['expected_document']['path']).resolve()).casefold()}
 assert g._wip_pin_preflight['validated_chunks']==(count+63)//64
 assert g._wip_pin_preflight['maximum_evidence_pins']==256 and g._active is False

@pytest.mark.parametrize('count',[0,257])
def test_outside_bound_rejected_before_any_native(tmp_path,count):
 with pytest.raises(ValueError,match='between 1 and 256'):m.WipCompleteDispatchGuard(NoApplication(),'metadata-only',**args(tmp_path,count))

@pytest.mark.parametrize('index',[64,128,192,255])
def test_bad_metadata_in_every_extra_chunk_rejected(tmp_path,index):
 a=args(tmp_path,256);a['evidence_pins'][index]['bytes']+=1
 with pytest.raises(ValueError,match='byte length'):m.WipCompleteDispatchGuard(NoApplication(),'metadata-only',**a)

@pytest.mark.parametrize('index',[64,128,192])
def test_duplicate_conflict_across_chunks_rejected(tmp_path,index):
 a=args(tmp_path,256);a['evidence_pins'][index]=dict(a['evidence_pins'][0],sha256='f'*64)
 with pytest.raises(ValueError,match='Conflicting hashes across'):m.WipCompleteDispatchGuard(NoApplication(),'metadata-only',**a)

def test_identical_duplicate_in_third_and_fourth_chunk_deduplicated(tmp_path):
 a=args(tmp_path,256)
 for i in(64,128,192):a['evidence_pins'][i]=dict(a['evidence_pins'][0])
 g=m.WipCompleteDispatchGuard(NoApplication(),'metadata-only',**a)
 assert len(g._rows)==254 and g._wip_pin_preflight['evidence_pin_count']==256

def test_entire_combined_union_hashed_at_each_inherited_boundary(tmp_path,monkeypatch):
 a=args(tmp_path,193);g=m.WipCompleteDispatchGuard(NoApplication(),'metadata-only',**a);g._identity=lambda:None
 seen=[];original=m.base._file_hash
 def hashfile(path):seen.append(str(Path(path).resolve()).casefold());return original(path)
 monkeypatch.setattr(m.base,'_file_hash',hashfile)
 invoked=[]
 with g:
  result=g.dispatch_once(lambda:invoked.append('once')or True,persist_pending=lambda:None)
  with pytest.raises(ValueError):g.dispatch_once(lambda:invoked.append('twice'),persist_pending=lambda:None)
 assert result is True and invoked==['once']
 expected={x[2]for x in g._rows};assert set(seen)==expected and all(seen.count(path)>=3 for path in expected)
 assert g.summary()['unique_file_count']==194 and g.summary()['wip_complete_evidence']['validated_chunks']==4

def test_last_chunk_hash_mismatch_stops_before_entered_dispatch(tmp_path):
 a=args(tmp_path,193);a['evidence_pins'][-1]['sha256']='f'*64
 g=m.WipCompleteDispatchGuard(NoApplication(),'metadata-only',**a);g._identity=lambda:None;invoked=[]
 with pytest.raises(ValueError,match='Pinned content changed'):
  with g:g.dispatch_once(lambda:invoked.append(1),persist_pending=lambda:None)
 assert invoked==[]and g._active is False and g._invalid is True
