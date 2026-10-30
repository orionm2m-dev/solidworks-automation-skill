"""File-only checks for completed, pinned inventory anchors."""
from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import Mock
import hashlib
import json

import pytest
from scripts import sw_cam_mill_route_evidence as e
from test_sw_cam_mill_route_tool import protected_fixture


@pytest.fixture
def anchor(tmp_path, monkeypatch):
    part = tmp_path / 'part.sldprt'
    part.write_bytes(b'saved route')
    source = hashlib.sha256(part.read_bytes()).hexdigest()
    state = protected_fixture()
    state.update(saved_file_sha256=source)
    state['document'] = dict(path=str(part), title=part.name, type=1, needs_save=False)
    messages = dict(subscribed=True, disconnected=True, active=False, event_count=0,
                    overflow=0, callback_errors=[], callback_error_count=0,
                    subscription_error=None, disconnect_errors=[])
    data = dict(status='review_required', phase='finished', read_only=True,
                inventory_read_complete=True, readback_verified=True,
                messages=messages, before=state, after=deepcopy(state),
                state_sha256=e._digest(state))
    for key in ('mutation_attempted', 'AFR_attempted', 'GOP_attempted', 'GTP_attempted',
                'model_saved', 'stock_edit_attempted', 'material_edit_attempted',
                'TechDB_write_attempted', 'post_cleanup_CAM_getters'):
        data[key] = False
    path = tmp_path / 'inventory.json'
    loader = Mock()
    monkeypatch.setattr(e, 'load_mill_inventory_recovery_evidence', loader)
    def run():
        raw = json.dumps(data).encode()
        path.write_bytes(raw)
        return e.load_mill_route_anchor(str(path), hashlib.sha256(raw).hexdigest(),
            process_id=731, expected_document_path=str(part), expected_source_sha256=source)
    return N(**locals())


def test_complete_zero_operation_anchor_is_pinned(anchor):
    result = anchor.run()
    assert result.verify(anchor.state)
    assert result.summary()['saved_source_rebase_allowed'] is False
    anchor.path.write_text('{}')
    with pytest.raises(ValueError):
        result.check_files()
    anchor.loader.assert_not_called()


@pytest.mark.parametrize('mode', [
    'partial', 'dirty', 'mutating', 'cleanup', 'event', 'different_snapshots',
    'state_digest', 'source', 'nonzero_ops', 'rebind_bool', 'unverified_rebind',
    'different_process', 'rebind_without_recovery'
])
def test_incomplete_or_stale_inventory_rejected_before_recovery(anchor, mode):
    data = anchor.data
    if mode == 'partial':
        data['inventory_read_complete'] = False
    if mode == 'dirty':
        data['before']['document']['needs_save'] = True
        data['after'] = deepcopy(data['before'])
        data['state_sha256'] = e._digest(data['before'])
    if mode == 'mutating':
        data['GOP_attempted'] = True
    if mode == 'cleanup':
        data['messages']['disconnected'] = False
    if mode == 'event':
        data['messages']['event_count'] = 1
    if mode == 'different_snapshots':
        data['after']['features'][0]['geometry']['island'] = 'changed'
    if mode == 'state_digest':
        data['state_sha256'] = 'a' * 64
    if mode == 'source':
        data['before']['saved_file_sha256'] = 'b' * 64
        data['after'] = deepcopy(data['before'])
        data['state_sha256'] = e._digest(data['before'])
    if mode == 'nonzero_ops':
        data['before'].update(operation_count=1, operation_counts=[1])
        data['after'] = deepcopy(data['before'])
        data['state_sha256'] = e._digest(data['before'])
    if mode == 'rebind_bool':
        data['allow_saved_process_rebind'] = 1
    if mode in ('unverified_rebind', 'different_process', 'rebind_without_recovery'):
        data.update(allow_saved_process_rebind=True, process_id=731,
                    saved_process_rebind_verified=True)
    if mode == 'unverified_rebind':
        data['saved_process_rebind_verified'] = False
    if mode == 'different_process':
        data['process_id'] = 730
    with pytest.raises((ValueError, KeyError)):
        anchor.run()
    anchor.loader.assert_not_called()


@pytest.mark.parametrize('rebind', [False, True])
def test_verified_recovery_forwards_exact_process_binding(anchor, rebind):
    proof = dict(recognition_receipt=dict(path='recognition.json', sha256='a' * 64),
                 preservation_save_receipt=dict(path='save.json', sha256='b' * 64))
    recovery = Mock()
    recovery.summary.return_value = proof
    anchor.loader.return_value = recovery
    anchor.data.update(recovery_evidence=proof, recovery_delta_verified=True)
    if rebind:
        anchor.data.update(allow_saved_process_rebind=True, process_id=731,
                           saved_process_rebind_verified=True)
    result = anchor.run()
    kwargs = anchor.loader.call_args.kwargs
    assert kwargs['process_id'] == 731
    if rebind:
        assert kwargs['allow_saved_process_rebind'] is True
        recovery.verify_inventory.assert_called_once_with(anchor.state, captured_process_id=731)
    else:
        assert 'allow_saved_process_rebind' not in kwargs
        recovery.verify_inventory.assert_called_once_with(anchor.state)
    recovery.check_files.assert_called_once()
    assert result.summary()['recovery_evidence'] == proof
