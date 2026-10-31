"""Relieved-neck geometry and once-only candidate batch regression tests."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import os,sys,json
import pytest
STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE))
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import scripts
scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_neck_cutter_geometry as geo
from scripts import sw_cam_neck_tool_candidate as m
from test_pocket_rough_exports import make_loaded

TARGET=dict(EffCutlength=3.,ShoulderLength=19.75,ShankLength=24.16233542676,
    NoOfFlutes=2,CutDiameter=2.,ShoulderDia=1.95,ShankDia=4.,MillToolShankType=2,
    Protrusion=26.,OverallLen=55.)
IDENTITY=dict(ToolIdentifier='SERIAL-D2-NECK',ToolVendor='Fixture',ToolDescription='Explicit conservative envelope')


def profile(target,shank=False):
    curves=[]
    for a,b in geo.expected_segments(target,shank_only=shank):
        curves.append(dict(read_complete=True,curve_type=0,start_native=[a[0],0,a[1]],end_native=[b[0],0,b[1]]))
    curves.append(dict(read_complete=True,curve_type=0,start_native=[1,0,3],end_native=[.975,0,3]))
    return dict(status='observed',declared_chain_count=1,chains=[dict(read_complete=True,declared_curve_count=len(curves),curves=curves)])


def test_declared_neck_is_separate_from_cutting_length():
    assert geo.validate_target(TARGET)==TARGET
    assert geo.expected_segments(TARGET)[0]==((1.,0.),(1.,3.))
    assert geo.expected_segments(TARGET)[1]==((.975,3.),(.975,19.75))
    assert geo.verify_profile(profile(TARGET),TARGET)['status']=='PASS'
    assert geo.verify_profile(profile(TARGET,True),TARGET,shank_only=True)['status']=='PASS'


@pytest.mark.parametrize('key,value',[('EffCutlength',20),('ShoulderDia',2),('Protrusion',20),
    ('ShankLength',19.75),('MillToolShankType',1),('MillToolShankType',True),
    ('NoOfFlutes',2.),('OverallLen',float('nan')),('CutDiameter',0)])
def test_invalid_or_unsafe_seating_target_rejected(key,value):
    target=dict(TARGET);target[key]=value
    with pytest.raises(ValueError):geo.validate_target(target)


@pytest.mark.parametrize('mode',['short_neck','long_cutting','wrong_radius','arc','gap','plane','incomplete','extra_cap'])
def test_native_profile_must_match_full_declared_envelope(mode):
    p=profile(TARGET);c=p['chains'][0]['curves']
    if mode=='short_neck':c[1]['end_native'][2]-=1
    elif mode=='long_cutting':c[0]['end_native'][2]=20
    elif mode=='wrong_radius':c[1]['start_native'][0]=1
    elif mode=='arc':c[2]['curve_type']=1
    elif mode=='gap':c[2]['start_native'][2]+=.1
    elif mode=='plane':c[1]['start_native'][1]=.01
    elif mode=='incomplete':c[1]['read_complete']=False
    elif mode=='extra_cap':c.append(dict(read_complete=True,curve_type=0,start_native=[1,0,10],end_native=[0,0,10]));p['chains'][0]['declared_curve_count']+=1
    with pytest.raises(ValueError):geo.verify_profile(p,TARGET)


def test_split_reversed_lines_still_require_full_coverage():
    p=profile(TARGET);c=p['chains'][0]['curves'];original=c.pop(1)
    a,b=original['start_native'],original['end_native'];mid=[.975,0,10]
    c.extend([dict(original,start_native=mid,end_native=a),dict(original,start_native=b,end_native=mid)])
    p['chains'][0]['declared_curve_count']=len(c)
    assert geo.verify_profile(p,TARGET)['status']=='PASS'


@pytest.fixture
def batch(tmp_path,monkeypatch):
    loaded,source=make_loaded(tmp_path)
    loaded['generated_face_operation_id']=267
    loaded['state']['operations'][6]['toolpath_record_counts']=[31196]
    loaded['generated_pocket']['record_counts']=[31196]
    evidence=tmp_path/'manufacturer.json';evidence.write_text('{}')
    recipe=dict(target=deepcopy(TARGET),identity=deepcopy(IDENTITY),
        profile_basis='declared_conservative_envelope_requires_native_readback',source_pins=[m.common._pin(evidence)])
    holder=dict(file_path=str(tmp_path/'holder.mh'),pins=[])
    before=m.rough.cl.validate_catalogue_authority(loaded)
    control=SimpleNamespace(created=0,saved=0,props=[],closed=0,fail=None,drift=None)
    class Backend:
        def __init__(self):
            self.new_id=None;self.values={k:0 if type(v) is not str else 'unconfigured' for k,v in dict(TARGET,**IDENTITY).items()}
            self.current_state=deepcopy(loaded['state'])
        def start(self):pass
        def close(self):control.closed+=1
        def boundary(self):pass
        def finish(self):pass
        def refresh_dirty(self):pass
        def snapshot(self,label):
            out=dict(route=m.prior.expected_route(loaded),tools=self.catalogue())
            if control.drift:control.drift(label,out)
            return out
        def catalogue(self):
            out=deepcopy(before)
            if self.new_id is not None:out.append(dict(native_id=self.new_id,tool_type_raw=1,CutDiameter=2.,Protrusion=26.,StnNo=19.))
            return out
        def create(self,pending,returned):
            pending();control.created+=1
            if control.fail=='create':raise RuntimeError('unknown factory outcome')
            self.new_id=500;returned(object());return self.new_id
        def created_classification(self):return dict(MillToolType=1,MillToolSubType=3,EndRadius=0.)
        def field(self,name):return self.values[name]
        def property(self,name,value,pending):
            pending();control.props.append(name)
            if control.fail==name:raise RuntimeError('injected field failure')
            self.values[name]=value;return None
        def attach_holder(self,path,pending):
            pending()
            if control.fail=='holder':raise ValueError('holder alias')
            return 0
        def candidate(self,label):
            return dict(full_tool={'values':deepcopy(self.values),'tool_native_id':500},identity=deepcopy(IDENTITY))
        def save(self):
            control.saved+=1
            if control.fail=='save':return False
            return 0
        def saved_hash(self,report):
            source.write_bytes(b'Synthetic saved new neck tool, no native execution')
            digest=m.common._pin(source)['sha256']
            self.current_state['saved_file_sha256']=digest
            return digest
    def verify(full,target,holder_recipe):
        assert {k:full['values'][k] for k in TARGET}==TARGET
        if control.fail=='profile':raise ValueError('native profile does not implement the proposal')
        return dict(profile_verified=True,conservative_envelope_only=True,production_qualified=False)
    monkeypatch.setattr(m.geometry,'verify_candidate',verify)
    report=dict(scope=m.SCOPE,source_path=str(source),initial_source_sha256=m.common._pin(source)['sha256'],
        actions={},mutation_attempted=False,phase='prepared',status='error')
    journal=m.Journal(report,tmp_path/'receipt.json',tmp_path/'once.json')
    return SimpleNamespace(loaded=loaded,recipe=recipe,holder=holder,backend=Backend(),journal=journal,control=control,source=source,root=tmp_path)


def run(b):return m.run_backend(b.backend,b.journal,b.loaded,b.recipe,b.holder)


def test_new_candidate_only_then_one_save(batch):
    r=run(batch)
    assert r['readback_verified'] is True,r.get('issue')
    assert batch.control.created==batch.control.saved==1
    assert batch.control.props==list(m.FIELD_ORDER)
    assert r['initial_observation']['route']==r['final_observation']['route']
    assert len(r['final_observation']['tools'])==19
    assert r['final_observation']['tools'][:18]==r['initial_observation']['tools']
    assert r['assignment_attempted'] is r['GTP_attempted'] is r['GOP_attempted'] is False
    assert r['prior_full_profiles_reused'] is True and r['prior_full_profiles_freshly_reverified'] is False
    assert json.loads(batch.journal.marker.read_text())['scope']==m.SCOPE
    with pytest.raises(ValueError):run(batch)
    assert batch.control.created==batch.control.saved==1


@pytest.mark.parametrize('stage',['create','ShoulderDia','holder','profile','save'])
def test_partial_outcome_is_never_replayed(batch,stage):
    batch.control.fail=stage;r=run(batch)
    assert r['readback_verified'] is False and batch.control.created==1
    assert batch.control.saved==(1 if stage=='save' else 0)
    with pytest.raises(ValueError):run(batch)
    assert batch.control.created==1


@pytest.mark.parametrize('kind',['old_tool','route_count','route_binding'])
def test_protected_route_and_previous_tools_block_save(batch,kind):
    def drift(label,out):
        if label!='configured':return
        if kind=='old_tool':out['tools'][0]['CutDiameter']+=.1
        elif kind=='route_count':out['route']['operations'][6]['toolpath_record_counts']=[31195]
        elif kind=='route_binding':out['route']['operations'][6]['assigned_tool']['native_id']=500
    batch.control.drift=drift;r=run(batch)
    assert r['readback_verified'] is False and batch.control.saved==0


def test_factory_database_enum_is_not_native_tool_type():
    before=[dict(native_id=1,tool_type_raw=1)]
    with pytest.raises(ValueError):m.verify_catalogue(before,before+[dict(native_id=2,tool_type_raw=3)],2)
    m.verify_catalogue(before,before+[dict(native_id=2,tool_type_raw=1)],2)


@pytest.mark.parametrize('key,value',[('MillToolType',2),('MillToolSubType',2),('EndRadius',.1)])
def test_wrong_factory_classification_stops_before_properties_or_save(batch,key,value):
    batch.backend.created_classification=lambda:dict(MillToolType=1,MillToolSubType=3,EndRadius=0.,**{})|{key:value}
    r=run(batch)
    assert r['readback_verified'] is False and batch.control.created==1
    assert batch.control.props==[] and batch.control.saved==0
    assert r['created_classification'][key]==value
    with pytest.raises(ValueError):run(batch)


def test_flat_saved_receipt_loader_reuses_exact_parent_without_recursing_old_source(batch,monkeypatch):
    loaded=batch.loaded
    loaded['holder_recipe']=batch.holder
    p=dict(process_id=123,expected_document_path=str(batch.source),expected_source_sha256=m.common._pin(batch.source)['sha256'],
        qualification_only=True,acknowledge_disposable_copy=True,message_policy='vendor_default',receipt_path=str(batch.root/'complete.json'))
    recipepath=batch.root/'recipe.json';recipepath.write_text(json.dumps(batch.recipe))
    monkeypatch.setattr(m,'NativeBackend',lambda *a,**k:batch.backend)
    r=m.execute(object(),'fixture','fixture.tlb',p=p,loaded=loaded,recipe=batch.recipe,
        recipepin=m.common._pin(recipepath),audit={'all_resolved':True},marker=batch.root/'complete-once.json')
    assert r['readback_verified'] is True,r.get('terminal_issue') or r.get('issue')
    pin=m.common._pin(p['receipt_path'])
    actual=m.load_completed(pin['path'],pin['sha256'],process_id=123,expected_document_path=str(batch.source),
        expected_source_sha256=m.common._pin(batch.source)['sha256'])
    assert actual['authority_kind']==m.AUTHORITY
    assert actual['neck_tool_candidate']['native_id']==500
    assert len(actual['neck_tool_checkpoint']['catalogue'])==19
    assert actual['state']['operations']==loaded['state']['operations']
    assert actual['tool_checkpoint']==loaded['tool_checkpoint']
    assert all(actual['parent_pin'][key]==value for key,value in pin.items())
    assert actual['source_sha256']!=p['expected_source_sha256']
    assert batch.control.created==batch.control.saved==1


def test_recipe_does_not_silently_accept_unpinned_profile(batch):
    batch.recipe['source_pins']=[]
    with pytest.raises(ValueError):run(batch)
    assert batch.control.created==0
