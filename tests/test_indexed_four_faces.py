"""Optional face associations use observed indexed names and guarded read callbacks only."""
from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_mill_profile_indexed as m
from test_sw_cam_pocket_pair_read import Ref,association_fakes
from profile_probe_fixtures import feature
from test_sw_cam_mill_profile_indexed import route,wrapper
from test_mcp_cam_mill_profile_indexed import probe,MODEL,TOOL

NAMES=['Outer']+['Actual face '+str(i) for i in range(4)]
MAPPING=[dict(native_index=i,expected_sketch_name=n)for i,n in enumerate(NAMES)]

@pytest.mark.parametrize('names,count,mapping',[(NAMES[1:],4,MAPPING),(None,5,MAPPING[:1])])
def test_optional_names_are_explicit_or_absent(names,count,mapping):
    m.validate_four_face_names(names,mapping,count)

@pytest.mark.parametrize('names,count,mapping',[(NAMES[1:4],4,MAPPING),(NAMES[1:]+['X'],4,MAPPING),(['Actual face 0','actual FACE 0','B','C'],4,MAPPING),(NAMES[1:],5,MAPPING),(NAMES[1:],True,MAPPING),(NAMES[1:],4,MAPPING[:4]),(['other']+NAMES[2:],4,MAPPING),([None]+NAMES[2:],4,MAPPING),(['x\x00']+NAMES[2:],4,MAPPING)])
def test_optional_scope_rejects_ambiguous_count_names_or_unmapped_face(names,count,mapping):
    with pytest.raises(ValueError):m.validate_four_face_names(names,mapping,count)

@pytest.fixture
def face_route(feature):
    feature.selected['island_count']=4;feature.mill.IGetIslandCount=lambda:4
    feature.profile.GetSketchCount=lambda:5;feature.profile.GetSketchNameList=lambda:tuple(NAMES)
    anchor=dict(headers=feature.run(),names=deepcopy(NAMES))
    result=dict(read_complete=True,indexed_chains=[dict(r,name_matches=True,read_complete=True)for r in MAPPING])
    r,sw_typed,log=association_fakes();lookups=[];sw=N(ActiveDoc=Ref());boundary=Mock();diag={};progress=Mock()
    def read(obj,name,*args):
        if obj is sw:return sw.ActiveDoc
        if isinstance(obj,Ref):
            if name=='FeatureByName':lookups.append(args[0])
            return r(obj,name,*args)
        return feature.read(obj,name,*args)
    def run():return m.read_indexed_face_associations(sw,feature.doc,names=NAMES[1:],result=result,selected=feature.selected,anchor=anchor,read=read,typed=feature.typed,sw_typed=sw_typed,boundary=boundary,diagnostic=diag,progress=progress)
    return N(**locals())

def test_actual_named_chains_bind_four_face_lookups_with_headers_before_after(face_route):
    r=face_route.run()
    assert r['all_four_faces_observed'] is True and face_route.lookups==NAMES[1:]
    assert face_route.diag['headers_before']['state']==face_route.diag['headers_after']['state']==face_route.anchor['headers']
    assert [c.args[0]for c in face_route.boundary.call_args_list]==['face_associations_before']+['face_before:'+n for n in NAMES[1:]]+['face_associations_after']
    assert r['geometric_role_mapping_verified'] is False

@pytest.mark.parametrize('damage',['incomplete','mismatched','anchor_names','headers'])
def test_changed_cam_binding_stops_before_any_face_lookup(face_route,damage):
    if damage=='incomplete':face_route.result['read_complete']=False
    if damage=='mismatched':face_route.result['indexed_chains'][2]['name_matches']=False
    if damage=='anchor_names':face_route.anchor['names'][2]='different'
    if damage=='headers':face_route.feature.owner.id=999
    with pytest.raises(ValueError):face_route.run()
    assert face_route.lookups==[]

def test_header_change_after_four_faces_revokes_result(face_route):
    real=face_route.read
    def changed(obj,name,*args):
        v=real(obj,name,*args)
        if name=='CircleParams' and len(face_route.lookups)==4:face_route.feature.owner.id=999
        return v
    with pytest.raises(ValueError):m.read_indexed_face_associations(face_route.sw,face_route.feature.doc,names=NAMES[1:],result=face_route.result,selected=face_route.feature.selected,anchor=face_route.anchor,read=changed,typed=face_route.feature.typed,sw_typed=face_route.sw_typed,boundary=face_route.boundary,diagnostic=face_route.diag,progress=face_route.progress)
    assert face_route.lookups==NAMES[1:] and face_route.diag['faces']['complete'] is True

def test_unresolved_face_preserves_diagnostic_and_stops_acceptance(face_route):
    real=face_route.read
    def absent(obj,name,*args):return None if name=='FeatureByName' and args[0]==NAMES[2] else real(obj,name,*args)
    with pytest.raises(ValueError,match='four named planar'):m.read_indexed_face_associations(face_route.sw,face_route.feature.doc,names=NAMES[1:],result=face_route.result,selected=face_route.feature.selected,anchor=face_route.anchor,read=absent,typed=face_route.feature.typed,sw_typed=face_route.sw_typed,boundary=face_route.boundary,diagnostic=face_route.diag,progress=face_route.progress)
    assert face_route.diag['faces']['rows'][1]['reason']=='exact_named_feature_absent'
    assert face_route.result['face_associations']['all_four_faces_observed'] is False

def test_generated_interface_pin_change_rejected_before_capture(tmp_path):
    p=tmp_path/'generated.py';p.write_text('before');bundle={'pins':[{'path':str(p),'sha256':m._file_hash(p)}]}
    m.verify_face_interface_pins(bundle);p.write_text('after')
    with pytest.raises(ValueError):m.verify_face_interface_pins(bundle)

def test_public_optional_field_reaches_same_locked_handler_without_reindexing(probe):
    data=probe.data|{'expected_island_count':4,'index_mapping':MAPPING,'face_association_names':NAMES[1:]}
    probe.ns[TOOL](MODEL(**data))
    assert probe.core.call_args.kwargs['face_association_names']==NAMES[1:]
    assert probe.core.call_args.kwargs['index_mapping']==MAPPING
    assert probe.registry[TOOL]['annotations']['readOnlyHint'] is True

def test_legacy_schema_default_requests_no_faces(probe):
    probe.ns[TOOL](MODEL(**probe.data))
    assert probe.core.call_args.kwargs.get('face_association_names') is None

@pytest.mark.parametrize('names',[NAMES[:3],['no such']+NAMES[2:],[True]+NAMES[2:],['A','a','B','C']])
def test_schema_rejects_bad_faces_before_target(probe,names):
    with pytest.raises(ValueError):MODEL(**(probe.data|{'expected_island_count':4,'index_mapping':MAPPING,'face_association_names':names}))
    probe.target.assert_not_called();probe.core.assert_not_called()


@pytest.mark.parametrize('mode',['qi_budget','generated_file_change'])
def test_optional_sw_qi_obeys_shared_budget_and_generated_file_guard(route,tmp_path,monkeypatch,mode):
    sw=N(GetProcessID=lambda:731);app=N(IGetActiveDoc=lambda:route.feature.doc)
    monkeypatch.setattr(m,'raw_part_identity',lambda *_:deepcopy(route.doc));monkeypatch.setattr(m,'_typed',lambda raw,name,path:raw)
    monkeypatch.setattr(m,'read_profile_indexed_chains',lambda *a,**kw:{'read_complete':True,'indexed_chains':[]})
    generated=tmp_path/'generated.py';generated.write_text('original');calls=[]
    def cls(raw):
        calls.append('SW_QI')
        if mode=='generated_file_change':generated.write_text('changed')
        return object()
    bundle={'classes':{'IPartDoc':cls},'pins':[{'path':str(generated),'sha256':m._file_hash(generated)}]}
    def associate(*args,**kw):kw['sw_typed'](N(_oleobj_=object()),'IPartDoc')
    monkeypatch.setattr(m,'read_indexed_face_associations',associate)
    if mode=='qi_budget':monkeypatch.setattr(m,'MAX_READS',2)
    diagnostic={}
    with pytest.raises(ValueError):m.capture_profile_indexed_chains(sw,app,'tlb',process_id=731,
        expected_document_path=str(route.part),expected_source_sha256=route.source,baseline=route.doc,
        selected=route.feature.selected,index_mapping=route.mapping,anchor=route.anchor,check=lambda:None,
        diagnostic=diagnostic,progress=lambda:None,face_association_names=NAMES[1:],face_interfaces=bundle)
    assert calls==([] if mode=='qi_budget' else ['SW_QI'])
    assert diagnostic['native_read_count']==(2 if mode=='qi_budget' else 3)


def test_optional_wrapper_revokes_face_success_when_second_observation_changes(wrapper,monkeypatch):
    route=wrapper.route
    route.names.pop();route.mapping.pop();route.feature.selected['island_count']=4
    route.feature.mill.IGetIslandCount=lambda:4;route.feature.profile.GetSketchCount=lambda:5
    state=route.feature.run();route.data.update(before=state,after=deepcopy(state),state_sha256=m._digest(state))
    sha=route.write();wrapper.kwargs.update(profile_headers_receipt_sha256=sha,expected_island_count=4)
    wrapper.state['face_associations']={'all_four_faces_observed':True,'all_four_analytic_geometry_complete':True,'rows':[{'name':n}for n in route.names[1:]]}
    monkeypatch.setattr(m,'prepare_face_interfaces',lambda:{'classes':{},'pins':[]})
    def change():
        if len(wrapper.calls)==2:wrapper.state['face_associations']['rows'][0]['name']='changed'
    wrapper.knobs['capture']=change
    result=wrapper.run(face_association_names=route.names[1:])
    assert result['status']=='error' and result['face_associations_read_complete'] is False and result['readback_verified'] is False
