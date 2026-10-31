"""Regression tests using a sanitized saved pocket-pair schema projection."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import json
import math
import pytest

ROOT=Path(__file__).resolve().parent.parent
MODULE=ROOT/'scripts/sw_cam_pocket_pair_read.py'
spec=importlib.util.spec_from_file_location('pocket_pair_under_test',MODULE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
FIXTURE=json.loads((Path(__file__).parent/'pocket79_saved_fixture.json').read_text(encoding='utf-8'))

class Ref:
    def __init__(self,ident=0,interface='',values=None):self.ident=ident;self.interface=interface;self.values=values or {}

def fake_binding(state):
    state=deepcopy(state)
    ops={v['native_id']:v for v in state['operations']}
    geometry=next(v['geometry'] for v in state['features'] if v['geometry']['native_id']==79)
    calls=[]
    def typed(obj,name):return Ref(obj.ident,name,obj.values)
    def read(obj,name,*args):
        calls.append((name,args))
        if name=='GetCWObjectFromID':return Ref(args[1]),True
        if name=='GetCWObjectID':return args[0].ident,True
        if name=='Count':return len(obj.values['items'])
        if name=='Item':return obj.values['items'][args[0]]
        if name=='IGetAllFeatures':return Ref(values={'items':[Ref(i) for i in ops[obj.ident]['linked_feature_ids']]})
        if name=='IGetEnumToolpaths':return Ref(values={'items':[Ref(values={'count':v}) for v in ops[obj.ident]['toolpath_record_counts']]})
        if name=='RecordCount':return obj.values['count']
        if name=='IGetTool':return Ref(ops[obj.ident]['assigned_tool']['native_id'])
        if name=='IsMillTool':return True
        if name=='ToolType':return 1
        if name=='CutDiameter':return 2.0
        if name=='Protrusion':return 20.0
        if name=='OpernType':return ops[obj.ident]['mill_operation_type' if obj.interface=='ICWMillOperation' else 'base_operation_type']
        if name=='GetIsToolpathGenerated':return ops[obj.ident]['toolpath_generated']
        if name=='Suppressed':return ops[obj.ident]['suppressed'] if obj.ident in ops else geometry['suppressed']
        if name=='GetOwner':return Ref(69)
        fields={'VolumeType':'volume_type','SubType':'subtype_raw','Shape':'shape_raw','FeatureName':'name',
            'Axis':'axis_native','Depth':'depth_native','GetBoundParams':'bounds_native','GetStartPosition':'start_native'}
        if name in fields:return geometry[fields[name]]
        if name=='IGetMachine':return Ref(900)
        if name=='MachType':return 1
        if name=='IGetEnumOpSetups':return Ref(values={'items':[Ref(v['native_id']) for v in state['operation_setups']]})
        if name=='IGetEnumOperations':return Ref(values={'items':[Ref(v['native_id']) for v in state['operations'] if v['setup_native_id']==obj.ident]})
        raise AssertionError(name)
    return Ref(),read,typed,calls


def test_actual_saved_schema_pair_binding_without_contours_or_catalogue():
    loaded=deepcopy(FIXTURE);doc,read,typed,calls=fake_binding(loaded['state'])
    out,handles=m.read_binding(doc,loaded,read=read,typed=typed)
    assert [v['native_id'] for v in out['operations']]==[143,144]
    assert out['setup']['operation_ids']==[143,144,195,196,267,247,248,271]
    assert handles[143].ident==143 and handles['feature'].ident==79
    assert not {'GetCurveAtIndex','GetAllTools','GetHolderSpec'} & {c[0] for c in calls}

@pytest.mark.parametrize('change',[lambda s:s['operations'][0].update(toolpath_generated=True),
    lambda s:s['operations'][0].update(linked_feature_ids=[78]),
    lambda s:s['operations'][1]['assigned_tool'].update(native_id=146),
    lambda s:s['features'][0]['geometry'].update(depth_native=4.9),
    lambda s:s['operations'].reverse()])
def test_actual_binding_rejects_changed_target_or_order(change):
    loaded=deepcopy(FIXTURE);actual=deepcopy(loaded['state']);change(actual)
    doc,read,typed,calls=fake_binding(actual)
    with pytest.raises(ValueError):m.read_binding(doc,loaded,read=read,typed=typed)


def association_fakes(*,failure=None,curve_kind='circle'):
    log=[]
    def typed(obj,name):return Ref(obj.ident,name,obj.values)
    def read(obj,name,*args):
        log.append(name)
        if name=='FeatureByName':return None if failure=='absent' else Ref(values={'name':args[0]})
        if name=='Name':return obj.values['name']
        if name=='GetTypeName2':return 'ProfileFeature' if failure=='not_attribute' else 'Attribute'
        if name=='GetSpecificFeature2':return Ref()
        if name=='GetEntityState':return args[0]==2 if failure=='ambiguous' else False
        if name=='GetEntity':return None if failure=='null' else Ref()
        if name=='GetType':return 1 if failure=='edge' else 2
        if name=='GetSurface':return Ref()
        if name=='IsPlane':return failure!='nonplanar'
        if name=='PlaneParams':return (0.,0.,1.,0.,0.,.0075)
        if name=='GetBox':return (-.0228,-.0228,.0075,.0228,.0228,.0075)
        if name=='GetLoops':return (Ref(),)
        if name=='IsOuter':return True
        if name=='GetEdges':return (Ref(),)
        if name=='GetCurveParams3' or name=='GetCurve':return Ref()
        if name in ('StartPoint','EndPoint'):return (.0228,0.,.0075)
        if name=='UMinValue':return 0.
        if name=='UMaxValue':return 2*math.pi
        if name=='Sense':return True
        if name=='IsLine':return curve_kind=='line'
        if name=='IsCircle':return curve_kind=='circle'
        if name=='CircleParams':return (0.,0.,.0075,0.,0.,1.,.0228)
        if name=='LineParams':return (0.,0.,.0075,1.,0.,0.)
        raise AssertionError(name)
    return read,typed,log

@pytest.mark.parametrize('kind',['line','circle'])
def test_associations_record_exact_model_geometry_not_cam_transform(kind):
    read,typed,log=association_fakes(curve_kind=kind);diagnostic={}
    out=m.read_face_associations(Ref(),FIXTURE['names'],read=read,typed=typed,diagnostic=diagnostic)
    assert out['all_six_analytic_geometry_complete'] is True and out['total_edges']==6
    assert diagnostic['complete'] is True and out['geometric_role_mapping_verified'] is False
    assert out['rows'][0]['plane_model_native']==[0.,0.,1.,0.,0.,.0075]
    assert all(r['cam_chain_transform_inferred'] is False for r in out['rows'])

@pytest.mark.parametrize('failure,forbidden',[('absent','GetTypeName2'),('not_attribute','GetSpecificFeature2'),
    ('ambiguous','GetEntity'),('null','GetType'),('edge','GetSurface'),('nonplanar','PlaneParams')])
def test_unavailable_association_preserved_without_fabricating_face(failure,forbidden):
    read,typed,log=association_fakes(failure=failure)
    out=m.read_face_associations(Ref(),FIXTURE['names'],read=read,typed=typed,diagnostic={})
    assert len(out['rows'])==6 and out['all_six_faces_observed'] is False
    assert all(r['status']=='unresolved' for r in out['rows'])
    assert forbidden not in log


def test_other_curve_not_claimed_analytically_complete():
    read,typed,_=association_fakes(curve_kind='spline')
    out=m.read_face_associations(Ref(),FIXTURE['names'],read=read,typed=typed,diagnostic={})
    assert out['all_six_faces_observed'] is True and out['all_six_analytic_geometry_complete'] is False


def test_finish_reader_only_settings_no_tool_profile():
    calls=[]
    def read(obj,name,*args):calls.append(name);return 0.0
    out=m.read_finish_parameters(Ref(),Ref(),read=read,typed=lambda o,n:o)
    assert len(out)==24
    assert not {'IGetTool','IGetMillToolHolder','GetHolderSpec','GetAllTools'}&set(calls)


def test_real_profile_header_schema_is_reused():
    assert FIXTURE['headers']['native_id']==79
    assert FIXTURE['headers']['sketch_names']['value']==FIXTURE['names']
    assert FIXTURE['headers']['end_conditions']['GetEndCondition1']['depth_native']==4.800001


def test_compact_read_progress_does_not_flush_full_snapshot_per_getter(tmp_path):
    calls=[];state={'member':'','returned':False,'read_index':0}
    with m.journal.ReadProgressJournal(full_persist=lambda:calls.append('full'),progress_path=tmp_path/'progress.json',
        describe=lambda:state,max_updates=100,protected_paths=[tmp_path/'source']) as progress:
        for i in range(45):state.update(member='read',returned=True,read_index=i);progress.read()
        progress.complete()
    assert calls==['full','full']
    assert json.loads((tmp_path/'progress.json').read_text())['status']=='completed'


def test_changed_parameter_shape_stops_with_prefix_diagnostic():
    calls=[];diag={}
    def read(obj,name,*args):
        calls.append(name)
        return 'bad-long' if name=='GetEntryExitType' else 0.0
    with pytest.raises(ValueError):m.rough.read_rough_entry_parameters(Ref(),Ref(),read=read,typed=lambda o,n:o,diagnostic=diag)
    assert calls==['GetEntryExitType'] and diag['read_complete'] is False

@pytest.mark.parametrize('value',[(1.,2.),(0.,0.,float('nan')),(True,0.,1.)])
def test_geometry_vector_type_and_finiteness_fail_closed(value):
    with pytest.raises(ValueError):m.vector(value,3)

def test_batch_rejects_out_of_scope_setter_and_invalidates():
    b=object.__new__(m.PocketReadBatch);b._invalid=False;b._completed=True;b._known_objects=set()
    with pytest.raises(ValueError):b.read(object(),'SetTool',1)
    assert b._invalid is True and b._completed is False


def test_batch_rejects_unretained_argument_and_invalidates():
    b=object.__new__(m.PocketReadBatch);b._invalid=False;b._completed=True;b._known_objects=set()
    with pytest.raises(ValueError):b.read(object(),'GetMachiningDepth',object())
    assert b._invalid is True and b._completed is False


@pytest.mark.parametrize('z_value',[(2.0,False),(50.0,True)])
def test_nc_z_feed_preserves_percent_flag_without_deprecated_pointer(monkeypatch,z_value):
    monkeypatch.setattr(m.nc,'read_planes',lambda *a,**k:{})
    monkeypatch.setattr(m.planes,'read_plane_parameters',lambda *a,**k:{})
    calls=[]
    def read(obj,name,*args):
        calls.append(name)
        if name=='IGetNCParam':return Ref()
        if name=='GetZFeedrate2':assert not args;return z_value
        return 1.0 if name in ('GetSpndlSpeed','XYFeed') else 0
    out=m.read_nc_settings(Ref(),Ref(),read=read,typed=lambda o,n:o,pointer_read=None,diagnostic={},persist=lambda:None)
    assert out['z_feed']['value_native']==z_value[0] and out['z_feed']['percentage'] is z_value[1]
    assert 'GetZFeedrate' not in calls


def level_callbacks(*,null_toolpath=False):
    calls=[];feature=Ref(79);op=Ref(143);dispatch=Ref(79,'IDispatch')
    def typed(obj,name):return Ref(obj.ident,name,obj.values)
    def read(obj,name,*args):
        calls.append((obj.interface,name,args))
        if name=='GetMachiningDepth':assert args==(dispatch,);return 4.800001
        if name=='GetOverrideMachiningDepth':assert args==(dispatch,);return False
        if name=='GetToolpathParam':return None if null_toolpath else Ref(1001)
        if name=='GetToolpathParameters':return (True,False,True,1,False,7.499999,12.3)
        if name=='GetSetupParameters':return Ref(1002),Ref(1003),Ref(1004)
        if name=='GetCoordinates':return (0.0,0.0,26.0) if obj.interface=='ICWPosition' else (0.0,0.0,1.0)
        raise AssertionError(name)
    def feature_dispatch(obj):assert obj is feature;return dispatch
    return op,feature,dict(read=read,typed=typed,feature_dispatch=feature_dispatch),calls


def test_levels_adapter_executes_real_shared_helper_with_interface_and_validator_keywords():
    # Exercise the imported production helper, including interface=True at
    # GetToolpathParam and validator=_setup_interfaces at GetSetupParameters.
    op,feature,callbacks,calls=level_callbacks()
    out=m.read_levels(op,feature,**callbacks)
    assert out['levels']['machining_depth_native']==4.800001
    assert out['levels']['override_machining_depth'] is False
    assert out['levels']['toolpath_parameters']==dict(use_setup_definition_for_top_Z=True,
        use_minimum_Z=False,adjust_feature_height=True,first_cut_Z_type_raw=1,
        use_setup_definition_for_bottom_Z=False,minimum_Z_native=7.499999,start_Z_native=12.3)
    assert out['setup']['origin_native']==[0.0,0.0,26.0]
    assert out['setup']['axis_native']==[0.0,0.0,1.0]
    assert [row[1] for row in calls]==['GetMachiningDepth','GetOverrideMachiningDepth','GetToolpathParam',
        'GetToolpathParameters','GetSetupParameters','GetCoordinates','GetCoordinates']


def test_levels_adapter_real_helper_null_interface_stops_before_downstream_getter():
    op,feature,callbacks,calls=level_callbacks(null_toolpath=True)
    with pytest.raises(ValueError,match='Non-null level interface'):
        m.read_levels(op,feature,**callbacks)
    assert [row[1] for row in calls]==['GetMachiningDepth','GetOverrideMachiningDepth','GetToolpathParam']