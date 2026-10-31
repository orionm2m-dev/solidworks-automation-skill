"""Bounded diagnostic progress for an already guarded read-only CAM batch.

Pass ``read`` only as a reader's diagnostic persist callback. Do not replace the
owner journal's persist method: mutation pending/returned, Save and once markers
must retain their original immediate durable writes. Full observations stay in
the caller's report and are flushed on entry, completion or failure.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
from scripts.sw_cam_generation import _write_receipt

MAX_PROGRESS_BYTES=8192
MAX_UPDATES=4096
SCOPE='BOUNDED_CAM_READ_PROGRESS_V1'


def _require(value,message):
    if not value:raise ValueError(message)


def _key(path):
    return str(Path(path).resolve()).casefold()


def _bounded(value,depth=0):
    """Only compact JSON values, never arbitrary objects or native pointers."""
    if value is None or type(value) in (bool,int):return
    if type(value) is float:
        _require(math.isfinite(value),'Finite progress numbers required');return
    if type(value) is str:
        _require(len(value)<=512,'Progress string exceeds bound');return
    if type(value) is dict:
        _require(depth<2 and len(value)<=16,'Progress object exceeds bound')
        for key,item in value.items():
            _require(type(key) is str and len(key)<=96,'Short progress keys required')
            _bounded(item,depth+1)
        return
    if type(value) is list:
        _require(depth<2 and len(value)<=8,'Progress list exceeds bound')
        for item in value:_bounded(item,depth+1)
        return
    raise ValueError('Progress values must be bounded JSON primitives')


class ReadProgressJournal:
    """One finite reader scope, with an explicitly acknowledged completion.

    ``describe`` supplies the last attempted/returned field, using only small
    scalar dictionaries. ``full_persist`` remains the owner's unmodified durable
    journal. Native guards and event checks are outside this diagnostic helper.
    A normal exit without ``complete`` fails closed and still flushes evidence.
    """
    def __init__(self,*,full_persist,progress_path,describe,max_updates,protected_paths):
        _require(callable(full_persist) and callable(describe),'Explicit persist and progress callbacks required')
        _require(type(max_updates) is int and 1<=max_updates<=MAX_UPDATES,'Finite read update budget required')
        _require(type(protected_paths) in (list,tuple) and 1<=len(protected_paths)<=128,
                 'Explicit bounded protected paths required')
        path=Path(progress_path)
        _require(path.is_absolute() and path.suffix.lower()=='.json' and path.parent.is_dir()
                 and not path.exists() and not path.is_symlink(),'Fresh absolute progress JSON required')
        _require(_key(path) not in {_key(p) for p in protected_paths},'Progress output aliases protected file')
        self.path=path;self._full_persist=full_persist;self._describe=describe;self._maximum=max_updates
        self._updates=0;self._last={};self._active=False;self._entered=False;self._complete=False
        self._created=False;self._failed=False

    def _emit(self,status,error=None):
        row=dict(schema_version=1,scope=SCOPE,status=status,read_only_progress=True,
            mutation_authority=False,read_updates=self._updates,max_read_updates=self._maximum,
            last_read=deepcopy(self._last),full_observations_in_owner_receipt=True)
        if error is not None:row['error_type']=type(error).__name__
        payload=json.dumps(row,ensure_ascii=False,allow_nan=False,separators=(',',':'))
        _require(len(payload.encode('utf-8'))<=MAX_PROGRESS_BYTES,'Compact progress byte budget exceeded')
        _write_receipt(self.path,row,create=not self._created);self._created=True

    def __enter__(self):
        _require(not self._entered,'Read progress scope cannot be reused')
        self._entered=True
        self._full_persist()
        self._emit('reading')
        self._active=True
        return self

    def read(self):
        """Persist only compact reader progress; never authorize a mutation."""
        _require(self._active and not self._failed and not self._complete,'Inactive or finished read scope')
        try:
            _require(self._updates<self._maximum,'Read progress update budget exceeded')
            value=self._describe()
            _require(type(value) is dict,'Progress description must be an object')
            _bounded(value)
            _require(len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8'))<=4096,
                     'Progress description byte budget exceeded')
            self._last=deepcopy(value);self._updates+=1
            self._emit('reading')
        except BaseException:
            self._failed=True
            raise

    def complete(self):
        """Call only after the reader and its native guard validate completion."""
        _require(self._active and not self._failed and not self._complete,'Incomplete or already finished read scope')
        self._complete=True

    def __exit__(self,exc_type,exc,traceback):
        _require(self._active,'Read progress scope was not active')
        self._active=False
        incomplete=None
        if exc is None and (not self._complete or self._failed):
            incomplete=ValueError('Read scope did not explicitly complete')
        error=exc if exc is not None else incomplete
        # Full durability comes before publishing completed progress. A compact
        # output failure never prevents the final full observation flush.
        try:self._full_persist()
        except BaseException as flush_error:
            try:self._emit('failed',flush_error)
            except BaseException:pass
            raise flush_error from error
        try:self._emit('failed' if error is not None else 'completed',error)
        except BaseException as progress_error:raise progress_error from error
        if incomplete is not None:raise incomplete
        return False
