<#
.SYNOPSIS
Build, register, probe, or unregister the CAD Studio SolidWorks C# Add-in host.

.DESCRIPTION
CurrentUser mode avoids elevation. Machine mode uses 64-bit RegAsm and HKLM.
All registry writes are scoped to the fixed Add-in GUID.
#>
[CmdletBinding()]
param(
    [ValidateSet('Build', 'Register', 'RegisterBuilt', 'ComSmoke', 'Probe', 'Unregister')]
    [string]$Action = 'Build',

    [ValidateSet('CurrentUser', 'Machine')]
    [string]$RegistrationScope = 'CurrentUser',

    [string]$SolidWorksApiDir = $env:SOLIDWORKS_API_DIR,
    [string]$DotNetPath = "$env:LOCALAPPDATA\Microsoft\dotnet\dotnet.exe",
    [string]$Configuration = 'Release',
    [string]$CamWorksTlbPath = $env:SOLIDWORKS_CAM_TLB,
    [string]$NetFxToolsDir = '',
    [string]$ExpectedAssemblySha256 = '',
    [string]$ExpectedTypeLibrarySha256 = '',
    [string]$ComSmokeDiagnosticPath = '',
    [string[]]$RequiredCamInterface = @('{DA9D97F8-EB0E-4D7B-A741-0E1736E899A2}'),
    [switch]$ElevatedChild
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ProjectPath = Join-Path $ProjectRoot 'dotnet\CadStudio.SolidWorks.AddinHost\CadStudio.SolidWorks.AddinHost.csproj'
$OutputDir = Join-Path $ProjectRoot "dotnet\CadStudio.SolidWorks.AddinHost\bin\$Configuration\net48"
$AssemblyPath = Join-Path $OutputDir 'CadStudio.SolidWorks.AddinHost.dll'
$TypeLibraryPath = Join-Path $OutputDir 'CadStudio.SolidWorks.AddinHost.tlb'
$AddinGuid = '{8EE76E8D-9B47-4DE0-AFA2-B2E36621A134}'
$ProgId = 'CadStudio.SolidWorks.AddinHost'
$ClassName = 'CadStudio.SolidWorks.AddinHost.SwAddin'
$RegAsmPath = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\RegAsm.exe"

function Get-ComSmokeExceptionEvidence {
    param([Parameter(Mandatory=$true)][Exception]$Exception)
    $pending = [Collections.Generic.Queue[object]]::new()
    $pending.Enqueue(@{ exception = $Exception; relation = 'root'; parent = $null })
    $rows = [Collections.Generic.List[object]]::new()
    $omitted = $false
    while ($pending.Count -gt 0 -and $rows.Count -lt 32) {
        $item = $pending.Dequeue()
        $current = $item.exception
        $row = [ordered]@{
            index = $rows.Count; parent = $item.parent; relation = $item.relation
            type = $current.GetType().FullName; message = $current.Message
            hresult = $current.HResult; stack_trace = $current.StackTrace
            file_name = $null; fusion_log = $null; property_read_errors = @()
        }
        foreach ($pair in @(@('FileName', 'file_name'), @('FusionLog', 'fusion_log'))) {
            try {
                if ($current.PSObject.Properties[$pair[0]]) { $row[$pair[1]] = $current.($pair[0]) }
            } catch { $row.property_read_errors += @{ property = $pair[0]; message = $_.Exception.Message } }
        }
        $index = $rows.Count
        $rows.Add($row)
        if ($current.InnerException) {
            $pending.Enqueue(@{ exception = $current.InnerException; relation = 'inner'; parent = $index })
        }
        if ($current -is [Reflection.ReflectionTypeLoadException]) {
            foreach ($loaderError in $current.LoaderExceptions) {
                if ($rows.Count + $pending.Count -ge 32) { $omitted = $true; break }
                if ($loaderError) { $pending.Enqueue(@{ exception = $loaderError; relation = 'loader'; parent = $index }) }
            }
        }
    }
    return @{ entries = $rows.ToArray(); truncated = ($omitted -or $pending.Count -gt 0); limit = 32 }
}

function Resolve-SolidWorksApiDir {
    if ($SolidWorksApiDir -and (Test-Path (Join-Path $SolidWorksApiDir 'SolidWorks.Interop.sldworks.dll'))) {
        return (Resolve-Path $SolidWorksApiDir).Path
    }
    $setupKeys = Get-ChildItem 'HKLM:\SOFTWARE\SOLIDWORKS' -ErrorAction SilentlyContinue |
        Where-Object { $_.PSChildName -like 'SOLIDWORKS 20*' } |
        Sort-Object PSChildName -Descending
    foreach ($setupKey in $setupKeys) {
        $setup = Get-ItemProperty (Join-Path $setupKey.PSPath 'Setup') -ErrorAction SilentlyContinue
        $installFolder = $setup.'SolidWorks Folder'
        if ($installFolder) {
            $candidate = Join-Path $installFolder 'api\redist'
            if (Test-Path (Join-Path $candidate 'SolidWorks.Interop.sldworks.dll')) {
                return (Resolve-Path $candidate).Path
            }
        }
    }
    throw 'SolidWorks PIA not found. Pass -SolidWorksApiDir <SOLIDWORKS\api\redist>.'
}

function Build-AddinHost {
    $apiDir = Resolve-SolidWorksApiDir
    $dotNetExe = $DotNetPath
    if (-not (Test-Path -LiteralPath $dotNetExe)) {
        $dotNetExe = (Get-Command dotnet.exe -ErrorAction Stop).Source
    }
    $camTlb = $CamWorksTlbPath
    if (-not $camTlb) {
        $solidWorksDir = Split-Path -Parent (Split-Path -Parent $apiDir)
        $camTlb = Join-Path (Split-Path -Parent $solidWorksDir) 'SOLIDWORKS CAM\camworks.tlb'
    }
    if (-not (Test-Path -LiteralPath $camTlb -PathType Leaf)) { throw "CAM typelib not found: $camTlb" }
    $toolsDir = $NetFxToolsDir
    if (-not $toolsDir) { $toolsDir = Join-Path ${env:ProgramFiles(x86)} 'Microsoft SDKs\Windows\v10.0A\bin\NETFX 4.8 Tools' }
    $importer = Join-Path $toolsDir 'TlbImp.exe'
    $strongName = Join-Path $toolsDir 'sn.exe'
    foreach ($tool in @($importer, $strongName)) { if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) { throw "Required build tool missing: $tool" } }
    $interopDir = Join-Path (Split-Path -Parent $ProjectPath) 'obj\cam-interop'
    New-Item -ItemType Directory -Force -Path $interopDir | Out-Null
    $interopPath = Join-Path $interopDir 'CamWorks.Interop.dll'
    $keyPath = Join-Path $interopDir 'CamWorks.Interop.snk'
    if (-not (Test-Path -LiteralPath $keyPath)) {
        & $strongName -k $keyPath
        if ($LASTEXITCODE -ne 0) { throw 'CAM interop development key creation failed.' }
    }
    $inputs = @{
        typelib_sha256 = (Get-FileHash -LiteralPath $camTlb -Algorithm SHA256).Hash
        importer_sha256 = (Get-FileHash -LiteralPath $importer -Algorithm SHA256).Hash
        key_sha256 = (Get-FileHash -LiteralPath $keyPath -Algorithm SHA256).Hash
    }
    $manifestPath = Join-Path $interopDir 'build-inputs.json'
    $reuse = $false
    if ((Test-Path -LiteralPath $manifestPath) -and (Test-Path -LiteralPath $interopPath)) {
        $old = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $reuse = $old.typelib_sha256 -eq $inputs.typelib_sha256 -and $old.importer_sha256 -eq $inputs.importer_sha256 -and $old.key_sha256 -eq $inputs.key_sha256 -and $old.output_sha256 -eq (Get-FileHash -LiteralPath $interopPath -Algorithm SHA256).Hash
    }
    if (-not $reuse) {
        & $importer $camTlb "/out:$interopPath" /namespace:CamWorks.Interop /machine:X64 "/keyfile:$keyPath" /silent
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $interopPath)) { throw 'CAM interop import failed.' }
        $inputs.output_sha256 = (Get-FileHash -LiteralPath $interopPath -Algorithm SHA256).Hash
        $inputs | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    }
    & $dotNetExe build $ProjectPath -c $Configuration "-p:SolidWorksApiDir=$apiDir" "-p:CamWorksInteropPath=$interopPath" --nologo
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $AssemblyPath)) {
        throw "Add-in build failed: $AssemblyPath"
    }
    Export-AddinTypeLibrary
}

function Export-AddinTypeLibrary {
    $toolsDir = $NetFxToolsDir
    if (-not $toolsDir) { $toolsDir = Join-Path ${env:ProgramFiles(x86)} 'Microsoft SDKs\Windows\v10.0A\bin\NETFX 4.8 Tools' }
    $exporter = Join-Path $toolsDir 'x64\TlbExp.exe'
    if (-not (Test-Path -LiteralPath $exporter -PathType Leaf)) { $exporter = Join-Path $toolsDir 'TlbExp.exe' }
    if (-not (Test-Path -LiteralPath $exporter -PathType Leaf)) { throw "Type library exporter missing: $exporter" }
    & $exporter $AssemblyPath "/out:$TypeLibraryPath" /win64 /silent
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $TypeLibraryPath -PathType Leaf)) { throw 'Host type library export failed.' }
    Invoke-CheckedTypeLibrary
}

function Initialize-NativeTypeLibraryRegistration {
    if ('CadStudio.Deployment.TypeLibraryNative' -as [type]) { return }
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace CadStudio.Deployment {
    public static class TypeLibraryNative {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetCurrentPackageFullName(ref uint length, IntPtr name);
        [DllImport("oleaut32.dll", CharSet = CharSet.Unicode)]
        private static extern int LoadTypeLibEx(string path, int kind, out IntPtr library);
        [DllImport("oleaut32.dll", CharSet = CharSet.Unicode)]
        private static extern int RegisterTypeLibForUser(IntPtr library, string path, string help);
        public static void AssertUnpackaged64() {
            if (!Environment.Is64BitProcess) throw new InvalidOperationException("64-bit registration process required.");
            uint length = 0;
            int result = GetCurrentPackageFullName(ref length, IntPtr.Zero);
            if (result != 15700) throw new InvalidOperationException("Unpackaged registration process required; package registry isolation is not supported. Status: " + result);
        }
        public static void Register(string path) {
            AssertUnpackaged64();
            IntPtr library = IntPtr.Zero;
            try {
                int result = LoadTypeLibEx(path, 2, out library); // REGKIND_NONE
                if (result != 0) throw new COMException("Type library operation did not return S_OK.", result);
                if (library == IntPtr.Zero) throw new InvalidOperationException("No loaded type library.");
                result = RegisterTypeLibForUser(library, path, null);
                if (result != 0) throw new COMException("Type library operation did not return S_OK.", result);
            } finally {
                if (library != IntPtr.Zero) Marshal.Release(library);
            }
        }
    }
}
"@
}

function Assert-TypeLibraryRegistrationInput {
    param([object]$Checked, [string]$Path, [string]$Sha256)
    if ($Sha256 -notmatch '^[0-9a-fA-F]{64}$' -or
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Sha256) {
        throw 'Validated type library hash changed before registration.'
    }
    $shape = $Checked.shape
    if ($Checked.status -ne 'validated' -or $Checked.registration_attempted -ne $false -or
        $shape.libid -ne '{AF071B05-0956-3EFB-B3F0-77BC51751AC9}' -or
        ($shape.version -join '.') -ne '1.0' -or $shape.syskind -ne 3) {
        throw 'Validated x64 host type library receipt required.'
    }
    $known = @('{DA9D97F8-EB0E-4D7B-A741-0E1736E899A2}', '{D8D32706-6533-47A3-821B-BB23D266C188}',
        '{63CD9668-1A04-4D45-AC42-AD484D30F9EB}', '{05C45FEF-D8E5-3BAF-BB0C-F24CFD6A65BA}',
        '{C3819565-9281-33ED-885A-1973E9AB1487}')
    $interfaces = @($shape.interfaces | ForEach-Object { $_.guid.ToUpperInvariant() })
    if ($interfaces.Count -lt 3 -or $interfaces.Count -gt 5 -or
        @($interfaces | Sort-Object -Unique).Count -ne $interfaces.Count) { throw 'Bounded unique host interfaces required.' }
    foreach ($identity in $interfaces) {
        if ($identity -notin $known) { throw 'Unknown exported host interface.' }
    }
    foreach ($identity in @($RequiredCamInterface) + @($known[0], $known[3], $known[4])) {
        if ($identity -notin $interfaces) { throw 'Required host interface missing from checked type library.' }
    }
    return $interfaces
}

function Read-UserTypeLibraryRegistration {
    param([string]$Path, [string[]]$Interfaces)
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser,
        [Microsoft.Win32.RegistryView]::Registry64)
    $read = {
        param([string]$Key, [string]$Name = '')
        $opened = $base.OpenSubKey('Software\Classes\' + $Key, $false)
        if ($null -eq $opened) { throw "Current-user registration key missing: $Key" }
        try {
            if ($opened.GetValueKind($Name) -ne [Microsoft.Win32.RegistryValueKind]::String) {
                throw 'String registration value required.'
            }
            return [string]$opened.GetValue($Name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        } finally { $opened.Dispose() }
    }
    try {
        $libid = '{AF071B05-0956-3EFB-B3F0-77BC51751AC9}'
        $actual = & $read ('TypeLib\' + $libid + '\1.0\0\win64')
        if (-not [string]::Equals([IO.Path]::GetFullPath($actual), [IO.Path]::GetFullPath($Path),
            [StringComparison]::OrdinalIgnoreCase)) { throw 'Registered type library path differs.' }
        foreach ($identity in $Interfaces) {
            $key = 'Interface\' + $identity
            if ((& $read ($key + '\TypeLib')) -ne $libid -or
                (& $read ($key + '\TypeLib') 'Version') -ne '1.0' -or
                (& $read ($key + '\ProxyStubClsid32')) -ne '{00020424-0000-0000-C000-000000000046}') {
                throw "Current-user interface registration differs: $identity"
            }
        }
        return [ordered]@{ verified = $true; type_library_path = $actual; interface_ids = $Interfaces;
            registry_scope = 'CurrentUser'; registry_view = 64; process_packaged = $false }
    } finally { $base.Dispose() }
}

function Register-NativeUserTypeLibrary {
    param([object]$Checked, [string]$Path, [string]$Sha256)
    $interfaces = @(Assert-TypeLibraryRegistrationInput -Checked $Checked -Path $Path -Sha256 $Sha256)
    Initialize-NativeTypeLibraryRegistration
    [CadStudio.Deployment.TypeLibraryNative]::AssertUnpackaged64()
    [CadStudio.Deployment.TypeLibraryNative]::Register($Path)
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Sha256) {
        throw 'Type library changed during registration; outcome requires inspection, no retry.'
    }
    return Read-UserTypeLibraryRegistration -Path $Path -Interfaces $interfaces
}

function Invoke-CheckedTypeLibrary {
    param([switch]$RegisterCurrentUser)
    $python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Project Python environment required for typelib validation.' }
    $metadataHash = (Get-FileHash -LiteralPath $TypeLibraryPath -Algorithm SHA256).Hash
    $arguments = @((Join-Path $PSScriptRoot 'sw_addin_typelib_registration.py'), '--typelib', $TypeLibraryPath)
    foreach ($interface in $RequiredCamInterface) { $arguments += @('--required-interface', $interface) }
    # Python is metadata-only: a Microsoft Store interpreter has a private HKCU overlay.
    $json = & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Host type library validation failed.' }
    $checked = ($json -join [Environment]::NewLine) | ConvertFrom-Json
    $null = Assert-TypeLibraryRegistrationInput -Checked $checked -Path $TypeLibraryPath -Sha256 $metadataHash
    $checked | Add-Member -NotePropertyName type_library_sha256 -NotePropertyValue $metadataHash
    if ($RegisterCurrentUser) {
        $readback = Register-NativeUserTypeLibrary -Checked $checked -Path $TypeLibraryPath -Sha256 $metadataHash
        $checked.registration_attempted = $true
        $checked.status = 'registered_verified'
        $checked.registry_scope = 'CurrentUser'
        $checked | Add-Member -NotePropertyName readback -NotePropertyValue $readback
    }
    $checked | ConvertTo-Json -Depth 20
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-ElevatedSelf {
    param([ValidateSet('Register', 'Unregister')][string]$ElevatedAction)
    $apiDir = Resolve-SolidWorksApiDir
    $quote = {
        param([string]$Value)
        return "'" + $Value.Replace("'", "''") + "'"
    }
    $command = "& $(& $quote $PSCommandPath) -Action $ElevatedAction -RegistrationScope Machine -SolidWorksApiDir $(& $quote $apiDir) -DotNetPath $(& $quote $DotNetPath) -Configuration $(& $quote $Configuration) -CamWorksTlbPath $(& $quote $CamWorksTlbPath) -NetFxToolsDir $(& $quote $NetFxToolsDir) -ElevatedChild"
    $requiredLiteral = ($RequiredCamInterface | ForEach-Object { & $quote $_ }) -join ","
    $command += " -RequiredCamInterface @($requiredLiteral)"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    $process = Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -Verb RunAs -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded
    ) -PassThru
    # Wait for this elevated helper only; compiler servers may outlive it.
    try {
        $process.WaitForExit()
        $exitCode = $process.ExitCode
        if ($exitCode -ne 0) {
            throw "Elevated $ElevatedAction failed or was cancelled. Exit code: $exitCode"
        }
    } finally {
        $process.Dispose()
    }
}

function Set-RegistryDefaultValue {
    param([string]$Path, [object]$Value, [Microsoft.Win32.RegistryValueKind]$Kind = [Microsoft.Win32.RegistryValueKind]::String)
    $key = New-Item -Path $Path -Force
    $key.SetValue('', $Value, $Kind)
    $key.Close()
}

function Get-AddinCodeBase {
    param([string]$ResolvedPath, [Reflection.AssemblyName]$Identity)
    # Framework RegistrationServices uses the original, unescaped CodeBase.
    if ($Identity -and $Identity.CodeBase) { return $Identity.CodeBase }
    if ($ResolvedPath -notmatch '^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+\\)') {
        throw 'Absolute Windows assembly path required.'
    }
    $uri = [Uri]$ResolvedPath
    if (-not $uri.IsFile) { throw 'File assembly CodeBase required.' }
    return $uri.GetComponents([UriComponents]::AbsoluteUri, [UriFormat]::Unescaped)
}

function Register-CurrentUser {
    Invoke-CheckedTypeLibrary -RegisterCurrentUser
    $resolvedAssembly = (Resolve-Path $AssemblyPath).Path
    $assemblyIdentity = [Reflection.AssemblyName]::GetAssemblyName($resolvedAssembly)
    $codeBase = Get-AddinCodeBase -ResolvedPath $resolvedAssembly -Identity $assemblyIdentity
    $assemblyName = $assemblyIdentity.FullName
    $assemblyVersion = $assemblyIdentity.Version.ToString()
    $classes = 'HKCU:\Software\Classes'
    Set-RegistryDefaultValue "$classes\$ProgId" $ClassName
    Set-RegistryDefaultValue "$classes\$ProgId\CLSID" $AddinGuid
    Set-RegistryDefaultValue "$classes\CLSID\$AddinGuid" $ClassName
    Set-RegistryDefaultValue "$classes\CLSID\$AddinGuid\InprocServer32" 'mscoree.dll'
    New-ItemProperty "$classes\CLSID\$AddinGuid\InprocServer32" -Name 'ThreadingModel' -Value 'Both' -PropertyType String -Force | Out-Null
    New-ItemProperty "$classes\CLSID\$AddinGuid\InprocServer32" -Name 'Class' -Value $ClassName -PropertyType String -Force | Out-Null
    New-ItemProperty "$classes\CLSID\$AddinGuid\InprocServer32" -Name 'Assembly' -Value $assemblyName -PropertyType String -Force | Out-Null
    New-ItemProperty "$classes\CLSID\$AddinGuid\InprocServer32" -Name 'RuntimeVersion' -Value 'v4.0.30319' -PropertyType String -Force | Out-Null
    New-ItemProperty "$classes\CLSID\$AddinGuid\InprocServer32" -Name 'CodeBase' -Value $codeBase -PropertyType String -Force | Out-Null
    New-Item "$classes\CLSID\$AddinGuid\InprocServer32\$assemblyVersion" -Force | Out-Null
    foreach ($name in @('Class', 'Assembly', 'RuntimeVersion', 'CodeBase')) {
        $value = switch ($name) { 'Class' { $ClassName } 'Assembly' { $assemblyName } 'RuntimeVersion' { 'v4.0.30319' } default { $codeBase } }
        New-ItemProperty "$classes\CLSID\$AddinGuid\InprocServer32\$assemblyVersion" -Name $name -Value $value -PropertyType String -Force | Out-Null
    }
    Set-RegistryDefaultValue "$classes\CLSID\$AddinGuid\ProgId" $ProgId
    New-Item "$classes\CLSID\$AddinGuid\Implemented Categories\{62C8FE65-4EBB-45E7-B440-6E39B2CDBF29}" -Force | Out-Null

}

function Unregister-CurrentUser {
    foreach ($path in @(
        "HKCU:\Software\Classes\$ProgId",
        "HKCU:\Software\Classes\CLSID\$AddinGuid",
        "HKCU:\Software\SOLIDWORKS\Addins\$AddinGuid",
        "HKCU:\Software\SOLIDWORKS\AddInsStartup\$AddinGuid"
    )) {
        if (Test-Path $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
}

switch ($Action) {
    'Build' {
        Build-AddinHost
    }
    'RegisterBuilt' {
        if ($RegistrationScope -ne 'CurrentUser') { throw 'RegisterBuilt supports only the current-user mapping.' }
        foreach ($pin in @($ExpectedAssemblySha256, $ExpectedTypeLibrarySha256)) {
            if ($pin -cnotmatch '^[0-9a-f]{64}$') { throw 'Exact reviewed DLL and type library SHA256 values required.' }
        }
        if ((Get-FileHash -LiteralPath $AssemblyPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedAssemblySha256 -or
            (Get-FileHash -LiteralPath $TypeLibraryPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedTypeLibrarySha256) {
            throw 'Existing reviewed DLL or type library changed.'
        }
        Register-CurrentUser
    }
    'Register' {
        if ($RegistrationScope -eq 'Machine') {
            if (-not (Test-IsAdministrator)) {
                if ($ElevatedChild) { throw 'Machine registration did not receive administrator privileges.' }
                Build-AddinHost
                Invoke-ElevatedSelf 'Register'
            } else {
                Build-AddinHost
                if (-not (Test-Path $RegAsmPath)) { throw "64-bit RegAsm not found: $RegAsmPath" }
                & $RegAsmPath $AssemblyPath /codebase "/tlb:$TypeLibraryPath"
                if ($LASTEXITCODE -ne 0) { throw 'RegAsm registration failed.' }
            }
        } else {
            Build-AddinHost
            Register-CurrentUser
        }
    }
    'ComSmoke' {
        if (-not (Test-Path "HKCU:\Software\Classes\CLSID\$AddinGuid\InprocServer32") -and
            -not (Test-Path "HKLM:\Software\Classes\CLSID\$AddinGuid\InprocServer32")) {
            throw 'COM class is not registered. Run Register first.'
        }
        $diagnosticStream = $null
        if ($ComSmokeDiagnosticPath) {
            if ($ComSmokeDiagnosticPath -notmatch '^(?:[A-Za-z]:[\\/]|[\\/]{2}[^\\/]+[\\/][^\\/]+(?:[\\/]|$))') {
                throw 'ComSmokeDiagnosticPath must be absolute.'
            }
            $diagnosticFile = [IO.Path]::GetFullPath($ComSmokeDiagnosticPath)
            # Reserve a fresh file before activation; never overwrite earlier evidence.
            $diagnosticStream = [IO.File]::Open($diagnosticFile, [IO.FileMode]::CreateNew,
                [IO.FileAccess]::Write, [IO.FileShare]::Read)
        }
        $smoke = [ordered]@{
            scope = 'ADDIN_COM_CONSTRUCTOR_SMOKE_V1'; status = 'pending'
            process_id = $PID; process_bits = ([IntPtr]::Size * 8)
            clr_version = [Environment]::Version.ToString(); prog_id = $ProgId; clsid = $AddinGuid
            expected_assembly_path = $AssemblyPath; activation_attempted = $false
            cad_connection_attempted = $false; registry_written = $false
        }
        try {
            $smoke.activation_attempted = $true
            $instance = New-Object -ComObject $ProgId
            if (-not $instance) { throw 'COM activation returned no object.' }
            if ([Runtime.InteropServices.Marshal]::IsComObject($instance)) {
                [Runtime.InteropServices.Marshal]::FinalReleaseComObject($instance) | Out-Null
            }
            $smoke.status = 'passed'
        } catch {
            $smoke.status = 'error'
            $smoke.exception_chain = Get-ComSmokeExceptionEvidence -Exception $_.Exception
            $smoke.error_id = $_.FullyQualifiedErrorId
            $smoke.category = $_.CategoryInfo.ToString()
            throw
        } finally {
            if ($diagnosticStream) {
                try {
                    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($smoke | ConvertTo-Json -Depth 20))
                    $diagnosticStream.Write($bytes, 0, $bytes.Length)
                    $diagnosticStream.Flush($true)
                } catch {
                    if ($smoke.status -ne 'error') { throw }
                    Write-Warning ('Could not persist ComSmoke failure evidence: ' + $_.Exception.Message) -WarningAction Continue
                } finally {
                    try { $diagnosticStream.Dispose() } catch {
                        Write-Warning ('Could not close ComSmoke evidence file: ' + $_.Exception.Message) -WarningAction Continue
                    }
                }
            }
        }
    }
    'Probe' {
        if (-not (Test-Path $AssemblyPath)) { Build-AddinHost }
        if (-not (Test-Path "HKLM:\SOFTWARE\SOLIDWORKS\Addins\$AddinGuid")) {
            throw 'HKLM SolidWorks Add-ins registration is missing. Run an elevated Machine registration before the in-process probe.'
        }
        & python (Join-Path $ProjectRoot 'tests\solidworks_addin_host_regression.py') --assembly $AssemblyPath --start
        if ($LASTEXITCODE -ne 0) { throw 'SolidWorks Add-in live probe failed.' }
    }
    'Unregister' {
        if ($RegistrationScope -eq 'Machine') {
            if (-not (Test-IsAdministrator)) {
                if ($ElevatedChild) { throw 'Machine unregister did not receive administrator privileges.' }
                Invoke-ElevatedSelf 'Unregister'
            } else {
                if (-not (Test-Path $RegAsmPath)) { throw "64-bit RegAsm not found: $RegAsmPath" }
                & $RegAsmPath $AssemblyPath /unregister "/tlb:$TypeLibraryPath"
                if ($LASTEXITCODE -ne 0) { throw 'RegAsm unregister failed.' }
            }
        } else {
            Unregister-CurrentUser
        }
    }
}

[pscustomobject]@{
    action = $Action
    scope = $RegistrationScope
    assembly = $AssemblyPath
    type_library = $TypeLibraryPath
    type_library_exists = Test-Path $TypeLibraryPath
    com_registered = (Test-Path "HKCU:\Software\Classes\CLSID\$AddinGuid\InprocServer32") -or (Test-Path "HKLM:\Software\Classes\CLSID\$AddinGuid\InprocServer32")
    solidworks_discovery_registered = Test-Path "HKLM:\SOFTWARE\SOLIDWORKS\Addins\$AddinGuid"
    in_process_probe_ready = (Test-Path "HKLM:\SOFTWARE\SOLIDWORKS\Addins\$AddinGuid") -and (Get-Process SLDWORKS -ErrorAction SilentlyContinue)
}
