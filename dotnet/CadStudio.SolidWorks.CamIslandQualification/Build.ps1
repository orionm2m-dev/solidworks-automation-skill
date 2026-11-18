[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ReferenceDirectory,[Parameter(Mandatory=$true)][string]$DotNet,[Parameter(Mandatory=$true)][string]$Roslyn,[Parameter(Mandatory=$true)][string]$TlbExp,[string]$SigningKeyPath,[switch]$Test)
$ErrorActionPreference='Stop'
$package=[IO.Path]::GetFullPath($PSScriptRoot)
$binary=Join-Path $package 'bin'
New-Item -ItemType Directory -Force -Path $binary | Out-Null
$compile=@($Roslyn,'/nologo','/platform:x64','/nostdlib+')
foreach($name in @('mscorlib.dll','System.dll','System.Core.dll','System.Web.Extensions.dll','Microsoft.CSharp.dll','System.Windows.Forms.dll','System.Drawing.dll')){$compile+=('/r:'+"$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\"+$name)}
foreach($name in @('CamWorks.Interop.dll','SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swpublished.dll')){$source=Join-Path $ReferenceDirectory $name; if(!(Test-Path -LiteralPath $source)){throw "Missing explicit reference: $source"};$compile+=('/r:'+$source);Copy-Item -LiteralPath $source -Destination (Join-Path $binary $name) -Force}
if($Test){
 $target=Join-Path $binary 'NativeContractHarness.exe'
 $compile+=@('/target:exe',('/out:'+$target),(Join-Path $package 'CamIslandQualification.cs'),(Join-Path $package 'tests\NativeContractHarness.cs'))
 & $DotNet @compile
 if($LASTEXITCODE -ne 0){throw 'Harness compilation failed'}
 & $target (Join-Path $package 'tests')
 if($LASTEXITCODE -ne 0){throw 'Harness execution failed'}
}else{
 if([String]::IsNullOrWhiteSpace($SigningKeyPath)){throw 'SigningKeyPath is required for a release build'};$key=[IO.Path]::GetFullPath($SigningKeyPath);if(!(Test-Path -LiteralPath $key)){throw 'Explicit strong-name key missing'}
 $target=Join-Path $binary 'CadStudio.SolidWorks.CamIslandQualification.dll'
 $compile+=@('/target:library',('/out:'+$target),('/keyfile:'+$key),(Join-Path $package 'CamIslandQualification.cs'))
 & $DotNet @compile
 if($LASTEXITCODE -ne 0){throw 'Native sidecar compilation failed'}
 & $TlbExp $target ('/out:'+(Join-Path $binary 'CadStudio.SolidWorks.CamIslandQualification.tlb')) /win64 /nologo
 if($LASTEXITCODE -ne 0){throw 'Native sidecar TLB export failed'}
}