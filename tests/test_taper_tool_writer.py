"""Independent orchestration tests; fake native boundaries, no COM dispatch."""
from copy import deepcopy
import importlib.util,json,os,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ['SOLIDWORKS_SKILL_ROOT']).resolve()
sys.path.insert(0,str(RUNTIME))
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value);return value
geo=module('scripts.sw_cam_taper_profile',STAGE/'scripts/sw_cam_taper_profile.py')
m=module('taper_writer_independent',STAGE/'scripts/sw_cam_taper_tool_candidate.py')
gf=module('taper_profile_fixture_independent',STAGE/'tests/test_taper_profile.py')
class FakeBackend:
    def __init__(self,loaded,recipe,report):
        self.loaded,self.recipe,self.report=loaded,recipe,report
        self.calls=[];self.fault=None;self.new=False;self.save_return=0;self.current_state=deepcopy(loaded['state'])
        self.parameters={k:(1 if k in m.INT_FIELDS else 'default' if k in m.TEXT_FIELDS else 1.) for k in m.TAPER_FIELDS+m.TOOL_FIELDS}
        self.parameters.update(TaperToolType=1,EndRadius=0.,MaxDia=2.,CutDiameter=2.)
        self.old=[dict(native_id=249,tool_type_raw=1,CutDiameter=6.,Protrusion=20.,StnNo=1.)]
    def call(self,label):
        self.calls.append(label)
        if self.fault==label:raise RuntimeError('Injected '+label)
    def start(self):self.call('start')
    def snapshot(self,label):
        self.call('snapshot:'+label);self.report['full_tool_snapshot_count']=self.report.get('full_tool_snapshot_count',0)+1
        out=dict(route=m.expected_route(self.loaded),units=deepcopy(self.loaded['finish_payload']['unit_record']),protected_tools={'249':deepcopy(self.loaded['finish_payload']['full_tool'])},tools=self.tools())
        if self.fault=='protected:'+label:out['protected_tools']['249']['corruption']=True
        if self.fault=='route:'+label:out['route']['operation_counts']=[999]
        return out
    def tools(self):return deepcopy(self.old)+([dict(native_id=900,tool_type_raw=8,CutDiameter=2.,Protrusion=self.parameters['Protrusion'],StnNo=1.)] if self.new else [])
    def catalogue(self):
        self.call('catalogue');out=self.tools()
        if self.fault=='catalogue_extra':out.append(dict(native_id=901,tool_type_raw=8))
        return out
    def create(self,pending,returned):pending();self.call('create');self.new=True;returned(object());return 900
    def fields(self):self.call('fields');return self.row(False)
    def field(self,name):
        self.call('field:'+name);return True if self.fault=='bool:'+name else self.parameters[name]
    def property(self,name,value,pending):pending();self.call('property:'+name);self.parameters[name]=value
    def refresh_dirty(self):self.call('refresh_dirty')
    def row(self,profiles=True):
        out=dict(native_id=900,tool_type_raw=8,parameters=deepcopy(self.parameters),profiles=gf.candidate() if profiles else {})
        if profiles:out['holder']=dict(GetName=self.recipe['holder_file_pin']['path'],profile={})
        return out
    def candidate(self,label):
        self.call('candidate:'+label);self.report['candidate_profile_capture_count']=self.report.get('candidate_profile_capture_count',0)+1;out=self.row()
        if self.fault=='geometry:'+label:out['profiles']=gf.candidate(radius=1.2)
        return out
    def attach_holder(self,path,pending):pending();self.call('holder');self.parameters['Protrusion']=31.;return 0
    def boundary(self):self.call('boundary')
    def save(self):self.call('save');return self.save_return
    def saved_hash(self,stage):self.call('saved_hash');self.current_state['saved_file_sha256']='b'*64;return 'b'*64
    def finish(self):self.call('finish')
    def close(self):self.call('close')
@pytest.fixture
def case(tmp_path,monkeypatch):
    units=dict(metric_document_scope_observed=True,unit='mm');old=dict(tool_native_id=249,validated='previous profile')
    loaded=dict(finish_payload=dict(full_tool=old,unit_record=units),holder_recipe={},settings={'face':{}},generated_face_operation_id=267,state=dict(features=[dict(geometry=dict(native_id=264))],operations=[dict(native_id=267,assigned_tool={'native_id':249})],feature_setups=[dict(native_id=112)],operation_setups=[dict(native_id=113)],operation_counts=[760]))
    holder=tmp_path/'holder.mh';holder.write_text('fixture')
    fields=dict(EndDia=.6,TaperLength=.7,TaperAngle=45.,ShankDia=3.,OverallLength=40.,MillToolShankType=0,ShoulderLength=.7,NoOfFlutes=4,Protrusion=20.,ToolIdentifier='2.FC.06020090.1',ToolVendor='Mikron',ToolDescription='Conservative qualification')
    recipe=dict(proposed_fields=fields,profile_contract=deepcopy(geo.CONTRACT),holder_file_pin={'path':str(holder),'sha256':m._file_hash(holder)},api_angle_status='proposed_value_requires_immediate_profile_proof',noncutting_status='conservative_envelope_not_factory_geometry')
    report=dict(phase='prepared',status='running',source_path=str(tmp_path/'saved.SLDPRT'),initial_source_sha256='a'*64,actions={},readback_verified=False,mutation_attempted=False)
    j=m.Journal(report,tmp_path/'receipt.json',tmp_path/'marker.json');b=FakeBackend(loaded,recipe,report)
    monkeypatch.setattr(m,'verify_holder_profile',lambda *args:{'holder_test_scope':'separate_reader_suite'})
    return SimpleNamespace(b=b,j=j,loaded=loaded,recipe=recipe,r=report)
def run(c):return m.run_backend(c.b,c.j,c.loaded,c.recipe)
def test_success_three_profiles_three_snapshots_and_one_save(case):
    r=run(case);assert r['readback_verified'] is True,r.get('issue')
    assert r['full_tool_snapshot_count']==3 and r['candidate_profile_capture_count']==3
    assert [x for x in case.b.calls if x.startswith('snapshot:')]==['snapshot:initial','snapshot:configured','snapshot:save_after']
    assert [x for x in case.b.calls if x.startswith('candidate:')]==['candidate:cone_proof','candidate:configured','candidate:save_after']
    assert case.b.calls.count('create')==1 and case.b.calls.count('save')==1
    assert case.b.calls.index('holder')<case.b.calls.index('property:Protrusion') and case.b.calls.count('property:Protrusion')==1
    assert case.b.calls.index('candidate:cone_proof')>case.b.calls.index('field:TaperAngle')
    assert case.b.calls[-2:]==['finish','close'] and all(a['returned'] and not a['pending'] for a in r['actions'].values())
@pytest.mark.parametrize('fault',['protected:initial','route:initial','start'])
def test_initial_mismatch_stops_before_create(case,fault):
    case.b.fault=fault;r=run(case);assert r['readback_verified'] is False and r['status']=='error'
    assert 'create' not in case.b.calls and 'save' not in case.b.calls and not case.j.marker.exists()
@pytest.mark.parametrize('fault',['create','property:EndDia','holder','save'])
def test_unknown_mutation_preserves_pending_and_does_not_repeat(case,fault):
    case.b.fault=fault;r=run(case);assert r['status']=='uncertain' and r['readback_verified'] is False
    label={'create':'AddNewTool3','holder':'SetFilePathForUserDefinedHolder','save':'SaveActiveDocument'}.get(fault,fault)
    assert r['actions'][label]['pending'] is True and r['actions'][label]['returned'] is False and case.b.calls.count(fault)==1
    marker=json.loads(case.j.marker.read_text());assert marker['actions'][label]['pending'] is True and marker['automatic_replay'] is False
    assert case.b.calls[-1]=='close'
@pytest.mark.parametrize('fault',['catalogue_extra','bool:NoOfFlutes','geometry:cone_proof','geometry:configured','protected:configured'])
def test_post_create_violation_prevents_save(case,fault):
    case.b.fault=fault;r=run(case);assert r['status']=='uncertain' and not r['readback_verified'] and 'save' not in case.b.calls
    if fault=='geometry:cone_proof':assert 'holder' not in case.b.calls and 'property:ShankDia' not in case.b.calls
@pytest.mark.parametrize('fault',['geometry:save_after','protected:save_after','snapshot:save_after','finish'])
def test_post_save_failure_never_claims_success_or_replays(case,fault):
    case.b.fault=fault;r=run(case);assert not r['readback_verified'] and r['status']=='uncertain'
    assert case.b.calls.count('save')==1 and r['saved_source_sha256']=='b'*64
@pytest.mark.parametrize('value',[False,True,None,1,'0'])
def test_save_hresult_is_strict_zero_int(case,value):
    case.b.save_return=value;r=run(case);assert not r['readback_verified'] and r['status']=='uncertain'
    assert case.b.calls.count('save')==1 and 'saved_hash' not in case.b.calls
@pytest.mark.parametrize('label',['AddNewTool3','property:EndDia','SaveActiveDocument'])
def test_journal_never_claims_same_action_twice(case,label):
    case.j.pending(label)
    with pytest.raises(ValueError):case.j.pending(label)
    assert len(case.r['actions'])==1

def test_existing_marker_stops_before_create(case):
    case.j.marker.write_text('{"prior":true}');r=run(case)
    assert not r['readback_verified'] and 'create' not in case.b.calls and json.loads(case.j.marker.read_text())=={'prior':True}

def test_scalar_only_default_does_not_read_profiles():
    seen=[];raw=object();doc=object()
    values={name:(1 if name in m.INT_FIELDS else '' if name in m.TEXT_FIELDS else 0.) for name in m.TAPER_FIELDS+m.TOOL_FIELDS}
    values.update(TaperToolType=1,ToolType=8,IsMillTool=True,GetCWObjectID=(900,True))
    def read(obj,name,*args):seen.append(name);return values[name]
    row=m.read_taper(raw,doc,read,lambda obj,name:obj,{},profiles=False)
    assert row['profiles']=={} and not any(name in seen for name in ('GetToolProfile','GetShankProfile','IGetMillToolHolder'))

