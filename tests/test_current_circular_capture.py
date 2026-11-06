from copy import deepcopy
from pathlib import Path
import importlib
import pytest
from test_current_parameter_capture import env,collection
from scripts import sw_cam_current_parameter_capture as capture
from scripts import sw_cam_mill_current_parameters as parameters
from scripts import sw_cam_current_circular_context as c
from scripts import sw_cam_comtypes as bridge


def single(e,**kw):
    return capture.capture_parameter_batch(e['state'],e['native'],[e['rows'][2]],feature_id=70,candidate_tool_native_id=249,expected_candidate_consumer_ids=[248,320],read=e['read'],typed=e['typed'],boundary=e['boundary'],expected_operation_types=(0,),**kw)


def test_real_single_rough_capture_retains_both_existing_consumers_nc(env):
    e=env;out=single(e)
    assert out['read_complete'] and len(e['state']['operation_parameters'])==1 and list(out['target_nc'])==['356']
    assert list(out['candidate_consumers'])==['248','320'] and out['candidate_consumers']['320']['feeds_compensation']['XYFeed']==420.
    assert not any(n.startswith(('Set','Save','Generate','Insert')) for n in e['calls'])


def test_single_target_requires_explicit_opt_in(env):
    e=env
    with pytest.raises(ValueError):capture.capture_parameter_batch(e['state'],e['native'],[e['rows'][2]],feature_id=70,candidate_tool_native_id=249,expected_candidate_consumer_ids=[248,320],read=e['read'],typed=e['typed'],boundary=e['boundary'])
    assert not e['calls']


def test_single_generated_observation_is_explicit(env):
    e=env;e['rows'][2].update(toolpath_generated=True,toolpath_record_counts=[40]);e['ops'][356]['GetIsToolpathGenerated']=True
    single(e,generation_observations={356:[40]});assert e['state']['parameter_capture_complete']


def test_real_registered_factory_capture_and_nc_preflight(monkeypatch):
    try:module=importlib.import_module('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0')
    except ImportError:pytest.skip('Optional locally installed vendor metadata unavailable')
    monkeypatch.setattr(bridge,'_load_type_library',lambda path:module)
    assert c.preflight('metadata-only','selected_continue')['automatic_GOP'] is False
    monkeypatch.delitem(bridge._INTERFACES,'ICWUnitVector')
    with pytest.raises(ValueError):c.preflight('metadata-only','selected_continue')


@pytest.fixture
def composed(env,monkeypatch):
    e=env;old=deepcopy(e['rows']);feature=dict(_id=80);feature['QueryInterface']=lambda cls:feature
    nc=dict(GetSpndlSpeed=1500.,XYFeed=500.,GetCNCComp=0,GetTlpComp=1)
    raw=dict(_id=360,OpernType=0,Suppressed=False,GetIsToolpathGenerated=False,IGetAllFeatures=collection([feature]),IGetTool=e['tools'][252],IGetNCParam=nc)
    row=deepcopy(e['rows'][2]);row.update(native_id=360,operation_index=4,linked_feature_ids=[80]);e['ops'][360]=raw;e['rows'].append(row)
    e['native']['doc']['GetCWObjectFromID']=lambda kind,oid:(feature if kind==1 else e['ops'][oid],True)
    e['state']['operation_count']=5;e['state']['operation_counts']=[5];e['state']['operation_setups'][0]['operation_count']=5
    document=dict(path='part.sldprt',title='part',type=1,needs_save=True)
    h=dict(native_id=80,volume_type=2,subtype_raw=0,suppressed=False,axis_native=[0.,0.,1.],start_native=[0.,0.,0.],bounds_native=[10.,10.,2.],depth_native=2.)
    base=deepcopy(e['state']);base.update(target_header=dict(native_id=70),profile=dict(complete_step_coverage=True),number_of_steps_raw=3,features=[dict(geometry=dict(native_id=70))])
    def route(app,tlb,read,typed,state,v,boundary,verify_operation_pins):
        state.update(deepcopy(base));state['operations']=deepcopy(e['rows']);return e['native']
    monkeypatch.setattr(c.batch.current,'_capture',route);monkeypatch.setattr(c.batch,'read_compound_strategy',lambda *a,**k:None);monkeypatch.setattr(c,'read_catalogues',lambda *a,**k:[])
    spec=dict(plane_axis='Z',plane_offset_mm=0.,plane_name='P',sketch_name='C',profile=dict(kind='circle',center_model_mm=[0.,0.,0.],radius_mm=5.))
    snapshot=dict(features=[],planes=[],solids=[],needs_save=True,saved_file_sha256='a'*64,spec=spec)
    model=dict(FeatureByName=lambda name:dict(GetSpecificFeature2={}))
    monkeypatch.setattr(c,'_snapshot',lambda *a:(deepcopy(snapshot),model,[]));monkeypatch.setattr(c,'_read_sketch',lambda *a:dict(entities=[dict(type='circle',center_model_m=[0.,0.,0.],radius_m=.005)],model_to_sketch_transform=[1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.]))
    monkeypatch.setattr(c,'read_header',lambda raw,doc,read,typed,owner:(deepcopy(h),feature));monkeypatch.setattr(c,'_circle_feature',lambda *a:deepcopy(h));feature['IGetIslandCount']=0
    ctx=c.NativeCircularContext.__new__(c.NativeCircularContext);ctx.request=dict(sketch_spec=spec,owner_setup_native_id=71);ctx.v=dict(process_id=123,expected_document_path='part.sldprt',expected_feature_native_id=70,expected_feature_setup_native_id=71,parameter_operation_native_ids=[356,358],candidate_tool_native_id=249)
    ctx.loaded=dict(binding=dict(expected_operation_native_ids=[x['native_id'] for x in old]),state=dict(operations=old));ctx.new_operation_ids=[360];ctx.new_feature_id=80;ctx.new_own_tool_id=252;ctx.created_names=['C'];ctx.reference_consumers=[248,320];ctx.report=dict(captures=[]);ctx.app={};ctx.sw={};ctx.tlb='fixture';ctx.data=dict(authority=dict(definition_mode='selected_continue'));ctx.read=e['read'];ctx.typed=e['typed'];ctx.boundary=lambda:deepcopy(document);ctx.persist=lambda:None
    return ctx,e,feature


def test_composed_context_reads_reference_and_new_rough_actual_nc(composed):
    ctx,e,_=composed;state=ctx.capture('capture')
    assert state['capture_complete'] and state['extended_capture_complete']
    assert state['reference_header']['native_id']==70 and state['target_header']['native_id']==80
    assert [r['operation_native_id'] for r in state['reference_parameter_observation']['operation_parameters']]==[356,358]
    assert [r['operation_native_id'] for r in state['operation_parameters']]==[360]
    assert state['parameter_batch']['target_nc']['360']['feeds_compensation']['XYFeed']==500.
    assert state['reference_parameter_observation']['parameter_batch']['candidate_consumer_ids']==[248,320]


def test_composed_partial_extended_failure_revokes_complete_preserves_observed(composed):
    ctx,e,feature=composed;feature['IGetIslandCount']=1
    with pytest.raises(ValueError):ctx.capture('partial')
    assert ctx.report['partial']['capture_complete'] is False and ctx.report['partial']['extended_capture_complete'] is False
    assert ctx.report['partial']['target_geometry']['island_count']==1


def test_context_derives_generated_counts_only_for_actual_attempted_new_id(composed):
    ctx,e,_=composed;e['rows'][-1].update(toolpath_generated=True,toolpath_record_counts=[45]);e['ops'][360]['GetIsToolpathGenerated']=True
    with pytest.raises(ValueError):ctx.capture('unrequested')
    state=ctx.capture('generated',attempted_generation_ids={360});assert state['operations'][-1]['toolpath_record_counts']==[45] and state['parameter_capture_complete']


def test_context_preserves_all_old_rows_before_parameter_getters(composed):
    ctx,e,_=composed;e['rows'][0]['toolpath_record_counts']=[999]
    with pytest.raises(ValueError):ctx.capture('bad_old')
    assert ctx.report['bad_old']['capture_complete'] is False
