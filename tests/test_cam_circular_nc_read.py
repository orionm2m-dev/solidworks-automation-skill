from contextlib import nullcontext
from copy import deepcopy
from ctypes import cast,POINTER,c_double,c_short
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from scripts import sw_cam_circular_nc_read as m


def owner(result=0,number=2.,flag=0):
    def call(a,b):
        if number is not None:cast(a,POINTER(c_double))[0]=number
        if flag is not None:cast(b,POINTER(c_short))[0]=flag
        return result
    return SimpleNamespace(_ICWNCParam__com_GetLeadinFeedrate=call)


@pytest.mark.parametrize('flag,expected',[(0,False),(-1,True)])
def test_owned_lead_pointer_populates_exact_pair(flag,expected):
    d={};r=m.lead_pointer_value(owner(flag=flag),d)
    assert r==dict(value_native=2.,is_percent=expected,physical_units_verified=False)
    assert d['returned'] and d['outputs_validated'] and d['hresult']==0


@pytest.mark.parametrize('kwargs',[{'result':True},{'result':1},{'result':None},{'number':None},{'number':float('nan')},{'flag':None},{'flag':1}])
def test_pointer_failure_is_not_a_default_or_retry(kwargs):
    d={}
    with pytest.raises(ValueError):m.lead_pointer_value(owner(**kwargs),d)
    assert d['attempted'] and d['returned'] and not d.get('outputs_validated')


@pytest.fixture
def lifecycle(tmp_path,monkeypatch):
    v=dict(process_id=123,expected_process_create_time=1.25,expected_document_path=str(tmp_path/'p.sldprt'),expected_source_sha256='a'*64,reconciliation_path='review.json',reconciliation_sha256='c'*64,operation_native_id=361,receipt_path=str(tmp_path/'out.json'),qualification_only=True,message_policy='vendor_default')
    doc=dict(path=v['expected_document_path'],title='p',type=1,needs_save=False)
    loaded=dict(state={'document':doc},pins=[],receipt=Path(v['receipt_path']))
    monkeypatch.setattr(m,'validate',lambda x:loaded);monkeypatch.setattr(m,'preflight',lambda x:({},{}));monkeypatch.setattr(m,'solidworks_operation_lock',lambda **x:nullcontext());monkeypatch.setattr(m,'_process_identity',lambda x:dict(alive=True,process_id=123,create_time=1.25,executable='C:/sldworks.exe'));monkeypatch.setattr(m,'document_snapshot',lambda x:deepcopy(doc));monkeypatch.setattr(m,'_file_hash',lambda p:'a'*64);monkeypatch.setattr(m,'_typed',lambda obj,*x:obj)
    state=dict(mode=None,captures=0,native=[],runtime_calls=0)
    def member(obj,name,*args):
        state['native'].append(name)
        if name=='GetProcessID':return 123
        if name in ('GetAddInObject','GetCWApp'):return object()
        raise AssertionError('Unexpected native member '+name)
    monkeypatch.setattr(m,'_member',member)
    class Session:
        def __init__(self,*x):self.active=False;self.closed=False
        def __enter__(self):self.active=True;return self
        def __exit__(self,*x):self.active=False;self.closed=True
        def summary(self):return dict(subscribed=True,active=self.active,disconnected=self.closed,event_count=1 if state['mode']=='event' else 0,overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=['bad'] if self.closed and state['mode']=='cleanup' else [])
    monkeypatch.setattr(m,'CamMessageSession',Session)
    def capture(app,loaded,v,read,typed,pointer,boundary):
        boundary();state['captures']+=1
        if state['mode']=='runtime':raise RuntimeError('runtime changed')
        if state['mode']=='source' and state['captures']==2:monkeypatch.setattr(m,'_file_hash',lambda p:'b'*64)
        boundary();return dict(capture_complete=True,value=3 if state['mode']=='mismatch' and state['captures']==2 else 2)
    monkeypatch.setattr(m,'capture',capture)
    def check():state['runtime_calls']+=1
    return v,state,check


def test_two_reads_clean_scope_and_durable_result(lifecycle):
    v,s,check=lifecycle;r=m.run_read(object(),'cls','tlb',runtime_check=check,**v)
    assert r['readback_verified'] and r['source_unchanged'] and r['runtime_unchanged'] and s['captures']==2
    assert r['before']==r['after'] and not any(r[k] for k in ('mutation_attempted','save_attempted','GTP_attempted','parameter_setter_attempted'))
    assert json.loads(Path(v['receipt_path']).read_text(encoding='utf-8'))==r
    assert set(s['native'])<={'GetProcessID','GetAddInObject','GetCWApp'}


@pytest.mark.parametrize('mode',['event','cleanup','source','mismatch','runtime'])
def test_guard_failure_does_not_promote_result(lifecycle,mode):
    v,s,check=lifecycle;s['mode']=mode;r=m.run_read(object(),'cls','tlb',runtime_check=check,**v)
    assert r['status']=='error' and not r['readback_verified'] and not r['runtime_unchanged']
    assert not r['mutation_attempted'] and not r['save_attempted'] and not r['GTP_attempted']


def test_only_fixed_getters_no_mutation_entry():
    assert not any(x.startswith('Set') or x in ('Save','GTP','GOP') for x in m.GETTERS)
    assert m.MAX_READS==1024


def graph():
    nc=dict(GetSpndlSpeed=200.,GetCNCComp=0,GetTlpComp=1,GetClrPlaneUseSetupStatus=False,GetRpdPlaneUseSetupStatus=False,GetRetractType=0,XYFeed=1000.,GetSpeedFeedMethod=0,LinkToTool=False,GetIsLockSpindleSpeed=False,GetZFeedrate2=(2.,False),GetLeadinFeedratePercent=2.)
    ops=[];expected=[]
    for i in range(26):
        oid=361 if i==25 else 100+i;counts=[11158 if i==25 else 10] if i<18 or i==25 else []
        ops.append(dict(native_id=oid,Suppressed=False,GetIsToolpathGenerated=bool(counts),IGetEnumToolpaths=[dict(RecordCount=x) for x in counts]))
        expected.append(dict(native_id=oid,setup_native_id=94,suppressed=False,toolpath_generated=bool(counts),toolpath_record_counts=counts))
    ops[-1].update(IGetAllFeatures=[dict(native_id=359)],IGetTool=dict(native_id=249),IGetNCParam=nc)
    setup=dict(native_id=94,IGetEnumOperations=ops);doc=dict(IGetMachine=dict(MachType=1,IGetEnumOpSetups=[setup]));doc['GetCWObjectID']=lambda x:(x['native_id'],True)
    app=dict(IGetActiveDoc=doc);loaded=dict(state=dict(operations=expected),target=dict(linked_feature_ids=[359],assigned_tool=dict(native_id=249)))
    counter=[0]
    def read(obj,name,*args):
        counter[0]+=1
        if name=='Count':return len(obj)
        if name=='Item':return obj[args[0]]
        v=obj[name];return v(*args) if callable(v) else v
    def typed(obj,name):counter[0]+=1;return obj
    def pointer(obj,name,item):counter[0]+=1;item['returned']=True;return dict(value_native=2.,is_percent=False) if name=='leadin' else dict(distance_native=5.,basis_raw=0)
    return app,loaded,dict(operation_native_id=361),read,typed,pointer,lambda:None,counter,ops,nc


def test_actual_cheap_capture_26_operations_19_paths_and_two_target_reads_under_budget():
    g=graph();a=m.capture(*g[:7]);b=m.capture(*g[:7]);assert a==b and len(a['inventory'])==26 and sum(x['toolpath_generated'] for x in a['inventory'])==19
    assert g[7][0]<m.MAX_READS and a['feature_ids']==[359] and a['tool_native_id']==249
    assert a['nc']['leadin_feed']==dict(value_native=2.,is_percent=False)


@pytest.mark.parametrize('change',[lambda g:g[8][0].update(GetIsToolpathGenerated=False),lambda g:g[8][0]['IGetEnumToolpaths'][0].update(RecordCount=11),lambda g:g[8][-1].update(IGetAllFeatures=[dict(native_id=999)]),lambda g:g[8][-1].update(IGetTool=dict(native_id=888)),lambda g:g[9].update(GetSpeedFeedMethod=True),lambda g:g[9].update(GetSpeedFeedMethod=9),lambda g:g[9].update(GetZFeedrate2=(2.,1))])
def test_actual_capture_rejects_mismatched_inventory_target_and_nc_shapes(change):
    g=graph();change(g)
    with pytest.raises(ValueError):m.capture(*g[:7])


def test_absolute_feed_mode_is_not_replaced_by_inactive_percent_field():
    g = graph()
    g[9].update(GetLeadinFeedratePercent=30., LinkToTool=True)
    result = m.capture(*g[:7])
    assert result['nc']['leadin_feed'] == dict(value_native=2., is_percent=False)
    assert result['nc']['GetLeadinFeedratePercent'] == 30.
    assert result['nc']['LinkToTool'] is True
    assert result['nc']['GetZFeedrate2'] == [2., False]
