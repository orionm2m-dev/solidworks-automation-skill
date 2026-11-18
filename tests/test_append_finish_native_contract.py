"""Exercise the real callback contract, with no COM objects or application calls."""
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
import os,sys
import pytest
RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]));sys.path.insert(0,str(RUNTIME));import scripts
STAGE=Path(__file__).resolve().parents[1]
if(STAGE/'scripts').is_dir():scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_append_finish_definitions as c

class Obj:
    def __init__(self,oid):self.oid=oid

@pytest.fixture
def native_stub(monkeypatch):
    trace=[];doc=Obj(999);feature=Obj(9);anchor=Obj(10);result=Obj(11);header=dict(native_id=9,suppressed=False)
    ctx=c.AppendContext.__new__(c.AppendContext);ctx.native={'doc':doc};ctx.added_rows=[];ctx.append_plan={'state':dict(target_header=header,reference_header={'native_id':8},operations=[{'native_id':10}],features=[{'geometry':{'native_id':9}}],operation_setups=[{'native_id':2}],feature_setups=[{'native_id':1}])}
    row=dict(role='floor',feature_native_id=9,feature_owner_setup_native_id=1,operation_setup_native_id=2,default_operation_name='Named floor',default_operation_id=146,expected_bottom_finish=True)
    class Guard:
        def __enter__(self):trace.append('guard_enter');return self
        def __exit__(self,*a):trace.append('guard_exit')
        def typed(self,obj,name):return obj
        def read(self,obj,name,*a):
            trace.append(('read',name,a))
            if name=='GetCWObjectFromID':return (feature if a[0]==1 else anchor,True)
            if name=='QueryInterface':return obj
            if name=='GetTdbIdForDefaultOperation':return 146
            raise AssertionError(name)
        def dispatch_once(self,callback,*,persist_pending):
            trace.append('dispatch');persist_pending();trace.append('pending_durable');value=callback();trace.append('guard_postcheck');return value
    ctx.guard=lambda:Guard();monkeypatch.setattr(c,'_object_id',lambda doc,obj,read:obj.oid);monkeypatch.setattr(c,'read_header',lambda *a:(deepcopy(header),feature));monkeypatch.setattr(c,'_member',lambda obj,name,*args:(trace.append(('native',name,args))or result));monkeypatch.setattr(c,'_is_comtypes_pointer',lambda value:isinstance(value,Obj))
    return ctx,row,trace,result


def test_one_native_insert_callback_return_precedes_postcheck(native_stub):
    ctx,row,trace,result=native_stub
    oid=ctx.insert(row,10,pending=lambda:trace.append('pending'),returned=lambda raw:trace.append(('returned',raw)))
    assert oid==11;assert trace.count('dispatch')==1;assert trace.index('pending')<trace.index(('returned',result))<trace.index('guard_postcheck')
    call=next(x for x in trace if type(x)is tuple and x[0]=='native');assert call[1]=='InsertOperation';assert call[2][:2]==(1,146);assert call[2][2].oid==10


def test_changed_default_no_native_call(native_stub):
    ctx,row,trace,result=native_stub;row['default_operation_id']=147
    with pytest.raises(ValueError,match='default'):ctx.insert(row,10,pending=lambda:None,returned=lambda x:None)
    assert 'dispatch'not in trace


def test_wrong_anchor_no_native_call(native_stub):
    ctx,row,trace,result=native_stub
    with pytest.raises(ValueError,match='Anchor'):ctx.insert(row,12,pending=lambda:None,returned=lambda x:None)
    assert 'dispatch'not in trace


def test_null_return_journaled_before_rejection(native_stub,monkeypatch):
    ctx,row,trace,result=native_stub;monkeypatch.setattr(c,'_member',lambda *a:None)
    with pytest.raises(ValueError,match='Nonnull'):ctx.insert(row,10,pending=lambda:trace.append('pending'),returned=lambda raw:trace.append(('returned',raw)))
    assert trace.count('dispatch')==1;assert ('returned',None)in trace
