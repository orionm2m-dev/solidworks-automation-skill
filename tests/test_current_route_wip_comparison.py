"""Portable offline regression; all identities and documents are synthetic."""
from copy import deepcopy
from pathlib import Path
import os,sys,pytest
from scripts import sw_cam_current_route_wip_comparison as m

def state():
 return dict(capture_complete=True,extended_capture_complete=True,parameter_capture_complete=True,parameter_batch={'read_complete':True},document={'needs_save':False,'path':str(Path.cwd()/'synthetic_owned.sldprt')},sketch_state={'needs_save':False,'pid':42,'saved_file_sha256':'a'*64,'solids':[{'box_m':[0.,0.,0.,1.,1.,1.],'mass_raw':[0.,0.,0.,1.]}]},operation_count=3,operation_counts=[3],operations=[dict(native_id=11,suppressed=False,toolpath_generated=True,toolpath_record_counts=[10]),dict(native_id=22,suppressed=False,toolpath_generated=True,toolpath_record_counts=[4]),dict(native_id=33,suppressed=False,toolpath_generated=False,toolpath_record_counts=[0])])

def contract(s=None):
 return m.comparison_contract(state()if s is None else s,process_id=42,source_sha256='a'*64,declared_empty_ids=[33],positive_operation_rows=[dict(operation_native_id=11,toolpath_record_counts=[10]),dict(operation_native_id=22,toolpath_record_counts=[4])])

def test_raw_zero_collection_preserved():
 s=state();before=deepcopy(s);c=contract(s);v=m.validate_capture(c,s['document'],s)
 assert s==before and v['snapshot']['operations'][-1]['toolpath_record_counts']==[0]
 assert c['inventory']['total_records']==14 and c['authority_revalidated']is False

@pytest.mark.parametrize('change',['empty_cleanup','empty_generated','positive_count','source','pid','dirty','parameter','suppressed'])
def test_capture_drift_rejected(change):
 c=contract();s=state()
 if change=='empty_cleanup':s['operations'][-1]['toolpath_record_counts']=[]
 elif change=='empty_generated':s['operations'][-1].update(toolpath_generated=True,toolpath_record_counts=[1])
 elif change=='positive_count':s['operations'][0]['toolpath_record_counts']=[9]
 elif change=='source':s['sketch_state']['saved_file_sha256']='b'*64
 elif change=='pid':s['sketch_state']['pid']=43
 elif change=='dirty':s['sketch_state']['needs_save']=True
 elif change=='parameter':s['parameter_batch']['extra']='changed'
 else:s['operations'][0]['suppressed']=True
 with pytest.raises(ValueError):m.validate_capture(c,s['document'],s)

@pytest.mark.parametrize('bad',[True,0.,-1,100001])
def test_strict_positive_counts(bad):
 s=state();s['operations'][0]['toolpath_record_counts']=[bad]
 with pytest.raises(ValueError):contract(s)

def test_undeclared_zero_rejected():
 with pytest.raises(ValueError):m.inventory(state(),[])

class Guard:
 def __enter__(self):self.used=False;return self
 def __exit__(self,*args):pass
 def typed(self,obj,name):assert name=='ICWMachine5';return obj
 def dispatch_once(self,call,persist_pending):
  assert not self.used;self.used=True;persist_pending();return call()
 def summary(self):return {'dispatch_count':1}

@pytest.mark.parametrize('result',[True,False])
def test_actual_core_once_no_save_gtp_and_no_after_read_on_failure(result):
 c=contract();r=dict(native_call_attempted=False,native_call_count=0);trace=[]
 def capture(label):trace.append(label);s=state();return s['document'],s,{'machine':object()}
 def invoke(machine):trace.append('export');return result
 args=dict(capture_existing=capture,guard_factory=Guard,persist=lambda:None,claim=lambda:trace.append('claim'),invoke=invoke,collect=lambda:[dict(stl_extension=True,bytes=123,sha256='b'*64)])
 if result:
  m.run_existing_core(c,r,**args);assert trace==['before','claim','export','after'];assert r['cache_freshness_verified']is False
 else:
  with pytest.raises(ValueError):m.run_existing_core(c,r,**args)
  assert trace==['before','claim','export']
 with pytest.raises(ValueError):m.run_existing_core(c,r,**args)
 assert trace.count('export')==1 and not any(x in trace for x in('save','gtp'))

def test_before_drift_stops_before_export():
 c=contract();r=dict(native_call_attempted=False,native_call_count=0);s=state();s['operations'][0]['toolpath_record_counts']=[9]
 with pytest.raises(ValueError):m.run_existing_core(c,r,capture_existing=lambda label:(s['document'],s,{}),guard_factory=lambda:pytest.fail('No export guard'),persist=lambda:None,claim=lambda:pytest.fail('No claim'),invoke=lambda m:pytest.fail('No export'),collect=lambda:[])
