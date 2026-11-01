from pathlib import Path
from copy import deepcopy
from types import ModuleType
import ast,importlib,inspect,json,os,sys
import pytest
R=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).resolve().parents[1]))).resolve();sys.path.insert(0,str(R));import scripts
importlib.import_module('scripts.sw_cam_deep_guide_preflight')
C=Path(os.environ.get('SW_CAM_DEEP_GUIDE_MODULE_ROOT',str(R/'scripts'))).resolve();scripts.__path__.insert(0,str(C))
m=importlib.import_module('scripts.sw_cam_deep_guide_group')

def test_actual_constructor_preserves_bootstrap_module_and_callable_methods():
    backend=m.NativeBackend({'guide_parameters':{'document':{}}},{},object(),'metadata-only','metadata-only',{},lambda:None)
    assert isinstance(backend.capture,ModuleType)
    assert callable(backend.capture.cone._bootstrap)
    assert callable(backend.capture_snapshot)
    tree=ast.parse(inspect.getsource(m.run_backend))
    names={n.func.attr for n in ast.walk(tree)if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and isinstance(n.func.value,ast.Name)and n.func.value.id=='backend'}
    assert 'capture_snapshot'in names and 'capture'not in names
    assert all(callable(getattr(backend,name))for name in names),names
    collisions=[name for name,value in vars(backend).items()if callable(getattr(type(backend),name,None))and not callable(value)]
    assert collisions==[]

@pytest.fixture
def failure():
    root=os.environ.get('SW_CAM_DEEP_GUIDE_EVIDENCE_ROOT')
    if not root:pytest.skip('Optional exact failed receipt fixture requires SW_CAM_DEEP_GUIDE_EVIDENCE_ROOT')
    E=Path(root)/'failed_before_mutation';r=json.loads((E/'ACTUAL_FAILED_NATIVE.json').read_text(encoding='utf-8'));req=json.loads((E/'REQUEST.json').read_text(encoding='utf-8'))
    p=deepcopy(r['request']);p['module_sha256']='f'*64
    archived={'path':str(E/'WRITER.py'),'sha256':r['module_pin']['sha256']}
    return r,p,{'ownership':deepcopy(r['ownership']),'deep_plan':deepcopy(r['plan'])},archived,req

def test_only_archived_failed_writer_pin_is_retired(failure,monkeypatch):
    args=failure;checked=[];monkeypatch.setattr(m.common,'_check',lambda rows:checked.extend(rows))
    pins=m.verify_zero_attempt(*args)
    assert args[3]in pins
    assert not any(m.common._key(x['path'])==m.common._key(args[0]['module_pin']['path'])for x in checked)
    assert len(checked)==len(args[0]['live_pins'])+len(args[0]['checkpoint_pins'])-1

@pytest.mark.parametrize('damage',['attempt','action','capture','export','cleanup','events','phase','issue','location','owner','source','archive','same_code','request','choices','plan','two_retired'])
def test_uncertain_failure_never_authorizes_retry(failure,monkeypatch,damage):
    r,p,l,a,q=failure;monkeypatch.setattr(m.common,'_check',lambda rows:None)
    if damage=='attempt':r['native_call_attempted']=True
    elif damage=='action':r['actions']={'unknown':{}}
    elif damage=='capture':r['captures']=[]
    elif damage=='export':r['cl_exports']={}
    elif damage=='cleanup':r['cleanup_session_active']=True
    elif damage=='events':r['messages']['event_count']=1
    elif damage=='phase':r['failed_phase']='SetTool'
    elif damage=='issue':r['issue']['type']='ValueError'
    elif damage=='location':r['issue']['locations'][0]['line']=238
    elif damage=='owner':l['ownership']['create_time']+=1
    elif damage=='source':p['expected_source_sha256']='a'*64
    elif damage=='archive':a['path']=r['module_pin']['path']
    elif damage=='same_code':p['module_sha256']=a['sha256']
    elif damage=='request':q['params']['process_id']+=1
    elif damage=='choices':p['choices']['guide80_rough']['default_operation_id']=135
    elif damage=='plan':l['deep_plan']['maximum_Save']=2
    elif damage=='two_retired':r['checkpoint_pins'].append(deepcopy(next(x for x in r['checkpoint_pins']if m.common._key(x['path'])==m.common._key(r['module_pin']['path']))))
    with pytest.raises(ValueError):m.verify_zero_attempt(r,p,l,a,q)
