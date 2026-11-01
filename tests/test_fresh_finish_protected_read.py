import importlib.util,sys
from pathlib import Path
from copy import deepcopy
import pytest
ROOT=Path(__file__).resolve().parents[1]
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_fresh_finish_protected_read as m

VALUES={'GougeCheck':True,'GetIsSingleCutDepth':False,'DepthProcessOpt':1,'ContourMillRestMachMethod':0,'GetToolRadiusLeadInLeadOut':False,'LeadType':1,'GetTlpComp':1,'GetCNCComp':1}
def execute(values=None,fail=None):
    data=dict(VALUES,**(values or {}));calls=[];record=[]
    def read(obj,member,*args):
        calls.append(member)
        if member==fail:raise RuntimeError('read failed')
        if member in ('IGetLeadin','IGetLeadout','IGetNCParam'):return object()
        return data[member]
    value=m.read_protected(object(),object(),read=read,typed=lambda obj,name:obj,record=lambda key,value:record.append((key,value)))
    return value,calls,record

def test_nine_returned_scalars_seven_fields():
    value,calls,record=execute();assert len(value)==7 and len(record)==9 and len(calls)==12
    assert m.prior_expectation_comparison(value)['differences']=={}

@pytest.mark.parametrize('field,value',[('GougeCheck',False),('GetIsSingleCutDepth',True),('ContourMillRestMachMethod',2),('LeadType',0),('LeadType',2),('DepthProcessOpt',3),('GetTlpComp',0),('GetCNCComp',4)])
def test_observe_other_legitimate_scalars_without_guard_assumption(field,value):
    result,_,observed=execute({field:value});assert len(observed)==9
    assert result['compensation'] or result['lead_types']

@pytest.mark.parametrize('member,bad',[('GougeCheck',1),('GetIsSingleCutDepth',0),('ContourMillRestMachMethod',True),('DepthProcessOpt',1.2),('LeadType',None),('GetCNCComp','1')])
def test_invalid_value_is_recorded_before_validation(member,bad):
    observed=[];values=dict(VALUES);values[member]=bad
    def read(obj,name,*args):return object() if name in ('IGetLeadin','IGetLeadout','IGetNCParam') else values[name]
    with pytest.raises(ValueError):m.read_protected(object(),object(),read=read,typed=lambda obj,name:obj,record=lambda key,value:observed.append((key,value)))
    assert observed[-1][1] is bad

@pytest.mark.parametrize('success', [True,False])
def test_cleanup_persists_real_disconnected_status_even_after_reader_error(success):
    class Session:
        active=True
        def summary(self):return dict(active=self.active,disconnected=not self.active,event_count=0)
    class Backend:
        session=Session();session_active=True
        def close(self):self.session.active=False;self.session_active=False
        def events(self,active):assert self.session.summary()['active'] is active
    report={'status':'observed' if success else 'error','readback_verified':success,'messages':{'active':True,'disconnected':False}}
    copies=[];m.close_and_observe(Backend(),report,lambda:copies.append(deepcopy(report)))
    assert report['messages']['disconnected'] is True and report['cleanup']['session_active'] is False
    assert copies[-1]==report and report['readback_verified'] is success

def test_cleanup_error_is_not_hidden():
    class Session:
        def summary(self):return {'active':True,'disconnected':False}
    class Backend:
        session=Session();session_active=True
        def close(self):raise ValueError('disconnect failed')
        def events(self,active):raise ValueError('still active')
    report={'status':'observed','readback_verified':True}
    m.close_and_observe(Backend(),report,lambda:None)
    assert report['status']=='error' and not report['readback_verified'] and report['cleanup']['messages']['active']

def test_no_mutation_method_in_read_whitelist():
    assert not ({'SetTool','GenerateToolpath','SaveActiveDocument','InsertOperation'}&m.MEMBERS)
