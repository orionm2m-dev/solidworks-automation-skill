from contextlib import contextmanager
from copy import deepcopy
import pytest
import json
from pathlib import Path
from scripts import sw_cam_current_saved_parameter_fields as m
from scripts import sw_cam_comtypes as bridge


def observed(value):return dict(raw=value,recorded=True)


def fixture():
 actual=json.loads((Path(__file__).parent/'fixtures/rough_parameter_row.json').read_text(encoding='utf-8'))['row']
 rough=deepcopy(actual['rough'])
 tool=dict(generic=dict(native_id=30,cut_diameter_native=12.),mill=dict(length=25.),holder=dict(length=100.))
 ops=[dict(native_id=10,linked_feature_ids=[20],suppressed=False,toolpath_generated=False,toolpath_record_counts=[],assigned_tool=deepcopy(tool['generic'])),dict(native_id=11,linked_feature_ids=[20],suppressed=False,toolpath_generated=False,toolpath_record_counts=[],assigned_tool=deepcopy(tool['generic'])),dict(native_id=12,linked_feature_ids=[21],suppressed=False,toolpath_generated=True,toolpath_record_counts=[99],assigned_tool=dict(native_id=31))]
 row=dict(operation_native_id=10,feature_native_id=20,operation_type=0,read_complete=True,rough=rough,rough_diagnostic=deepcopy(actual['rough_diagnostic']),tool=tool,levels=dict(depth=7.6))
 finish=dict(operation_native_id=11,feature_native_id=20,operation_type=1,read_complete=True,finish=dict(SideAllow=observed(1.)),tool=deepcopy(tool),levels=dict(depth=7.6))
 state=dict(parameter_capture_complete=True,document=dict(path='part',needs_save=False),operations=ops,operation_parameters=[row,finish],own_nc={'10':dict(spindle=1200.,feed=100.,cnc=0,tlp=1),'11':dict(spindle=1200.,feed=100.,cnc=0,tlp=1)},profile={'depth':7.6})
 recipe=dict(schema_version=1,rows=[dict(operation_native_id=10,feature_native_id=20,operation_type=0,expected_tool_native_id=30,existing_tool_native_id=32,fields=[dict(field='side_allowance',expected=1.,new=.5),dict(field='floor_allowance',expected=1.,new=.2),dict(field='first_depth',expected=[False,10.],new=[False,.3])])])
 candidate=dict(generic=dict(native_id=32,cut_diameter_native=8.),mill=dict(length=12.),holder=dict(length=100.))
 state['parameter_batch']=dict(read_complete=True,candidate_tool=deepcopy(candidate),source_tools={'30':deepcopy(tool)},toolcrib_catalogue=[deepcopy(tool['generic']),deepcopy(candidate['generic'])],target_nc={str(oid):dict(operation_native_id=oid,read_complete=True,feeds_compensation=dict(GetSpndlSpeed=1200.,XYFeed=100.,GetCNCComp=0,GetTlpComp=1),tool_defaults_read=False) for oid in (10,11)},candidate_consumer_ids=[],candidate_consumers={})
 return state,recipe,candidate


def assigned(before,candidate):
 after=deepcopy(before);after['operations'][0]['assigned_tool']=deepcopy(candidate['generic']);after['operation_parameters'][0]['tool']=deepcopy(candidate)
 b=after['parameter_batch'];b['source_tools']['32']=deepcopy(candidate);b['candidate_consumer_ids']=[10];b['candidate_consumers']['10']=dict(deepcopy(b['target_nc']['10']),assigned_tool_native_id=32)
 return after


def actual_change(row,key,value):
 spec=m.FIELDS[key]
 for member,new in [(spec.getter,value)]+([(spec.alias,value[1])] if spec.alias else []):
  decoded=row['rough'][spec.area][member];decoded['raw']=deepcopy(new)
  if type(new) is list:
   decoded['is_percent']=new[0];decoded['value_native']=new[1];decoded['value_mode']='percent_flag_set' if new[0] else 'percent_flag_clear'
  observation=next(x for x in row['rough_diagnostic']['observations'] if x['member']==member)
  observation['raw_observation']['raw']=deepcopy(new);observation['value']=deepcopy(decoded)


def test_compile_actual_observed_fields_and_existing_legacy_mapping():
 state,recipe,_=fixture();plan=m.compile_plan(state,recipe);assert plan==recipe
 assert set(m.FIELDS)=={s[0] for s in m.legacy.ROUGH_FIELDS}
 assert not m.NATIVE_QUALIFICATION_COMPLETE

@pytest.mark.parametrize('value',[True,1,'0.5',float('nan'),float('inf'),-1.])
def test_strict_scalar_rejects_coercion(value):
 state,recipe,_=fixture();recipe['rows'][0]['fields'][0]['new']=value
 with pytest.raises(ValueError):m.compile_plan(state,recipe)

@pytest.mark.parametrize('defect',['arbitrary_member','wrong_expected','finish','duplicate','wrong_tool','generated'])
def test_recipe_and_identity_rejections(defect):
 state,recipe,_=fixture();row=recipe['rows'][0]
 if defect=='arbitrary_member':row['fields'][0]['field']='SetAnything'
 elif defect=='wrong_expected':row['fields'][0]['expected']=2.
 elif defect=='finish':row['operation_type']=1
 elif defect=='duplicate':row['fields'].append(deepcopy(row['fields'][0]))
 elif defect=='wrong_tool':row['expected_tool_native_id']=31
 else:state['operations'][0]['toolpath_generated']=True
 with pytest.raises(ValueError):m.compile_plan(state,recipe)


def test_assignment_only_allows_selected_tool_and_derived_usage():
 before,recipe,candidate=fixture();after=assigned(before,candidate)
 m.verify_assignment_delta(before,after,recipe['rows'][0],candidate)
 after['operation_parameters'][0]['rough']['boundary']['SideAllow']['raw']=.7
 with pytest.raises(ValueError):m.verify_assignment_delta(before,after,recipe['rows'][0],candidate)
 assert before['operations'][0]['assigned_tool']['native_id']==30

@pytest.mark.parametrize('defect',['speed','feed','cnc','tlp','finish','paths','levels','profile','undeclared','candidate'])
def test_assignment_rejects_every_unrequested_delta(defect):
 before,recipe,candidate=fixture();after=assigned(before,candidate)
 if defect in ('speed','feed','cnc','tlp'):after['own_nc']['10'][{'speed':'spindle','feed':'feed','cnc':'cnc','tlp':'tlp'}[defect]]+=1
 elif defect=='finish':after['operation_parameters'][1]['finish']['SideAllow']['raw']=0.
 elif defect=='paths':after['operations'][2]['toolpath_record_counts']=[100]
 elif defect=='levels':after['operation_parameters'][0]['levels']['depth']=8.
 elif defect=='profile':after['profile']['depth']=8.
 elif defect=='undeclared':after['operation_parameters'][0]['rough']['entry']['GetSpiralRadius']['raw']=3.
 else:after['operation_parameters'][0]['tool']['mill']['length']=13.
 with pytest.raises(ValueError):m.verify_assignment_delta(before,after,recipe['rows'][0],candidate)


def test_only_established_depth_alias_is_permitted():
 before,recipe,_=fixture();row=recipe['rows'][0];change=row['fields'][2];after=deepcopy(before)
 actual_change(after['operation_parameters'][0],'first_depth',[False,.3])
 m.verify_field_delta(before,after,row,change)
 after['operation_parameters'][0]['rough']['depth']['DepthAllow']['raw']=.3
 with pytest.raises(ValueError):m.verify_field_delta(before,after,row,change)


def test_floor_allowance_cannot_change_depthallow():
 before,recipe,_=fixture();row=recipe['rows'][0];change=row['fields'][1];after=deepcopy(before)
 actual_change(after['operation_parameters'][0],'floor_allowance',.2)
 m.verify_field_delta(before,after,row,change)
 after['operation_parameters'][0]['rough']['depth']['DepthAllow']['raw']=.2
 with pytest.raises(ValueError):m.verify_field_delta(before,after,row,change)


def test_final_exact_targets_with_old_route_and_nc_preserved():
 before,recipe,candidate=fixture();after=assigned(before,candidate)
 for change in recipe['rows'][0]['fields']:
  actual_change(after['operation_parameters'][0],change['field'],change['new'])
 m.verify_final(before,after,recipe,{32:candidate})
 after['operation_parameters'][0]['rough']['boundary']['SideAllow']['raw']=.6
 with pytest.raises(ValueError):m.verify_final(before,after,recipe,{32:candidate})

@pytest.fixture
def native(monkeypatch):
 class Object(dict):
  def __setattr__(self,key,value):self[key]=value
 feature=Object(_id=20);feature['QueryInterface']=lambda iid:feature
 op=Object(_id=10,OpernType=0,Suppressed=False,GetIsToolpathGenerated=False,IGetAllFeatures=dict(Count=1,Item=lambda i:feature),SideAllow=1.)
 doc={'GetCWObjectFromID':lambda kind,oid:(op if kind==3 else feature,True),'GetCWObjectID':lambda raw:(raw['_id'],True)}
 calls=[];state=dict(claimed=False,event=False)
 def read(obj,name,*args):calls.append(name);v=obj[name];return v(*args) if callable(v) else v
 monkeypatch.setattr(m,'_member',read)
 class Context:
  @contextmanager
  def guard(self):
   if state['event']:raise RuntimeError('event stop')
   yield self
  typed=staticmethod(lambda raw,name:raw)
  def dispatch_once(self,call,persist_pending):
   if state['claimed']:raise RuntimeError('no replay')
   state['claimed']=True;persist_pending();value=call()
   if state['event']:raise RuntimeError('post event')
   return value
 Context.read=staticmethod(read)
 def put(value):op['SideAllow']=value;return state.get('hresult',0)
 op['_ICWRghMillOp__com__set_SideAllow']=put
 Object.__getattr__=lambda self,key:self[key]
 return Context(),doc,op,calls,state


def test_native_fixed_property_raw_hresult_and_durable_order(native):
 ctx,doc,op,calls,state=native;_,recipe,_=fixture();row=recipe['rows'][0];change=row['fields'][0];journal=[]
 result=m.write_field_once(ctx,doc,row,change,pending=lambda:journal.append('pending'),returned=lambda v:journal.append(('returned',v)))
 assert result==0 and type(result) is int and op['SideAllow']==.5 and journal==['pending',('returned',0)]
 with pytest.raises(RuntimeError):m.write_field_once(ctx,doc,row,dict(change,expected=.5),pending=lambda:None,returned=lambda v:None)


def test_return_preserved_before_event_stop(native):
 ctx,doc,op,calls,state=native;_,recipe,_=fixture();journal=[]
 def returned(value):journal.append(('returned',value));state['event']=True
 with pytest.raises(RuntimeError):m.write_field_once(ctx,doc,recipe['rows'][0],recipe['rows'][0]['fields'][0],pending=lambda:journal.append('pending'),returned=returned)
 assert op['SideAllow']==.5 and journal==['pending',('returned',0)]


def test_expected_mismatch_causes_zero_native_mutation(native):
 ctx,doc,op,calls,state=native;_,recipe,_=fixture();change=dict(recipe['rows'][0]['fields'][0],expected=2.)
 with pytest.raises(ValueError):m.write_field_once(ctx,doc,recipe['rows'][0],change,pending=lambda:None,returned=lambda v:None)
 assert op['SideAllow']==1. and not state['claimed']


def test_primary_local_metadata_preflight_optional(monkeypatch):
 primary=pytest.importorskip('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0',reason='Requires installed CAM primary metadata')
 monkeypatch.setattr(bridge,'_load_type_library',lambda path:primary);m.preflight('offline')
 monkeypatch.delitem(bridge._INTERFACES,'ICWRghMillOp')
 with pytest.raises(ValueError):m.preflight('offline')


@pytest.mark.parametrize('field,expected,new',[('entry_type',1,4),('spiral_radius',.2,3.),('spiral_pitch',.1,.2),('first_depth',[False,10.],[False,.3]),('subsequent_depth',[False,10.],[False,.3]),('side_allowance',1.,.5),('floor_allowance',1.,.2),('side_step',[True,50.],[False,1.6])])
def test_actual_native_decoder_and_diagnostic_shape(field,expected,new):
 before,recipe,_=fixture();row=recipe['rows'][0];change=dict(field=field,expected=expected,new=new);after=deepcopy(before)
 actual_change(after['operation_parameters'][0],field,new)
 m.verify_field_delta(before,after,row,change)
 spec=m.FIELDS[field];observation=next(x for x in after['operation_parameters'][0]['rough_diagnostic']['observations'] if x['member']==spec.getter)
 observation['raw_observation']['original_variant_tag_verified']=True
 with pytest.raises(ValueError):m.verify_field_delta(before,after,row,change)

@pytest.mark.parametrize('bad',['catalogue','candidate','oldsource','usage_order','consumerNC','targetNC','roughfield','finish'])
def test_actual_assignment_preserves_shared_and_observed_state(bad):
 before,recipe,candidate=fixture();after=assigned(before,candidate);b=after['parameter_batch']
 if bad=='catalogue':b['toolcrib_catalogue'][1]['cut_diameter_native']=9.
 elif bad=='candidate':b['candidate_tool']['mill']['length']=99.
 elif bad=='oldsource':b['source_tools']['30']['holder']['length']=99.
 elif bad=='usage_order':b['candidate_consumer_ids']=[11,10]
 elif bad=='consumerNC':b['candidate_consumers']['10']['feeds_compensation']['GetCNCComp']=1
 elif bad=='targetNC':b['target_nc']['10']['feeds_compensation']['XYFeed']=200.
 elif bad=='roughfield':actual_change(after['operation_parameters'][0],'first_depth',[False,.3])
 else:after['operation_parameters'][1]['finish']['SideAllow']['raw']=0.
 with pytest.raises(ValueError):m.verify_assignment_delta(before,after,recipe['rows'][0],candidate)

@pytest.mark.parametrize('outcome',[None,True,1,-2147467259])
def test_unknown_hresult_preserved_after_one_actual_mutation_no_replay(native,outcome):
 ctx,doc,op,calls,state=native;_,recipe,_=fixture();journal=[];state['hresult']=outcome
 with pytest.raises(ValueError,match='HRESULT'):m.write_field_once(ctx,doc,recipe['rows'][0],recipe['rows'][0]['fields'][0],pending=lambda:journal.append('pending'),returned=lambda v:journal.append(('returned',v)))
 assert op['SideAllow']==.5 and state['claimed'] and journal==['pending',('returned',outcome)]

@pytest.mark.parametrize('name',['GetSpndlSpeed','GetTlpComp','GetCNCComp','_get_XYFeed'])
def test_nc_getter_abi_mismatch_before_native(monkeypatch,name):
 primary=pytest.importorskip('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0')
 monkeypatch.setattr(bridge,'_load_type_library',lambda path:primary)
 cls=primary.ICWNCParam2 if name=='_get_XYFeed' else primary.ICWNCParam
 from types import SimpleNamespace
 methods=[]
 for method in cls._methods_:
  methods.append(SimpleNamespace(name=method.name,restype=method.restype,idlflags=[999]+list(method.idlflags[1:]),argtypes=method.argtypes,paramflags=method.paramflags) if method.name==name else method)
 proxy=SimpleNamespace(_iid_=cls._iid_,_methods_=methods);original=bridge._interface_class
 interface='ICWNCParam2' if name=='_get_XYFeed' else 'ICWNCParam'
 monkeypatch.setattr(bridge,'_interface_class',lambda requested,path:proxy if requested==interface else original(requested,path))
 with pytest.raises(ValueError,match='NC getter ABI'):m.preflight('offline')
