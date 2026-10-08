"""显式文件映射的原生 Pack and Go；源文档不保存、不关闭。"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field


class CopyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)


def canonical(path):
    """规范化用于文件映射比较的绝对路径。"""
    return os.path.normcase(os.path.abspath(path))


def validate_mapping(entries, native_names):
    """拒绝缺失映射、文件类型变化、重名和原位覆盖。"""
    mapping = {}
    targets = set()
    for entry in entries:
        source, target = Path(entry.source), Path(entry.target)
        if not source.is_absolute() or not target.is_absolute():
            raise ValueError("Absolute source and target paths required")
        if source.suffix.lower() != target.suffix.lower():
            raise ValueError("Document extension must be preserved")
        src, dst = canonical(source), canonical(target)
        if src in mapping or dst in targets or src == dst:
            raise ValueError("Duplicate or in-place mapping")
        if not source.is_file():
            raise FileNotFoundError(source)
        if target.exists():
            raise FileExistsError(target)
        mapping[src] = str(target); targets.add(dst)
    names = [canonical(n) for n in native_names]
    if set(names) != set(mapping) or len(names) != len(mapping):
        raise ValueError(f"Native Pack and Go enumeration does not match mapping: native={native_names}, mapped={list(mapping)}")
    return [mapping[n] for n in names]


def _names(value):
    """归一化不同 COM 代理的数组返回形式。"""
    if isinstance(value, str): return [value]
    if isinstance(value, (list, tuple)):
        result=[]
        for item in value: result.extend(_names(item))
        return result
    return []


def copy_named_document_set(sw, model, entries, dry_run=True):
    """在调用方持有的操作互斥锁内，执行严格 PID/路径保护的 PIA 复制。"""
    import base64,json,subprocess
    from scripts.sw_connect import get_com_member as get
    from scripts.cad_installation import discover_installation
    validate_mapping(entries,[e.source for e in entries])
    checksums={e.source:hashlib.sha256(Path(e.source).read_bytes()).hexdigest() for e in entries}
    install=Path(discover_installation("solidworks")["executable"]).parent
    candidates=[install/'api/redist',install]
    interop=next((p for p in candidates if (p/'SolidWorks.Interop.sldworks.dll').is_file()),None)
    if interop is None:raise FileNotFoundError("Installed SOLIDWORKS PIA not found")
    payload={"process_id":int(get(sw,"GetProcessID")),"source":str(get(model,"GetPathName")),
             "dry_run":dry_run,"entries":[e.model_dump() for e in entries]}
    encoded=base64.b64encode(json.dumps(payload).encode('utf-8')).decode('ascii')
    script=Path(__file__).with_suffix('.ps1')
    cmd=['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script),
         '-InputBase64',encoded,'-InteropRoot',str(interop)]
    proc=subprocess.run(cmd,capture_output=True,encoding='utf-8',errors='replace',timeout=240,
                        creationflags=subprocess.CREATE_NO_WINDOW)
    if proc.returncode:raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    result=json.loads(proc.stdout.lstrip('\ufeff'))
    if any(hashlib.sha256(Path(n).read_bytes()).hexdigest()!=digest for n,digest in checksums.items()):
        raise RuntimeError("Source file changed during copy")
    result['source_hashes_unchanged']=True
    if not dry_run:
        result['outputs']=[]
        for dest in result['targets']:
            p=Path(dest)
            if not p.is_file() or p.stat().st_size==0:raise RuntimeError(f"Missing output {dest}")
            result['outputs'].append({'path':dest,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    return result
