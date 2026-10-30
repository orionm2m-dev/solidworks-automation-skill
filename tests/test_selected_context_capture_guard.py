"""Offline guard invariants; no native application calls or timing benchmarks."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
import os
import pytest
from scripts import sw_cam_mill_feature_context as shared
from scripts import sw_cam_circle_lifecycle_evidence as evidence
from test_sw_cam_circular_mill_lifecycle import saved, case
from test_sw_cam_mill_feature_context import context, capture


def tracked_opens(saved, monkeypatch):
    original=Path.open
    streams=[]
    targets={saved.case.part,saved.creator_path}
    def opened(path,*args,**kwargs):
        stream=original(path,*args,**kwargs)
        mode=args[0] if args else kwargs.get('mode','r')
        if path in targets and mode=='rb':streams.append(stream)
        return stream
    monkeypatch.setattr(Path,'open',opened)
    return streams


def stat_copy(value, **changes):
    names=('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_ctime_ns')
    return N(**({name:getattr(value,name) for name in names}|changes))


def test_full_identity_count_is_bounded_not_per_inner_read(saved,monkeypatch):
    ctx=context(saved)
    original_identity=shared.selected_context_identity
    identities=[]
    def full(*args,**kwargs):
        identities.append(kwargs.get('current_source_sha256'))
        return original_identity(*args,**kwargs)
    monkeypatch.setattr(shared,'selected_context_identity',full)
    original_capture=saved.capture
    def many_checks(*args,**kwargs):
        for _ in range(5):kwargs['check']()
        return original_capture(*args,**kwargs)
    saved.capture=many_checks
    before=deepcopy(saved.state)
    state,_=capture(saved,ctx)
    assert identities==[None,None]
    assert state['selected_feature']==before['selected_feature']
    assert state['circle_reference']['solids']==saved.creation['after']['solids']


@pytest.mark.parametrize('switch',['pid','path','missing_doc','nonstr_path'])
def test_inner_native_identity_switch_stops_immediately(saved,monkeypatch,switch):
    ctx=context(saved);streams=tracked_opens(saved,monkeypatch);continued=[]
    def switched(*args,**kwargs):
        assert sum(not stream.closed for stream in streams)==2
        if switch=='pid':monkeypatch.setattr(saved.case.sw,'GetProcessID',lambda:732)
        elif switch=='path':saved.case.document['path']=str(saved.case.tmp_path/'other.sldprt')
        elif switch=='missing_doc':monkeypatch.setattr(saved.case.sw,'ActiveDoc',None)
        else:monkeypatch.setattr(saved.case.model,'GetPathName',lambda:123)
        kwargs['check']();continued.append(True)
    saved.capture=switched
    with pytest.raises(Exception):capture(saved,ctx)
    assert not continued and streams and all(stream.closed for stream in streams)


@pytest.mark.parametrize('target',['source','creator'])
def test_write_during_capture_stops_at_metadata_guard(saved,monkeypatch,target):
    ctx=context(saved);streams=tracked_opens(saved,monkeypatch);continued=[]
    path=saved.case.part if target=='source' else saved.creator_path
    def changed(*args,**kwargs):
        path.write_bytes(path.read_bytes()+b' ')
        kwargs['check']();continued.append(True)
    saved.capture=changed
    with pytest.raises(ValueError,match='metadata changed'):capture(saved,ctx)
    assert not continued and all(stream.closed for stream in streams)


@pytest.mark.parametrize('target',['source','creator'])
def test_replacement_same_size_mtime_is_detected_by_inode(saved,monkeypatch,target):
    ctx=context(saved)
    path=saved.case.part if target=='source' else saved.creator_path
    pinned=path.stat()
    replacement=saved.case.tmp_path/('replacement_'+target)
    replacement.write_bytes(path.read_bytes())
    os.utime(replacement,ns=(pinned.st_atime_ns,pinned.st_mtime_ns))
    replacement_stat=replacement.stat()
    assert replacement_stat.st_size==pinned.st_size
    assert replacement_stat.st_mtime_ns==pinned.st_mtime_ns
    assert replacement_stat.st_ino!=pinned.st_ino
    # Ordinary Windows rb handles may or may not allow rename. Simulate only
    # path resolution to a real distinct file; do not claim rb is a lock.
    # Hold all other stamp fields equal to prove this is identity, not size/time.
    replacement_stamp=stat_copy(pinned,st_ino=replacement_stat.st_ino)
    original_stat=Path.stat;replaced=False
    def path_stat(p,*args,**kwargs):
        return replacement_stamp if replaced and p==path else original_stat(p,*args,**kwargs)
    monkeypatch.setattr(Path,'stat',path_stat)
    def switched(*args,**kwargs):
        nonlocal replaced
        replaced=True
        kwargs['check']()
        raise AssertionError('replacement guard should stop')
    saved.capture=switched
    with pytest.raises(ValueError,match='metadata changed'):capture(saved,ctx)


def test_zero_inode_fails_before_capture_and_closes_handles(saved,monkeypatch):
    ctx=context(saved);streams=tracked_opens(saved,monkeypatch)
    inode=saved.case.part.stat().st_ino;original=os.fstat
    def unusable(fd):
        value=original(fd)
        return stat_copy(value,st_ino=0) if value.st_ino==inode else value
    monkeypatch.setattr(shared.os,'fstat',unusable)
    called=Mock();saved.capture=called
    with pytest.raises(ValueError,match='metadata identity'):capture(saved,ctx)
    called.assert_not_called()
    assert streams and all(stream.closed for stream in streams)


@pytest.mark.parametrize('phase',['legacy','reference','end_identity'])
def test_exception_closes_all_scope_handles(saved,monkeypatch,phase):
    ctx=context(saved);streams=tracked_opens(saved,monkeypatch)
    if phase=='legacy':saved.capture=Mock(side_effect=RuntimeError('capture failure'))
    elif phase=='reference':monkeypatch.setattr(evidence,'verify_circle_reference',Mock(side_effect=RuntimeError('reference failure')))
    else:
        original=shared.selected_context_identity;calls=[]
        def failed_end(*args,**kwargs):
            calls.append(True)
            if len(calls)==2:raise RuntimeError('end failure')
            return original(*args,**kwargs)
        monkeypatch.setattr(shared,'selected_context_identity',failed_end)
    with pytest.raises(RuntimeError,match='failure'):capture(saved,ctx)
    assert streams and all(stream.closed for stream in streams)


def test_partial_handle_acquisition_failure_closes_first(saved,monkeypatch):
    ctx=context(saved);streams=tracked_opens(saved,monkeypatch)
    saved.creator_path.unlink()
    with pytest.raises(FileNotFoundError):capture(saved,ctx)
    assert streams and all(stream.closed for stream in streams)


def test_boundary_full_sha_still_detects_drift_if_metadata_is_unchanged(saved,monkeypatch):
    ctx=context(saved);original=saved.capture
    # Isolate the full-content boundary: adversarial/restored metadata cannot
    # turn the optimized path into a metadata-only cache.
    monkeypatch.setattr(shared._CaptureReadFiles,'check',lambda self:None)
    def altered(*args,**kwargs):
        value=original(*args,**kwargs)
        data=saved.case.part.read_bytes()
        saved.case.part.write_bytes(bytes([data[0]^1])+data[1:])
        return value
    saved.capture=altered
    with pytest.raises(ValueError,match='source SHA'):capture(saved,ctx)


@pytest.mark.parametrize('field,value',[('title','changed title'),('needs_save',False),('type',2)])
def test_end_full_identity_preserves_fields_not_in_light_guard(saved,monkeypatch,field,value):
    ctx=context(saved);original=saved.capture
    if field=='needs_save':value=not saved.case.document[field]
    def altered(*args,**kwargs):
        result=original(*args,**kwargs)
        saved.case.document[field]=value
        return result
    saved.capture=altered
    with pytest.raises(ValueError):capture(saved,ctx)


def test_events_still_stop_and_close_scope(saved,monkeypatch):
    ctx=context(saved);streams=tracked_opens(saved,monkeypatch);event=False
    def check():
        if event:raise RuntimeError('event failure')
    def changed(*args,**kwargs):
        nonlocal event
        event=True
        kwargs['check']()
    with pytest.raises(RuntimeError,match='event failure'):
        shared.capture_selected_mill_context(saved.case.sw,'clsid','tlb',str(saved.case.part),
            expected_feature_native_id=99,check=check,context=ctx,legacy_capture=changed)
    assert streams and all(stream.closed for stream in streams)


def test_capture_handles_are_closed_before_own_save_and_new_sha_is_explicit(saved,monkeypatch):
    streams=tracked_opens(saved,monkeypatch)
    original_save=saved.app.SaveActiveDocument.side_effect
    observations=[]
    def save():
        observations.append(len(streams))
        assert streams and all(stream.closed for stream in streams)
        return original_save()
    saved.app.SaveActiveDocument.side_effect=save
    result=saved.apply()
    assert result['status']=='review_required' and result['save_readback_verified'],result
    assert len(observations)==1
    assert result['after']['saved_file_sha256']!=result['before']['saved_file_sha256']
    assert all(stream.closed for stream in streams)
    assert all(row['circle_solid_observation']['comparison_verified'] for row in result['snapshot_diagnostics'])


def test_file_scope_is_not_reusable(tmp_path):
    source=tmp_path/'source';creator=tmp_path/'creator'
    source.write_bytes(b's');creator.write_bytes(b'c')
    scope=shared._CaptureReadFiles(source,creator)
    with scope:scope.check()
    with pytest.raises(ValueError,match='closed'):scope.check()
    with pytest.raises(ValueError,match='reused'):
        with scope:pass

@pytest.mark.parametrize('drift',['pid','path','source','creator'])
def test_lifecycle_shared_guard_blocks_inner_drift_without_saving(saved,monkeypatch,drift):
    from scripts import sw_cam_mill_feature_lifecycle as lifecycle
    original=saved.capture
    def capture_with_drift(*args,**kwargs):
        value=original(*args,**kwargs)
        if drift=='pid':monkeypatch.setattr(saved.case.sw,'GetProcessID',lambda:732)
        elif drift=='path':saved.case.document['path']=str(saved.case.tmp_path/'foreign.sldprt')
        elif drift=='source':saved.case.part.write_bytes(saved.case.part.read_bytes()+b'x')
        else:saved.creator_path.write_bytes(saved.creator_path.read_bytes()+b'x')
        kwargs['check']()
        raise AssertionError('guard must stop before returning a mixed capture')
    monkeypatch.setattr(lifecycle,'capture_mill_feature_state',capture_with_drift)
    out=saved.run()
    assert out['status']=='error' and not out['mutation_attempted'],out
    saved.app.SaveActiveDocument.assert_not_called()


def test_lifecycle_inner_event_callback_does_not_rehash_each_read(saved,monkeypatch):
    from scripts import sw_cam_mill_feature_lifecycle as lifecycle
    original_hash=lifecycle._file_hash;calls=[]
    def counted(path):
        calls.append(str(path))
        return original_hash(path)
    monkeypatch.setattr(lifecycle,'_file_hash',counted)
    original=saved.capture
    def extra_checks(*args,**kwargs):
        for _ in range(5):kwargs['check']()
        return original(*args,**kwargs)
    monkeypatch.setattr(lifecycle,'capture_mill_feature_state',extra_checks)
    out=saved.run()
    assert out['status']=='ok',out
    # Full lifecycle identity remains at its boundaries, not inside every read.
    assert calls.count(str(saved.case.part))<=10
    assert calls.count(str(saved.creator_path))<=10

def test_explicit_source_only_scope_closes_without_creator(tmp_path):
    source=tmp_path/'source.sldprt';source.write_bytes(b'source')
    scope=shared._CaptureReadFiles(source,creator_path=None)
    with scope:
        assert len(scope._rows)==1 and scope._rows[0][0]=='source'
        stream=scope._rows[0][2]
        assert not stream.closed
        scope.check()
    assert stream.closed


def test_source_only_still_rejects_content_metadata_drift(tmp_path):
    source=tmp_path/'source.sldprt';source.write_bytes(b'source')
    scope=shared._CaptureReadFiles(source)
    with pytest.raises(ValueError,match='metadata changed'):
        with scope:
            source.write_bytes(b'changed source length')
            scope.check()
    assert all(row[2].closed for row in scope._rows)


@pytest.mark.parametrize('creator_path',[None,'','relative.json'])
def test_circle_cannot_use_optional_source_only_mode(saved,monkeypatch,creator_path):
    ctx=context(saved);ctx['evidence']['path']=creator_path
    called=Mock();saved.capture=called
    with pytest.raises(ValueError,match='pinned creator receipt path'):capture(saved,ctx)
    called.assert_not_called()