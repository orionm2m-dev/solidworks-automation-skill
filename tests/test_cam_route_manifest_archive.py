"""归档字节、重放标记与引用图的合成回归测试。"""
from base64 import b64encode
from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts import sw_cam_route_manifest as m


def write_pin(path,data):
    path.write_bytes(data if isinstance(data,bytes) else json.dumps(data).encode())
    return dict(path=str(path),canonical_path=str(path.resolve()),sha256=m._file_hash(path),bytes=path.stat().st_size)

@pytest.fixture
def archive(tmp_path):
    owned=write_pin(tmp_path/'owned.json',dict(status='ok'))
    completed=dict(scope='MILL_ENTRY_EDIT_WORKING_SAVE_V1',phase='finished',status='review_required',automatic_replay=False)
    good=write_pin(tmp_path/('save_'+'a'*64+'.json'),completed)
    unknown=write_pin(tmp_path/('move_'+'b'*64+'.json'),dict(status='uncertain',automatic_replay=False))
    profile=write_pin(tmp_path/'synthetic.mh',b'synthetic native profile input')
    code=write_pin(tmp_path/'historical.py',b'raise RuntimeError("must not execute archived code")')
    pins=[owned,good,unknown,profile,code]
    return m._archive(pins,owned['canonical_path']),pins


def test_archive_roundtrip_preserves_bytes_and_active_roles(archive):
    audit,pins=archive;decoded=m._unpack(audit)
    assert all(decoded[p['sha256']]==Path(p['path']).read_bytes() for p in pins)
    assert [r['role'] for r in audit['references']]==['owned_session','historical_replay_marker','active_replay_marker','current_profile_input','historical_implementation']

@pytest.mark.parametrize('status,pending,expected',[
 ('review_required',False,'historical_replay_marker'),('uncertain',False,'active_replay_marker'),
 ('review_required',True,'active_replay_marker'),('error',False,'active_replay_marker')])
def test_only_completed_nonpending_known_marker_may_be_archived(status,pending,expected):
    raw=json.dumps(dict(scope='MILL_ENTRY_EDIT_WORKING_SAVE_V1',phase='finished',status=status,native_dispatch_pending=pending,automatic_replay=False)).encode()
    assert m._marker_role(raw)==expected

@pytest.mark.parametrize('field,value',[
 ('scope','UNKNOWN'),('phase','running'),('save_pending',True),('automatic_replay',True)])
def test_uncertain_marker_variants_stay_active(field,value):
    data=dict(scope='MILL_ENTRY_EDIT_WORKING_SAVE_V1',phase='finished',status='review_required');data[field]=value
    assert m._marker_role(json.dumps(data).encode())=='active_replay_marker'

@pytest.mark.parametrize('change',['base64','bytes','digest','duplicate','role','aggregate','metadata','nested','unreferenced'])
def test_archive_tamper_rejected(archive,change):
    audit,_=archive;a=deepcopy(audit);h=next(iter(a['blobs']));blob=a['blobs'][h]
    if change=='base64':blob['chunks']=['!!!!']
    elif change=='bytes':blob['bytes']=True
    elif change=='digest':blob['chunks']=[b64encode(b'changed').decode()]
    elif change=='duplicate':a['references'].append(deepcopy(a['references'][0]))
    elif change=='role':a['references'][2]['role']='historical_replay_marker'
    elif change=='aggregate':a['decoded_bytes']+=1
    elif change=='metadata':a['references'][0]['original_pin']['bytes']+=1
    elif change=='nested':
        raw=json.dumps({'scope':'SAVED_ROUTE_MANIFEST_UNKNOWN'}).encode();new=m.sha256(raw).hexdigest();r=a['references'][0]
        del a['blobs'][h];a['blobs'][new]=dict(bytes=len(raw),chunks=[b64encode(raw).decode()]);r.update(sha256=new,bytes=len(raw));r['original_pin'].update(sha256=new,bytes=len(raw))
    else:a['blobs']['f'*64]=dict(bytes=0,chunks=[])
    with pytest.raises(ValueError):m._unpack(a)


def test_changed_source_bytes_rejected_before_archive(archive):
    _,pins=archive;Path(pins[-1]['path']).write_bytes(b'changed')
    with pytest.raises(ValueError):m._archive(pins,pins[0]['path'])


def test_reference_cannot_follow_foreign_original_path(archive):
    audit,pins=archive;decoded=m._unpack(audit);pin=dict(pins[0],path=str(Path(pins[0]['path']).with_name('foreign.json')),canonical_path=str(Path(pins[0]['path']).with_name('foreign.json')))
    with pytest.raises(ValueError):m._record(audit['references'],decoded,pin)


def test_archive_limits_are_explicit(archive):
    audit,pins=archive
    with pytest.raises(ValueError):m._archive([],pins[0]['path'])
    with pytest.raises(ValueError):m._archive(pins*13,pins[0]['path'])
    invalid=deepcopy(audit);invalid['coverage']='all filesystem'
    with pytest.raises(ValueError):m._unpack(invalid)
