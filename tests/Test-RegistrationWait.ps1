param([string]$HelperPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts\sw_addin_host.ps1'))
$ErrorActionPreference = 'Stop'
$tokens = $null; $parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($HelperPath,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) { throw 'Staged helper does not parse.' }
$functions = @($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-ElevatedSelf'},$true))
if ($functions.Count -ne 1) { throw 'Exact single elevation function required.' }
# Define only this function. Never dot-source the script's build/registry actions.
. ([scriptblock]::Create($functions[0].Extent.Text))
function Resolve-SolidWorksApiDir { 'C:\fixture\api\redist' }
$DotNetPath='C:\fixture\dotnet.exe'; $Configuration='Release'
$CamWorksTlbPath='C:\fixture\camworks.tlb'; $NetFxToolsDir='C:\fixture\netfx'
$script:checks=0
function Assert-Test([bool]$Condition,[string]$Message) {
 if (-not $Condition) { throw $Message }; $script:checks++
}
function Start-Process {
 param([string]$FilePath,[string]$WindowStyle,[string]$Verb,[string[]]$ArgumentList,[switch]$PassThru,[switch]$Wait)
 $script:startCalls++
 Assert-Test (-not $Wait) 'Must not wait for descendants through Start-Process -Wait.'
 Assert-Test ($PassThru -and $FilePath -eq 'powershell.exe') 'Must retain exact launched child object.'
 Assert-Test ($Verb -eq 'RunAs' -and $WindowStyle -eq 'Hidden') 'UAC and hidden helper must remain.'
 Assert-Test ($ArgumentList.Count -eq 5 -and $ArgumentList[3] -eq '-EncodedCommand') 'Encoded command launch contract changed.'
 $script:decoded=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($ArgumentList[4]))
 Assert-Test ($script:decoded -match '-RegistrationScope Machine' -and $script:decoded -match '-ElevatedChild') 'Elevated scope guard missing.'
 if ($script:scenario -eq 'cancel') { throw 'MOCK_UAC_CANCELLED' }
 $child=[pscustomobject]@{Id=123456}
 $child | Add-Member ScriptMethod WaitForExit {
  $script:waitCalls++
  if ($script:scenario -eq 'wait_error') { throw 'MOCK_WAIT_DENIED' }
 }
 $child | Add-Member ScriptProperty ExitCode {
  if ($script:waitCalls -ne 1) { throw 'ExitCode observed before exact child completion.' }
  $script:exitReads++
  if ($script:scenario -eq 'child_failure') { return 9 }; return 0
 }
 $child | Add-Member ScriptMethod Dispose { $script:disposeCalls++ }
 return $child
}
$caseResults=@()
foreach ($case in @(
 @{name='successful_register';action='Register';scenario='success';error=$null},
 @{name='successful_unregister';action='Unregister';scenario='success';error=$null},
 @{name='child_failure';action='Register';scenario='child_failure';error='Exit code: 9'},
 @{name='uac_cancel';action='Register';scenario='cancel';error='MOCK_UAC_CANCELLED'},
 @{name='wait_access_failure';action='Register';scenario='wait_error';error='MOCK_WAIT_DENIED'}
)) {
 $script:startCalls=0;$script:waitCalls=0;$script:disposeCalls=0;$script:exitReads=0;$script:decoded='';$script:scenario=$case.scenario
 $errorText=$null
 try { Invoke-ElevatedSelf $case.action } catch { $errorText=$_.Exception.Message }
 Assert-Test ($script:startCalls -eq 1) 'Launch must occur exactly once.'
 Assert-Test ($script:decoded -match ('-Action '+$case.action)) 'Requested action changed.'
 if ($null -eq $case.error) { Assert-Test ($null -eq $errorText) ('Unexpected failure: '+$errorText) }
 else { Assert-Test ($null -ne $errorText -and $errorText.Contains($case.error)) ('Expected error not preserved: '+$errorText) }
 $hasChild=$case.scenario -ne 'cancel'
 Assert-Test ($script:waitCalls -eq [int]$hasChild) 'Wait must target only returned child exactly once.'
 Assert-Test ($script:disposeCalls -eq [int]$hasChild) 'Returned process object must be disposed on success/failure.'
 $shouldReadExit=$hasChild -and $case.scenario -ne 'wait_error'
 Assert-Test ($script:exitReads -eq [int]$shouldReadExit) 'ExitCode ordering changed.'
 $caseResults += @{case=$case.name;passed=$true}
}
[ordered]@{status='passed';checks=$script:checks;cases=$caseResults;helper_sha256=(Get-FileHash -LiteralPath $HelperPath -Algorithm SHA256).Hash.ToLower();real_child_launches=0;CAD_calls=0;registry_writes=0;runtime_changes=$false;parse_errors=0} | ConvertTo-Json -Depth 5

