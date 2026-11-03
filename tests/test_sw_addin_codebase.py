"""Offline CodeBase formatting checks; no registration or COM activation."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'sw_addin_host.ps1'


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell path semantics required')
@pytest.mark.parametrize('executable', ['powershell.exe', 'pwsh.exe'])
def test_framework_compatible_codebase_paths(executable):
    shell = shutil.which(executable)
    if shell is None:
        pytest.skip(executable + ' unavailable')
    path = str(SCRIPT).replace("'", "''")
    command = r"""
$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('__SCRIPT__',[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'PowerShell parser errors'}
$function=@($ast.FindAll({param($n)$n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-AddinCodeBase'},$true))
if($function.Count -ne 1){throw 'One CodeBase formatter required'}
Invoke-Expression $function[0].Extent.Text
$cases=@(
 @('C:\Program Files\Host\host.dll','file:///C:/Program Files/Host/host.dll'),
 @('\\server\share\Host folder\host.dll','file://server/share/Host folder/host.dll'),
 @('C:\Host\literal %20 # symbol.dll','file:///C:/Host/literal %20 # symbol.dll')
)
foreach($case in $cases){
 if((Get-AddinCodeBase -ResolvedPath $case[0]) -cne $case[1]){throw 'File CodeBase format differs'}
}
$rejected=0
foreach($invalid in @('relative.dll','C:relative.dll','https://example.test/host.dll')){
 try{$null=Get-AddinCodeBase -ResolvedPath $invalid}catch{$rejected++}
}
if($rejected -ne 3){throw 'Non-file absolute input accepted'}
$location=[object].Assembly.Location
$identity=[Reflection.AssemblyName]::GetAssemblyName($location)
$expected=if($identity.CodeBase){$identity.CodeBase}else{([Uri]$location).GetComponents([UriComponents]::AbsoluteUri,[UriFormat]::Unescaped)}
if((Get-AddinCodeBase -ResolvedPath $location -Identity $identity) -cne $expected){throw 'Assembly metadata CodeBase differs'}
[ordered]@{path_cases=3;invalid_rejected=3;actual_metadata_match=$true;registration_calls=0;COM_calls=0}|ConvertTo-Json -Compress
""".replace('__SCRIPT__', path)
    encoded = base64.b64encode(command.encode('utf-16-le')).decode('ascii')
    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
    evidence = json.loads(result.stdout.decode('utf-8-sig'))
    assert evidence == dict(path_cases=3, invalid_rejected=3, actual_metadata_match=True,
        registration_calls=0, COM_calls=0)


def test_registration_uses_metadata_codebase_formatter():
    text=SCRIPT.read_text(encoding='utf-8-sig')
    body=text.split('function Register-CurrentUser {')[1].split('function Unregister-CurrentUser {')[0]
    assert 'Get-AddinCodeBase -ResolvedPath $resolvedAssembly -Identity $assemblyIdentity' in body
    assert '$codeBase = ([Uri]$resolvedAssembly).AbsoluteUri' not in body
