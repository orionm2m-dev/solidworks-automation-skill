"""Bounded own-host replacement and one fixed MILL read.

Current-user registration reuses the established managed-class mapping and the
documented RegisterTypeLibForUser API. No CAM edit, Save, retry or rollback.
A trusted checkpoint provider supplies the current 17/8 reference independently
of request data; the request cannot select a Python module or native member.
"""
from copy import deepcopy
from pathlib import Path
import base64, ctypes, hashlib, json, os, subprocess, time, uuid
from scripts import sw_cam_inprocess_reader as common
from scripts import sw_cam_inprocess_host_load as loader
from scripts import sw_cam_mill_packet_projection as projection
from scripts.sw_cam_generation import _write_receipt

require=common.require
SCOPE='OWN_HOST_VERSIONED_MILL_QUALIFICATION_V1'
MILL_IID='{D8D32706-6533-47A3-821B-BB23D266C188}'
PROGID='CadStudio.SolidWorks.AddinHost'
CLASS='CadStudio.SolidWorks.AddinHost.SwAddin'
VERSION='1.0.1.0'
CLASS_ROOT='Software\\Classes\\CLSID\\'+common.HOST_CLSID
TLB_ROOT='Software\\Classes\\TypeLib\\'+common.HOST_LIBID
PROG_ROOT='Software\\Classes\\'+PROGID
STARTUP='Software\\SOLIDWORKS\\AddInsStartup\\'+common.HOST_CLSID
DISCOVERY='SOFTWARE\\SOLIDWORKS\\Addins\\'+common.HOST_CLSID
AUTO_INTERFACES=('{C3819565-9281-33ED-885A-1973E9AB1487}','{05C45FEF-D8E5-3BAF-BB0C-F24CFD6A65BA}')
INTERFACES=(common.READER_IID,MILL_IID)+AUTO_INTERFACES
PARAMS={'process_id','expected_process_creation_time','expected_document_path','expected_source_sha256',
        'expected_dirty','expected_configuration','old_artifact_pin','new_artifact_pin',
        'checkpoint_receipt_pin','module_sha256','checkpoint_provider_sha256','projector_sha256','receipt_path'}
ARTIFACT={'assembly','version','public_key_token','mvid','dll','tlb','dependencies'}

def pin(path):
    p=Path(path);return dict(path=str(p),sha256=common.digest(p),bytes=p.stat().st_size)

def read_pin(value):
    require(type(value)is dict and set(value)=={'path','sha256','bytes'},'Exact file pin required')
    common.check_files([value]);p=Path(value['path'])
    require(type(value['bytes'])is int and p.stat().st_size==value['bytes']<=1024*1024,'Bounded evidence file required')
    return common.decode(p.read_text(encoding='utf-8-sig'))

def merge_pins(*groups):
    result={}
    for group in groups:
        require(type(group)is list and len(group)<=512,'Bounded proof list required')
        for p in group:
            require(type(p)is dict and {'path','sha256'}<=set(p),'Exact proof pin required')
            k=common.key(p['path'])
            if k in result:require(result[k]['sha256']==p['sha256'],'Conflicting proof hashes')
            else:result[k]=deepcopy(p)
    require(0<len(result)<=512,'Bounded complete proof closure required')
    return list(result.values())

def artifact(value,version):
    require(type(value)is dict and set(value)==ARTIFACT,'Exact artifact manifest required')
    require(value['version']==version and type(value['public_key_token'])is str and
            len(value['public_key_token'])==16 and all(c in '0123456789abcdef'for c in value['public_key_token']),
            'Exact strong-name version/token required')
    require(value['assembly']==PROGID+', Version='+version+', Culture=neutral, PublicKeyToken='+value['public_key_token'],
            'Exact full assembly identity required')
    require(str(uuid.UUID(value['mvid']))==value['mvid'],'Canonical artifact MVID required')
    for key,suffix in [('dll','.dll'),('tlb','.tlb')]:
        p=value[key];require(type(p)is dict and set(p)=={'path','sha256','bytes'},'Exact artifact file pin required')
        require(Path(p['path']).is_absolute() and Path(p['path']).suffix.lower()==suffix,'Absolute artifact path required')
    require(Path(value['dll']['path']).name==PROGID+'.dll' and
            common.key(Path(value['dll']['path']).parent)==common.key(Path(value['tlb']['path']).parent),
            'Side-by-side named DLL/TLB pair required')
    require(type(value['dependencies'])is list and 1<=len(value['dependencies'])<=8,'Bounded dependency manifest required')
    common.check_files([value['dll'],value['tlb']]+value['dependencies'])
    return value

def class_writes(a):
    """The existing Register-CurrentUser mapping, with the actual version key."""
    codebase=Path(a['dll']['path']).resolve().as_uri()
    values={'Class':CLASS,'Assembly':a['assembly'],'RuntimeVersion':'v4.0.30319','CodeBase':codebase}
    result={(PROG_ROOT,''):CLASS,(PROG_ROOT+'\\CLSID',''):common.HOST_CLSID,
            (CLASS_ROOT,''):CLASS,(CLASS_ROOT+'\\InprocServer32',''):'mscoree.dll',
            (CLASS_ROOT+'\\InprocServer32','ThreadingModel'):'Both',
            (CLASS_ROOT+'\\ProgId',''):PROGID}
    for k,v in values.items():
        result[(CLASS_ROOT+'\\InprocServer32',k)]=v
        result[(CLASS_ROOT+'\\InprocServer32\\'+a['version'],k)]=v
    return result

def registry_roots():
    return [CLASS_ROOT,PROG_ROOT,TLB_ROOT]+['Software\\Classes\\Interface\\'+i for i in INTERFACES]+[STARTUP,DISCOVERY]

def registry_snapshot():
    import winreg
    result={}
    for label,hive in [('HKCU',winreg.HKEY_CURRENT_USER),('HKLM',winreg.HKEY_LOCAL_MACHINE)]:
        rows={}
        def visit(path,depth=0):
            require(depth<=8 and len(rows)<256,'Bounded own-host registry tree required')
            try:key=winreg.OpenKey(hive,path,0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY)
            except FileNotFoundError:return
            with key:
                nk,nv,_=winreg.QueryInfoKey(key);require(nk<=64 and nv<=64,'Bounded own-host key required')
                vals={}
                for i in range(nv):
                    name,value,kind=winreg.EnumValue(key,i)
                    require(kind in (winreg.REG_SZ,winreg.REG_EXPAND_SZ,winreg.REG_DWORD,winreg.REG_BINARY,winreg.REG_MULTI_SZ),
                            'Unsupported registry value type')
                    if isinstance(value,bytes):value={'base64':base64.b64encode(value).decode()}
                    require(len(json.dumps(value,ensure_ascii=False))<=16384,'Bounded registry value required')
                    vals[name]={'type':kind,'value':value}
                rows[path]=vals
                for i in range(nk):visit(path+'\\'+winreg.EnumKey(key,i),depth+1)
        for root in registry_roots():visit(root)
        result[label]=rows
    return result

def verify_registry(before,after,new):
    """Account for every observed key in the host-only snapshot."""
    require(before['HKLM']==after['HKLM'],'Machine registration/discovery changed')
    for root in (STARTUP,DISCOVERY):
        require({k:v for k,v in before['HKCU'].items()if k==root or k.startswith(root+'\\')}==
                {k:v for k,v in after['HKCU'].items()if k==root or k.startswith(root+'\\')},
                'Personal SolidWorks discovery/startup changed')
    expected=deepcopy(before['HKCU'])
    for (path,name),value in class_writes(new).items():
        # CreateKeyEx also creates previously absent intermediate nodes.
        pieces=path.split('\\')
        root=CLASS_ROOT if path.startswith(CLASS_ROOT)else PROG_ROOT
        for n in range(len(root.split('\\')),len(pieces)+1):expected.setdefault('\\'.join(pieces[:n]),{})
        expected[path][name]={'type':1,'value':value}
    category=CLASS_ROOT+'\\Implemented Categories\\{62C8FE65-4EBB-45E7-B440-6E39B2CDBF29}'
    expected.setdefault(CLASS_ROOT+'\\Implemented Categories',{})
    expected.setdefault(category,{})
    interface_roots=['Software\\Classes\\Interface\\'+i for i in INTERFACES]
    def is_registration_library(k):
        return k==TLB_ROOT or k==TLB_ROOT+'\\1.0' or k.startswith(TLB_ROOT+'\\1.0\\') or any(k==r or k.startswith(r+'\\')for r in interface_roots)
    require({k:v for k,v in expected.items()if not is_registration_library(k)}==
            {k:v for k,v in after['HKCU'].items()if not is_registration_library(k)},
            'Unexpected personal class or preserved-version registration change')
    rows=after['HKCU'];node=rows.get(TLB_ROOT+'\\1.0\\0\\win64',{})
    require(common.key(node.get('',{}).get('value',''))==common.key(new['tlb']['path']),
            'Personal TLB CodeBase differs')
    for root in interface_roots:
        values=rows.get(root+'\\TypeLib',{})
        require(str(values.get('',{}).get('value','')).upper()==common.HOST_LIBID and
                values.get('Version',{}).get('value')=='1.0','Personal reader interface library differs')
    return dict(machine_unchanged=True,discovery_startup_unchanged=True,personal_class_exact=True,
                personal_library_and_interfaces_verified=True)

def inspect_assembly(path):
    """Metadata-only .NET Framework child; never instantiates the host."""
    script=("$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
        "$a=[Reflection.Assembly]::ReflectionOnlyLoad([IO.File]::ReadAllBytes($env:CADSTUDIO_HOST_INSPECT_PATH));"
        "$n=$a.GetName();"
        "@{assembly=$n.FullName;version=$n.Version.ToString();"
        "public_key_token=([BitConverter]::ToString($n.GetPublicKeyToken())).Replace('-','').ToLowerInvariant();"
        "mvid=$a.ManifestModule.ModuleVersionId.ToString()}|ConvertTo-Json -Compress")
    executable=Path(os.environ['WINDIR'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    env=dict(os.environ,CADSTUDIO_HOST_INSPECT_PATH=str(Path(path).resolve()))
    done=subprocess.run([str(executable),'-NoProfile','-NonInteractive','-EncodedCommand',
        base64.b64encode(script.encode('utf-16le')).decode()],env=env,capture_output=True,
        text=False,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    stdout=done.stdout.decode('utf-8',errors='strict');stderr=done.stderr.decode('utf-8',errors='replace')
    require(done.returncode==0 and len(stdout)<4096 and not stderr.strip(),'Offline assembly metadata probe failed: '+stderr[:2000])
    return common.decode(stdout)

def checked_host_abi(shape):
    expected=dict(typekind=3,function_count=1,memid=1,invkind=1,funckind=1,callconv=4,
        vtable_offset=56,parameter_count=2,optional_count=0,return_vt=25,
        arguments=[dict(vt=8,pointee_vt=None,flags=1),dict(vt=26,pointee_vt=8,flags=10)])
    require(shape==expected,'Actual dual host BSTR ABI differs')
    return shape


def type_library(path,*,mill):
    from ctypes import POINTER
    from comtypes import BSTR,HRESULT,COMMETHOD,GUID,dispid,typeinfo
    from comtypes.automation import IDispatch
    lib=typeinfo.LoadTypeLibEx(path,typeinfo.REGKIND_NONE);a=lib.GetLibAttr()
    require(str(a.guid).upper()==common.HOST_LIBID and (a.wMajorVerNum,a.wMinorVerNum)==(1,0),
            'Exact owned type library required')
    interfaces=set();selected=None;name='ICamMillBatchReader'if mill else'ICamBatchReader'
    require(1<=lib.GetTypeInfoCount()<=8,'Bounded own-host typelib required')
    for i in range(lib.GetTypeInfoCount()):
        info=lib.GetTypeInfo(i);attr=info.GetTypeAttr()
        if int(attr.typekind)in(3,4):interfaces.add(str(attr.guid).upper())
        if lib.GetDocumentation(i)[0]==name:selected=info
    require(interfaces==set(INTERFACES if mill else (common.READER_IID,)+AUTO_INTERFACES),
            'Type library would register an unexpected interface')
    expected=MILL_IID if mill else common.READER_IID
    require(selected is not None and str(selected.GetTypeAttr().guid).upper()==expected,'Fixed reader IID differs')
    dual=selected.GetRefTypeInfo(selected.GetRefTypeOfImplType(-1));attr=dual.GetTypeAttr()
    require(int(attr.cFuncs)==1,'Exactly one direct reader vtable method required')
    method='ReadMillSnapshotBatch'if mill else'ReadTurnSnapshot';f=dual.GetFuncDesc(0)
    require(dual.GetDocumentation(f.memid)[0]==method,'Fixed reader member differs')
    args=[]
    for i in range(f.cParams):
        e=f.lprgelemdescParam[i];vt=int(e.tdesc.vt)
        args.append(dict(vt=vt,pointee_vt=int(e.tdesc.lptdesc.contents.vt)if vt==26 else None,
                         flags=int(e._.paramdesc.wParamFlags)))
    checked_host_abi(dict(typekind=int(attr.typekind),function_count=int(attr.cFuncs),memid=int(f.memid),
        invkind=int(f.invkind),funckind=int(f.funckind),callconv=int(f.callconv),vtable_offset=int(f.oVft),
        parameter_count=int(f.cParams),optional_count=int(f.cParamsOpt),return_vt=int(f.elemdescFunc.tdesc.vt),arguments=args))
    # Fixed typed interface, deliberately independent of GetModule's LIBID/1.0 cache.
    # The actual typelib above must match before this interface can be used.
    class FixedReader(IDispatch):
        _iid_=GUID(expected)
        _methods_=[COMMETHOD([dispid(1)],HRESULT,method,
            (['in'],BSTR,'requestJson'),(['out','retval'],POINTER(BSTR),'resultJson'))]
    return lib,FixedReader,method


def inspect_artifact(dll_path):
    """Offline manifest for an existing immutable old or new host directory."""
    path=Path(dll_path);require(path.is_absolute() and path.name==PROGID+'.dll','Exact host DLL path required')
    meta=inspect_assembly(path);require(meta['version']in('1.0.0.0',VERSION),'Explicit old/new host version required')
    type_library(str(path.with_suffix('.tlb')),mill=meta['version']==VERSION)
    dependencies=[pin(path.parent/name)for name in('CamWorks.Interop.dll','SolidWorks.Interop.sldworks.dll',
        'SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swpublished.dll')]
    value=dict(meta,dll=pin(path),tlb=pin(path.with_suffix('.tlb')),dependencies=dependencies)
    artifact(value,meta['version']);return value


def same_registration_user(pid):
    import win32api,win32con,win32security
    def sid(process):
        token=win32security.OpenProcessToken(process,win32con.TOKEN_QUERY)
        try:return win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token,win32security.TokenUser)[0])
        finally:token.Close()
    selected=win32api.OpenProcess(0x1000,False,pid)
    try:owned=sid(selected)
    finally:selected.Close()
    current=sid(win32api.GetCurrentProcess())
    require(current==owned,'CurrentUser registration account differs from selected SolidWorks owner')
    return dict(current_user_sid=current,selected_process_user_sid=owned,same_user_verified=True)


def event_check(summary,*,closed=False):
    require(summary.get('subscribed')is True and summary.get('active')is(not closed) and
            summary.get('event_count')==0 and summary.get('overflow')==0 and
            summary.get('callback_error_count')==0 and summary.get('callback_errors')==[] and
            summary.get('subscription_error')is None and summary.get('disconnect_errors')==[],
            'Native CAM event session reported an error')
    if closed:require(summary.get('disconnected')is True,'Native event subscription not released')

def validate_old_identity(r,p,old):
    require(r.get('schema_version')==1 and r.get('scope')=='TURN_INPROCESS_READ_V1' and
            r.get('engine_version')=='turn-reader-1' and r.get('stage')=='request' and
            r.get('status')=='error' and r.get('message')=='REQUEST_FIELDS' and
            r.get('read_only')is True and r.get('mutation_attempted')is False and
            r.get('readback_verified')is False,'Exact pre-CAM identity-only response required')
    require(r.get('process_id')==p['process_id'] and r.get('host_module_version_id')==old['mvid'] and
            common.key(r.get('host_assembly_location',''))==common.key(old['dll']['path']),
            'Actually loaded old host identity differs')
    require(not any(k in r for k in ('document_before','inventory','tools','nc_parameters','cam_configuration')),
            'Identity-only request unexpectedly reached CAM')

class NativeBackend(loader.LoaderBackend):
    def __init__(self,p,old,new,reference):
        super().__init__(p);self.old=old;self.new=new;self.reference=reference;self.session=None
    def preflight(self):
        require(ctypes.sizeof(ctypes.c_void_p)==8,'64-bit client required')
        self.registration_identity=same_registration_user(self.p['process_id'])
        drive=ctypes.WinDLL('kernel32').GetDriveTypeW;drive.argtypes=(ctypes.c_wchar_p,);drive.restype=ctypes.c_uint
        for a in(self.old,self.new):
            require(drive(Path(a['dll']['path']).anchor)==3,'Host activation requires a local fixed drive')
        for a in(self.old,self.new):
            require(inspect_assembly(a['dll']['path'])=={k:a[k]for k in ('assembly','version','public_key_token','mvid')},
                    'Actual assembly metadata differs')
        type_library(self.old['tlb']['path'],mill=False);type_library(self.new['tlb']['path'],mill=True)
        getattr(ctypes.WinDLL('oleaut32'),'RegisterTypeLibForUser')
        before=registry_snapshot()
        require(DISCOVERY in before['HKLM'],'Existing machine SolidWorks discovery is required')
        return before
    def registry(self):return registry_snapshot()
    def _read(self,artifact,*,mill,text):
        from scripts.sw_cam_comtypes import _marshal_pywin32_unknown
        _,interface,method=type_library(artifact['tlb']['path'],mill=mill)
        raw=common._member(self.application(),'GetAddInObject',common.HOST_CLSID)
        require(raw is not None,'Owned reader host is not loaded')
        pointer=_marshal_pywin32_unknown(raw).QueryInterface(interface)
        return getattr(pointer,method)(text)
    def old_identity(self):return common.decode(self._read(self.old,mill=False,text='{}'))
    def unload_once(self):return common._member(self.application(),'UnloadAddIn',self.old['dll']['path'])
    def register_once(self):
        import winreg
        lib,_,_=type_library(self.new['tlb']['path'],mill=True)
        api=ctypes.WinDLL('oleaut32').RegisterTypeLibForUser
        api.argtypes=(ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_wchar_p);api.restype=ctypes.c_long
        result=api(ctypes.cast(lib,ctypes.c_void_p),self.new['tlb']['path'],None)
        require(result==0,'RegisterTypeLibForUser did not return S_OK')
        for (path,name),value in class_writes(self.new).items():
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,path,0,winreg.KEY_WRITE|winreg.KEY_WOW64_64KEY)as k:
                winreg.SetValueEx(k,name,0,winreg.REG_SZ,value)
        category=CLASS_ROOT+'\\Implemented Categories\\{62C8FE65-4EBB-45E7-B440-6E39B2CDBF29}'
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,category,0,winreg.KEY_WRITE|winreg.KEY_WOW64_64KEY):pass
        return dict(typelib_hresult=result,scope='CurrentUser',class_mapping='existing_Register_CurrentUser_version_derived')
    def load_once(self):return common._member(self.application(),'LoadAddIn',self.new['dll']['path'])
    def start_events(self):
        from scripts.sw_cam_mill_qualification import _bootstrap
        from scripts.sw_cam_events import CamMessageSession
        app=_bootstrap(self.application(),common.CAM_CLSID,self.reference['cam_typelib_pin']['path'],self.p['expected_document_path'])
        self.session=CamMessageSession(app,self.reference['cam_typelib_pin']['path'])
        self.session.__enter__();return self.session.summary()
    def read_once(self,request):
        return self._read(self.new,mill=True,text=json.dumps(request,ensure_ascii=False,allow_nan=False))
    def close_events(self):
        if self.session is None:return None
        self.session.__exit__(None,None,None);summary=self.session.summary()
        if summary.get('active')is False:self.session=None
        return summary

def prepare(params,*,reference_provider):
    require(type(params)is dict and set(params)==PARAMS,'Exact replacement parameters required')
    p=deepcopy(params)
    require(type(p['process_id'])is int and 0<p['process_id']<2**31 and common.finite(p['expected_process_creation_time']) and p['expected_process_creation_time']>0,
            'Exact owned process lifetime required')
    require(type(p['expected_dirty'])is bool and p['expected_dirty']is False,'Saved clean checkpoint required')
    require(type(p['expected_configuration'])is str and 0<len(p['expected_configuration'])<=4096,'Exact configuration required')
    require(p['module_sha256']==common.digest(__file__),'Sealed lifecycle implementation differs')
    require(p['projector_sha256']==common.digest(projection.__file__),'Sealed semantic projector differs')
    require(callable(reference_provider),'Trusted current-checkpoint provider required')
    old=artifact(read_pin(p['old_artifact_pin']),'1.0.0.0');new=artifact(read_pin(p['new_artifact_pin']),VERSION)
    require(old['public_key_token']==new['public_key_token'] and old['mvid']!=new['mvid'] and
            common.key(old['dll']['path'])!=common.key(new['dll']['path']),'Distinct versioned artifact with same key required')
    od={Path(v['path']).name:v['sha256']for v in old['dependencies']}
    nd={Path(v['path']).name:v['sha256']for v in new['dependencies']}
    require(od==nd,'Same-identity dependency replacement is not qualified')
    reference=reference_provider(deepcopy(p['checkpoint_receipt_pin']))
    require(reference.get('provider_pin',{}).get('sha256')==p['checkpoint_provider_sha256'],'Sealed checkpoint provider differs')
    require(type(reference)is dict and reference.get('verified_current_checkpoint')is True and
            reference.get('authority_pin')==p['checkpoint_receipt_pin'],'Verified exact checkpoint provider required')
    require(reference['source_sha256']==p['expected_source_sha256'] and
            common.key(reference['document']['path'])==common.key(p['expected_document_path']) and
            reference['document']['needs_save']is False and
            reference['document']['configuration']==p['expected_configuration'],
            'Reference source/document differs')
    common.check_owner(reference['ownership'],p)
    req=reference['mill_request']
    require(req['expected_process_id']==p['process_id'] and
            common.key(req['expected_document_path'])==common.key(p['expected_document_path']) and
            req['expected_sw_configuration']==p['expected_configuration'] and
            len(req['expected_operation_ids'])==17 and len(req['parameter_targets'])==8,
            'Exact current seventeen/eight request required')
    direct=merge_pins([p['old_artifact_pin'],p['new_artifact_pin'],
        pin(__file__),pin(projection.__file__),pin(common.__file__),pin(loader.__file__),
        reference['cam_typelib_pin'],dict(path=p['expected_document_path'],sha256=p['expected_source_sha256'])],
        [old['dll'],old['tlb']]+old['dependencies'],[new['dll'],new['tlb']]+new['dependencies'])
    pins=merge_pins(reference['pins'],[p['checkpoint_receipt_pin']],direct)
    reference['_lifecycle_live_pins']=merge_pins(reference.get('live_pins',reference['pins']),direct)
    require(len(reference['_lifecycle_live_pins'])<=96,'Bounded complete host-phase live closure required')
    common.check_files(pins)
    output=Path(p['receipt_path'])
    require(output.is_absolute() and output.suffix.lower()=='.json' and output.parent.is_dir() and not output.exists() and
            not output.is_symlink() and common.key(output)not in {common.key(x['path'])for x in pins},
            'Fresh nonaliased receipt required')
    return p,old,new,reference,pins

def marker_path(p,new):
    root=Path(os.environ['LOCALAPPDATA'])/'CAD Studio/SolidWorksAddin/lifecycle'
    identity=[SCOPE,p['process_id'],p['expected_process_creation_time'],common.key(p['expected_document_path']),new['mvid']]
    return root/(hashlib.sha256(json.dumps(identity,separators=(',',':')).encode()).hexdigest()+'.json')

def run_prepared(prepared,*,backend=None,marker=None):
    p,old,new,reference,pins=prepared
    engine=backend or NativeBackend(p,old,new,reference);out=Path(p['receipt_path'])
    marker=Path(marker)if marker is not None else marker_path(p,new)
    require(not marker.exists(),'Previous host lifecycle outcome exists; automatic replay is forbidden')
    r=dict(scope=SCOPE,status='prepared',phase='prepared',request=deepcopy(p),actions={},
           model_saved=False,GTP_attempted=False,model_change_requested=False,readback_verified=False,
           loaded_mvid_verified=False,native_dispatch_pending=False,automatic_replay=False,
           source_sha256=p['expected_source_sha256'],pins=pins,registration_scope='CurrentUser',
           live_pin_count=len(reference['_lifecycle_live_pins']),proof_pin_count=len(pins))
    _write_receipt(out,r,create=True);started=time.perf_counter();claimed=False
    def persist():_write_receipt(out,r)
    def boundary():
        common.check_owner(engine.owner(),p)
        doc=engine.document();common.validate_document(doc,p)
        require(doc['needs_save']is p['expected_dirty'] and doc['configuration']==p['expected_configuration'] and
                doc==reference['document'],'Current document/configuration/dirty state differs')
        common.check_files(reference['_lifecycle_live_pins'])
    def action(name,call):
        nonlocal claimed
        boundary()
        if not claimed:
            marker.parent.mkdir(parents=True,exist_ok=True)
            _write_receipt(marker,dict(scope=SCOPE,status='pending',request=deepcopy(p)),create=True);claimed=True
        row=dict(attempted=True,returned=False,verified=False);r['actions'][name]=row
        r.update(phase=name,native_dispatch_pending=True);persist()
        value=call();row['returned']=True
        row['result']=dict(response_bytes=len(value.encode('utf-8')),response_sha256=hashlib.sha256(value.encode('utf-8')).hexdigest())if name=='ReadMillSnapshot'else value
        r['native_dispatch_pending']=False;persist()
        boundary();return value
    try:
        boundary();r['registration_before']=engine.preflight();r['registration_identity']=getattr(engine,'registration_identity',None);persist()
        # This fixed malformed request is rejected by the old host parser before any CAM getter.
        r['old_identity']=engine.old_identity();validate_old_identity(r['old_identity'],p,old);boundary();persist()
        diagnostic=engine.diagnostics()
        require(diagnostic and diagnostic['data'].get('status')=='connected' and
                diagnostic['data'].get('hostProcessId')==p['process_id'],'Owned connected old host required')
        r['diagnostics_before']=diagnostic
        unload_started=time.time();value=action('UnloadOwnedHost',engine.unload_once)
        require(type(value)is int and value==0,'UnloadAddIn did not return zero')
        disconnected=engine.diagnostics();r['diagnostics_disconnected']=disconnected
        require(disconnected and disconnected['sha256']!=diagnostic['sha256'] and
                disconnected['data'].get('status')=='disconnected' and
                disconnected['data'].get('hostProcessId')==p['process_id'] and
                disconnected['data'].get('errors')==[] and
                str(disconnected['data'].get('addinGuid','')).strip('{}').upper()==common.HOST_CLSID.strip('{}') and
                loader.utc_epoch(disconnected['data'].get('lastUpdatedUtc'))>=unload_started-1,
                'Owned host disconnect not verified')
        require(engine.registry()==r['registration_before'],'Registration changed before explicit registration')
        r['actions']['UnloadOwnedHost']['verified']=True;persist()
        action('RegisterCurrentUserHost',engine.register_once)
        r['registration_after']=engine.registry()
        r['registration_proof']=verify_registry(r['registration_before'],r['registration_after'],new)
        r['actions']['RegisterCurrentUserHost']['verified']=True;persist()
        load_started=time.time();value=action('LoadVersionedHost',engine.load_once)
        require(type(value)is int and value==0,'LoadAddIn did not return zero')
        r['diagnostics_connected']=engine.diagnostics()
        loader.verify_diagnostics(disconnected,r['diagnostics_connected'],p,load_started)
        r['actions']['LoadVersionedHost']['verified']=True;persist()
        r['events_before']=engine.start_events();event_check(r['events_before']);boundary();persist()
        def read_packet():
            start=time.perf_counter();text=engine.read_once(reference['mill_request'])
            r['host_call_seconds']=time.perf_counter()-start;return text
        raw=action('ReadMillSnapshot',read_packet)
        packet=common.decode(raw);r['host_response']=packet;persist()
        require(packet.get('host_module_version_id')==new['mvid'] and
                common.key(packet.get('host_assembly_location',''))==common.key(new['dll']['path']),
                'Actually loaded new host identity differs')
        checked=projection.project_packet(packet,reference['mill_request'])
        require(projection.reader.group.exact(checked['snapshot'],reference['expected_snapshot']),
                'Host seventeen/eight semantics differ from current saved native baseline')
        r['projection']=checked;r['actions']['ReadMillSnapshot']['verified']=True
        r['events_after']=engine.close_events();event_check(r['events_after'],closed=True)
        boundary();common.check_files(pins)
        require(engine.registry()==r['registration_after'],'Registration changed during host read')
        r.update(status='qualified_read_only_mill_host',phase='finished',readback_verified=True,
                 loaded_mvid_verified=True,document_unchanged_verified=True)
    except Exception as exc:
        r.update(status='uncertain'if claimed else'error',phase='finished',issue=common._error(exc))
        # Only release this client's event subscription; no post-error CAD/host/registry action.
        try:
            if getattr(engine,'session',None)is not None:r['events_after']=engine.close_events()
        except Exception as clean:r['cleanup_issue']=common._error(clean)
    r['elapsed_seconds']=time.perf_counter()-started;persist()
    if claimed:_write_receipt(marker,dict(scope=SCOPE,status=r['status'],receipt_pin=pin(out),
        native_dispatch_pending=r['native_dispatch_pending'],automatic_replay=False))
    return r

def dispatch_request(request,*,reference_provider,validate_only=False,backend_factory=None):
    require(type(request)is dict and set(request)=={'action','params'} and
            request['action']=='replace_owned_host_and_read_mill','Fixed lifecycle action required')
    prepared=prepare(request['params'],reference_provider=reference_provider)
    if validate_only:return dict(status='validated_offline',scope=SCOPE,native_called=False,
        runtime_registration_checked=False,reference_source=prepared[0]['expected_source_sha256'])
    p,old,new,ref,_=prepared
    with common.solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        backend=backend_factory(p,old,new,ref)if backend_factory else None
        return run_prepared(prepared,backend=backend)

