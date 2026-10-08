"""MCP 运行目录与源代码快照校验；不调用 COM。"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path


class RuntimeIdentityError(RuntimeError):
    """运行目录不符或进程加载后代码改变。"""
    def __init__(self, report):
        self.details = report
        super().__init__(report['error_code'] + ': restart MCP from the configured runtime directory')


def source_fingerprint(root):
    """计算可执行项目源文件摘要；不包含测试、缓存、文档或私有模型。"""
    root = Path(root).resolve()
    files = []
    for folder in ('mcp-server', 'scripts', 'subskills'):
        base = root / folder
        if base.is_dir():
            files.extend(p for p in base.rglob('*')
                         if p.is_file() and p.suffix.lower() in {'.py', '.cs', '.ps1'}
                         and '__pycache__' not in p.parts)
    capability = root / 'capabilities.yaml'
    if capability.is_file():
        files.append(capability)
    digest = sha256()
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode('utf-8')
        digest.update(len(relative).to_bytes(4, 'big'))
        digest.update(relative)
        digest.update(sha256(path.read_bytes()).digest())
    return digest.hexdigest(), len(files)


def _same_path(left, right):
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


@dataclass(frozen=True)
class RuntimeIdentity:
    """服务启动时捕获，后续仅核对；不能在运行中刷新基线掩盖陈旧模块。"""
    root: Path
    expected_root: str | None
    source_sha256: str
    source_file_count: int

    @classmethod
    def capture(cls, root, expected_root=None):
        root = Path(root).resolve()
        expected = expected_root if expected_root is not None else os.environ.get('SOLIDWORKS_MCP_RUNTIME_ROOT')
        fingerprint, count = source_fingerprint(root)
        return cls(root, expected, fingerprint, count)

    def status(self):
        """返回可审计身份；错误报告不连接任何 SOLIDWORKS 会话。"""
        report = {'status': 'ready', 'runtime_protocol': 1,
                  'server_process_id': os.getpid(), 'runtime_root': str(self.root),
                  'server_path': str(self.root / 'mcp-server/server.py'),
                  'expected_runtime_root': self.expected_root,
                  'startup_source_sha256': self.source_sha256,
                  'source_file_count': self.source_file_count,
                  'com_probe_performed': False}
        try:
            current, count = source_fingerprint(self.root)
            report.update(current_source_sha256=current, current_source_file_count=count)
            if self.expected_root and not Path(self.expected_root).is_absolute():
                report.update(status='blocked', error_code='SW_RUNTIME_ROOT_INVALID')
            elif self.expected_root and not _same_path(self.root, self.expected_root):
                report.update(status='blocked', error_code='SW_RUNTIME_ROOT_MISMATCH')
            elif current != self.source_sha256:
                report.update(status='blocked', error_code='SW_RUNTIME_SOURCE_CHANGED')
        except OSError as exc:
            report.update(status='blocked', error_code='SW_RUNTIME_SOURCE_UNREADABLE', detail=str(exc))
        return report

    def assert_current(self):
        """CAD 操作之前拒绝错误目录及陈旧服务进程。"""
        report = self.status()
        if report['status'] != 'ready':
            raise RuntimeIdentityError(report)
        return report
