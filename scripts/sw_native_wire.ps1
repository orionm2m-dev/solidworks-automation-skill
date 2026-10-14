param([Parameter(Mandatory=$true)][string]$InputBase64,[Parameter(Mandatory=$true)][string]$InteropRoot)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$dll=Join-Path $InteropRoot 'SolidWorks.Interop.sldworks.dll'
$constants=Join-Path $InteropRoot 'SolidWorks.Interop.swconst.dll'
Add-Type -Path $dll
Add-Type -Path $constants
Add-Type -TypeDefinition ([IO.File]::ReadAllText((Join-Path $PSScriptRoot 'sw_native_wire.cs'))) -ReferencedAssemblies @($dll,$constants,'System.Web.Extensions','System.Core')
[NativeWireTools]::Run([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($InputBase64)))