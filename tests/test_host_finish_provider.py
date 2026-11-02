"""Offline compatibility checks for the actual completed checkpoint pin schema."""
import ast,os
from pathlib import Path
from types import SimpleNamespace
import pytest
from cam_public_test_support import add_runtime, required_module
ROOT=add_runtime()
MODULE=Path(required_module('sw_cam_mill_host_checkpoint').__file__)
def functions():
    tree=ast.parse(MODULE.read_text(encoding='utf-8-sig'));ns={'Path':Path}
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef)],type_ignores=[]),str(MODULE),'exec'),ns);return ns
def require(condition,message):
    if not condition:raise ValueError(message)
def reader():return SimpleNamespace(require=require,key=lambda p:str(Path(p)).casefold())
def test_current_authority_import_is_exact():
    tree=ast.parse(MODULE.read_text(encoding='utf-8-sig'))
    imports=[n for n in tree.body if isinstance(n,ast.ImportFrom)and any(a.asname=='authority'for a in n.names)]
    assert len(imports)==1 and [(a.name,a.asname)for a in imports[0].names]==[('sw_cam_mixed_root_finish','authority')]
def setup_provider(tmp_path):
    ns=functions();path=tmp_path/'saved.json';path.write_bytes(b'0123456789');sealed=dict(path=str(path),sha256='1'*64,bytes=10)
    loaded=dict(root_pocket_checkpoint_pin={k:sealed[k]for k in ('path','sha256')});calls=[]
    def loader(path,digest,*,check_current):calls.append((path,digest,check_current));return loaded
    ns.update(__file__='provider.py',reader=reader(),authority=SimpleNamespace(__file__='producer.py',load_completed=loader,common=SimpleNamespace(_pin=lambda p:{'path':p})),reference_from_loaded=lambda value,pin:{'pins':[],'same':value is loaded})
    return ns,sealed,loaded,calls
def test_exact_current_authority_two_field_loaded_pin_and_three_field_seal(tmp_path):
    ns,sealed,loaded,calls=setup_provider(tmp_path);result=ns['provide_reference'](sealed)
    assert calls==[(sealed['path'],'1'*64,True)]
    assert result=={'pins':[{'path':'provider.py'},{'path':'producer.py'}],'same':True,'provider_pin':{'path':'provider.py'}}
@pytest.mark.parametrize('size',[11,True,0])
def test_wrong_byte_size_rejected(tmp_path,size):
    ns,sealed,_,_=setup_provider(tmp_path);sealed['bytes']=size
    with pytest.raises(ValueError,match='byte size'):ns['provide_reference'](sealed)
def test_wrong_loaded_pin_rejected_before_projection(tmp_path):
    ns,sealed,loaded,_=setup_provider(tmp_path);loaded['root_pocket_checkpoint_pin']['sha256']='2'*64
    ns['reference_from_loaded']=lambda *a:pytest.fail('Wrong checkpoint projected')
    with pytest.raises(ValueError,match='identity differs'):ns['provide_reference'](sealed)
def test_failed_current_authority_has_no_fallback():
    ns=functions();calls=[]
    def fail(*a,**k):calls.append((a,k));raise ValueError('Current authority rejected')
    ns.update(reader=reader(),authority=SimpleNamespace(load_completed=fail))
    with pytest.raises(ValueError,match='authority rejected'):ns['provide_reference'](dict(path='saved.json',sha256='1'*64,bytes=10))
    assert len(calls)==1
def test_no_native_calls_added():
    tree=ast.parse(MODULE.read_text(encoding='utf-8-sig'))
    calls={n.func.attr for n in ast.walk(tree)if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)}
    assert not calls.intersection({'Save','SaveActiveDocument','GenerateToolpath','CreateMillFeature2','SetTool','LoadAddIn','UnloadAddIn'})