"""Repeat immutable JSON pin checks without decoding already qualified bytes.

Every call still reopens and hashes the complete bounded file through the
unchanged receipt reader, including handle/path identity and alias checks.
Only JSON decoding is memoized by a SHA that passed the full reader once.
"""
from pathlib import Path
from time import perf_counter,sleep
from scripts import sw_cam_current_circular_context as circular
from scripts import sw_cam_circular_reconfigure as revision_context
from scripts import sw_cam_append_finish_definitions as append_context
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_mill_stock_export_evidence import _receipt_bytes,_sha,_require
require=circular.require


def qualified_pin(context,path,sha):
    _sha(sha)
    cache=getattr(context,'_decoded_immutable_json_shas',None)
    if cache is None:cache=set();context._decoded_immutable_json_shas=cache
    require(type(cache)is set,'Private decoded JSON qualification cache changed')
    if sha not in cache:
        observed=read_pin(path,sha)[1]
        cache.add(sha)
        return observed
    raw,observed=_receipt_bytes(path)
    _require(observed['sha256']==sha,'Pinned receipt SHA differs')
    return observed


def _verify_external_files(self):
    def checked(path,sha,expected=None):
        episode=None
        for attempt in range(1,4):
            try:observed=qualified_pin(self,path,sha)
            except Exception as exc:
                cause=exc.__cause__
                retryable=type(exc)is ValueError and isinstance(cause,OSError)
                if not retryable:
                    if episode is not None:
                        episode.update(outcome='non_retryable_error',completed_attempt=attempt);self.persist()
                    raise
                if episode is None:
                    journal=self.report.setdefault('file_pin_read_retries',[])
                    if len(journal)>=64:
                        self.report['file_pin_retry_journal_limit_reached']=True;self.persist();raise
                    episode=dict(path=path,sha256=sha,failures=[],outcome='retry_pending');journal.append(episode)
                episode['failures'].append(dict(attempt=attempt,errno=cause.errno if type(cause.errno)is int else None,winerror=getattr(cause,'winerror',None)if type(getattr(cause,'winerror',None))is int else None))
                episode.update(outcome='retry_budget_exhausted'if attempt==3 else'retry_pending',completed_attempt=attempt);self.persist()
                if attempt==3:raise
                sleep(.05);continue
            matches=expected is None or observed==expected
            if episode is not None:
                episode.update(outcome='verified_after_retry'if matches else'pin_mismatch',completed_attempt=attempt);self.persist()
            require(matches,'Immutable circular authority changed')
            return observed
    for p in self.pins:checked(p['path'],p['sha256'],p)
    if self.request.get('prepare_receipt_path'):checked(self.request['prepare_receipt_path'],self.request['prepare_receipt_sha256'])
    if getattr(self,'_capture_pin_scope',False):return
    # Preserve both inherited guards after the JSON pins, in the same order.
    if hasattr(self,'revision'):
        revision_context.require(revision_context._file_hash(self.revision['cl_pin']['path'])==self.revision['cl_pin']['sha256'],'Historical full CL changed')
        revision_context.require(revision_context._file_hash(revision_context.__file__)==self.revision['module_sha256'],'Revision implementation changed')
    if hasattr(self,'append_plan'):
        for p in self.append_plan['pins']:
            if Path(p['path']).suffix.lower()!='.json'and Path(p['path']).resolve()!=Path(self.v['expected_document_path']).resolve():append_context.binding.common.direct(p)


def verify_files(context):
    if getattr(context,'_capture_pin_scope',False)is True:
        context._capture_pin_episode['nested_checks_deferred']+=1
        return
    started=perf_counter()
    try:return _verify_external_files(context)
    finally:
        elapsed=perf_counter()-started
        timing=context.report.setdefault('external_file_pin_verification',dict(count=0,total_seconds=0.,max_seconds=0.))
        timing['count']+=1;timing['total_seconds']+=elapsed;timing['max_seconds']=max(timing['max_seconds'],elapsed)
        # Normal operation persistence writes this aggregate; no per-getter write.
