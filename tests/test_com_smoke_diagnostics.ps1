param(
 [string]$ScriptPath='',
 [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference='Stop'
if(-not $ScriptPath){$ScriptPath=Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts\sw_addin_host.ps1'}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($ScriptPath,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$definition=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-ComSmokeExceptionEvidence'},$true)
Invoke-Expression $definition.Extent.Text
$block=$null
foreach($node in $ast.FindAll({param($node) $node -is [Management.Automation.Language.SwitchStatementAst]},$true)){
 foreach($clause in $node.Clauses){if($clause.Item1.Value -eq 'ComSmoke'){$block=$clause.Item2.Extent.Text}}
}
if(-not $block){throw 'ComSmoke branch not found'}
$smokeBlock=[ScriptBlock]::Create($block.Substring(1,$block.Length-2))
$root=[IO.Path]::GetFullPath($OutputDirectory)
if([IO.Directory]::Exists($root)){throw 'Fresh output directory required'}
[IO.Directory]::CreateDirectory($root)|Out-Null
$ProgId='Synthetic.Host';$AddinGuid='{00000000-0000-0000-0000-000000000000}';$AssemblyPath='synthetic.dll'
function Test-Path {param([string]$Path) return $true}
$script:Calls=0;$script:Mode='pass';$script:Checks=0
function Check([bool]$Value,[string]$Name){if(-not $Value){throw ('FAILED: '+$Name)};$script:Checks++}
function New-Object {param([string]$ComObject) $script:Calls++;if($script:Mode -eq 'fail'){throw [IO.FileNotFoundException]::new('outer missing','outer.dll',[IO.FileNotFoundException]::new('inner missing','inner.dll'))};return [pscustomobject]@{synthetic=$true}}
$ComSmokeDiagnosticPath=[IO.Path]::Combine($root,'pass.json');& $smokeBlock
$d=Get-Content -LiteralPath $ComSmokeDiagnosticPath -Raw|ConvertFrom-Json
Check ($d.status -eq 'passed' -and $script:Calls -eq 1) 'one synthetic success'
$script:Mode='fail';$ComSmokeDiagnosticPath=[IO.Path]::Combine($root,'fail.json');$caught=$null
try{& $smokeBlock}catch{$caught=$_}
Check ($null -ne $caught -and $script:Calls -eq 2) 'failed activation rethrown once'
$d=Get-Content -LiteralPath $ComSmokeDiagnosticPath -Raw|ConvertFrom-Json
Check ($d.status -eq 'error' -and $d.activation_attempted) 'failure receipt'
$names=@($d.exception_chain.entries|ForEach-Object {$_.file_name})
Check ($names -contains 'outer.dll' -and $names -contains 'inner.dll') 'FileName chain retained'
Check (@($d.exception_chain.entries|Where-Object {$_.PSObject.Properties['fusion_log']}).Count -eq $d.exception_chain.entries.Count) 'FusionLog field present'
$bytes=[IO.File]::ReadAllBytes($ComSmokeDiagnosticPath);try{& $smokeBlock}catch{}
Check ($script:Calls -eq 2 -and [Convert]::ToBase64String($bytes) -eq [Convert]::ToBase64String([IO.File]::ReadAllBytes($ComSmokeDiagnosticPath))) 'existing output rejected before activation'
$ComSmokeDiagnosticPath='relative.json';try{& $smokeBlock}catch{}
Check ($script:Calls -eq 2) 'relative output rejected before activation'
foreach($invalid in @('C:relative.json','\root-relative.json')) {
 $ComSmokeDiagnosticPath=$invalid;$caught=$null
 try{& $smokeBlock}catch{$caught=$_}
 Check ($script:Calls -eq 2 -and $caught.Exception.Message -eq 'ComSmokeDiagnosticPath must be absolute.') ('incomplete root rejected: '+$invalid)
}
$chain=[Exception]::new('leaf');for($i=0;$i -lt 40;$i++){$chain=[Exception]::new(('outer '+$i),$chain)}
$e=Get-ComSmokeExceptionEvidence $chain
Check ($e.entries.Count -eq 32 -and $e.truncated) 'bounded inner chain'
$loaders=[Exception[]]@([IO.FileNotFoundException]::new('loader','dependency.dll'))
$e=Get-ComSmokeExceptionEvidence ([Reflection.ReflectionTypeLoadException]::new([Type[]]@(),$loaders))
Check (@($e.entries|Where-Object {$_.relation -eq 'loader' -and $_.file_name -eq 'dependency.dll'}).Count -eq 1) 'LoaderExceptions retained'
$many=[Exception[]](1..40|ForEach-Object {[IO.FileNotFoundException]::new('loader','many.dll')})
$e=Get-ComSmokeExceptionEvidence ([Reflection.ReflectionTypeLoadException]::new([Type[]]@(),$many))
Check ($e.entries.Count -eq 32 -and $e.truncated) 'bounded loader list'
# Disposing the held stream simulates a write failure after activation without replacing the activation error.
function New-Object {param([string]$ComObject) $script:Calls++;$diagnosticStream.Dispose();throw [IO.FileNotFoundException]::new('original activation failure','original.dll')}
$ComSmokeDiagnosticPath=[IO.Path]::Combine($root,'write-fails.json');$caught=$null
try{& $smokeBlock}catch{$caught=$_}
Check ($caught.Exception.Message -eq 'original activation failure') 'diagnostic write failure preserves original exception'
@{status='PASS';checks=$script:Checks;synthetic_activation_calls=$script:Calls;com_activated=$false;cad_called=$false;registry_written=$false}|ConvertTo-Json
