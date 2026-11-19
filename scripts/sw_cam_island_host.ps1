<# Fixed, reversible current-user registration for the CAM island companion.
No SOLIDWORKS process is activated. Fixed HKLM discovery is explicit/admin-only; no autostart is written.
#>
[CmdletBinding()]
param(
 [ValidateSet('Validate','RegisterBuilt','Probe','Rollback','AddDiscovery','RemoveDiscovery','RelocateBuilt','RollbackCodeBase')][string]$Action='Validate',
 [string]$AssemblyPath, [string]$TypeLibraryPath,
 [string]$ExpectedAssemblySha256, [string]$ExpectedTypeLibrarySha256,
 [Parameter(Mandatory=$true)][string]$ReceiptPath,
 [string]$RegistrationReceiptPath, [string]$RegistrationReceiptSha256,
 [string]$DiscoveryReceiptPath, [string]$DiscoveryReceiptSha256,
 [string]$PreviousAssemblyPath, [string]$ExpectedPreviousAssemblySha256,
 [string]$ProbeReceiptPath, [string]$ProbeReceiptSha256,
 [string]$RelocationReceiptPath, [string]$RelocationReceiptSha256
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$clsid='{F69869EF-C175-4A06-9426-E1502BFA8921}'
$iid='{36B207A9-AF3A-4F89-B211-5755E7CF6327}'
$libid='{91FE2D85-D19A-4DBB-8BB0-B6D02A948FA5}'
$prog='CadStudio.SolidWorks.CamIslandQualification'
$class='CadStudio.SolidWorks.CamIslandQualification.IslandAddin'
$discoveryRoot="SOFTWARE\SOLIDWORKS\AddIns\$clsid"
$discoveryTitle='CAM Island Qualification'
$discoveryDescription='Bounded native owner-STA CAM island qualification; manual load only.'
$discoveryScope='CAM_ISLAND_COMPANION_DISCOVERY_V1'
$machineRegistry=$null
$isDiscoveryAction=$Action -in @('AddDiscovery','RemoveDiscovery')
$isRelocationAction=$Action -in @('RelocateBuilt','RollbackCodeBase')
$relocationScope='CAM_ISLAND_COMPANION_CODEBASE_RELOCATION_V1'
$codeBaseKeys=@("Software\Classes\CLSID\$clsid\InprocServer32","Software\Classes\CLSID\$clsid\InprocServer32\1.0.0.0")
$roots=@("Software\Classes\CLSID\$clsid","Software\Classes\$prog","Software\Classes\TypeLib\$libid","Software\Classes\Interface\$iid")
function Assert-True([bool]$Value,[string]$Message){if(-not $Value){throw $Message}}
function Hash([string]$Path){return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function Json($Value){return ConvertTo-Json -InputObject $Value -Depth 60 -Compress}
function Write-New([string]$Path,$Value){
 Assert-True ([IO.Path]::IsPathRooted($Path)) 'Absolute receipt path required.'
 $data=[Text.UTF8Encoding]::new($false).GetBytes((Json $Value))
 $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
 try{$stream.Write($data,0,$data.Length);$stream.Flush($true)}finally{$stream.Dispose()}
}
Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using TYPELIBATTR = System.Runtime.InteropServices.ComTypes.TYPELIBATTR;
using TYPEATTR = System.Runtime.InteropServices.ComTypes.TYPEATTR;
using SYSKIND = System.Runtime.InteropServices.ComTypes.SYSKIND;
namespace CadStudio.IslandDeployment {
 public static class Native {
  [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern int GetCurrentPackageFullName(ref uint size,IntPtr name);
  [DllImport("oleaut32.dll",CharSet=CharSet.Unicode)] static extern int LoadTypeLibEx(string path,int kind,out ITypeLib lib);
  [DllImport("oleaut32.dll",CharSet=CharSet.Unicode)] static extern int RegisterTypeLibForUser(ITypeLib lib,string path,string help);
  public static void CheckProcess(){uint n=0;if(!Environment.Is64BitProcess||GetCurrentPackageFullName(ref n,IntPtr.Zero)!=15700)throw new InvalidOperationException("Unpackaged 64-bit process required.");}
  static void Ok(int hr){if(hr!=0)throw new COMException("Type library operation failed.",hr);}
  public static string[] Validate(string path){
   CheckProcess();ITypeLib lib;Ok(LoadTypeLibEx(path,2,out lib));IntPtr pa=IntPtr.Zero;
   try{lib.GetLibAttr(out pa);var a=(TYPELIBATTR)Marshal.PtrToStructure(pa,typeof(TYPELIBATTR));
    if(a.guid!=new Guid("91FE2D85-D19A-4DBB-8BB0-B6D02A948FA5")||a.wMajorVerNum!=1||a.wMinorVerNum!=0||a.syskind!=SYSKIND.SYS_WIN64)throw new InvalidOperationException("Fixed x64 library required.");
    var types=new List<string>();for(int i=0;i<lib.GetTypeInfoCount();i++){ITypeInfo info;lib.GetTypeInfo(i,out info);IntPtr p=IntPtr.Zero;try{info.GetTypeAttr(out p);var t=(TYPEATTR)Marshal.PtrToStructure(p,typeof(TYPEATTR));types.Add(t.typekind+":"+t.guid.ToString("B").ToUpperInvariant());}finally{if(p!=IntPtr.Zero)info.ReleaseTypeAttr(p);Marshal.ReleaseComObject(info);}}
    return types.ToArray();
   }finally{if(pa!=IntPtr.Zero)lib.ReleaseTLibAttr(pa);Marshal.ReleaseComObject(lib);}
  }
  public static void Register(string path){CheckProcess();ITypeLib lib;Ok(LoadTypeLibEx(path,2,out lib));try{Ok(RegisterTypeLibForUser(lib,path,null));}finally{Marshal.ReleaseComObject(lib);}}
 }
}
"@
[CadStudio.IslandDeployment.Native]::CheckProcess()
$registry=[Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser,[Microsoft.Win32.RegistryView]::Registry64)
function Snapshot-Key([string]$Path,[Microsoft.Win32.RegistryKey]$BaseKey=$registry){
 $key=$BaseKey.OpenSubKey($Path,$false);if($null -eq $key){return $null}
 try{
  $values=@();foreach($name in @($key.GetValueNames()|Sort-Object)){$values+=,[ordered]@{name=$name;kind=$key.GetValueKind($name).ToString();value=$key.GetValue($name,$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)}}
  $children=@();foreach($name in @($key.GetSubKeyNames()|Sort-Object)){$children+=,[ordered]@{name=$name;tree=(Snapshot-Key "$Path\$name" $BaseKey)}}
  return [ordered]@{values=$values;children=$children}
 }finally{$key.Dispose()}
}
function Snapshot-All{$result=@();foreach($path in $roots){$result+=,[ordered]@{path=$path;tree=(Snapshot-Key $path)}};return ,$result}
function Set-Value([string]$Path,[string]$Name,[string]$Value){$key=$registry.CreateSubKey($Path);try{$key.SetValue($Name,$Value,[Microsoft.Win32.RegistryValueKind]::String)}finally{$key.Dispose()}}
function Read-Value([string]$Path,[string]$Name=''){$key=$registry.OpenSubKey($Path,$false);Assert-True ($null -ne $key) "Missing registry key: $Path";try{Assert-True ($key.GetValueKind($Name) -eq [Microsoft.Win32.RegistryValueKind]::String) 'Expected string registry value.';return $key.GetValue($Name,$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)}finally{$key.Dispose()}}
# Discovery contracts are pure guards; they never request elevation or change keys.
function Discovery-ExpectedTree {
 return [ordered]@{values=@(
  [ordered]@{name='';kind='DWord';value=0},
  [ordered]@{name='Description';kind='String';value=$discoveryDescription},
  [ordered]@{name='Title';kind='String';value=$discoveryTitle}
 );children=@()}
}
function Assert-DiscoveryComReceipt($Registered,$CurrentCom,[string]$Dll,[string]$Tlb,[string]$DllSha,[string]$TlbSha){
 Assert-True ($Registered.scope -ceq 'CAM_ISLAND_COMPANION_REGISTRATION_V1' -and $Registered.action -ceq 'RegisterBuilt' -and $Registered.status -ceq 'registered' -and $Registered.mutation_attempted -eq $true) 'Successful own COM registration receipt required.'
 Assert-True ($Registered.registry_scope -ceq 'CurrentUser' -and $Registered.registry_view -eq 64 -and $Registered.autostart_written -eq $false) 'Exact current-user 64-bit COM registration scope required.'
 Assert-True ((Json $Registered.owned_keys) -ceq (Json $roots)) 'COM receipt owns different roots.'
 Assert-True (@($Registered.before).Count -eq 4 -and @($Registered.before|Where-Object {$null -ne $_.tree}).Count -eq 0) 'COM receipt must record four initially absent roots.'
 Assert-True ((Json $Registered.after) -ceq (Json $CurrentCom)) 'Current COM registration differs from pinned receipt.'
 Assert-True ([IO.Path]::GetFullPath($Registered.assembly.path) -ieq [IO.Path]::GetFullPath($Dll) -and $Registered.assembly.sha256 -ceq $DllSha -and [IO.Path]::GetFullPath($Registered.typelib.path) -ieq [IO.Path]::GetFullPath($Tlb) -and $Registered.typelib.sha256 -ceq $TlbSha) 'COM receipt assembly/type-library pins differ.'
}
function Assert-DiscoveryRemovalReceipt($Added,$CurrentTree,[string]$ComReceiptSha,[string]$DllSha,[string]$TlbSha){
 Assert-True ($Added.scope -ceq $discoveryScope -and $Added.action -ceq 'AddDiscovery' -and $Added.status -in @('discovery_added','failed') -and $Added.mutation_attempted -eq $true) 'Completed own discovery-add attempt receipt required.'
 Assert-True ($Added.registry_scope -ceq 'LocalMachine' -and $Added.registry_view -eq 64 -and $Added.owned_machine_key -ceq $discoveryRoot -and $Added.autostart_written -eq $false) 'Discovery receipt owns a different key or scope.'
 Assert-True ($Added.PSObject.Properties.Name -contains 'discovery_before' -and $Added.PSObject.Properties.Name -contains 'discovery_after' -and $null -eq $Added.discovery_before) 'Only initially absent discovery key may be removed.'
 Assert-True ((Json $Added.discovery_after) -ceq (Json $CurrentTree)) 'Discovery key changed since receipt; refusing removal.'
 Assert-True ($Added.registration_receipt.sha256 -ceq $ComReceiptSha -and $Added.assembly.sha256 -ceq $DllSha -and $Added.typelib.sha256 -ceq $TlbSha) 'Discovery removal evidence pins differ.'
}
function Assert-DiscoveryAdministrator {
 $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
 try{$principal=[Security.Principal.WindowsPrincipal]::new($identity);Assert-True ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Explicit elevated administrator process required for fixed HKLM discovery; no automatic UAC is launched.'}finally{$identity.Dispose()}
}
# Versioned deployment contracts. Pure snapshot guards never access registry or activate COM.
function CodeBase-Uri([string]$Path){return ([Uri]([IO.Path]::GetFullPath($Path))).GetComponents([UriComponents]::AbsoluteUri,[UriFormat]::Unescaped)}
function Assert-RelocationPaths([string]$Old,[string]$New,[string]$Tlb){
 foreach($p in @($Old,$New,$Tlb)){Assert-True ([IO.Path]::IsPathRooted($p)) 'Absolute relocation paths required.'}
 $oldFull=[IO.Path]::GetFullPath($Old);$newFull=[IO.Path]::GetFullPath($New);$tlbFull=[IO.Path]::GetFullPath($Tlb)
 Assert-True ($oldFull -ine $newFull -and [IO.Path]::GetDirectoryName($oldFull) -ieq [IO.Path]::GetDirectoryName($newFull) -and [IO.Path]::GetDirectoryName($oldFull) -ieq [IO.Path]::GetDirectoryName($tlbFull)) 'Distinct versioned DLL in the existing binary directory required.'
 Assert-True ([IO.Path]::GetFileName($oldFull) -cmatch '^CadStudio\.SolidWorks\.CamIslandQualification(?:\.r[0-9]{2})?\.dll$' -and [IO.Path]::GetFileName($newFull) -cmatch '^CadStudio\.SolidWorks\.CamIslandQualification\.r[0-9]{2}\.dll$' -and [IO.Path]::GetFileName($tlbFull) -ceq 'CadStudio.SolidWorks.CamIslandQualification.tlb') 'Only fixed companion filenames and versioned DLL suffix rNN are admitted.'
}
function Assert-RelocationIdentity([string]$Old,[string]$New){$fixed="$prog, Version=1.0.0.0, Culture=neutral, PublicKeyToken=6f0670dca5152b74";Assert-True ($Old -ceq $fixed -and $New -ceq $fixed) 'Identical fixed strong-name/token/version required.'}
function Snapshot-Node($Snapshot,[string]$Root,[string]$Relative=''){
 $rows=@($Snapshot|Where-Object {$_.path -ceq $Root});Assert-True ($rows.Count -eq 1 -and $null -ne $rows[0].tree) 'Exact non-null registration root required.';$node=$rows[0].tree
 if($Relative){foreach($part in $Relative.Split('\')){$children=@($node.children|Where-Object {$_.name -ceq $part});Assert-True ($children.Count -eq 1 -and $null -ne $children[0].tree) 'Exact registered child required.';$node=$children[0].tree}}
 return $node
}
function Snapshot-String($Node,[string]$Name=''){$values=@($Node.values|Where-Object {$_.name -ceq $Name});Assert-True ($values.Count -eq 1 -and $values[0].kind -ceq 'String' -and $values[0].value -is [string]) 'Exact existing string value required.';return $values[0].value}
function Assert-CodeBaseSnapshot($Snapshot,[string]$CodeBase,[string]$Identity,[string]$Tlb){
 Assert-True (@($Snapshot).Count -eq 4 -and (Json @($Snapshot|ForEach-Object {$_.path})) -ceq (Json $roots)) 'Exact four owned roots required.'
 Assert-True ((Snapshot-String (Snapshot-Node $Snapshot $roots[0])) -ceq $class -and (Snapshot-String (Snapshot-Node $Snapshot $roots[0] 'ProgId')) -ceq $prog) 'Fixed class/ProgID required.'
 Assert-True ((Snapshot-String (Snapshot-Node $Snapshot $roots[1])) -ceq $class -and (Snapshot-String (Snapshot-Node $Snapshot $roots[1] 'CLSID')) -ceq $clsid) 'Fixed ProgID mapping required.'
 foreach($relative in @('InprocServer32','InprocServer32\1.0.0.0')){
  $node=Snapshot-Node $Snapshot $roots[0] $relative
  Assert-True ((Snapshot-String $node 'CodeBase') -ceq $CodeBase -and (Snapshot-String $node 'Assembly') -ceq $Identity -and (Snapshot-String $node 'Class') -ceq $class -and (Snapshot-String $node 'RuntimeVersion') -ceq 'v4.0.30319') 'Existing fixed CLR registration differs.'
 }
 $node=Snapshot-Node $Snapshot $roots[0] 'InprocServer32'
 Assert-True ((Snapshot-String $node) -ceq 'mscoree.dll' -and (Snapshot-String $node 'ThreadingModel') -ceq 'Both') 'CLR server/threading differs.'
 Assert-True ((Snapshot-String (Snapshot-Node $Snapshot $roots[2] '1.0\0\win64')) -ieq [IO.Path]::GetFullPath($Tlb)) 'Existing TLB path differs.'
 Assert-True ((Snapshot-String (Snapshot-Node $Snapshot $roots[3] 'TypeLib')) -ceq $libid -and (Snapshot-String (Snapshot-Node $Snapshot $roots[3] 'TypeLib') 'Version') -ceq '1.0' -and (Snapshot-String (Snapshot-Node $Snapshot $roots[3] 'ProxyStubClsid32')) -ceq '{00020424-0000-0000-C000-000000000046}') 'Existing interface marshaler/TLB differs.'
}
function Assert-CodeBaseProbe($Probe,$Current,[string]$OldCodeBase,[string]$Identity,[string]$Tlb){
 Assert-True ($Probe.scope -ceq 'CAM_ISLAND_COMPANION_REGISTRATION_V1' -and $Probe.action -ceq 'Probe' -and $Probe.status -ceq 'observed' -and $Probe.registry_scope -ceq 'CurrentUser' -and $Probe.registry_view -eq 64 -and $Probe.mutation_attempted -is [bool] -and $Probe.mutation_attempted -eq $false -and $Probe.solidworks_activated -is [bool] -and $Probe.solidworks_activated -eq $false -and $Probe.autostart_written -is [bool] -and $Probe.autostart_written -eq $false) 'Exact read-only own registration probe required.'
 Assert-True ((Json $Probe.owned_keys) -ceq (Json $roots) -and (Json $Probe.before) -ceq (Json $Current)) 'Current registration differs from pinned probe.'
 Assert-CodeBaseSnapshot $Current $OldCodeBase $Identity $Tlb
}
function With-CodeBases($Snapshot,[string[]]$Values){
 Assert-True ($Values.Count -eq 2) 'Exactly two CodeBase values required.';$copy=(Json $Snapshot)|ConvertFrom-Json
 $index=0;foreach($relative in @('InprocServer32','InprocServer32\1.0.0.0')){$node=Snapshot-Node $copy $roots[0] $relative;$value=@($node.values|Where-Object {$_.name -ceq 'CodeBase'});Assert-True ($value.Count -eq 1 -and $value[0].kind -ceq 'String') 'Existing CodeBase string required.';$value[0].value=$Values[$index];$index++}
 # Windows PowerShell 5.1 annotates the ConvertFrom-Json array; re-enumerate into a plain array before serialization.
 return ,@($copy | ForEach-Object {$_})
}
function Assert-CodeBaseRollback($Previous,$Current,$Probe,[string]$ProbeSha,[string]$OldSha,[string]$NewSha,[string]$TlbSha,[string]$OldCodeBase,[string]$NewCodeBase){
 Assert-True ($Previous.scope -ceq $relocationScope -and $Previous.action -ceq 'RelocateBuilt' -and $Previous.status -in @('relocated','failed') -and $Previous.mutation_attempted -is [bool] -and $Previous.mutation_attempted -eq $true -and $Previous.registry_scope -ceq 'CurrentUser' -and $Previous.registry_view -eq 64 -and $Previous.solidworks_activated -is [bool] -and $Previous.solidworks_activated -eq $false -and $Previous.autostart_written -is [bool] -and $Previous.autostart_written -eq $false) 'Only a completed own relocation attempt may be rolled back.'
 Assert-True ((Json $Previous.owned_keys) -ceq (Json $roots) -and (Json $Previous.before) -ceq (Json $Probe.before) -and (Json $Previous.after) -ceq (Json $Current)) 'Relocation/current registry lineage differs.'
 Assert-True ($Previous.probe_receipt.sha256 -ceq $ProbeSha -and $Previous.previous_assembly.sha256 -ceq $OldSha -and $Previous.assembly.sha256 -ceq $NewSha -and $Previous.typelib.sha256 -ceq $TlbSha -and $Previous.previous_assembly.codebase -ceq $OldCodeBase -and $Previous.assembly.codebase -ceq $NewCodeBase) 'Relocation artifact pins differ.'
 $old=With-CodeBases $Probe.before @($OldCodeBase,$OldCodeBase);$one=With-CodeBases $Probe.before @($NewCodeBase,$OldCodeBase);$two=With-CodeBases $Probe.before @($NewCodeBase,$NewCodeBase)
 Assert-True ((Json $Current) -cin @((Json $old),(Json $one),(Json $two))) 'Current state is not an exact bounded relocation prefix.'
 if($Previous.status -ceq 'relocated'){Assert-True ((Json $Current) -ceq (Json $two)) 'Successful relocation must have both exact new CodeBases.'}
}
function Set-ExistingCodeBase([string]$Path,[string]$Value){
 Assert-True ($Path -cin $codeBaseKeys) 'Only the two fixed CodeBase keys are writable.'
 $key=$registry.OpenSubKey($Path,$true);Assert-True ($null -ne $key) 'Existing CodeBase key required; never create keys.'
 try{Assert-True ($key.GetValueKind('CodeBase') -eq [Microsoft.Win32.RegistryValueKind]::String) 'Existing CodeBase string required.';$key.SetValue('CodeBase',$Value,[Microsoft.Win32.RegistryValueKind]::String)}finally{$key.Dispose()}
}

$receipt=[ordered]@{scope='CAM_ISLAND_COMPANION_REGISTRATION_V1';action=$Action;status='not_started';utc=[DateTime]::UtcNow.ToString('o');registry_scope='CurrentUser';registry_view=64;process_packaged=$false;mutation_attempted=$false;solidworks_activated=$false;autostart_written=$false;owned_keys=$roots}
if($isDiscoveryAction){$receipt.scope=$discoveryScope;$receipt.registry_scope='LocalMachine';$receipt.owned_machine_key=$discoveryRoot}
if($isRelocationAction){$receipt.scope=$relocationScope}
try{
 Assert-True ([IO.Path]::IsPathRooted($ReceiptPath) -and -not [IO.File]::Exists($ReceiptPath)) 'Fresh absolute output required.'
 $before=Snapshot-All;$receipt.before=$before
 if($Action -eq 'Probe'){$receipt.status='observed';Write-New $ReceiptPath $receipt;return}
 if($Action -eq 'Rollback'){
  Assert-True ($RegistrationReceiptSha256 -match '^[0-9a-f]{64}$' -and (Hash $RegistrationReceiptPath) -ceq $RegistrationReceiptSha256) 'Pinned registration receipt required.'
  $registered=Get-Content -Raw -LiteralPath $RegistrationReceiptPath | ConvertFrom-Json
  Assert-True ($registered.scope -eq $receipt.scope -and $registered.action -eq 'RegisterBuilt' -and $registered.status -in @('registered','failed') -and $registered.mutation_attempted -eq $true) 'Completed own registration attempt receipt required.'
  Assert-True ((Json $registered.owned_keys) -ceq (Json $roots)) 'Fixed owned registry roots required.'
  Assert-True (@($registered.before|Where-Object {$null -ne $_.tree}).Count -eq 0) 'Only initially absent own keys may be rolled back.'
  Assert-True ((Json $registered.after) -ceq (Json $before)) 'Registration changed since receipt; refusing rollback.'
  Write-New ($ReceiptPath+'.intent.json') $receipt
  $receipt.mutation_attempted=$true
  foreach($path in $roots){$registry.DeleteSubKeyTree($path,$false)}
  $receipt.after=Snapshot-All
  Assert-True (@($receipt.after|Where-Object {$null -ne $_.tree}).Count -eq 0) 'Rollback readback differs.'
  $receipt.status='rolled_back';Write-New $ReceiptPath $receipt;return
 }
 foreach($pin in @(@($AssemblyPath,$ExpectedAssemblySha256),@($TypeLibraryPath,$ExpectedTypeLibrarySha256))){Assert-True ([IO.Path]::IsPathRooted($pin[0]) -and $pin[1] -cmatch '^[0-9a-f]{64}$' -and (Hash $pin[0]) -ceq $pin[1]) 'Exact existing assembly/type-library SHA256 required.'}
 $resolved=[IO.Path]::GetFullPath($AssemblyPath);$tlb=[IO.Path]::GetFullPath($TypeLibraryPath)
 $identity=[Reflection.AssemblyName]::GetAssemblyName($resolved)
 Assert-True ($identity.Name -eq $prog -and $identity.Version.ToString() -eq '1.0.0.0' -and $identity.GetPublicKeyToken().Length -eq 8) 'Fixed strong-named companion required.'
 $types=@([CadStudio.IslandDeployment.Native]::Validate($tlb)|Sort-Object)
 $expectedTypes=@("TKIND_DISPATCH:$iid","TKIND_COCLASS:$clsid",'TKIND_COCLASS:{43BEBF37-6F28-4F0D-8F92-78D11261D48B}')|Sort-Object
 Assert-True ((Json $types) -ceq (Json @($expectedTypes))) 'Unexpected exported TLB identities.'
 $codebase=$identity.CodeBase
 if(-not $codebase){$codebase=([Uri]$resolved).GetComponents([UriComponents]::AbsoluteUri,[UriFormat]::Unescaped)}
 $receipt.assembly=[ordered]@{path=$resolved;sha256=$ExpectedAssemblySha256;identity=$identity.FullName;codebase=$codebase}
 $receipt.typelib=[ordered]@{path=$tlb;sha256=$ExpectedTypeLibrarySha256;types=$types}
 if($Action -eq 'Validate'){$receipt.status='validated';Write-New $ReceiptPath $receipt;return}
 if($isRelocationAction){
  Assert-True ([IO.Path]::IsPathRooted($PreviousAssemblyPath) -and $ExpectedPreviousAssemblySha256 -cmatch '^[0-9a-f]{64}$' -and (Hash $PreviousAssemblyPath) -ceq $ExpectedPreviousAssemblySha256 -and $ExpectedPreviousAssemblySha256 -cne $ExpectedAssemblySha256) 'Distinct pinned old/new DLL bytes required.'
  Assert-RelocationPaths $PreviousAssemblyPath $resolved $tlb
  $oldPath=[IO.Path]::GetFullPath($PreviousAssemblyPath);$oldIdentity=[Reflection.AssemblyName]::GetAssemblyName($oldPath)
  $fixedIdentity="$prog, Version=1.0.0.0, Culture=neutral, PublicKeyToken=6f0670dca5152b74"
  Assert-RelocationIdentity $oldIdentity.FullName $identity.FullName
  $oldCodeBase=CodeBase-Uri $oldPath;$newCodeBase=CodeBase-Uri $resolved
  Assert-True ([IO.Path]::IsPathRooted($ProbeReceiptPath) -and $ProbeReceiptSha256 -cmatch '^[0-9a-f]{64}$' -and (Hash $ProbeReceiptPath) -ceq $ProbeReceiptSha256) 'Pinned absolute current-registration probe required.'
  $probe=Get-Content -Raw -LiteralPath $ProbeReceiptPath|ConvertFrom-Json
  Assert-CodeBaseProbe $probe $probe.before $oldCodeBase $fixedIdentity $tlb
  $receipt.previous_assembly=[ordered]@{path=$oldPath;sha256=$ExpectedPreviousAssemblySha256;identity=$oldIdentity.FullName;codebase=$oldCodeBase}
  $receipt.assembly.codebase=$newCodeBase;$receipt.probe_receipt=[ordered]@{path=[IO.Path]::GetFullPath($ProbeReceiptPath);sha256=$ProbeReceiptSha256}
  $destination=$newCodeBase
  if($Action -eq 'RelocateBuilt'){Assert-True ((Json $before) -ceq (Json $probe.before)) 'Registration drift from pinned probe.'}else{
   Assert-True ([IO.Path]::IsPathRooted($RelocationReceiptPath) -and $RelocationReceiptSha256 -cmatch '^[0-9a-f]{64}$' -and (Hash $RelocationReceiptPath) -ceq $RelocationReceiptSha256) 'Pinned own relocation receipt required.'
   $previous=Get-Content -Raw -LiteralPath $RelocationReceiptPath|ConvertFrom-Json
   Assert-CodeBaseRollback $previous $before $probe $ProbeReceiptSha256 $ExpectedPreviousAssemblySha256 $ExpectedAssemblySha256 $ExpectedTypeLibrarySha256 $oldCodeBase $newCodeBase
   $receipt.relocation_receipt=[ordered]@{path=[IO.Path]::GetFullPath($RelocationReceiptPath);sha256=$RelocationReceiptSha256};$destination=$oldCodeBase
  }
  $receipt.codebase_keys=$codeBaseKeys;$receipt.expected_after=With-CodeBases $before @($destination,$destination);$receipt.stage='validated_before_two_codebase_values'
  Write-New ($ReceiptPath+'.intent.json') $receipt
  $expected=$before
  for($index=0;$index -lt 2;$index++){
   Assert-True ((Hash $oldPath) -ceq $ExpectedPreviousAssemblySha256 -and (Hash $resolved) -ceq $ExpectedAssemblySha256 -and (Hash $tlb) -ceq $ExpectedTypeLibrarySha256 -and (Hash $ProbeReceiptPath) -ceq $ProbeReceiptSha256) 'Inputs changed before CodeBase write.'
   if($Action -eq 'RollbackCodeBase'){Assert-True ((Hash $RelocationReceiptPath) -ceq $RelocationReceiptSha256) 'Relocation receipt changed before rollback.'}
   Assert-True ((Json (Snapshot-All)) -ceq (Json $expected)) 'Unrelated registry drift before CodeBase write.'
   $receipt.pending_value_index=$index;$receipt.stage='write_codebase_value';Write-New ($ReceiptPath+'.value-'+$index+'.intent.json') $receipt
   $receipt.mutation_attempted=$true;Set-ExistingCodeBase $codeBaseKeys[$index] $destination
   $values=@((Snapshot-String (Snapshot-Node $expected $roots[0] 'InprocServer32') 'CodeBase'),(Snapshot-String (Snapshot-Node $expected $roots[0] 'InprocServer32\1.0.0.0') 'CodeBase'));$values[$index]=$destination;$expected=With-CodeBases $expected $values
   $receipt.after=Snapshot-All;Assert-True ((Json $receipt.after) -ceq (Json $expected)) 'Readback differs beyond the single allowed CodeBase value.'
   $receipt.completed_value_count=$index+1
  }
  Assert-True ((Json $receipt.after) -ceq (Json $receipt.expected_after)) 'Final two-value CodeBase readback differs.'
  Assert-CodeBaseSnapshot $receipt.after $destination $fixedIdentity $tlb
  Assert-True ((Hash $oldPath) -ceq $ExpectedPreviousAssemblySha256 -and (Hash $resolved) -ceq $ExpectedAssemblySha256 -and (Hash $tlb) -ceq $ExpectedTypeLibrarySha256 -and (Hash $ProbeReceiptPath) -ceq $ProbeReceiptSha256) 'Pinned files changed during relocation.'
  $receipt.pending_value_index=$null;$receipt.status=if($Action -eq 'RelocateBuilt'){'relocated'}else{'codebase_rolled_back'};$receipt.stage='finished';Write-New $ReceiptPath $receipt;return
 }
 if($isDiscoveryAction){
  Assert-True ([IO.Path]::IsPathRooted($RegistrationReceiptPath) -and $RegistrationReceiptSha256 -cmatch '^[0-9a-f]{64}$' -and (Hash $RegistrationReceiptPath) -ceq $RegistrationReceiptSha256) 'Pinned absolute COM registration receipt required.'
  $registered=Get-Content -Raw -LiteralPath $RegistrationReceiptPath | ConvertFrom-Json
  Assert-DiscoveryComReceipt $registered $before $resolved $tlb $ExpectedAssemblySha256 $ExpectedTypeLibrarySha256
  $receipt.registration_receipt=[ordered]@{path=[IO.Path]::GetFullPath($RegistrationReceiptPath);sha256=$RegistrationReceiptSha256}
  Assert-DiscoveryAdministrator
  $machineRegistry=[Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine,[Microsoft.Win32.RegistryView]::Registry64)
  $receipt.discovery_before=Snapshot-Key $discoveryRoot $machineRegistry
  if($Action -eq 'AddDiscovery'){
   Assert-True ($null -eq $receipt.discovery_before) 'Existing discovery key requires review; no overwrite.'
  }else{
   Assert-True ([IO.Path]::IsPathRooted($DiscoveryReceiptPath) -and $DiscoveryReceiptSha256 -cmatch '^[0-9a-f]{64}$' -and (Hash $DiscoveryReceiptPath) -ceq $DiscoveryReceiptSha256) 'Pinned absolute discovery-add receipt required.'
   $added=Get-Content -Raw -LiteralPath $DiscoveryReceiptPath | ConvertFrom-Json
   Assert-DiscoveryRemovalReceipt $added $receipt.discovery_before $RegistrationReceiptSha256 $ExpectedAssemblySha256 $ExpectedTypeLibrarySha256
   $receipt.discovery_add_receipt=[ordered]@{path=[IO.Path]::GetFullPath($DiscoveryReceiptPath);sha256=$DiscoveryReceiptSha256}
  }
  # All file/COM/ownership/admin gates have passed before durable intent and HKLM entry.
  $receipt.stage='validated_before_fixed_machine_write'
  Write-New ($ReceiptPath+'.intent.json') $receipt
  Assert-True ((Hash $resolved) -ceq $ExpectedAssemblySha256 -and (Hash $tlb) -ceq $ExpectedTypeLibrarySha256 -and (Hash $RegistrationReceiptPath) -ceq $RegistrationReceiptSha256) 'Inputs changed before discovery write.'
  Assert-True ((Json (Snapshot-All)) -ceq (Json $before) -and (Json (Snapshot-Key $discoveryRoot $machineRegistry)) -ceq (Json $receipt.discovery_before)) 'Registry changed before discovery write.'
  if($Action -eq 'RemoveDiscovery'){Assert-True ((Hash $DiscoveryReceiptPath) -ceq $DiscoveryReceiptSha256) 'Discovery receipt changed before removal.'}
  $receipt.mutation_attempted=$true
  if($Action -eq 'AddDiscovery'){
   $key=$machineRegistry.CreateSubKey($discoveryRoot)
   try{$key.SetValue('',0,[Microsoft.Win32.RegistryValueKind]::DWord);$key.SetValue('Title',$discoveryTitle,[Microsoft.Win32.RegistryValueKind]::String);$key.SetValue('Description',$discoveryDescription,[Microsoft.Win32.RegistryValueKind]::String)}finally{$key.Dispose()}
  }else{$machineRegistry.DeleteSubKeyTree($discoveryRoot,$false)}
  $receipt.discovery_after=Snapshot-Key $discoveryRoot $machineRegistry
  $receipt.after=Snapshot-All
  Assert-True ((Json $receipt.after) -ceq (Json $before)) 'COM registration changed during discovery operation.'
  if($Action -eq 'AddDiscovery'){Assert-True ((Json $receipt.discovery_after) -ceq (Json (Discovery-ExpectedTree))) 'Discovery exact readback differs.';$receipt.status='discovery_added'}else{Assert-True ($null -eq $receipt.discovery_after) 'Discovery removal readback differs.';$receipt.status='discovery_removed'}
  Assert-True ((Hash $resolved) -ceq $ExpectedAssemblySha256 -and (Hash $tlb) -ceq $ExpectedTypeLibrarySha256 -and (Hash $RegistrationReceiptPath) -ceq $RegistrationReceiptSha256) 'Pinned inputs changed during discovery operation.'
  $receipt.stage='finished';Write-New $ReceiptPath $receipt;return
 }
 Assert-True (@($before|Where-Object {$null -ne $_.tree}).Count -eq 0) 'Existing companion registration requires review; no overwrite.'
 Write-New ($ReceiptPath+'.intent.json') $receipt
 $receipt.mutation_attempted=$true
 [CadStudio.IslandDeployment.Native]::Register($tlb)
 $classRoot="Software\Classes\CLSID\$clsid";$inproc="$classRoot\InprocServer32"
 Set-Value "Software\Classes\$prog" '' $class
 Set-Value "Software\Classes\$prog\CLSID" '' $clsid
 Set-Value $classRoot '' $class
 Set-Value $inproc '' 'mscoree.dll'
 Set-Value $inproc 'ThreadingModel' 'Both'
 foreach($target in @($inproc,"$inproc\1.0.0.0")){
  Set-Value $target 'Class' $class;Set-Value $target 'Assembly' $identity.FullName
  Set-Value $target 'RuntimeVersion' 'v4.0.30319';Set-Value $target 'CodeBase' $codebase
 }
 Set-Value "$classRoot\ProgId" '' $prog
 $category=$registry.CreateSubKey("$classRoot\Implemented Categories\{62C8FE65-4EBB-45E7-B440-6E39B2CDBF29}");$category.Dispose()
 Assert-True ((Read-Value "Software\Classes\TypeLib\$libid\1.0\0\win64") -eq $tlb) 'Type library path readback differs.'
 Assert-True ((Read-Value "Software\Classes\Interface\$iid\TypeLib") -eq $libid -and (Read-Value "Software\Classes\Interface\$iid\TypeLib" 'Version') -eq '1.0') 'Interface library readback differs.'
 Assert-True ((Read-Value "Software\Classes\Interface\$iid\ProxyStubClsid32") -eq '{00020424-0000-0000-C000-000000000046}') 'Interface marshaler readback differs.'
 Assert-True ((Read-Value $inproc 'CodeBase') -ceq $codebase -and (Read-Value $inproc 'Assembly') -ceq $identity.FullName) 'Class readback differs.'
 Assert-True ((Hash $resolved) -ceq $ExpectedAssemblySha256 -and (Hash $tlb) -ceq $ExpectedTypeLibrarySha256) 'Installed artifacts changed during registration.'
 $receipt.after=Snapshot-All;$receipt.status='registered';Write-New $ReceiptPath $receipt
} catch {
 $receipt.status='failed';$receipt.error=$_.Exception.Message
 try{$receipt.after=Snapshot-All;if($null -ne $machineRegistry){$receipt.discovery_after=Snapshot-Key $discoveryRoot $machineRegistry};if(-not [IO.File]::Exists($ReceiptPath)){Write-New $ReceiptPath $receipt}}catch{}
 throw
} finally {if($null -ne $machineRegistry){$machineRegistry.Dispose()};$registry.Dispose()}
