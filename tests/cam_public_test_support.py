"""Strict test paths for installed runtime and committed synthetic fixtures."""
import importlib
import importlib.util
import os
from pathlib import Path
import re
import sys

TESTS = Path(__file__).resolve().parent

def runtime_root():
    raw = os.environ.get("SOLIDWORKS_SKILL_ROOT")
    if raw is not None and (not raw.strip() or not Path(raw).is_absolute()):
        raise RuntimeError("Explicit runtime root must be an absolute nonempty path")
    root = Path(raw) if raw is not None else TESTS.parent
    if not root.is_dir() or not (root / "scripts").is_dir():
        raise RuntimeError("Required runtime scripts directory is missing")
    return root.resolve()

def add_runtime():
    root = runtime_root()
    for path in reversed((root, TESTS, root / "tests")):
        text = str(path)
        if text in sys.path:
            sys.path.remove(text)
        sys.path.insert(0, text)
    return root

def required_module(name):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise RuntimeError("Expected one fixed runtime module name")
    root = add_runtime()
    expected = root / "scripts" / (name + ".py")
    if not expected.is_file() or expected.is_symlink():
        raise RuntimeError("Required installed module is missing: " + name)
    module = importlib.import_module("scripts." + name)
    if Path(module.__file__).resolve() != expected.resolve():
        raise RuntimeError("Runtime module came from an unexpected location: " + name)
    return module

def required_test_module(name):
    if not re.fullmatch(r"test_[a-z0-9_]+", name):
        raise RuntimeError("Expected one fixed sibling test module name")
    expected = TESTS / (name + ".py")
    if not expected.is_file() or expected.is_symlink():
        raise RuntimeError("Required sibling test fixture is missing: " + name)
    module = sys.modules.get(name)
    if module is not None:
        if Path(module.__file__).resolve() != expected.resolve():
            raise RuntimeError("Test fixture came from an unexpected location: " + name)
        return module
    spec = importlib.util.spec_from_file_location(name, expected)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module

def fixture_path(name):
    if not isinstance(name, str) or Path(name).name != name or name in ("", ".", ".."):
        raise RuntimeError("Expected one committed fixture filename")
    path = TESTS / "fixtures" / name
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Required committed fixture is missing: " + name)
    return path
