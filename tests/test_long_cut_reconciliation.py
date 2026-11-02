from copy import deepcopy
from pathlib import Path
import importlib.util,json,os,sys
import pytest
from cam_optional_test_evidence import evidence_root
R=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).resolve().parents[1])))
sys.path.insert(0,str(R))
D=Path(__file__).resolve().parents[1]
P=Path(os.environ.get('SW_CAM_RECONCILIATION_MODULE',str(R/'scripts'/'sw_cam_long_cut_reconciliation.py')))
spec=importlib.util.spec_from_file_location('reconciliation_tested',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.fixture(scope='module')
def actual():
 F=evidence_root('SW_CAM_LONG_CUT_EVIDENCE_ROOT')
 audit=F/'ACTUAL_SAVED_RESULT_AUDIT.json'
 if not audit.is_file():audit=F/'long_cut_tool_definition_fix_20261102/ACTUAL_SAVED_RESULT_AUDIT.json'
 if not audit.is_file():pytest.fail('SW_CAM_LONG_CUT_EVIDENCE_ROOT must name the development_staging root or the preserved factory stage containing ACTUAL_SAVED_RESULT_AUDIT.json',pytrace=False)
 a=json.loads(audit.read_bytes())
 r,p=m.read_pin(a['native_receipt']['path'],a['native_receipt']['sha256'])
 x,q=m.read_pin(a['context']['path'],a['context']['sha256'])
 return a,r,x

@pytest.mark.parametrize('raw',[b'{"x":NaN}',b'{"x":Infinity}',b'{"x":1,"x":2}',b'[]',b'{',b'null'])
def test_invalid_json(raw):
 with pytest.raises(ValueError):m.decode_bounded(raw)

@pytest.mark.parametrize('value',[{'x':[0]*8193},{'x':'a'*16385}])
def test_list_string_bounds(value):
 with pytest.raises(ValueError):m.decode_bounded(json.dumps(value).encode())

def test_depth_bound():
 x={}
 for _ in range(66):x={'x':x}
 with pytest.raises(ValueError):m.decode_bounded(json.dumps(x).encode())

def test_node_bound():
 x={'x':[[0]*1000 for _ in range(1000)]}
 with pytest.raises(ValueError):m.decode_bounded(json.dumps(x).encode())

def test_bytes_bound():
 with pytest.raises(ValueError):m.decode_bounded(b' '*(m.MAX_BYTES+1))

def test_hash_rejected(tmp_path):
 p=tmp_path/'a.json';p.write_text('{}')
 with pytest.raises(ValueError):m.read_pin(str(p),'0'*64)

def test_actual_old_bound_and_new_loader(actual):
 a,r,x=actual
 from scripts.sw_cam_mill_stock_export_evidence import _decode
 for key in ('native_receipt','context'):
  with pytest.raises(ValueError,match='structure exceeds bounds'):_decode(Path(a[key]['path']).read_bytes())
 assert r['new_tool_native_id']==338 and len(x['state']['operations'])==17
 assert m.decode_bounded(Path(a['native_receipt']['path']).read_bytes())==r

def test_actual_failure_contract(actual):m._exact_failure(actual[1])

@pytest.mark.parametrize('field,value',[('status','error'),('phase','prepared'),('readback_verified',True),('phase_proofs_verified',True),('automatic_replay',True),('automatic_rollback',True),('production_qualified',True),('mutation_attempted',False),('cleanup_issue',{'type':'ValueError'})])
def test_other_failure_rejected(actual,field,value):
 r=deepcopy(actual[1]);r[field]=value
 with pytest.raises(ValueError):m._exact_failure(r)

def test_other_trace_rejected(actual):
 r=deepcopy(actual[1]);r['terminal_issue']['locations'][0]['function']='other'
 with pytest.raises(ValueError):m._exact_failure(r)

def test_event_error_rejected(actual):
 r=deepcopy(actual[1]);r['messages']['active']=True
 with pytest.raises(ValueError):m._exact_failure(r)

def ready(r):
 r=deepcopy(r);r.update(status='review_required',readback_verified=True,phase_proofs_verified=True);return r

def test_actual_complete_semantics(actual):
 original=deepcopy(actual[1]);m._validate_terminal_semantics(ready(original),actual[2]);assert original==actual[1]

@pytest.mark.parametrize('change', ['pending','save_code','profile_id','checkpoint_digest','protected_route','protected_parameter','field_value','saved_cl'])
def test_terminal_damage_rejected(actual,change):
 r=ready(actual[1])
 if change=='pending':r['actions']['AddNewTool3']['pending']=True
 elif change=='save_code':r['actions']['SaveActiveDocument']['native_return_value']=1
 elif change=='profile_id':r['final_candidate']['full_tool']['tool_native_id']=339
 elif change=='checkpoint_digest':r['checkpoint_digest']='0'*64
 elif change=='protected_route':r['final_observation']['route']['operations'][0]['native_id']=999
 elif change=='protected_parameter':r['final_observation']['guide_snapshot']={}
 elif change=='field_value':r['field_readbacks'][0]['actual']=-1
 elif change=='saved_cl':r['saved_cl_comparison']['all_fourteen_complete_streams_unchanged']=False
 with pytest.raises(ValueError):m._validate_terminal_semantics(r,actual[2])

def test_semantics_copy_exact_frozen_function():
 p=Path(m.creator.__file__);s=p.read_text(encoding='utf-8')
 expected=s[s.index('def validate_terminal(r):'):s.index('\n\ndef execute',s.index('def validate_terminal(r):'))]
 expected=expected.replace('def validate_terminal(r):','def _validate_terminal_semantics(r, initial):')
 expected=expected.replace("    from scripts.sw_cam_mill_selected_plan_evidence import read_pin\n    initial,_=read_pin(r['loaded_context_pin']['path'],r['loaded_context_pin']['sha256'])\n",'')
 now=P.read_text(encoding='utf-8');now=now[now.index('def _validate_terminal_semantics'):now.index('\n\ndef verify_original')]
 assert now.strip()==expected.strip()
