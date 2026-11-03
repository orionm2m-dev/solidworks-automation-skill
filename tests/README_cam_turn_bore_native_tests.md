# Native bore synthetic tests

On Windows, from the repository root after building the add-in dependencies:

```powershell
python tests/run_cam_turn_bore_native_tests.py --output-dir C:/Temp/bore-check-001
```

The output directory must be new and short. Omitting it creates a fresh temporary directory. The runner compiles `CamTurnBoreBuilder.cs`, `CamBatchReader.cs` and the unchanged `tests/NativeBoreTests.cs`, then executes the 64 synthetic checks with no visible console. It does not load the add-in into CAD, activate COM, or write the registry. It uses the existing interop DLLs under `dotnet/CadStudio.SolidWorks.AddinHost/bin/Release/net48`.

`--source-root`, `--harness`, `--dependencies-dir`, `--framework-dir`, and `--compiler` override discovery. By default the runner finds Roslyn in an installed dotnet SDK and NET48 reference assemblies (or the installed 64-bit .NET Framework assembly directory). `--compiler` accepts Roslyn `csc.dll` or `csc.exe`.

Exit codes: `0` = all 64 checks pass; `1` = compile/test/input failure; `77` = missing platform, SDK, framework or interop dependencies (explicit skip). `result.json` records source/compiler/dependency hashes, commands and outcomes; compiler and harness logs remain beside it. No existing output directory is overwritten or deleted. These tests exercise the fake backend and guards, not native CAD initialization or Save/reopen persistence.
