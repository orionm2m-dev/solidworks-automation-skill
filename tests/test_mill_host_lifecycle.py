from copy import deepcopy
import importlib.util, json, os, sys
from pathlib import Path
import pytest

from cam_public_test_support import add_runtime, required_module, fixture_path
ROOT=add_runtime()
P=required_module("sw_cam_mill_packet_projection")
M=required_module("sw_cam_mill_host_lifecycle")

def events(closed=False):
    return dict(subscribed=True,active=not closed,disconnected=closed,event_count=0,overflow=0,
        callback_error_count=0,callback_errors=[],subscription_error=None,disconnect_errors=[])

@pytest.fixture
def case(tmp_path):
    fixture=json.loads(fixture_path('cam_mill_packet17_8_synthetic.json').read_text(encoding='utf-8-sig'))
    source=tmp_path/'part.sldprt';source.write_bytes(b'saved model')
    olddir=tmp_path/'old';newdir=tmp_path/'new';olddir.mkdir();newdir.mkdir()
    def art(directory,version,mvid):
        dll=directory/(M.PROGID+'.dll');dll.write_bytes(version.encode())
        tlb=dll.with_suffix('.tlb');tlb.write_bytes(b'tlb'+version.encode())
        dep=directory/'CamWorks.Interop.dll';dep.write_bytes(b'unchanged interop')
        token='1234567890abcdef'
        return dict(assembly=M.PROGID+', Version='+version+', Culture=neutral, PublicKeyToken='+token,
            version=version,public_key_token=token,mvid=mvid,dll=M.pin(dll),tlb=M.pin(tlb),dependencies=[M.pin(dep)])
    old=art(olddir,'1.0.0.0','339e4829-82ce-4274-b7b0-cac5ed1ec64c')
    new=art(newdir,'1.0.1.0','63a6b7e6-59d1-483d-a6bc-64cc805420d5')
    def save(name,value):
        path=tmp_path/name;path.write_text(json.dumps(value));return M.pin(path)
    checkpoint=save('checkpoint.json',{'saved':True})
    req=fixture['request'];req['expected_document_path']=str(source);req['expected_process_id']=123
    packet=fixture['packet'];packet['validated_request']=deepcopy(req);packet['process_id']=123
    packet.update(host_module_version_id=new['mvid'],host_assembly_location=new['dll']['path'])
    for key in('document_before','document_after'):
        packet[key]['path']=str(source)
    doc=deepcopy(packet['document_before']);doc['needs_save']=False
    packet['document_before']=deepcopy(doc);packet['document_after']=deepcopy(doc)
    ref=dict(provider_pin=M.pin(__file__),ownership=dict(alive=True,process_id=123,create_time=1000.,executable='C:/apps/SLDWORKS.exe'),verified_current_checkpoint=True,authority_pin=checkpoint,source_sha256=M.common.digest(source),
        document=doc,mill_request=req,expected_snapshot=fixture['expected_snapshot'],pins=[],
        cam_typelib_pin=old['tlb'])
    p=dict(process_id=123,expected_process_creation_time=1000.,expected_document_path=str(source),
        expected_source_sha256=ref['source_sha256'],expected_dirty=False,expected_configuration=doc['configuration'],
        old_artifact_pin=save('old.json',old),new_artifact_pin=save('new.json',new),checkpoint_receipt_pin=checkpoint,
        module_sha256=M.common.digest(M.__file__),checkpoint_provider_sha256=M.common.digest(__file__),projector_sha256=M.common.digest(P.__file__),receipt_path=str(tmp_path/'receipt.json'))
    prepared=M.prepare(p,reference_provider=lambda _:ref)
    return prepared,packet,tmp_path/'marker.json'

class Fake(M.NativeBackend):
    def __init__(self,prepared,packet,fail=None):
        p,old,new,ref,_=prepared;super().__init__(p,old,new,ref)
        self.packet=deepcopy(packet);self.fail=fail;self.calls=[];self.state='connected';self.closed=0
        self.reg={'HKCU':{},'HKLM':{M.DISCOVERY:{'':{'type':4,'value':0}}}}
    def owner(self):return dict(alive=True,process_id=123,create_time=1000.,executable='C:/apps/SLDWORKS.exe')
    def document(self):return deepcopy(self.reference['document'])
    def preflight(self):
        if self.fail=='preflight':raise ValueError('metadata rejected')
        return deepcopy(self.reg)
    def registry(self):return deepcopy(self.reg)
    def diagnostics(self):
        return dict(path='diagnostic.json',sha256=self.state,data=dict(status='disconnected'if self.state=='off'else'connected',
            hostProcessId=123,hostProcessName='SLDWORKS',addinGuid=M.common.HOST_CLSID,errors=[],
            callbackRegistered=True,commandGroupReady=True,taskPaneReady=True,propertyManagerPageReady=True,
            connectedAtUtc='2099-01-01T00:00:00Z',lastUpdatedUtc='2099-01-01T00:00:00Z'))
    def old_identity(self):
        return dict(schema_version=1,scope='TURN_INPROCESS_READ_V1',engine_version='turn-reader-1',stage='request',
            status='error',message='REQUEST_FIELDS',read_only=True,mutation_attempted=False,readback_verified=False,
            process_id=123,host_module_version_id=self.old['mvid'],host_assembly_location=self.old['dll']['path'])
    def call(self,name):
        self.calls.append(name)
        if self.fail==name:raise RuntimeError(name)
    def unload_once(self):self.call('unload');self.state='off';return 0
    def register_once(self):
        self.call('register')
        rows=self.reg['HKCU']
        for (path,name),value in M.class_writes(self.new).items():
            root=M.CLASS_ROOT if path.startswith(M.CLASS_ROOT)else M.PROG_ROOT
            parts=path.split('\\')
            for n in range(len(root.split('\\')),len(parts)+1):rows.setdefault('\\'.join(parts[:n]),{})
            rows[path][name]={'type':1,'value':value}
        rows[M.CLASS_ROOT+'\\Implemented Categories']={}
        rows[M.CLASS_ROOT+'\\Implemented Categories\\{62C8FE65-4EBB-45E7-B440-6E39B2CDBF29}']={}
        rows[M.TLB_ROOT]={};rows[M.TLB_ROOT+'\\1.0']={};rows[M.TLB_ROOT+'\\1.0\\0']={}
        rows[M.TLB_ROOT+'\\1.0\\0\\win64']={'':{'type':1,'value':self.new['tlb']['path']}}
        for iid in M.INTERFACES:
            root='Software\\Classes\\Interface\\'+iid
            rows[root]={};rows[root+'\\TypeLib']={'':{'type':1,'value':M.common.HOST_LIBID},'Version':{'type':1,'value':'1.0'}}
        return dict(typelib_hresult=0)
    def load_once(self):self.call('load');self.state='new';return 0
    def start_events(self):self.call('events');self.session=True;return events()
    def read_once(self,request):self.call('read');assert request==self.reference['mill_request'];return json.dumps(self.packet)
    def close_events(self):self.closed+=1;self.session=None;return events(True)

def test_fixed_class_registration_is_versioned_personal_only():
    writes=M.class_writes(dict(version='1.0.1.0',assembly='full-name',dll={'path':'C:/host/new.dll'}))
    assert all(p.startswith('Software\\Classes\\')for p,n in writes)
    assert any(p.endswith('\\1.0.1.0')for p,n in writes)
    assert not any('1.0.0.0'in p or 'SOLIDWORKS'in p for p,n in writes)

def test_native_constructor_reuses_loader_and_fixed_method_graph():
    p={'process_id':123};backend=M.NativeBackend(p,{}, {}, {})
    assert backend.p is p and backend.sw is None and backend.session is None
    for name in('preflight','registry','owner','document','diagnostics','old_identity','unload_once','register_once','load_once','read_once','start_events','close_events'):
        assert callable(getattr(backend,name))

def test_success_preserves17_8_and_records_new_mvid(case):
    prepared,packet,marker=case;engine=Fake(prepared,packet)
    result=M.run_prepared(prepared,backend=engine,marker=marker)
    assert result['status']=='qualified_read_only_mill_host',result.get('issue')
    assert engine.calls==['unload','register','load','events','read'] and engine.closed==1
    assert result['loaded_mvid_verified'] and result['readback_verified'] and not result['model_saved']
    assert list(result['actions'])==['UnloadOwnedHost','RegisterCurrentUserHost','LoadVersionedHost','ReadMillSnapshot']
    assert result['projection']['snapshot']==prepared[3]['expected_snapshot']
    assert not isinstance(result['actions']['ReadMillSnapshot']['result'],str)

@pytest.mark.parametrize('fail,expected',[('unload',['unload']),('register',['unload','register']),
    ('load',['unload','register','load']),('events',['unload','register','load','events']),
    ('read',['unload','register','load','events','read'])])
def test_no_following_action_after_failure(case,fail,expected):
    prepared,packet,marker=case;engine=Fake(prepared,packet,fail=fail)
    result=M.run_prepared(prepared,backend=engine,marker=marker)
    assert result['status']=='uncertain' and engine.calls==expected and marker.exists()
    assert not result['readback_verified']

def test_preflight_failure_has_no_mutation_marker(case):
    prepared,packet,marker=case;engine=Fake(prepared,packet,fail='preflight')
    result=M.run_prepared(prepared,backend=engine,marker=marker)
    assert result['status']=='error' and not engine.calls and not marker.exists()

def test_replay_not_bypassed_by_new_receipt(case):
    prepared,packet,marker=case;engine=Fake(prepared,packet,fail='register')
    M.run_prepared(prepared,backend=engine,marker=marker)
    prepared[0]['receipt_path']=str(marker.parent/'another.json')
    with pytest.raises(ValueError,match='replay'):M.run_prepared(prepared,backend=Fake(prepared,packet),marker=marker)

@pytest.mark.parametrize('change',['pid','creation','dirty','configuration','source'])
def test_owner_or_source_change_prevents_all_actions(case,change):
    prepared,packet,marker=case;engine=Fake(prepared,packet)
    if change=='pid':engine.owner=lambda:dict(alive=True,process_id=124,create_time=1000.,executable='SLDWORKS.exe')
    elif change=='creation':engine.owner=lambda:dict(alive=True,process_id=123,create_time=1001.,executable='SLDWORKS.exe')
    elif change in('dirty','configuration'):
        d=engine.document();d['needs_save'if change=='dirty'else'configuration']=True if change=='dirty'else'other'
        engine.document=lambda:d
    else:Path(prepared[0]['expected_document_path']).write_bytes(b'changed')
    result=M.run_prepared(prepared,backend=engine,marker=marker)
    assert result['status']=='error' and not engine.calls and not marker.exists()

@pytest.mark.parametrize('change',['mvid','location','request_echo','parameter','operation'])
def test_new_packet_must_match_exact_build_and_reference(case,change):
    prepared,packet,marker=case;engine=Fake(prepared,packet)
    if change=='mvid':engine.packet['host_module_version_id']=prepared[1]['mvid']
    elif change=='location':engine.packet['host_assembly_location']=prepared[1]['dll']['path']
    elif change=='request_echo':engine.packet['validated_request']['feature_setup_id']+=1
    elif change=='parameter':engine.packet['parameters'][0]['feature_native_id']+=1
    else:engine.packet['binding']['operations'].reverse()
    result=M.run_prepared(prepared,backend=engine,marker=marker)
    assert result['status']=='uncertain' and not result['readback_verified'] and engine.closed==1

@pytest.mark.parametrize('change',['machine','startup','class','tlb','interface'])
def test_registry_readback_is_exact(case,change):
    prepared,packet,marker=case;engine=Fake(prepared,packet);before=engine.registry();engine.register_once()
    after=engine.registry()
    if change=='machine':after['HKLM'][M.DISCOVERY]['']['value']=1
    elif change=='startup':after['HKCU'][M.STARTUP]={'':{'type':4,'value':1}}
    elif change=='class':after['HKCU'][M.CLASS_ROOT+'\\InprocServer32']['CodeBase']['value']='file:///C:/other.dll'
    elif change=='tlb':after['HKCU'][M.TLB_ROOT+'\\1.0\\0\\win64']['']['value']='C:/other.tlb'
    else:after['HKCU']['Software\\Classes\\Interface\\'+M.MILL_IID+'\\TypeLib']['']['value']='foreign'
    with pytest.raises(ValueError):M.verify_registry(before,after,prepared[2])

def test_wrong_old_mvid_stops_before_unload(case):
    prepared,packet,marker=case;engine=Fake(prepared,packet)
    old=engine.old_identity();old['host_module_version_id']=prepared[2]['mvid'];engine.old_identity=lambda:old
    result=M.run_prepared(prepared,backend=engine,marker=marker)
    assert result['status']=='error' and engine.calls==[] and not marker.exists()

@pytest.mark.parametrize('field',['inventory','tools','cam_configuration'])
def test_identity_probe_may_not_reach_cam(field,case):
    prepared,packet,_=case;engine=Fake(prepared,packet);r=engine.old_identity();r[field]={}
    with pytest.raises(ValueError):M.validate_old_identity(r,prepared[0],prepared[1])

def test_event_error_blocks_acceptance():
    r=events(True);r['event_count']=1
    with pytest.raises(ValueError):M.event_check(r,closed=True)


def test_bounded_history_closure_allows_current330_and_rejects513():
    values=[dict(path='C:/evidence/'+str(i)+'.json',sha256='a'*64)for i in range(330)]
    assert len(M.merge_pins(values))==330
    with pytest.raises(ValueError):M.merge_pins(values+[dict(path='C:/more/'+str(i),sha256='a'*64)for i in range(183)])

def test_existing_historical_registration_subkey_is_preserved(case):
    prepared,packet,_=case;engine=Fake(prepared,packet)
    root=M.CLASS_ROOT+'\\InprocServer32\\1.0.0.0'
    engine.reg['HKCU'][root]={'Assembly':{'type':1,'value':'historical'}}
    before=engine.registry();engine.register_once();after=engine.registry()
    assert M.verify_registry(before,after,prepared[2])['personal_class_exact']
    after['HKCU'][root]['Assembly']['value']='changed'
    with pytest.raises(ValueError):M.verify_registry(before,after,prepared[2])

def test_no_near_matching_typelib_version_is_ignored(case):
    prepared,packet,_=case;engine=Fake(prepared,packet);before=engine.registry();engine.register_once();after=engine.registry()
    after['HKCU'][M.TLB_ROOT+'\\1.01']={'x':{'type':1,'value':'unexpected'}}
    with pytest.raises(ValueError):M.verify_registry(before,after,prepared[2])

def wrapper_namespace(tmp_path):
    import ast,types,hashlib
    path=ROOT/'mcp-server/server.py';tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    names={'_cam_host_lifecycle_sealed_payload','solidworks_cam_replace_reader_host_and_read_mill'}
    assert {n.name for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names}==names
    ns=dict(SCRIPTS_DIR=str(tmp_path),SolidWorksCamHostLifecycleInput=object,
        _selected_process_id=123,_run_locked=lambda op,*a,**kw:op())
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and node.name in names:
            node.decorator_list=[]
            exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),ns)
    p=dict(process_id=123,receipt_path=str(tmp_path/'result.json'))
    for filename,field in [('sw_cam_mill_host_lifecycle.py','module_sha256'),
        ('sw_cam_mill_host_checkpoint.py','checkpoint_provider_sha256'),
        ('sw_cam_mill_packet_projection.py','projector_sha256')]:
        target=tmp_path/filename;target.write_text(filename);p[field]=hashlib.sha256(target.read_bytes()).hexdigest()
    payload=dict(action='replace_owned_host_and_read_mill',params=p)
    sealed=tmp_path/'request.json';sealed.write_text(json.dumps(payload))
    call=dict(request_path=str(sealed),request_sha256=hashlib.sha256(sealed.read_bytes()).hexdigest(),process_id=123)
    return ns,payload,sealed,call

@pytest.mark.parametrize('change',['hash','pid','module','receipt_alias'])
def test_sealed_wrapper_rejects_change(tmp_path,change):
    import hashlib
    ns,payload,sealed,call=wrapper_namespace(tmp_path)
    if change=='hash':call['request_sha256']='0'*64
    elif change=='pid':call['process_id']=124
    elif change=='module':(tmp_path/'sw_cam_mill_host_checkpoint.py').write_text('changed')
    else:
        payload['params']['receipt_path']=str(sealed);sealed.write_text(json.dumps(payload))
        call['request_sha256']=hashlib.sha256(sealed.read_bytes()).hexdigest()
    with pytest.raises(ValueError):ns['_cam_host_lifecycle_sealed_payload'](**call)

def test_wrapper_dispatch_cannot_mutate_sealed_payload(tmp_path,monkeypatch):
    import types
    ns,payload,sealed,call=wrapper_namespace(tmp_path)
    main=types.ModuleType('scripts.sw_cam_mill_host_lifecycle');provider=types.ModuleType('scripts.sw_cam_mill_host_checkpoint')
    def dispatch(request,**kwargs):
        request['params']['new_default']='inserted';return {'ok':True}
    main.dispatch_request=dispatch;provider.provide_reference=lambda p:None
    monkeypatch.setitem(sys.modules,main.__name__,main);monkeypatch.setitem(sys.modules,provider.__name__,provider)
    result=ns['solidworks_cam_replace_reader_host_and_read_mill'](types.SimpleNamespace(**call,response_format='json'))
    assert result=={'ok':True} and json.loads(sealed.read_text())==payload


@pytest.mark.parametrize('field,value',[('vtable_offset',48),('return_vt',8),('callconv',3),('parameter_count',1),('memid',2)])
def test_raw_abi_rejects_wrong_slot_type_or_signature(field,value):
    shape=dict(typekind=3,function_count=1,memid=1,invkind=1,funckind=1,callconv=4,
        vtable_offset=56,parameter_count=2,optional_count=0,return_vt=25,
        arguments=[dict(vt=8,pointee_vt=None,flags=1),dict(vt=26,pointee_vt=8,flags=10)])
    M.checked_host_abi(shape);shape[field]=value
    with pytest.raises(ValueError):M.checked_host_abi(shape)

@pytest.mark.parametrize('hresult',[0,-2147319780])
def test_native_registration_backend_is_personal_and_fail_closed(case,monkeypatch,hresult):
    import types,ctypes
    prepared,_,_=case;p,old,new,ref,_=prepared;backend=M.NativeBackend(p,old,new,ref)
    writes=[]
    class Key:
        def __init__(self,path):self.path=path
        def __enter__(self):return self
        def __exit__(self,*args):pass
    fake=types.ModuleType('winreg');fake.HKEY_CURRENT_USER=1;fake.KEY_WRITE=2;fake.KEY_WOW64_64KEY=256;fake.REG_SZ=1
    fake.CreateKeyEx=lambda hive,path,*args:(writes.append(('key',hive,path))or Key(path))
    fake.SetValueEx=lambda key,name,unused,kind,value:writes.append(('value',key.path,name,kind,value))
    monkeypatch.setitem(sys.modules,'winreg',fake)
    class Api:
        def __call__(self,pointer,path,helpdir):
            assert pointer.value==42 and path==new['tlb']['path'] and helpdir is None
            return hresult
    monkeypatch.setattr(M.ctypes,'WinDLL',lambda name:types.SimpleNamespace(RegisterTypeLibForUser=Api()))
    monkeypatch.setattr(M,'type_library',lambda path,**kw:(ctypes.c_void_p(42),None,None))
    if hresult:
        with pytest.raises(ValueError):backend.register_once()
        assert writes==[]
    else:
        result=backend.register_once();assert result['typelib_hresult']==0
        assert all(row[1]==1 for row in writes if row[0]=='key')
        assert all(row[2].startswith('Software\\Classes\\')for row in writes if row[0]=='key')
        assert any('\\1.0.1.0'in row[2]for row in writes if row[0]=='key')

