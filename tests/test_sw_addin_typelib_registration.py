from copy import deepcopy
from pathlib import Path
import importlib.util
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'sw_addin_typelib_registration.py'
SPEC = importlib.util.spec_from_file_location('reviewed_host_typelib_registration', SCRIPT)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def shape(*optional):
    rows = [dict(guid=m.TURN,name='ICamBatchReader',method='ReadTurnSnapshot',abi=deepcopy(m.ABI))]
    for identity in optional:
        name, method = m.CAM_INTERFACES[identity]
        rows.append(dict(guid=identity,name=name,method=method,abi=deepcopy(m.ABI)))
    rows += [dict(guid=k,name=v) for k,v in m.AUTO_INTERFACES.items()]
    return dict(libid=m.LIBID,version=[1,0],syskind=3,interfaces=rows,
        coclasses=[m.PROPERTY_PAGE_CLSID,m.CLSID]+([m.BORE_SINK_CLSID] if m.BORE in optional else []))


class Backend:
    def __init__(self, value=None, result=0, verified=True):
        self.value = value or shape(m.BORE)
        self.result=result;self.verified=verified;self.calls=[]
    def load(self,path):
        self.calls.append('metadata');return object(),self.value
    def register(self,library,path):
        self.calls.append('register');return self.result
    def readback(self,path,interfaces):
        self.calls.append('readback');return dict(verified=self.verified,interfaces=interfaces)


def test_metadata_validation_does_not_register():
    b=Backend();out=m.run('unused.tlb',[m.BORE],backend=b)
    assert out['status']=='validated' and b.calls==['metadata']
    assert out['registration_attempted'] is False and out['native_CAD_calls']==0


def test_success_registers_exact_validated_library_once_and_reads_back():
    b=Backend();out=m.run('unused.tlb',[m.BORE],register=True,backend=b)
    assert b.calls==['metadata','register','readback']
    assert out['status']=='registered_verified'


@pytest.mark.parametrize('change',[
    lambda s:s.update(libid=m.CLSID),
    lambda s:s.update(version=[2,0]),
    lambda s:s.update(syskind=1),
    lambda s:s.update(coclasses=[m.CLSID]),
    lambda s:s['interfaces'].append(dict(guid=m.CLSID,name='Unexpected')),
    lambda s:s['interfaces'].append(deepcopy(s['interfaces'][0])),
    lambda s:s['interfaces'][1].update(method='ArbitraryMethod'),
    lambda s:s['interfaces'][1]['abi'].update(parameter_count=3),
    lambda s:s['interfaces'][1]['abi']['arguments'][1].update(pointee_vt=9),
    lambda s:s['interfaces'][1]['abi'].update(vtable_offset=64),
])
def test_invalid_metadata_rejects_before_any_registration(change):
    s=shape(m.BORE);change(s);b=Backend(s)
    with pytest.raises(ValueError):m.run('unused.tlb',[m.BORE],register=True,backend=b)
    assert b.calls==['metadata']


def test_required_missing_interface_rejects_before_registration():
    b=Backend(shape())
    with pytest.raises(ValueError):m.run('unused.tlb',[m.BORE],register=True,backend=b)
    assert b.calls==['metadata']


def test_unknown_required_guid_is_not_registered():
    b=Backend()
    with pytest.raises(ValueError):m.run('unused.tlb',[m.CLSID],register=True,backend=b)
    assert b.calls==['metadata']


@pytest.mark.parametrize('result',[1,-2147467259,None,True])
def test_hresult_failure_stops_no_readback_or_retry(result):
    b=Backend(result=result)
    with pytest.raises(ValueError):m.run('unused.tlb',[m.BORE],register=True,backend=b)
    assert b.calls==['metadata','register']


def test_readback_failure_cannot_claim_verified():
    b=Backend(verified=False)
    with pytest.raises(ValueError):m.run('unused.tlb',[m.BORE],register=True,backend=b)
    assert b.calls==['metadata','register','readback']


@pytest.mark.parametrize('optional',[(),(m.MILL,),(m.BORE,),(m.MILL,m.BORE)])
def test_exact_known_version_profiles(optional):
    ids=m.validate_shape(shape(*optional),[m.TURN,*optional])
    assert set(ids)==set(m.AUTO_INTERFACES)|{m.TURN,*optional}


def test_build_and_registration_wiring():
    text=(SCRIPT.parent/'sw_addin_host.ps1').read_text(encoding='utf-8')
    assert 'Export-AddinTypeLibrary\n}' in text
    assert '& $exporter $AssemblyPath "/out:$TypeLibraryPath" /win64 /silent' in text
    assert 'function Register-CurrentUser {\n    Invoke-CheckedTypeLibrary -RegisterCurrentUser' in text
    assert 'InprocServer32\\$assemblyVersion' in text
    assert 'InprocServer32\\1.0.0.0' not in text
    assert '$command += " -RequiredCamInterface @($requiredLiteral)"' in text
    assert 'Register-CurrentUser' in text and '-WindowStyle Hidden' in text



def registration_values(version, *, root=False):
    values=dict(Class='CadStudio.SolidWorks.AddinHost.SwAddin',
        Assembly='CadStudio.SolidWorks.AddinHost, Version='+version+', Culture=neutral, PublicKeyToken=6f0670dca5152b74',
        RuntimeVersion='v4.0.30319',CodeBase='file:///C:/host/CadStudio.SolidWorks.AddinHost.dll')
    if root:values.update({'':'mscoree.dll','ThreadingModel':'Both'})
    return values


def retirement(tmp_path):
    return dict(schema_version=1,current_version='1.0.0.0',retire_version='1.0.1.0',
        expected_current_values=registration_values('1.0.0.0',root=True),
        expected_old_values=registration_values('1.0.1.0'),
        rollback_path=str(tmp_path/'rollback.json'))


class Retirer:
    def __init__(self,p):
        self.p=p;self.calls=[];self.deleted=False;self.fail_delete=False;self.change_after_backup=False
    def read(self,version=None):
        self.calls.append(('read',version))
        value=deepcopy(self.p['expected_old_values'] if version else self.p['expected_current_values'])
        if self.change_after_backup and Path(self.p['rollback_path']).exists():value['CodeBase']='changed'
        return value
    def delete_leaf(self,version):
        self.calls.append(('delete',version))
        assert Path(self.p['rollback_path']).is_file()
        if self.fail_delete:raise OSError('simulated delete failure')
        self.deleted=True
    def absent(self,version):
        self.calls.append(('absent',version));return self.deleted


def test_one_leaf_retirement_after_durable_rollback(tmp_path):
    p=retirement(tmp_path);b=Retirer(p);out=m.retire_stale_user_version(p,backend=b)
    assert out['status']=='retired_verified' and out['recursive_delete'] is False
    assert [v for k,v in b.calls if k=='delete']==['1.0.1.0']
    import json
    backup=json.loads(Path(p['rollback_path']).read_text(encoding='utf-8'))
    assert backup['old_values']==p['expected_old_values']
    assert backup['exact_leaf']==m.CLASS_ROOT+'\\1.0.1.0'
    assert backup['current_root_values']==p['expected_current_values']


@pytest.mark.parametrize('change',[
    lambda p:p.update(retire_version='1.0.0.0'),
    lambda p:p.update(retire_version='../other'),
    lambda p:p.update(retire_version='1.0.70000.0'),
    lambda p:p['expected_old_values'].update(Class='Foreign.Class'),
    lambda p:p['expected_old_values'].update(CodeBase='https://example.org/CadStudio.SolidWorks.AddinHost.dll'),
    lambda p:p['expected_old_values'].update(Other='unexpected'),
    lambda p:p['expected_current_values'].update(Assembly=p['expected_old_values']['Assembly']),
])
def test_invalid_retirement_never_reads_or_deletes_registry(tmp_path,change):
    p=retirement(tmp_path);change(p);b=Retirer(p)
    with pytest.raises(ValueError):m.retire_stale_user_version(p,backend=b)
    assert b.calls==[] and not Path(p['rollback_path']).exists()


def test_registration_drift_after_backup_stops_before_delete(tmp_path):
    p=retirement(tmp_path);b=Retirer(p);b.change_after_backup=True
    with pytest.raises(ValueError):m.retire_stale_user_version(p,backend=b)
    assert Path(p['rollback_path']).is_file() and not any(k=='delete' for k,v in b.calls)


def test_delete_failure_retains_marker_and_cannot_replay(tmp_path):
    p=retirement(tmp_path);b=Retirer(p);b.fail_delete=True
    with pytest.raises(OSError):m.retire_stale_user_version(p,backend=b)
    assert Path(p['rollback_path']).is_file()
    before=list(b.calls)
    with pytest.raises(ValueError):m.retire_stale_user_version(p,backend=b)
    assert b.calls==before and len([x for x in b.calls if x[0]=='delete'])==1



def test_missing_bore_callback_rejected_before_registration():
    value=shape(m.BORE);value['coclasses'].remove(m.BORE_SINK_CLSID);b=Backend(value)
    with pytest.raises(ValueError):m.run('unused.tlb',[m.BORE],register=True,backend=b)
    assert b.calls==['metadata']


def test_register_built_does_not_rebuild_reviewed_binaries():
    text=(SCRIPT.parent/'sw_addin_host.ps1').read_text(encoding='utf-8')
    case=text.split("    'RegisterBuilt' {")[1].split("    'Register' {")[0]
    assert 'Build-AddinHost' not in case
    assert 'Register-CurrentUser' in case and "-ne 'CurrentUser'" in case
    assert 'ExpectedAssemblySha256' in case and 'ExpectedTypeLibrarySha256' in case
    assert 'Get-FileHash -LiteralPath $AssemblyPath' in case
    assert 'Get-FileHash -LiteralPath $TypeLibraryPath' in case


@pytest.mark.parametrize('action', ['register', 'retire', 'backend_register', 'backend_delete'])
def test_packaged_process_rejects_all_real_write_paths_before_other_work(monkeypatch, action):
    calls=[]
    def reject():
        calls.append('package_guard')
        raise ValueError('Unpackaged registration process required')
    monkeypatch.setattr(m, 'assert_unpacked_registry_writer', reject)
    with pytest.raises(ValueError, match='Unpackaged'):
        if action == 'register': m.run('nonexistent.tlb', [], register=True)
        elif action == 'retire': m.retire_stale_user_version({})
        elif action == 'backend_register': m.RegistrationBackend().register(None, 'nonexistent.tlb')
        else: m.VersionRetirementBackend().delete_leaf('1.0.1.0')
    assert calls == ['package_guard']


def test_packaged_process_still_allows_metadata_only(monkeypatch):
    monkeypatch.setattr(m, 'assert_unpacked_registry_writer', lambda: pytest.fail('write guard on read-only path'))
    out=m.run('unused.tlb',[m.BORE],backend=Backend())
    assert out['status']=='validated'


def test_powershell_uses_metadata_python_and_unpacked_native_writer():
    text=(SCRIPT.parent/'sw_addin_host.ps1').read_text(encoding='utf-8')
    invoke=text.split('function Invoke-CheckedTypeLibrary {')[1].split('function Test-IsAdministrator {')[0]
    assert "'--register-current-user'" not in invoke
    assert 'Register-NativeUserTypeLibrary -Checked $checked' in invoke
    assert 'GetCurrentPackageFullName' in text and 'result != 15700' in text
    assert '[Microsoft.Win32.RegistryView]::Registry64' in text
    assert 'if (library != IntPtr.Zero) Marshal.Release(library);' in text
    assert 'LoadTypeLibEx(path, 2, out library)' in text
