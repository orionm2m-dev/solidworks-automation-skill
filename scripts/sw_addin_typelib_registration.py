"""Exported add-in typelib validation and bounded per-user registration.

No SOLIDWORKS/CAM instance is activated. Registration is limited to the fixed
host library and the interfaces verified from its actual exported typelib.
"""
from pathlib import Path
import argparse
import ctypes
import json
import os
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit, unquote

LIBID = '{AF071B05-0956-3EFB-B3F0-77BC51751AC9}'
CLSID = '{8EE76E8D-9B47-4DE0-AFA2-B2E36621A134}'
PROPERTY_PAGE_CLSID = '{8F33287B-C62A-4E05-85E6-3D7339A7F74B}'
BORE_SINK_CLSID = '{046D82BC-7F81-3EB9-BC2E-A6AD9EF1E95D}'
TURN = '{DA9D97F8-EB0E-4D7B-A741-0E1736E899A2}'
MILL = '{D8D32706-6533-47A3-821B-BB23D266C188}'
BORE = '{63CD9668-1A04-4D45-AC42-AD484D30F9EB}'
CAM_INTERFACES = {
    TURN: ('ICamBatchReader', 'ReadTurnSnapshot'),
    MILL: ('ICamMillBatchReader', 'ReadMillSnapshotBatch'),
    BORE: ('ICamTurnBoreBuilder', 'QualifyCreateBoundTurnBore'),
}
AUTO_INTERFACES = {
    '{C3819565-9281-33ED-885A-1973E9AB1487}': '_PropertyPageHandler',
    '{05C45FEF-D8E5-3BAF-BB0C-F24CFD6A65BA}': '_SwAddin',
}
ABI = dict(typekind=3, function_count=1, memid=1, invkind=1, funckind=1,
    callconv=4, vtable_offset=56, parameter_count=2, optional_count=0,
    return_vt=25, arguments=[dict(vt=8,pointee_vt=None,flags=1),
    dict(vt=26,pointee_vt=8,flags=10)])


def require(value, message):
    if not value:
        raise ValueError(message)


def assert_unpacked_registry_writer():
    """Reject private package registry overlays before any real registration write."""
    require(ctypes.sizeof(ctypes.c_void_p) == 8, '64-bit registration process required')
    native = ctypes.WinDLL('kernel32').GetCurrentPackageFullName
    native.argtypes = (ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p)
    native.restype = ctypes.c_long
    length = ctypes.c_uint32(0)
    result = native(ctypes.byref(length), None)
    require(result == 15700,
        'Unpackaged registration process required; use the PowerShell host helper for real HKCU writes')


def guid(value):
    return '{' + str(uuid.UUID(str(value).strip('{}'))).upper() + '}'


def validate_shape(shape, required):
    require(shape['libid'] == LIBID and shape['version'] == [1, 0]
        and shape['syskind'] == 3, 'Exact x64 host LIBID/version required')
    required = {guid(value) for value in required} | {TURN}
    require(required <= set(CAM_INTERFACES), 'Unknown required host interface')
    rows = shape['interfaces']
    require(type(rows) is list and 3 <= len(rows) <= 5, 'Bounded host interfaces required')
    ids = {row['guid'] for row in rows}
    require(len(ids) == len(rows), 'Duplicate exported interface')
    require(set(AUTO_INTERFACES) <= ids and ids <= set(AUTO_INTERFACES) | set(CAM_INTERFACES)
        and required <= ids, 'Missing or unexpected exported host interface')
    coclasses = {CLSID, PROPERTY_PAGE_CLSID} | ({BORE_SINK_CLSID} if BORE in ids else set())
    require(len(shape['coclasses']) == len(coclasses) and set(shape['coclasses']) == coclasses,
        'Exact host, property-page and optional bore callback coclasses required')
    for row in rows:
        if row['guid'] in AUTO_INTERFACES:
            require(row['name'] == AUTO_INTERFACES[row['guid']], 'Automatic host interface name differs')
        else:
            name, method = CAM_INTERFACES[row['guid']]
            require(row['name'] == name and row['method'] == method
                and row['abi'] == ABI, 'Fixed host BSTR method ABI differs')
    return sorted(ids)


def load_shape(path):
    from comtypes import typeinfo
    require(ctypes.sizeof(ctypes.c_void_p) == 8, '64-bit metadata process required')
    path = Path(path)
    require(path.is_absolute() and path.is_file() and path.suffix.lower() == '.tlb',
        'Existing absolute host type library required')
    lib = typeinfo.LoadTypeLibEx(str(path), typeinfo.REGKIND_NONE)
    attr = lib.GetLibAttr()
    shape = dict(libid=guid(attr.guid), version=[int(attr.wMajorVerNum), int(attr.wMinorVerNum)],
        syskind=int(attr.syskind), interfaces=[], coclasses=[])
    count = lib.GetTypeInfoCount()
    require(1 <= count <= 12, 'Bounded own host type information required')
    for index in range(count):
        info = lib.GetTypeInfo(index); attr = info.GetTypeAttr()
        identity = guid(attr.guid); name = lib.GetDocumentation(index)[0]
        if int(attr.typekind) == 5:
            shape['coclasses'].append(identity)
        elif int(attr.typekind) in (3, 4):
            row = dict(guid=identity, name=name)
            if identity in CAM_INTERFACES:
                dual = info.GetRefTypeInfo(info.GetRefTypeOfImplType(-1))
                dualattr = dual.GetTypeAttr()
                require(int(dualattr.cFuncs) == 1, 'One direct interface method required')
                function = dual.GetFuncDesc(0)
                arguments = []
                for i in range(function.cParams):
                    item = function.lprgelemdescParam[i]; vt = int(item.tdesc.vt)
                    arguments.append(dict(vt=vt,
                        pointee_vt=int(item.tdesc.lptdesc.contents.vt) if vt == 26 else None,
                        flags=int(item._.paramdesc.wParamFlags)))
                row.update(method=dual.GetDocumentation(function.memid)[0], abi=dict(
                    typekind=int(dualattr.typekind), function_count=int(dualattr.cFuncs),
                    memid=int(function.memid), invkind=int(function.invkind),
                    funckind=int(function.funckind), callconv=int(function.callconv),
                    vtable_offset=int(function.oVft), parameter_count=int(function.cParams),
                    optional_count=int(function.cParamsOpt), return_vt=int(function.elemdescFunc.tdesc.vt),
                    arguments=arguments))
            shape['interfaces'].append(row)
    return lib, shape


def read_user_registration(path, interface_ids):
    import winreg
    def read(key, name=''):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as handle:
            value, kind = winreg.QueryValueEx(handle, name)
            require(kind == winreg.REG_SZ, 'String registration value required')
            return value
    base = 'Software\\Classes\\'
    actual = read(base + 'TypeLib\\' + LIBID + '\\1.0\\0\\win64')
    require(os.path.normcase(os.path.abspath(actual)) == os.path.normcase(os.path.abspath(path)),
        'Per-user registered type library path differs')
    for identity in interface_ids:
        key = base + 'Interface\\' + identity
        require(guid(read(key + '\\TypeLib')) == LIBID
            and read(key + '\\TypeLib', 'Version') == '1.0',
            'Per-user interface library mapping differs')
        require(guid(read(key + '\\ProxyStubClsid32')) == '{00020424-0000-0000-C000-000000000046}',
            'Per-user interface marshaler differs')
    return dict(type_library_path=actual, interface_ids=interface_ids, verified=True)


class RegistrationBackend:
    def load(self, path):
        return load_shape(path)

    def register(self, library, path):
        assert_unpacked_registry_writer()
        native = ctypes.WinDLL('oleaut32').RegisterTypeLibForUser
        native.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p)
        native.restype = ctypes.c_long
        return native(ctypes.cast(library, ctypes.c_void_p), str(path), None)

    def readback(self, path, interfaces):
        return read_user_registration(path, interfaces)


def run(path, required, *, register=False, backend=None):
    if register and backend is None:
        assert_unpacked_registry_writer()
    backend = backend or RegistrationBackend()
    library, shape = backend.load(path)
    interfaces = validate_shape(shape, required)
    report = dict(status='validated', shape=shape, registration_attempted=False,
        registry_scope='CurrentUser' if register else None, native_CAD_calls=0)
    if register:
        report['registration_attempted'] = True
        result = backend.register(library, path)
        require(type(result) is int and result == 0, 'RegisterTypeLibForUser did not return S_OK')
        report['readback'] = backend.readback(path, interfaces)
        require(report['readback'].get('verified') is True, 'Registration readback not verified')
        report['status'] = 'registered_verified'
    return report


CLASS_ROOT = 'Software\\Classes\\CLSID\\' + CLSID + '\\InprocServer32'
VERSION_VALUES = {'Class', 'Assembly', 'RuntimeVersion', 'CodeBase'}
ROOT_VALUES = VERSION_VALUES | {'', 'ThreadingModel'}
RETIRE_FIELDS = {'schema_version', 'current_version', 'retire_version',
    'expected_current_values', 'expected_old_values', 'rollback_path'}


def checked_version(value):
    require(type(value) is str and re.fullmatch(r'[0-9]{1,5}(?:\.[0-9]{1,5}){3}', value)
        and all(int(x) <= 65535 for x in value.split('.')), 'Four bounded version fields required')
    return value


def checked_mapping(values, version, *, root=False):
    require(type(values) is dict and set(values) == (ROOT_VALUES if root else VERSION_VALUES),
        'Exact known host registration values required')
    require(all(type(x) is str and len(x) <= 32767 for x in values.values()),
        'Bounded string registration values required')
    require(values['Class'] == 'CadStudio.SolidWorks.AddinHost.SwAddin'
        and values['RuntimeVersion'] == 'v4.0.30319', 'Exact managed host class required')
    match = re.fullmatch(r'CadStudio\.SolidWorks\.AddinHost, Version=' + re.escape(version)
        + r', Culture=neutral, PublicKeyToken=([0-9a-f]{16})', values['Assembly'])
    require(match is not None, 'Exact managed host assembly version required')
    uri = urlsplit(values['CodeBase'])
    require(uri.scheme.lower() == 'file' and not uri.netloc and not uri.query and not uri.fragment
        and unquote(uri.path).replace('\\', '/').rsplit('/', 1)[-1].lower()
            == 'cadstudio.solidworks.addinhost.dll', 'Exact local host DLL CodeBase required')
    if root:
        require(values[''] == 'mscoree.dll' and values['ThreadingModel'] == 'Both',
            'Exact CLR registration values required')
    return match.group(1)


def validate_retirement(params):
    require(type(params) is dict and set(params) == RETIRE_FIELDS
        and type(params['schema_version']) is int and params['schema_version'] == 1,
        'Exact version-retirement request required')
    current = checked_version(params['current_version'])
    old = checked_version(params['retire_version'])
    require(current != old, 'Current registered version cannot be retired')
    current_token = checked_mapping(params['expected_current_values'], current, root=True)
    old_token = checked_mapping(params['expected_old_values'], old)
    require(current_token == old_token, 'Old and current strong-name tokens differ')
    path = Path(params['rollback_path'])
    require(path.is_absolute() and path.parent.is_dir() and path.suffix.lower() == '.json'
        and not path.exists() and not path.is_symlink(), 'New absolute rollback JSON required; no replay')
    return params


class VersionRetirementBackend:
    def read(self, version=None):
        import winreg
        path = CLASS_ROOT + ('\\' + version if version else '')
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as handle:
            children, count, _ = winreg.QueryInfoKey(handle)
            require(count <= 8 and (version is None or children == 0),
                'Only the exact bounded leaf version key can be retired')
            values = {}
            for i in range(count):
                name, value, kind = winreg.EnumValue(handle, i)
                require(kind == winreg.REG_SZ, 'Unexpected registration value kind')
                values[name] = value
            return values

    def delete_leaf(self, version):
        assert_unpacked_registry_writer()
        import winreg
        # Fixed own class, one reviewed non-current version, no recursive delete.
        winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, CLASS_ROOT + '\\' + version,
            winreg.KEY_WOW64_64KEY, 0)

    def absent(self, version):
        try:
            self.read(version)
        except FileNotFoundError:
            return True
        return False


def retire_stale_user_version(params, *, backend=None):
    if backend is None:
        assert_unpacked_registry_writer()
    p = validate_retirement(params)
    backend = backend or VersionRetirementBackend()
    current = backend.read()
    old = backend.read(p['retire_version'])
    require(current == p['expected_current_values'] and old == p['expected_old_values'],
        'Registration changed or differs from reviewed exact values')
    backup = dict(schema_version=1, scope='OWN_HOST_RETIRED_USER_VERSION_ROLLBACK',
        captured_utc=datetime.now(timezone.utc).isoformat(), hive='HKEY_CURRENT_USER', view=64,
        exact_leaf=CLASS_ROOT + '\\' + p['retire_version'],
        old_values=old, current_root_values=current,
        action='delete_one_noncurrent_leaf_once', native_CAD_calls=0)
    with Path(p['rollback_path']).open('x', encoding='utf-8') as stream:
        json.dump(backup, stream, ensure_ascii=False, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    # The retained rollback file is also the one-attempt marker; a failure never replays.
    require(backend.read() == current and backend.read(p['retire_version']) == old,
        'Registration changed after durable rollback capture')
    backend.delete_leaf(p['retire_version'])
    require(backend.absent(p['retire_version']) and backend.read() == current,
        'Leaf retirement or preserved current mapping not verified')
    return dict(status='retired_verified', registry_scope='CurrentUser',
        retired_version=p['retire_version'], current_version=p['current_version'],
        rollback_path=p['rollback_path'], recursive_delete=False, native_CAD_calls=0,
        registration_root_preserved=True, deletion_calls=1, automatic_retry=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--typelib')
    mode.add_argument('--retire-version-request')
    parser.add_argument('--required-interface', action='append', default=[])
    parser.add_argument('--register-current-user', action='store_true')
    args = parser.parse_args()
    if args.retire_version_request:
        require(not args.register_current_user and not args.required_interface,
            'Version retirement is a separate explicit operation')
        request = Path(args.retire_version_request)
        require(request.is_absolute() and request.is_file() and request.stat().st_size <= 65536,
            'Bounded absolute retirement request required')
        params = json.loads(request.read_text(encoding='utf-8-sig'))
        require(request.resolve() != Path(params['rollback_path']).resolve(),
            'Rollback may not replace its request')
        result = retire_stale_user_version(params)
    else:
        result = run(args.typelib, args.required_interface, register=args.register_current_user)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
