import math
import pytest
from scripts import sw_cam_thread_feature_attributes as a

@pytest.mark.parametrize("value,tag",[(None,"NoneType"),(True,"bool"),(False,"bool"),(0,"int"),(-7,"int"),(1.5,"float"),(-0.0,"float"),("резьба","str"),(b"\x00\xff","bytes"),([],"list"),((),"tuple")])
def test_exact_tags(value,tag):
 r=a.bounded_variant_tree(value)
 assert r['tree']['python_type']==tag
 assert r['native_variant_type_preserved'] is False
 assert r['field_semantics_verified'] is False and r['units_verified'] is False

@pytest.mark.parametrize("value",[float('nan'),float('inf'),-float('inf'),1<<64,-(1<<63)-1,{"depth":1},bytearray(b'a'),set(),complex(1)])
def test_reject_unknown(value):
 with pytest.raises(ValueError):a.bounded_variant_tree(value)

class Trap:
 def __repr__(self):raise AssertionError('repr forbidden')
 def __str__(self):raise AssertionError('str forbidden')
 def __iter__(self):raise AssertionError('iter forbidden')
 @property
 def value(self):raise AssertionError('value forbidden')

def test_no_object_introspection():
 with pytest.raises(ValueError):a.bounded_variant_tree(Trap())

def test_builtin_subclasses_rejected():
 class Number(int):pass
 with pytest.raises(ValueError):a.bounded_variant_tree(Number(2))

def test_nested_preserve_order_and_types():
 r=a.bounded_variant_tree((['d',1,1.0,True],None))['tree']
 assert [x['python_type'] for x in r['items'][0]['items']]==['str','int','float','bool']

def test_cycle():
 x=[];x.append(x)
 with pytest.raises(ValueError,match='Cyclic'):a.bounded_variant_tree(x)

def test_repeated_noncyclic_reference():
 x=[1];assert a.bounded_variant_tree([x,x])['budget_used']['nodes']==5

@pytest.mark.parametrize('kind',['depth','nodes','str','totalstr','bytes'])
def test_bounds(kind):
 if kind=='depth':
  x=1
  for _ in range(a.MAX_DEPTH+1):x=[x]
 elif kind=='nodes':x=[None]*a.MAX_NODES
 elif kind=='str':x='x'*(a.MAX_STRING_CHARACTERS+1)
 elif kind=='totalstr':x=['x'*a.MAX_STRING_CHARACTERS]*5
 else:x=b'0'*(a.MAX_BINARY_BYTES+1)
 with pytest.raises(ValueError):a.bounded_variant_tree(x)

def test_exact_one_native_call_no_depth_inference():
 calls=[];checks=[];d={}
 r=a.read_feature_attributes(object(),read=lambda f,n:calls.append(n) or ('.9',1.5),check=lambda:checks.append(1),diagnostic=d)
 assert calls==['GetFeatureAttributes'] and len(checks)==2
 assert r['status']=='review_required' and not r['total_thread_depth_verified']
 assert d['native_call_succeeded'] and d['payload_copied']

def test_check_before_native_blocks():
 calls=[];d={}
 def bad():raise ValueError('event')
 with pytest.raises(ValueError):a.read_feature_attributes(None,read=lambda *x:calls.append(x),check=bad,diagnostic=d)
 assert not calls and not d['native_call_attempted']

def test_native_failure_no_retry_and_durable_partial():
 calls=[];d={}
 def fail(*args):calls.append(args);raise RuntimeError('native failure')
 with pytest.raises(RuntimeError):a.read_feature_attributes(None,read=fail,check=lambda:None,diagnostic=d)
 assert len(calls)==1 and d['native_call_attempted'] and not d['native_call_returned']

def test_after_call_event_no_payload_processing():
 checks=[];d={};calls=[]
 def check():
  checks.append(1)
  if len(checks)==2:raise ValueError('event')
 with pytest.raises(ValueError):a.read_feature_attributes(None,read=lambda *x:calls.append(x) or Trap(),check=check,diagnostic=d)
 assert len(calls)==1 and d['native_call_returned'] and not d['payload_copied']

def test_bad_payload_preserves_native_return():
 d={}
 with pytest.raises(ValueError):a.read_feature_attributes(None,read=lambda *x:Trap(),check=lambda:None,diagnostic=d)
 assert d['native_call_succeeded'] and not d['payload_copied']
