[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$CscPath,[Parameter(Mandatory=$true)][string]$SidecarAssemblyPath,[Parameter(Mandatory=$true)][string]$SidecarSha256,[Parameter(Mandatory=$true)][string]$ExistingHostAssemblyPath,[Parameter(Mandatory=$true)][string]$ExistingHostSha256,[Parameter(Mandatory=$true)][string]$ReceiptPath)
$ErrorActionPreference='Stop'
$package=[IO.Path]::GetFullPath($PSScriptRoot)
$exe=Join-Path $package 'ComProjectionHarness.exe'
& $CscPath /nologo /target:exe /platform:x64 /r:System.Core.dll /r:System.Web.Extensions.dll ('/out:'+$exe) (Join-Path $package 'ComProjectionHarness.cs')
if($LASTEXITCODE -ne 0){throw 'Projection harness build failed'}
& $exe $SidecarAssemblyPath $SidecarSha256 $ExistingHostAssemblyPath $ExistingHostSha256 $ReceiptPath
if($LASTEXITCODE -ne 0){throw 'Projection harness failed'}