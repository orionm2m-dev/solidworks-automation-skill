"""Shared explicit provenance for a single selected MILL feature; no mutation ownership."""
from contextlib import ExitStack
from pathlib import Path
import os
import stat
import re
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def validate_selected_mill_context_request(*, feature_kind='open_pocket',
        expected_feature_native_id=None, expected_source_sha256=None,
        circle_creation_receipt_path=None, circle_creation_receipt_sha256=None):
    """Pure pairing validator; legacy inputs retain their own existing validation."""
    if type(feature_kind) is not str or feature_kind not in ('open_pocket','circular_pocket'):
        raise ValueError('Explicit supported selected-feature kind required')
    if feature_kind=='open_pocket':
        if circle_creation_receipt_path is not None or circle_creation_receipt_sha256 is not None:
            raise ValueError('Circle provenance is forbidden for default open_pocket mode')
        return
    if type(expected_feature_native_id) is not int or not 0<expected_feature_native_id<2**32:
        raise ValueError('Exact selected circle feature ID required')
    for value in (expected_source_sha256,circle_creation_receipt_sha256):
        if type(value) is not str or re.fullmatch('[0-9a-f]{64}',value) is None:
            raise ValueError('Exact current source and immutable creator SHA required')
    if (type(circle_creation_receipt_path) is not str or not absolute_document_path(circle_creation_receipt_path)
            or Path(circle_creation_receipt_path).suffix.casefold()!='.json'):
        raise ValueError('Absolute pinned circular creation receipt path required')


def load_selected_mill_context(*, process_id, expected_document_path, expected_feature_native_id,
        expected_source_sha256, feature_kind='open_pocket',circle_creation_receipt_path=None,
        circle_creation_receipt_sha256=None):
    """File-only evidence loading. Creator geometry is immutable; current operations are not."""
    validate_selected_mill_context_request(feature_kind=feature_kind,
        expected_feature_native_id=expected_feature_native_id,expected_source_sha256=expected_source_sha256,
        circle_creation_receipt_path=circle_creation_receipt_path,circle_creation_receipt_sha256=circle_creation_receipt_sha256)
    if feature_kind=='open_pocket':return None
    if (type(process_id) is not int or not 0<process_id<2**32 or
            type(expected_document_path) is not str or not absolute_document_path(expected_document_path)
            or Path(expected_document_path).suffix.casefold()!='.sldprt'):
        raise ValueError('Exact process and saved part identity required for circle context')
    from scripts.sw_cam_circle_lifecycle_evidence import read_circle_creation_evidence
    evidence=read_circle_creation_evidence(circle_creation_receipt_path,circle_creation_receipt_sha256,
                                          expected_document_path,expected_feature_native_id)
    return dict(schema_version=1,process_id=process_id,expected_document_path=expected_document_path,
                expected_source_sha256=expected_source_sha256,expected_feature_native_id=expected_feature_native_id,
                feature_kind=feature_kind,evidence=evidence)


def selected_context_identity(sw,context,*,current_source_sha256=None):
    """Strict identity for explicit circle context; no default-branch COM reads."""
    from scripts.sw_cam import _member
    from scripts.sw_cam_thread import _file_hash
    from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
    pid=_member(sw,'GetProcessID')
    if type(pid) is not int or pid!=context['process_id']:raise ValueError('Selected context PID changed')
    doc=raw_part_identity(sw)
    check_document_target(doc['path'],doc['title'],expected_path=context['expected_document_path'],required=True)
    source=context['expected_source_sha256'] if current_source_sha256 is None else current_source_sha256
    if type(source) is not str or re.fullmatch('[0-9a-f]{64}',source) is None:raise ValueError('Exact current source SHA required')
    if _file_hash(context['expected_document_path'])!=source:raise ValueError('Selected context current source SHA changed')
    evidence=context['evidence']
    if _file_hash(evidence['path'])!=evidence['sha256']:raise ValueError('Immutable circular creator receipt changed')
    return dict(document=doc,saved_file_sha256=source)


def _capture_file_stamp(value, label):
    """Metadata identity only; never a replacement for boundary content hashes."""
    names=('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_ctime_ns')
    values=tuple(getattr(value,name,None) for name in names)
    if (any(type(item) is not int for item in values) or values[0]<0 or values[1]<=0
            or values[3]<0 or not stat.S_ISREG(values[2])):
        raise ValueError('Usable regular-file metadata identity required: '+label)
    return values


class _CaptureReadFiles:
    """Ordinary rb handles scoped to one capture, NOT a file lock or write lease."""
    def __init__(self, source_path, creator_path=None):
        self._paths=(('source',source_path),)
        if creator_path is not None:self._paths+=(('creator',creator_path),)
        self._stack=ExitStack()
        self._rows=[]
        self._active=False
        self._entered=False

    def __enter__(self):
        if self._entered:raise ValueError('Capture file scope cannot be reused')
        self._entered=True
        try:
            for label,path in self._paths:
                stream=self._stack.enter_context(Path(path).open('rb'))
                handle_stamp=_capture_file_stamp(os.fstat(stream.fileno()),label+' handle')
                path_stamp=_capture_file_stamp(Path(path).stat(),label+' path')
                if path_stamp!=handle_stamp:
                    raise ValueError('Capture path/handle metadata differs: '+label)
                self._rows.append((label,path,stream,handle_stamp))
            self._active=True
            self.check()
            return self
        except BaseException:
            self._active=False
            self._stack.close()
            raise

    def check(self):
        if not self._active:raise ValueError('Capture file scope is closed')
        for label,path,stream,pinned in self._rows:
            handle_stamp=_capture_file_stamp(os.fstat(stream.fileno()),label+' handle')
            path_stamp=_capture_file_stamp(Path(path).stat(),label+' path')
            if handle_stamp!=pinned or path_stamp!=pinned:
                raise ValueError('Capture file metadata changed: '+label)

    def __exit__(self, exc_type, exc, traceback):
        self._active=False
        return self._stack.__exit__(exc_type,exc,traceback)


def _check_capture_document(sw, context, begin):
    """Cheap native identity between full capture-boundary checks."""
    from scripts.sw_cam import _member
    from scripts.sw_cam_circle_lifecycle_evidence import call, _nonnull
    pid=_member(sw,'GetProcessID')
    if type(pid) is not int or pid!=context['process_id']:
        raise ValueError('Selected context PID changed during capture')
    model=_nonnull(sw.ActiveDoc,'ActiveDoc')
    path=call(model,'GetPathName')
    if type(path) is not str or not path:
        raise ValueError('Strict active document path required during capture')
    check_document_target(path,None,expected_path=begin['document']['path'],required=True)


def capture_selected_mill_context(sw,clsid,typelib_path,expected_path,*,expected_feature_native_id,
        check,diagnostic=None,context=None,legacy_capture=None,current_source_sha256=None):
    """Caller owns event subscription and allowed mutation deltas. Export scope is unchanged."""
    if legacy_capture is None:
        from scripts.sw_cam_mill_feature_process import capture_mill_feature_state
        legacy_capture=capture_mill_feature_state
    if context is None:
        return legacy_capture(sw,clsid,typelib_path,expected_path,
            expected_feature_native_id=expected_feature_native_id,check=check,diagnostic=diagnostic)
    if expected_feature_native_id!=context['expected_feature_native_id'] or expected_path!=context['expected_document_path']:
        raise ValueError('Selected capture request differs from loaded provenance')
    creator_path=context['evidence'].get('path')
    if type(creator_path) is not str or not absolute_document_path(creator_path):
        raise ValueError('Circular capture requires the pinned creator receipt path')
    check()
    with _CaptureReadFiles(expected_path,creator_path) as files:
        check();begin=selected_context_identity(sw,context,current_source_sha256=current_source_sha256);check()
        files.check()
        def guarded():
            check()
            _check_capture_document(sw,context,begin)
            files.check()
            check()
        state,native=legacy_capture(sw,clsid,typelib_path,expected_path,
            expected_feature_native_id=expected_feature_native_id,check=guarded,diagnostic=diagnostic,
            feature_kind='circular_pocket')
        from scripts.sw_cam_circle_lifecycle_evidence import verify_circle_reference
        verify_circle_reference(sw,state,context['evidence'],guarded,native['app'],diagnostic=diagnostic)
        observed={key:state[key] for key in ('document','saved_file_sha256')}
        if observed!=begin:raise ValueError('Capture identity differs from strict selected context')
        guarded()
        check();end=selected_context_identity(sw,context,current_source_sha256=current_source_sha256);check()
        files.check()
        if end!=begin:raise ValueError('Strict document/source changed across selected-context capture')
        state['selected_mill_context']=dict(schema_version=1,process_id=context['process_id'],
            feature_kind='circular_pocket',expected_feature_native_id=expected_feature_native_id,
            circle_creation_receipt_path=context['evidence']['path'],circle_creation_receipt_sha256=context['evidence']['sha256'])
    # The native mutation belongs to the caller: no rb handle survives this return.
    return state,native
