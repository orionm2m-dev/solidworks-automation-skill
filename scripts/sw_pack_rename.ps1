param([Parameter(Mandatory=$true)][string]$InputBase64,[Parameter(Mandatory=$true)][string]$InteropRoot)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$assemblyPath=Join-Path $InteropRoot 'SolidWorks.Interop.sldworks.dll'
Add-Type -Path $assemblyPath
Add-Type -TypeDefinition ([IO.File]::ReadAllText((Join-Path $PSScriptRoot 'sw_pack_rename.cs'))) -ReferencedAssemblies @($assemblyPath,'System.Web.Extensions','System.Core')
$payload=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($InputBase64))
[NativeNamedCopy]::Run($payload)
