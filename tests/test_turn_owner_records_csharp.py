"""Compile/run pure host-loop fixtures; never activate COM or a CAD process."""
import json,os,shutil,subprocess
from pathlib import Path
import pytest

RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',Path(__file__).resolve().parents[1]))
ROOT=Path(__file__).resolve().parents[1]

def test_compiled_owner_loop(tmp_path):
    csc=Path(os.environ.get('SWMCP_CSC',str(Path(os.environ.get('WINDIR',''))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe')))
    refs=Path(os.environ.get('SWMCP_HOST_REFERENCES',str(RUNTIME/'dotnet/CadStudio.SolidWorks.AddinHost/bin/Release/net48')))
    if not csc.is_file():pytest.skip('Explicit .NET Framework C# compiler unavailable')
    host=ROOT/'dotnet/CadStudio.SolidWorks.AddinHost'
    for name in ('CamWorks.Interop.dll','SolidWorks.Interop.sldworks.dll'):
        if not (refs/name).is_file():pytest.skip('Explicit installed public interop references unavailable')
        shutil.copy2(refs/name,tmp_path/name)
    exe=tmp_path/'OwnerRecordsHarness.exe'
    args=[str(csc),'/nologo','/target:exe','/platform:x64','/out:'+str(exe),'/r:System.Core.dll','/r:System.Web.Extensions.dll','/r:Microsoft.CSharp.dll']
    args+=['/r:'+str(refs/name) for name in ('CamWorks.Interop.dll','SolidWorks.Interop.sldworks.dll')]
    args += [str(host/'CamBatchReader.cs'),str(host/'CamTurnRecordRead.cs'),str(ROOT/'tests/OwnerRecordsHarness.cs')]
    built=subprocess.run(args,capture_output=True,text=True);assert built.returncode==0,built.stdout+built.stderr
    ran=subprocess.run([str(exe)],capture_output=True,text=True,cwd=tmp_path);assert ran.returncode==0,ran.stdout+ran.stderr
    r=json.loads(ran.stdout);assert r['status']=='passed' and r['checks']>=20
