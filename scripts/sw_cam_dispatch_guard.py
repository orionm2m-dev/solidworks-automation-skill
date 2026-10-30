"""Bounded native dispatch guard with content hashes at phase boundaries.

The caller owns command allowlisting, durable attempt records, semantic evidence,
result interpretation and post-mutation readback. No strategy API is exposed.
"""
from contextlib import ExitStack
from pathlib import Path
import re
from scripts.sw_cam import _member
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_mill_feature_context import _CaptureReadFiles
from scripts.sw_operation_guard import check_document_target

class ScopedCamDispatchGuard:
    """One read/dispatch scope for an already validated, unchanged saved document.

    rb handles detect metadata/path changes; they are not locks or write leases.
    Full immutable content hashes and owned-process identity are rechecked before
    dispatch. No source handles or cached state may survive a native save.
    """
    def __init__(self, sw, typelib_path, *, process_id, expected_document,
                 source_sha256, evidence_pins, verify_evidence, verify_owned_process,
                 check_events):
        if type(process_id) is not int or not 0 < process_id < 2**32:
            raise ValueError("Exact strict process ID required")
        if (type(expected_document) is not dict or expected_document.get("type") != 1
            or type(expected_document.get("type")) is not int
            or type(expected_document.get("needs_save")) is not bool):
            raise ValueError("Exact part identity and dirty flag required")
        if type(evidence_pins) is not list or not 1 <= len(evidence_pins) <= 64:
            raise ValueError("Explicit bounded complete evidence pin list required")
        if not all(callable(v) for v in (verify_evidence, verify_owned_process, check_events)):
            raise ValueError("Evidence, ownership and event callbacks required")
        self.sw = sw
        self.typelib_path = typelib_path
        self.process_id = process_id
        self.expected_document = dict(expected_document)
        self.verify_evidence = verify_evidence
        self.verify_owned_process = verify_owned_process
        self.check_events = check_events
        self._stack = ExitStack()
        self._files = []
        self._active = False
        self._entered = False
        self._invalid = False
        self._claimed = False
        self._attempted = False
        self._returned = False
        self._boundary_count = 0
        self._hash_count = 0
        self._metadata_checks = 0
        self._rows = []
        source_pin = dict(path=expected_document["path"], sha256=source_sha256)
        seen = {}
        for pin in [source_pin] + evidence_pins:
            if (type(pin) is not dict or type(pin.get("path")) is not str
                or type(pin.get("sha256")) is not str
                or re.fullmatch("[0-9a-f]{64}", pin["sha256"]) is None):
                raise ValueError("Exact immutable file path and SHA-256 required")
            path = Path(pin["path"])
            if not path.is_absolute() or not path.is_file() or path.is_symlink():
                raise ValueError("Existing absolute non-symlink pinned file required")
            canonical = str(path.resolve()).casefold()
            if pin.get("canonical_path") is not None and canonical != str(Path(pin["canonical_path"]).resolve()).casefold():
                raise ValueError("Pinned canonical file path differs")
            if pin.get("bytes") is not None and (type(pin["bytes"]) is not int or pin["bytes"] != path.stat().st_size):
                raise ValueError("Pinned byte length differs")
            if canonical in seen:
                if seen[canonical] != pin["sha256"]:
                    raise ValueError("Conflicting hashes for the same pinned file")
                continue
            seen[canonical] = pin["sha256"]
            self._rows.append((path, pin["sha256"], canonical))
    def _require_live(self, *, allow_claimed=False):
        if not self._active or self._invalid or (self._claimed and not allow_claimed):
            raise ValueError("Dispatch scope is closed, invalid or already claimed")
    def _identity(self):
        pid = _member(self.sw, "GetProcessID")
        if type(pid) is not int or pid != self.process_id:
            raise ValueError("Exact selected process changed")
        doc = raw_part_identity(self.sw)
        check_document_target(doc["path"], doc["title"],
            expected_path=self.expected_document["path"], required=True)
        if doc != self.expected_document:
            raise ValueError("Active document identity or dirty state changed")
    def _fast(self, *, allow_claimed=False):
        self._require_live(allow_claimed=allow_claimed)
        self.check_events()
        for item in self._files:
            item.check()
            self._metadata_checks += 1
        self._identity()
        self.check_events()
    def _boundary(self, *, allow_claimed=False):
        self._fast(allow_claimed=allow_claimed)
        self.verify_owned_process()
        for path, digest, canonical in self._rows:
            if str(path.resolve()).casefold() != canonical or _file_hash(path) != digest:
                raise ValueError("Pinned content changed at dispatch phase boundary")
            self._hash_count += 1
        self._fast(allow_claimed=allow_claimed)
        self._boundary_count += 1
    def __enter__(self):
        if self._entered:
            raise ValueError("Dispatch guard cannot be entered twice")
        self._entered = True
        try:
            self.check_events()
            self.verify_evidence()
            for path, _, _ in self._rows:
                self._files.append(self._stack.enter_context(_CaptureReadFiles(path)))
            self._active = True
            self._boundary()
            return self
        except BaseException:
            self._invalid = True
            self._active = False
            self._stack.close()
            raise
    def _observe(self, callback):
        try:
            self._fast()
            result = callback()
            self._fast()
            return result
        except BaseException:
            self._invalid = True
            raise
    def read(self, obj, name, *args):
        """Guard one read-only native getter; caller must never pass a setter."""
        return self._observe(lambda: _member(obj, name, *args))
    def typed(self, obj, interface_name):
        return self._observe(lambda: _typed(obj, interface_name, self.typelib_path))
    def dispatch_once(self, invoke, *, persist_pending):
        """Invoke an allowlisted callback once after durable pending evidence.

        Caller must fsync its persistent attempt marker before persist_pending
        returns. An exception here never authorizes replay with a fresh guard.
        No native/readback checks follow the callback: the caller must close this
        scope and use its operation-specific post-mutation validator.
        """
        self._require_live()
        if not callable(invoke) or not callable(persist_pending):
            raise ValueError("Explicit native invocation and durable pending callback required")
        self._claimed = True
        try:
            self._boundary(allow_claimed=True)
            persist_pending()
            # Pending publication can take time: repeat exact content, owned
            # process, document, dirty and event checks immediately before call.
            self._boundary(allow_claimed=True)
            self._attempted = True
            result = invoke()
            self._returned = True
            return result
        except BaseException:
            self._invalid = True
            raise
    def summary(self):
        return dict(scope="SCOPED_CAM_DISPATCH_GUARD_V1", active=self._active,
            invalid=self._invalid, claimed=self._claimed, native_call_attempted=self._attempted,
            native_call_returned=self._returned, unique_file_count=len(self._rows),
            complete_boundary_checks=self._boundary_count, content_hash_reads=self._hash_count,
            metadata_checks=self._metadata_checks, automatic_replay=False,
            write_lease=False, post_mutation_readback_performed=False)
    def __exit__(self, exc_type, exc, traceback):
        self._active = False
        return self._stack.__exit__(exc_type, exc, traceback)
