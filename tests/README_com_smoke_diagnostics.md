# COM constructor diagnostic tests

From the repository root on Windows PowerShell 5.1:

```powershell
powershell.exe -NoProfile -File tests/test_com_smoke_diagnostics.ps1 -OutputDirectory C:/Temp/com-smoke-check-001
```

Use a new output directory. The driver reads the current `scripts/sw_addin_host.ps1` by default; `-ScriptPath` can select another staged copy. It extracts the diagnostic helper and ComSmoke branch, replaces activation and registry lookup with synthetic functions, and exercises 13 checks. No COM object, CAD connection or registry write is performed.

The checks cover exception fields and bounded inner/loader chains, successful and failed synthetic activation, fresh output protection, relative/drive-relative/root-relative path rejection, and preservation of the original activation failure when evidence writing fails. The separate real `-Action ComSmoke -ComSmokeDiagnosticPath <fully-qualified-fresh-file>` command activates the registered host once and is not run by this test driver.
