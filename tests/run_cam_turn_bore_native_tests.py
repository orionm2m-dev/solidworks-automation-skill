#!/usr/bin/env python3
"""Compile and run the owner-STA bore synthetic harness without activating CAD."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


INTEROP_NAMES = (
    "SolidWorks.Interop.sldworks.dll", "SolidWorks.Interop.swconst.dll",
    "SolidWorks.Interop.swpublished.dll", "CamWorks.Interop.dll",
)
FRAMEWORK_NAMES = (
    "mscorlib.dll", "System.dll", "System.Core.dll", "System.Web.Extensions.dll",
    "System.Drawing.dll", "System.Windows.Forms.dll", "Microsoft.CSharp.dll",
    "System.Runtime.Serialization.dll",
)


class MissingPrerequisite(Exception):
    pass


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def invoke(argv, timeout):
    return subprocess.run(
        [str(x) for x in argv], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def compiler_command(explicit):
    dotnet = shutil.which("dotnet")
    if explicit:
        compiler = Path(explicit).resolve()
        if not compiler.is_file():
            raise MissingPrerequisite("Compiler file missing: " + str(compiler))
        if compiler.suffix.lower() == ".dll":
            if not dotnet:
                raise MissingPrerequisite("dotnet is required for a compiler DLL")
            return [dotnet, str(compiler)]
        if compiler.suffix.lower() != ".exe":
            raise ValueError("--compiler must name a Roslyn csc.dll or csc.exe")
        return [str(compiler)]
    if not dotnet:
        raise MissingPrerequisite("No dotnet SDK found; install an SDK or provide --compiler")
    result = invoke([dotnet, "--list-sdks"], 30)
    if result.returncode:
        raise MissingPrerequisite("dotnet --list-sdks failed: " + result.stderr.strip())
    candidates = []
    for line in result.stdout.splitlines():
        match = re.fullmatch(r"(\S+)\s+\[(.+)\]", line.strip())
        if match:
            version, location = match.groups()
            candidate = Path(location) / version / "Roslyn" / "bincore" / "csc.dll"
            if candidate.is_file():
                numbers = tuple(int(n) for n in re.findall(r"\d+", version.split("-", 1)[0]))
                candidates.append((numbers, "-" not in version, version, candidate))
    if not candidates:
        raise MissingPrerequisite("No SDK Roslyn csc.dll found; provide --compiler")
    return [dotnet, str(max(candidates)[-1])]


def framework_directory(explicit):
    if explicit:
        candidates = [Path(explicit).resolve()]
    else:
        windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
        program_files = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        candidates = [
            program_files / "Reference Assemblies/Microsoft/Framework/.NETFramework/v4.8",
            windows / "Microsoft.NET/Framework64/v4.0.30319",
        ]
    for path in candidates:
        if all((path / name).is_file() for name in FRAMEWORK_NAMES):
            return path
    raise MissingPrerequisite("NET48 references are unavailable; provide --framework-dir")


def quote_rsp(value):
    text = str(value)
    if any(c in text for c in ('"', '\r', '\n')):
        raise ValueError("Unsupported quote or newline in compiler path")
    return '"' + text + '"'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Checkout root containing dotnet/CadStudio.SolidWorks.AddinHost")
    parser.add_argument("--harness", type=Path, help="NativeBoreTests.cs (default: source-root/tests)")
    parser.add_argument("--dependencies-dir", type=Path, help="Existing built host interop DLL directory")
    parser.add_argument("--framework-dir", type=Path, help="NET48 reference/runtime assembly directory")
    parser.add_argument("--compiler", type=Path, help="Roslyn csc.dll or csc.exe; default: installed dotnet SDK")
    parser.add_argument("--output-dir", type=Path, help="New short directory; existing paths are never overwritten")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds for each compile/test process")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    output = None
    report = {"scope": "TURN_BORE_SYNTHETIC_TESTS_V1", "status": "FAIL", "native_called": False,
              "COM_activated": False, "registry_written": False,
              "qualification": "Synthetic IBackend checks only; no native CAD lifecycle or persistence qualification."}
    code = 1
    try:
        if args.output_dir:
            output = args.output_dir.resolve()
            output.mkdir(parents=True, exist_ok=False)
        else:
            output = Path(tempfile.mkdtemp(prefix="bore-tests-"))
        report["output_dir"] = str(output)
        report["runner_sha256"] = digest(Path(__file__))
        if os.name != "nt":
            raise MissingPrerequisite("Windows and NET48 are required for this synthetic harness")
        if len(str(output / "fixtures")) > 140:
            raise ValueError("Use a shorter --output-dir (fixture root limit 140 characters for NET48)")
        root = args.source_root.resolve()
        host = root / "dotnet/CadStudio.SolidWorks.AddinHost"
        harness = (args.harness or root / "tests/NativeBoreTests.cs").resolve()
        sources = [host / "CamTurnBoreBuilder.cs", host / "CamBatchReader.cs", harness]
        absent = [str(path) for path in sources if not path.is_file()]
        if absent:
            raise ValueError("Test sources missing: " + ", ".join(absent))
        dependencies = (args.dependencies_dir or host / "bin/Release/net48").resolve()
        interop = [dependencies / name for name in INTEROP_NAMES]
        absent = [str(path) for path in interop if not path.is_file()]
        if absent:
            raise MissingPrerequisite("Build the add-in dependencies first; missing: " + ", ".join(absent))
        framework = framework_directory(args.framework_dir)
        references = interop + [framework / name for name in FRAMEWORK_NAMES]
        compiler = compiler_command(args.compiler)
        inputs = sources + references + [Path(compiler[-1])]
        pins = {str(path): digest(path) for path in inputs}
        report.update({"source_root": str(root), "inputs_sha256": pins, "compiler": compiler,
                       "framework_dir": str(framework), "dependencies_dir": str(dependencies)})
        binary_dir = output / "bin"
        binary_dir.mkdir()
        executable = binary_dir / "NativeBoreTests.exe"
        response = output / "compile.rsp"
        lines = ["/nologo", "/nostdlib+", "/langversion:latest", "/target:exe",
                 "/out:" + quote_rsp(executable)]
        lines.extend("/r:" + quote_rsp(path) for path in references)
        lines.extend(quote_rsp(path) for path in sources)
        response.write_text("\n".join(lines) + "\n", encoding="utf-8")
        compile_command = compiler + ["/noconfig", "@" + str(response)]
        report["compile_command"] = compile_command
        result = invoke(compile_command, args.timeout)
        (output / "compile.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (output / "compile.stderr.txt").write_text(result.stderr, encoding="utf-8")
        report["compile_exit_code"] = result.returncode
        if result.returncode:
            raise RuntimeError("Compilation failed; see compile.stdout.txt and compile.stderr.txt")
        for path in interop:
            shutil.copyfile(path, binary_dir / path.name)
        report["executable_sha256"] = digest(executable)
        command = [str(executable), str(output / "fixtures")]
        report["test_command"] = command
        result = invoke(command, args.timeout)
        (output / "test.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (output / "test.stderr.txt").write_text(result.stderr, encoding="utf-8")
        report["test_exit_code"] = result.returncode
        if result.returncode:
            raise RuntimeError("Synthetic harness failed; see test.stdout.txt and test.stderr.txt")
        payload = json.loads(result.stdout)
        report["harness_result"] = payload
        if (payload.get("status") != "passed" or payload.get("passed") != 64
                or payload.get("failed") != 0 or payload.get("native_called") is not False
                or payload.get("COM_activated") is not False):
            raise RuntimeError("Harness did not report the expected 64 synthetic checks")
        if any(digest(Path(path)) != value for path, value in pins.items()):
            raise RuntimeError("Input files changed while tests were running")
        report["status"] = "PASS"
        code = 0
    except MissingPrerequisite as exc:
        report.update(status="SKIP", reason=str(exc))
        code = 77
    except Exception as exc:
        report.update(status="FAIL", reason=type(exc).__name__ + ": " + str(exc))
    report["exit_code"] = code
    if output and output.is_dir():
        # An existing directory belongs to the caller and is never reused.
        if "output_dir" in report:
            (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
