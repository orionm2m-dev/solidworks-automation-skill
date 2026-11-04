from copy import deepcopy
from types import SimpleNamespace
import importlib
import pytest
from test_sw_cam_turn_variable_allowance import env
from scripts import sw_cam_turn_variable_allowance as base
from scripts import sw_cam_turn_post_parameter_probe as m

@pytest.fixture
def probe(env,monkeypatch):
    for name in ['CamMessageSession','solidworks_operation_lock','_member','_typed','document_snapshot','_context','_inventory','_items','_object_id','_file_hash']:
        monkeypatch.setattr(m,name,getattr(base,name))
    env['process']=dict(alive=True,process_id=123,create_time=100.25,executable=r'C:\bin\SLDWORKS.exe')
    monkeypatch.setattr(m,'_process_identity',lambda pid:deepcopy(env['process']))
    monkeypatch.setattr(m,'_abi',lambda path:dict(getter_count=2,native_calls=0))
    env['inventory']['operations']=[dict(setup_index=0,operation_index=0,toolpath_generated=True,toolpath_record_counts=[40])]
    env['machine']['GetNumPostParam']=3
    env['raw']=('X parameter','0.1',True);env['indices']=[]
    def zero(index):env['indices'].append(index);return env['raw']
    env['machine']['GetPostParam']=zero
    env['args']=dict(process_id=123,expected_process_create_time=100.25,expected_document_path=r'C:\review\part.SLDPRT',expected_source_sha256='a'*64,
        expected_operation_count=1,expected_generated_operation_count=1,expected_total_record_count=40,
        action='probe_index_zero',qualification_only=True,message_policy='vendor_default')
    env['run']=lambda **kw:m.probe_turn_post_parameter(env['sw'],'clsid','fixture.tlb',**dict(env['args'],**kw))
    return env


def test_single_count_single_index_no_semantic_or_catalog_claim(probe):
    r=probe['run']()
    assert r['status']=='review_required' and r['observation_verified'] and r['guards_verified']
    assert r['index_zero_acceptance_verified'] and r['before']==r['after']
    assert r['entry_raw']==dict(index=0,name='X parameter',value='0.1')
    assert probe['indices']==[0] and probe['calls'].count('GetNumPostParam')==1 and probe['calls'].count('GetPostParam')==1
    assert r['native_parameter_call_count']==2 and r['messages']['disconnected']
    assert all(r[k] is False for k in ['readback_verified','catalog_complete','zero_based_catalog_verified','preset_values_verified','units_verified','mutation_attempted','model_saved','GTP_attempted','GOP_attempted','production_qualified'])
    assert not any(x.startswith('Set') or x in ['GetController','GetControllerParameters','GenerateToolpath','Save3','IGetTool','GetAllVariableAllowances','GetPostOptionParamList'] for x in probe['calls'])


def test_zero_count_never_gets_index(probe):
    probe['machine']['GetNumPostParam']=0;r=probe['run']()
    assert r['status']=='review_required' and r['observation_verified']
    assert r['reason']=='NATIVE_POST_PARAMETER_COUNT_ZERO' and not r['index_zero_acceptance_verified']
    assert 'GetPostParam' not in r and not probe['indices'] and r['native_parameter_call_count']==1


def test_false_found_preserves_raw_diagnostic_without_interpreting_outs(probe):
    probe['raw']=(None,42,False);r=probe['run']()
    assert r['status']=='review_required' and r['observation_verified']
    assert r['index_zero_found_native'] is False and 'entry_raw' not in r
    assert r['reason']=='INDEX_ZERO_NOT_FOUND' and probe['indices']==[0]
    assert r['GetPostParam']['converted_output_shape']['items'][1]['value']==42

@pytest.mark.parametrize('count',[True,-1,513,3.,None,'3',float('inf')])
def test_invalid_count_never_reads_index(probe,count):
    probe['machine']['GetNumPostParam']=count;r=probe['run']()
    assert r['status']=='error' and not probe['indices'] and r['native_parameter_call_count']==1
    assert r['GetNumPostParam']['returned'] and not r['observation_verified']

@pytest.mark.parametrize('raw',[None,(),('x','1'),('x','1',1),('x','1',True,0),(None,'1',True),('x',1,True),('x'*1001,'1',True),('x','1'*1001,True)])
def test_invalid_found_shape_retained_and_never_retried(probe,raw):
    probe['raw']=raw;r=probe['run']()
    assert r['status']=='error' and not r['observation_verified'] and probe['indices']==[0]
    assert r['GetPostParam']['returned'] and 'converted_output_shape' in r['GetPostParam']

@pytest.mark.parametrize('method',['GetNumPostParam','GetPostParam'])
def test_exception_stops_probe_no_retry_no_followup_CAM(probe,method):
    def fail(*args):raise OSError('unsupported getter')
    probe['machine'][method]=fail;r=probe['run']()
    assert r['status']=='error' and probe['calls'].count(method)==1 and probe['calls'][-1]==method
    assert r[method]['attempted'] and not r[method]['returned'] and r['messages']['disconnected']
    if method=='GetNumPostParam':assert 'GetPostParam' not in probe['calls']

@pytest.mark.parametrize('method',['GetNumPostParam','GetPostParam'])
def test_return_then_event_keeps_raw_shape_stops_all_CAM(probe,method):
    def hook(name):
        if name==method:probe['session'].state['event_count']=1
    probe['hook']=hook;r=probe['run']()
    assert r['status']=='error' and probe['calls'][-1]==method and probe['calls'].count(method)==1
    assert r[method]['returned'] and 'converted_output_shape' in r[method]
    assert not r['observation_verified'] and r['messages']['disconnected']

@pytest.mark.parametrize('field,value',[
 ('process_id',True),('expected_process_create_time',True),('expected_process_create_time',float('nan')),
 ('expected_process_create_time',0),('expected_document_path','relative.SLDPRT'),('expected_source_sha256','Z'*64),
 ('expected_operation_count',True),('expected_operation_count',513),('expected_generated_operation_count',2),
 ('expected_total_record_count',-1),('action','read'),('action','apply'),('qualification_only',1),('qualification_only',False),('message_policy','auto_accept')])
def test_bad_admission_no_calls(probe,field,value):
    r=probe['run'](**{field:value});assert r['status']=='error' and not probe['calls']

@pytest.mark.parametrize('field,value',[('alive',False),('process_id',124),('create_time',101),('executable','other.exe')])
def test_lifetime_wrong_before_bootstrap(probe,field,value):
    probe['process'][field]=value;r=probe['run']();assert r['status']=='error' and not probe['calls']

@pytest.mark.parametrize('kind',['source','document','pid','machine','counts'])
def test_actual_gate_before_probe(probe,kind):
    if kind=='source':probe['digest']='b'*64
    elif kind=='document':probe['args']['expected_document_path']=r'C:\review\other.SLDPRT'
    elif kind=='pid':probe['sw']['GetProcessID']=124
    elif kind=='machine':probe['inventory']['machine_type']=2
    else:probe['args']['expected_total_record_count']=41
    r=probe['run']();assert r['status']=='error' and 'GetNumPostParam' not in probe['calls']

@pytest.mark.parametrize('kind',['id','inventory','source','dirty','process'])
def test_after_probe_drift_preserves_returned_entry_rejects_success(probe,kind):
    def hook(name):
        if name!='GetPostParam':return
        if kind=='id':probe['operation']['native_id']+=1
        elif kind=='inventory':probe['inventory']['feature_count']+=1
        elif kind=='source':probe['digest']='b'*64
        elif kind=='dirty':probe['dirty']=True
        else:probe['process']['create_time']+=1
    probe['hook']=hook;r=probe['run']()
    assert r['status']=='error' and not r['observation_verified'] and not r['index_zero_acceptance_verified']
    assert r['entry_raw']['value']=='0.1' and r['GetPostParam']['returned']
    assert probe['indices']==[0]


def test_preexisting_dirty_preserved(probe):
    probe['dirty']=True;r=probe['run']();assert r['observation_verified'] and r['unsaved_memory_present']


def test_exact_installed_metadata_only(monkeypatch):
    mod=importlib.import_module('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0')
    monkeypatch.setattr(m,'_interface_class',lambda name,path:getattr(mod,name))
    assert m._abi('no-CAD')['getter_count']==2

@pytest.mark.parametrize('defect',['iid','name','dispid','flags','type','retval','duplicate','property'])
def test_corrupt_ABI_rejected(monkeypatch,defect):
    from ctypes import HRESULT,POINTER,c_int,c_double
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes import BSTR
    methods=[SimpleNamespace(name='GetNumPostParam',restype=HRESULT,idlflags=(27,),argtypes=(POINTER(c_int),),paramflags=((10,'c'),)),
        SimpleNamespace(name='GetPostParam',restype=HRESULT,idlflags=(28,),argtypes=(c_int,POINTER(BSTR),POINTER(BSTR),POINTER(VARIANT_BOOL)),paramflags=((1,'i'),(2,'n'),(2,'v'),(10,'f')))]
    cls=SimpleNamespace(_iid_=m._IID,_methods_=methods)
    if defect=='iid':cls._iid_='wrong'
    elif defect=='name':methods[0].name='Wrong'
    elif defect=='dispid':methods[0].idlflags=(28,)
    elif defect=='flags':methods[1].paramflags=((2,'i'),(2,'n'),(2,'v'),(10,'f'))
    elif defect=='type':methods[0].argtypes=(POINTER(c_double),)
    elif defect=='retval':methods[0].restype=c_int
    elif defect=='property':methods[0].idlflags=(27,'propget')
    else:methods.append(methods[0])
    monkeypatch.setattr(m,'_interface_class',lambda *args:cls)
    with pytest.raises(ValueError):m._abi('no-CAD')
