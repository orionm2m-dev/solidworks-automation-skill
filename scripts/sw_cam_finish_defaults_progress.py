"""Compact diagnostics for existing guarded Finish defaults reads.

Use CompactDefaultsMixin before the existing native backend in the MRO.
Only the read-only diagnostic callback is redirected. The owner journal,
mutation claims, return receipts, Save and once markers remain unchanged.
"""
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
import re
from scripts import sw_cam_chamfer_insert_defaults as insert
from scripts import sw_cam_chamfer_defaults as defaults
from scripts import sw_cam_checkpoint_exports as exports
from scripts import sw_cam_read_progress_journal as progress
from scripts.sw_cam import _member
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_rough_firstcut import require


def read_defaults_phase(operation, feature, *, batch, diagnostic, full_persist,
                        progress_path, protected_paths):
    """Flush full observations at phase entry and terminal exit, including failure."""
    started = monotonic()
    stamp = diagnostic['read_journal'] = dict(
        progress_path=str(progress_path),
        started_utc=datetime.now(timezone.utc).isoformat(),
        completed=False, read_only=True, mutation_authority=False)

    def describe():
        read = diagnostic['read']
        last = read.get('calls', [{}])[-1] if read.get('calls') else {}
        return dict(
            label=diagnostic['label'], operation_native_id=diagnostic['operation_native_id'],
            member=last.get('name'), kind=last.get('kind'),
            attempted=last.get('attempted', False), returned=last.get('returned', False),
            validated=last.get('validated', False),
            native_call_count=read.get('native_call_count', 0),
            max_native_calls=defaults.MAX_NATIVE_CALLS,
            read_complete=read.get('read_complete', False),
            observed_utc=datetime.now(timezone.utc).isoformat(),
            elapsed_seconds=monotonic()-started)

    with progress.ReadProgressJournal(
            full_persist=full_persist, progress_path=progress_path, describe=describe,
            max_updates=defaults.MAX_NATIVE_CALLS*3,
            protected_paths=protected_paths) as journal:
        try:
            with batch:
                value = defaults.read_defaults(operation, feature, read=batch.read,
                    typed=batch.typed, persist=journal.read, diagnostic=diagnostic['read'])
            batch.require_complete()
            stamp['completed'] = True
        finally:
            # Full final durability includes guard completion or failure evidence.
            diagnostic['batch'] = batch.summary()
            stamp.update(finished_utc=datetime.now(timezone.utc).isoformat(),
                         elapsed_seconds=monotonic()-started)
        journal.complete()
    return value


class CompactDefaultsMixin:
    """The existing guarded reader sequence with bounded progress publication."""
    def operation_defaults(self, operation_id, label, feature_native_id=None):
        fid = self.args['feature_native_id'] if feature_native_id is None else feature_native_id
        if feature_native_id is None:
            feature, _ = self.selected_feature()
        else:
            with self.ctx.guard() as g:
                found = g.read(self.native['doc'], 'GetCWObjectFromID', 1, fid)
                require(type(found) in (tuple, list) and len(found) == 2 and found[1] is True,
                        'Existing anchor feature lookup failed')
                feature = g.typed(found[0], 'ICWMillFeature')
                require(_object_id(self.native['doc'], feature, g.read) == fid, 'Anchor feature ID changed')
        with self.ctx.guard() as g:
            raw = self.native['operations'][operation_id]
            require(_object_id(self.native['doc'], raw, g.read) == operation_id, 'Defaults target identity changed')
        def binding():
            self.events()
            require(_object_id(self.native['doc'], raw, _member) == operation_id,
                    'Retained defaults operation identity changed')
            require(_object_id(self.native['doc'], feature, _member) == fid,
                    'Retained defaults feature identity changed')
            self.events()
        batch = insert.DefaultsReadBatch(self.sw, self.typelib_path,
            process_id=self.args['process_id'], expected_document=self.ctx.identity(),
            source_sha256=self.ctx.args['expected_source_sha256'], evidence_pins=self.loaded['pins'],
            verify_evidence=self.ctx.files, verify_owned_process=self.ctx.owned, check_events=self.events,
            retained_objects=(self.native['doc'], raw, feature), verify_retained_binding=binding,
            max_native_calls=defaults.MAX_NATIVE_CALLS)
        diagnostic = dict(label=label, operation_native_id=operation_id, read={})
        self.report.setdefault('defaults_observations', []).append(diagnostic)
        require(type(label) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', label),
                'Bounded defaults phase label required')
        owner = getattr(self.persist, '__self__', None)
        require(owner is not None and hasattr(owner, 'marker'), 'Bound owner journal required')
        require(exports._pin(progress.__file__) in self.loaded['pins'],
                'Read progress implementation must be in the verified live closure')
        receipt = Path(self.args['receipt_path'])
        progress_path = receipt.with_name(receipt.stem + '.defaults.' + label + '.' + str(operation_id) + '.json')
        protected = [self.args['expected_document_path'], receipt, owner.marker]
        protected.extend(pin['path'] for pin in self.loaded['pins'])
        return read_defaults_phase(raw, feature, batch=batch, diagnostic=diagnostic,
            full_persist=self.persist, progress_path=progress_path, protected_paths=protected)
