"""Saved deep authority and actual constructor/callable contracts; no live CAD."""
from copy import deepcopy
from pathlib import Path
from types import ModuleType
import ast,importlib.util,inspect,os,sys
import pytest
R=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).resolve().parents[1]))).resolve()
sys.path.insert(0,str(R));import scripts
scripts.__path__.insert(0,os.environ.get('SW_CAM_DEEP_CHECKPOINT_MODULE_ROOT',str(R/'scripts')))
from scripts import sw_cam_deep_guide_checkpoint as m
from scripts import sw_cam_deep_guide_reopen as reopen
from scripts import sw_cam_deep_guide_wip as wip


def targets():
    return [dict(operation_native_id=401+2*i,feature_native_id=f,operation_type=k,key='guide'+str(f)+('_rough'if k==0 else'_finish'),
      reference_nc={'GetCNCComp':0,'GetTlpComp':1})for i,(f,k)in enumerate(m.writer.PAIRS)]


def actions():
    rows=targets();base=dict(status='verified',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,native_return=m.group.return_observation(0))
    r={'actions':{},'after_tools':{'parameters':[]}}
    for t in rows:r['actions']['insert:'+t['key']]=dict(base,returned_interface_pointer=True,actual_native_id=t['operation_native_id'])
    for t in rows:r['actions']['SetTool:'+str(t['operation_native_id'])]=deepcopy(base)
    for t in rows:
        oid=t['operation_native_id'];r['after_tools']['parameters'].append(dict(operation_native_id=oid,nc={'feeds_compensation':{'GetCNCComp':1,'GetTlpComp':1}}))
        for spec in m.writer.config.ROUGH_FIELDS if t['operation_type']==0 else m.writer.config.FINISH_FIELDS:
            r['actions'][str(oid)+':'+spec[0]]=dict(base,attempted=False,returned=False,observed={'already_satisfied':True})
        r['actions']['CNC0:'+str(oid)]=deepcopy(base)
    for t in rows:r['actions']['GTP:'+str(t['operation_native_id'])]=deepcopy(base)
    r['actions']['SaveActiveDocument']=deepcopy(base)
    return r,rows


def test_complete_dynamic_action_order():
    r,t=actions();assert m.action_contract(r,t)==[401,403,405,407]


@pytest.mark.parametrize('bad',['missing','reordered','extra','pending','failed','no_id','wrong_id','boolean_return','skipped_save','altered_tlp','duplicate_id','shallow_id'])
def test_action_receipts_refuse_partial_rebound_or_unknown_dispatch(bad):
    r,t=actions()
    if bad=='missing':r['actions'].pop('GTP:407')
    if bad=='reordered':r['actions']=dict(reversed(list(r['actions'].items())))
    if bad=='extra':r['actions']['GTP:409']=deepcopy(r['actions']['GTP:407'])
    if bad=='pending':r['actions']['GTP:407']['native_dispatch_pending']=True
    if bad=='failed':r['actions']['GTP:407']['status']='returned'
    if bad=='no_id':r['actions']['insert:guide80_rough'].pop('actual_native_id')
    if bad=='wrong_id':r['actions']['insert:guide80_rough']['actual_native_id']=777
    if bad=='boolean_return':r['actions']['SaveActiveDocument']['native_return']['value']=False
    if bad=='skipped_save':r['actions']['SaveActiveDocument'].update(attempted=False,returned=False,observed={'already_satisfied':True})
    if bad=='altered_tlp':r['after_tools']['parameters'][0]['nc']['feeds_compensation']['GetTlpComp']=0
    if bad=='duplicate_id':t[-1]['operation_native_id']=401
    if bad=='shallow_id':t[0]['operation_native_id']=322
    with pytest.raises(ValueError):m.action_contract(r,t)


def test_actual_parameter_constructor_preserves_module_and_all_read_calls():
    loaded={'guide_parameters':{'document':{}},'deep_targets':targets()}
    b=m.ParameterBackend(loaded,{},object(),'metadata-only','metadata-only',{},lambda:None)
    assert isinstance(b.capture,ModuleType)and callable(b.capture.cone._bootstrap)
    assert b.learned==targets() and b.learned is not loaded['deep_targets']
    for name in ('capture_snapshot','capture_parameters','capture_binding','batch','boundary','configuration','start','finish','close','events','persist'):
        assert callable(getattr(b,name)),name
    for name,value in vars(b).items():
        assert not(callable(getattr(type(b),name,None))and not callable(value)),name
    assert not any(hasattr(b,n)for n in ('save','generate','assign','set_field','set_nc','insert'))


def test_actual_lifecycle_constructor_has_no_method_shadow_and_all_engine_calls_callable():
    b=reopen.NativeBackend({}, {},object(),'metadata-only','metadata-only',{},lambda:None)
    tree=ast.parse(inspect.getsource(reopen.reopen.run_backend))
    calls={n.func.attr for n in ast.walk(tree)if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and isinstance(n.func.value,ast.Name)and n.func.value.id=='backend'}
    assert {'start','capture_binding','capture_parameters','finish'}<=calls
    assert all(callable(getattr(b,n,None))for n in calls)
    assert not any(callable(getattr(type(b),n,None))and not callable(v)for n,v in vars(b).items())


def test_actual_readonly_parameter_alias_requests_full_eight_parameters(monkeypatch):
    b=m.ParameterBackend({'guide_parameters':{'document':{}},'deep_targets':targets()}, {},object(),'metadata-only','metadata-only',{},lambda:None)
    calls=[];monkeypatch.setattr(b,'capture_snapshot',lambda *a,**k:calls.append((a,k))or{'full':True})
    assert b.capture_parameters('after')=={'full':True}
    assert calls==[(('after',),{'full':True})]


@pytest.mark.parametrize('bad',['scope','module','status','phase','issue','model_saved','continuation_ready','pending','replayed','rollback','already_reopened'])
def test_incomplete_packet_refused_before_reading_history(monkeypatch,bad):
    r=dict(scope=m.writer.SCOPE,module_pin=m.common._pin(m.writer.__file__),status='saved_deep_guides_review_required',phase='finished',
      readback_verified=True,model_saved=True,continuation_ready=True,save_attempted=True,GTP_attempted=True,SetTool_attempted=True,operation_creation_attempted=True,
      native_dispatch_pending=False,automatic_retry=False,automatic_rollback=False,persistence_after_reopen_verified=False)
    if bad=='scope':r['scope']='wrong'
    elif bad=='module':r['module_pin']['sha256']='f'*64
    elif bad=='status':r['status']='uncertain'
    elif bad=='phase':r['phase']='saving'
    elif bad=='issue':r['issue']={}
    elif bad=='pending':r['native_dispatch_pending']=True
    elif bad=='replayed':r['automatic_retry']=True
    elif bad=='rollback':r['automatic_rollback']=True
    elif bad=='already_reopened':r['persistence_after_reopen_verified']=True
    else:r[bad]=False
    monkeypatch.setattr(m,'read_pin',lambda *a:pytest.fail('Uncertain packet must not read historical authority'))
    with pytest.raises(ValueError):m.completed_packet(r,{})


def test_historical_loader_does_not_reuse_old_current_source_loader():
    tree=ast.parse(inspect.getsource(m.completed_packet))
    assert not any(isinstance(n,ast.Attribute)and n.attr=='load_checkpoint'for n in ast.walk(tree))
    assert 'load_zero_attempt'in {n.attr for n in ast.walk(tree)if isinstance(n,ast.Attribute)}


@pytest.mark.parametrize('failed',[False,True])
def test_reused_close_open_protocol_exports_and_rejects_changed_cl(tmp_path,failed):
    spec=importlib.util.spec_from_file_location('existing_reopen_tests',R/'tests/test_guide_group_reopen.py')
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    expected={'binding':{'operations':[{'native_id':i}for i in list(m.inspect.ORDER)+[401,403,405,407]]},'parameters':[{'saved':i}for i in range(8)]}
    b=old.Fake(expected);loaded={'guide_parameters':{'expected_parameters':expected,'baseline':expected['binding']}}
    r=dict(scope=reopen.SCOPE,source_path='synthetic.SLDPRT',source_sha256='b'*64,deep_checkpoint_pin={'path':'saved.json','sha256':'c'*64})
    j=reopen.Journal(r,tmp_path/'receipt.json',tmp_path/'marker.json')
    def finish():
        b.trace.append('export14')
        if failed:raise ValueError('Complete CL changed')
        r['cl_persistence_verified']=True
    b.finish=finish;result=reopen.reopen.run_backend(b,j,loaded)
    assert b.trace.count('native_close')==b.trace.count('native_open')==1
    assert result['persistence_after_reopen_verified']is(not failed)
    assert not result['save_attempted']and not result['GTP_attempted']
    with pytest.raises(ValueError):reopen.reopen.run_backend(b,j,loaded)
