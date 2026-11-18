"""Portable offline regression; all identities and documents are synthetic."""
from copy import deepcopy
from pathlib import Path
import json,math,os,sys
import pytest
from scripts import sw_cam_current_saved_finish_wip as m
from test_current_route_wip_comparison import state,Guard

MESSAGES=dict(policy='vendor_default',response='default_unknown',subscribed=True,disconnected=True,active=False,event_count=0,events=[],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])

def setup(tmp_path):
 s=state();s['document']['path']=str(tmp_path/'owned.sldprt');(tmp_path/'owned.sldprt').write_bytes(b'saved model')
 v=dict(process_id=42,expected_process_create_time=12.0,expected_document_path=s['document']['path'],expected_source_sha256='a'*64,generation_receipt_path=str(tmp_path/'generation.json'),generation_receipt_sha256='b'*64,qualification_only=True,message_policy='vendor_default',project_root=str(tmp_path),output_dir=str(tmp_path/'wip'),receipt_path=str(tmp_path/'receipt.json'),module_sha256=m._file_hash(m.__file__),acknowledge_machine_scope=True,declared_empty_operation_ids=[33])
 rows=[dict(operation_native_id=11,toolpath_record_counts=[10]),dict(operation_native_id=22,toolpath_record_counts=[4])]
 contract=m.comparison.comparison_contract(s,process_id=42,source_sha256='a'*64,declared_empty_ids=[33],positive_operation_rows=rows)
 d=dict(authority_scope=m.authority.SCOPE,original_terminal_status='uncertain',original_runtime_unchanged=False,generation_receipt_pin=dict(path=v['generation_receipt_path'],sha256='b'*64),generation_marker_pin=dict(path=str(tmp_path/'oldmarker.json'),sha256='c'*64),pin=dict(path=str(tmp_path/'configuration.json'),sha256='d'*64),pins=[],source_sha256='a'*64,recovery_saved_state=s,saved_boundary_proof=dict(positive_rows=rows),planes=[dict(raw_plane=2.0)])
 p=dict(data=d,contract=contract,directory=v['output_dir'],canonical=str(Path(v['output_dir']).resolve()),marker=str(m.marker_path(v)))
 r=m.new_report(v,p,dict(native_calls=0));r['receipt_created']=True
 def persist():m._write_receipt(v['receipt_path'],r)
 persist();return s,v,p,r,persist

class Context:
 def __init__(self,s,p,r,trace,*,drift=False,close_error=False):self.s=s;self.p=p;self.r=r;self.trace=trace;self.closed=False;self.session=None;self.drift=drift;self.close_error=close_error
 def start(self):self.trace.append('start')
 def capture_existing(self,label):
  self.trace.append(label);s=deepcopy(self.s)
  if self.drift:s['operations'][0]['toolpath_record_counts']=[9]
  else:s['sketch_state']['solids'][0]['mass_raw'][3]=math.nextafter(1.0,2.0)
  self.r['plane_observations']['wip_'+label]=deepcopy(self.p['data']['planes'])
  return s['document'],s,dict(machine=object())
 def guard(self):return Guard()
 def finish(self):self.trace.append('finish');self.r['messages']=deepcopy(MESSAGES)
 def close(self):
  self.closed=True
  if self.close_error:raise ValueError('close failed')
 def identity(self):return deepcopy(self.s['document'])

@pytest.mark.parametrize('result',[True,False,0,1,None])
def test_real_core_adapter_one_export_strict_return(tmp_path,monkeypatch,result):
 s,v,p,r,persist=setup(tmp_path);trace=[];ctx=Context(s,p,r,trace)
 def member(machine,name,*args):
  assert name=='CreateSTLOfWIPs2'and args==tuple(r['native_parameters']);trace.append('export');(Path(v['output_dir'])/'wip.stl').write_bytes(b'nonempty-stl-test');return result
 monkeypatch.setattr(m,'_member',member)
 m.run_backend(ctx,v,p,r,persist,lambda:None)
 assert trace.count('export')==1 and r['native_call_count']==1 and Path(p['marker']).is_file()
 assert r['native_return_type']==type(result).__name__ and r['native_return_value']==result
 assert r['original_terminal_status']=='uncertain'and not r['cache_freshness_verified']and not r['material_removal_verified']
 assert r['GTP_attempted']is False and r['save_attempted']is False
 if result is True:
  assert r['status']=='review_required'and trace==['start','before','export','after','finish']
  monkeypatch.setattr(m.authority,'load_saved_boundary',lambda request:p['data'])
  out=m.verify_export_receipt(r);assert out['verified']is True and out['native_calls']==0
 else:
  assert r['status']=='uncertain'and trace==['start','before','export']
  with pytest.raises(ValueError):m.verify_export_receipt(r)

@pytest.mark.parametrize('failure',['before_drift','invoke_exception','cleanup'])
def test_failures_stop_without_replay(tmp_path,monkeypatch,failure):
 s,v,p,r,persist=setup(tmp_path);trace=[];ctx=Context(s,p,r,trace,drift=failure=='before_drift',close_error=failure=='cleanup')
 def member(*a):
  trace.append('export')
  if failure=='invoke_exception':raise RuntimeError('uncertain native result')
  (Path(v['output_dir'])/'wip.stl').write_bytes(b'nonempty');return True
 monkeypatch.setattr(m,'_member',member)
 m.run_backend(ctx,v,p,r,persist,lambda:None)
 assert trace.count('export')==(0 if failure=='before_drift'else 1)
 assert r['status']==('error'if failure=='before_drift'else'uncertain')and not r['readback_verified']
 if failure=='invoke_exception':assert r['native_dispatch_pending']is True and 'after'not in trace
 if failure=='cleanup':assert r['native_call_returned']is True and r['native_return_value']is True and r['cleanup_verified']is False

@pytest.mark.parametrize('name',['export_cl','generate','save','adopt_saved_source','assign','set_change','create_sketch','create_feature','insert_finish'])
def test_all_inherited_mutators_forbidden(name):
 with pytest.raises(ValueError):getattr(m.ReadContext,name)(object())

def test_mass_only_tolerance_raw_retention_and_bound_rejection():
 s=state();c=m.comparison.comparison_contract(s,process_id=42,source_sha256='a'*64,declared_empty_ids=[33],positive_operation_rows=[dict(operation_native_id=11,toolpath_record_counts=[10]),dict(operation_native_id=22,toolpath_record_counts=[4])])
 after=deepcopy(s);after['sketch_state']['solids'][0]['mass_raw'][3]=math.nextafter(1.0,2.0)
 proof=m.comparison.validate_capture(c,after['document'],after)
 assert proof['snapshot']['sketch_state']['solids'][0]['mass_raw']==s['sketch_state']['solids'][0]['mass_raw']
 assert after['sketch_state']['solids'][0]['mass_raw'][3]!=1.0
 after['sketch_state']['solids'][0]['box_m'][0]=1e-20
 with pytest.raises(ValueError):m.comparison.validate_capture(c,after['document'],after)

@pytest.mark.parametrize('field,value',[('native_call_count',2),('material_removal_verified',True),('original_terminal_status','review_required'),('source_after_sha256','e'*64)])
def test_offline_receipt_rejects_forged_authority(tmp_path,monkeypatch,field,value):
 s,v,p,r,persist=setup(tmp_path);trace=[];ctx=Context(s,p,r,trace)
 def member(*a):(Path(v['output_dir'])/'wip.stl').write_bytes(b'nonempty');return True
 monkeypatch.setattr(m,'_member',member);m.run_backend(ctx,v,p,r,persist,lambda:None)
 monkeypatch.setattr(m.authority,'load_saved_boundary',lambda request:p['data'])
 r[field]=value
 with pytest.raises(ValueError):m.verify_export_receipt(r)
def test_prepare_loads_once_consume_checks_pins_and_forbids_reuse(tmp_path,monkeypatch):
 s,v,p,r,persist=setup(tmp_path);Path(v['receipt_path']).unlink();calls=[]
 monkeypatch.setattr(m,'validate',lambda request:(calls.append('load')or deepcopy(p)))
 bundle=m._prepare_invocation(v,runtime_check=lambda:calls.append('runtime'))
 got=m.consume(bundle,v,lambda:calls.append('runtime'))
 assert got==p and calls.count('load')==1
 with pytest.raises(ValueError):m.consume(bundle,v,lambda:None)
 assert calls.count('load')==1

def test_prepared_request_drift_rejected(tmp_path,monkeypatch):
 s,v,p,r,persist=setup(tmp_path);monkeypatch.setattr(m,'validate',lambda request:deepcopy(p))
 bundle=m._prepare_invocation(v,runtime_check=lambda:None);bundle.plan['contract']['process_id']=43
 with pytest.raises(ValueError):m.consume(bundle,v,lambda:None)

