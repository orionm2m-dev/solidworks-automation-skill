"""Observed type2 geometry and two-field continuation regression tests."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib.util,json,os,sys
import pytest

STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE))
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import scripts
scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_neck_tool_continuation as m
from test_pocket_rough_exports import make_loaded

OBSERVED=json.loads((STAGE/'tests/fixtures/observed_neck_type2.json').read_text())
OLD=dict(EffCutlength=3.,ShoulderLength=19.75,ShankLength=24.16233542676,NoOfFlutes=2,CutDiameter=2.,ShoulderDia=1.95,
    ShankDia=4.,MillToolShankType=2,Protrusion=26.,OverallLen=55.)
NEW=dict(OLD,ShoulderLength=3.,ShankLength=19.75)
IDENTITY=dict(ToolIdentifier='SERIAL-D2-NECK',ToolVendor='Fixture',ToolDescription='Observed stepped envelope')


def corrected(full):
    result=deepcopy(full);result['mill_tool'].update(shoulder_length_native=3.,shank_length_native=19.75)
    for name in ('tool','shank'):
        for chain in result['profiles'][name]['chains']:
            for curve in chain['curves']:
                for key in ('start_native','end_native'):
                    z=curve[key][2]
                    if z==OLD['ShoulderLength']:curve[key][2]=NEW['ShoulderLength']
                    elif z==OLD['ShankLength']:curve[key][2]=NEW['ShankLength']
    return result


def holder_recipe(full,path):
    shift=full['holder']['holder_protrusion_native'];records=[]
    for chain in full['profiles']['holder']['chains']:
        for curve in chain['curves']:
            row=dict(kind='line' if curve['curve_type']==0 else 'arc',
                start_rz=[curve['start_native'][0],curve['start_native'][2]-shift],
                end_rz=[curve['end_native'][0],curve['end_native'][2]-shift])
            if curve['curve_type']==1:row['center_rz']=[curve['centre_native'][0],curve['centre_native'][2]-shift]
            records.append(row)
    return dict(file_path=str(path),records=records,pins=[m.common._pin(path)])


def test_actual_failed_profile_proves_observed_scalar_mapping():
    assert m.verify_profile(OBSERVED['profiles']['tool'],OLD)['status']=='PASS'
    assert m.verify_profile(OBSERVED['profiles']['shank'],OLD,shank_only=True)['status']=='PASS'
    with pytest.raises(ValueError):m.verify_profile(OBSERVED['profiles']['tool'],NEW)


def test_corrected_actual_chain_shape_accepts_zero_length_seam():
    full=corrected(OBSERVED)
    assert m.verify_profile(full['profiles']['tool'],NEW)['status']=='PASS'
    assert m.verify_profile(full['profiles']['shank'],NEW,shank_only=True)['status']=='PASS'
    for chain in full['profiles']['tool']['chains']:
        chain['curves']=[x for x in chain['curves'] if x['start_native']!=x['end_native']]
        chain['declared_curve_count']=len(chain['curves'])
    assert m.verify_profile(full['profiles']['tool'],NEW)['status']=='PASS'


@pytest.mark.parametrize('kind',['gap','wrong_radius','cutting_extension','cone','off_plane','incomplete','extra_cap'])
def test_corrected_profile_rejects_undercoverage_or_undeclared_shape(kind):
    full=corrected(OBSERVED);p=full['profiles']['tool'];curve=p['chains'][1]['curves'][1]
    if kind=='gap':curve['start_native'][2]+=.1
    elif kind=='wrong_radius':curve['start_native'][0]=.9
    elif kind=='cutting_extension':p['chains'][0]['curves'][3]['end_native'][2]=10.
    elif kind=='cone':curve['curve_type']=1
    elif kind=='off_plane':curve['end_native'][1]=.1
    elif kind=='incomplete':curve['read_complete']=False
    elif kind=='extra_cap':
        p['chains'][1]['curves'].append(dict(read_complete=True,curve_type=0,start_native=[0,0,10],end_native=[.975,0,10]));p['chains'][1]['declared_curve_count']+=1
    with pytest.raises(ValueError):m.verify_profile(p,NEW)


def test_reversed_and_split_lines_still_cover_whole_neck():
    p=corrected(OBSERVED)['profiles']['shank'];chain=p['chains'][0];curve=chain['curves'].pop(1)
    a,b=curve['start_native'],curve['end_native'];mid=[.975,0.,10.]
    chain['curves'] += [dict(curve,start_native=mid,end_native=a),dict(curve,start_native=b,end_native=mid)]
    chain['declared_curve_count']=len(chain['curves'])
    assert m.verify_profile(p,NEW,shank_only=True)['status']=='PASS'


@pytest.fixture
def batch(tmp_path):
    loaded,source=make_loaded(tmp_path);loaded['generated_face_operation_id']=267
    loaded['state']['operations'][6]['toolpath_record_counts']=[31196];loaded['generated_pocket']['record_counts']=[31196]
    before=m.rough.cl.validate_catalogue_authority(loaded)
    full=deepcopy(OBSERVED);holderfile=tmp_path/'holder.mh';holderfile.write_text('Public unchanged nominal holder fixture')
    full['holder']['name']=str(holderfile);holder=holder_recipe(full,holderfile)
    evidence=tmp_path/'enclosure.json';evidence.write_text('{}');pin=m.common._pin(evidence)
    recipe=dict(target=deepcopy(NEW),identity=deepcopy(IDENTITY),profile_basis=m.BASIS,source_pins=[pin])
    oldrecipe=dict(recipe,target=deepcopy(OLD),profile_basis='declared_conservative_envelope_requires_native_readback')
    observed=dict(full_tool=full,identity=deepcopy(IDENTITY));newfull=corrected(full)
    oldvalues=dict(OLD,**IDENTITY)
    actions={'AddNewTool3':dict(attempted=True,returned=True,pending=False,returned_interface_pointer=True),
        'SetFilePathForUserDefinedHolder':dict(attempted=True,returned=True,pending=False,native_return_type='int',native_return_value=0)}
    for name in m.original.FIELD_ORDER:actions['property:'+name]=dict(attempted=True,returned=True,pending=False,native_return_type='NoneType',native_return_value=None)
    failed=dict(scope=m.original.SCOPE,status='uncertain',readback_verified=False,model_saved=False,new_tool_native_id=273,
        issue={'type':'ValueError','locations':[{'function':'verify_profile'}]},messages={'subscribed':True},
        assignment_attempted=False,GTP_attempted=False,GOP_attempted=False,TechDB_write_attempted=False,
        recipe=oldrecipe,holder_recipe=holder,actions=actions,
        field_readbacks=[dict(property=name,requested=oldvalues[name],actual=oldvalues[name],readback_verified=True) for name in m.original.FIELD_ORDER],
        candidate_reads=[dict(stage='complete',capture_complete=True,batch={'read_scope_complete':True},state=full)],
        initial_observation={'route':m.prior.expected_route(loaded),'tools':deepcopy(before)})
    control=SimpleNamespace(bound=[],props=[],saved=0,closed=0,fail=None,drift=None)
    class Backend:
        def __init__(self):self.values=dict(OLD);self.new_id=None;self.current_state=deepcopy(loaded['state'])
        def start(self):pass
        def bind_candidate(self,ident):self.new_id=ident;control.bound.append(ident)
        def close(self):control.closed+=1
        def boundary(self):pass
        def finish(self):pass
        def refresh_dirty(self):pass
        def create(self,*args):raise AssertionError('Factory must never be called')
        def attach_holder(self,*args):raise AssertionError('Holder must never be assigned')
        def catalogue(self):return deepcopy(before)+[dict(native_id=273,tool_type_raw=1,CutDiameter=2.,Protrusion=26.000000000000004,StnNo=19.)]
        def snapshot(self,label):
            out=dict(route=m.prior.expected_route(loaded),tools=self.catalogue())
            if control.drift:control.drift(label,out)
            return out
        def field(self,name):return self.values[name]
        def property(self,name,value,pending):
            pending();control.props.append(name)
            if control.fail==name:raise RuntimeError('injected uncertain setter')
            self.values[name]=value
            if control.fail=='return':return 0
            if control.fail=='readback':self.values[name]+=.1
            return None
        def candidate(self,label):
            out=deepcopy(observed) if label=='reconcile' else dict(full_tool=deepcopy(newfull),identity=deepcopy(IDENTITY))
            if control.fail=='reconcile' and label=='reconcile':out['full_tool']['mill_tool']['shank_length_native']-=.1
            if control.fail=='profile' and label!='reconcile':out['full_tool']['profiles']['shank']['chains'][0]['curves'][1]['end_native'][2]-=.1
            if control.fail=='holder' and label!='reconcile':out['full_tool']['profiles']['holder']['chains'][0]['curves'][0]['end_native'][0]+=.1
            if control.fail=='save_drift' and label.startswith('save_'):out['full_tool']['mill_tool']['flute_count_raw']=3
            return out
        def save(self):control.saved+=1;return False if control.fail=='save' else 0
        def saved_hash(self,report):
            source.write_bytes(b'Synthetic saved corrected existing cutter')
            sha=m.common._pin(source)['sha256'];self.current_state['saved_file_sha256']=sha;return sha
    r=dict(scope=m.SCOPE,source_path=str(source),initial_source_sha256=m.common._pin(source)['sha256'],failed_receipt_pin={'sha256':'f'*64},
        new_tool_native_id=273,actions={},mutation_attempted=False,phase='prepared',status='error',**{k:False for k in m.FORBIDDEN})
    journal=m.Journal(r,tmp_path/'receipt.json',tmp_path/'once.json')
    return SimpleNamespace(loaded=loaded,source=source,recipe=recipe,holder=holder,failed=failed,backend=Backend(),control=control,journal=journal)


def run(b):return m.run_backend(b.backend,b.journal,b.loaded,b.failed,b.recipe,b.holder)


def test_two_fields_one_save_no_factory_no_holder_change(batch):
    original=deepcopy(batch.failed);m.validate_failed(batch.failed)
    r=run(batch);assert r['readback_verified'] is True,r.get('issue')
    assert batch.control.bound==[273] and batch.control.props==list(m.FIELD_ORDER) and batch.control.saved==1
    assert set(r['actions'])=={'property:ShoulderLength','property:ShankLength','SaveActiveDocument'}
    assert batch.failed==original and all(r[k] is False for k in m.FORBIDDEN)
    assert r['initial_observation']==r['configured_observation']==r['final_observation']
    with pytest.raises(ValueError):run(batch)
    assert batch.control.saved==1 and batch.control.props==list(m.FIELD_ORDER)


@pytest.mark.parametrize('stage',['reconcile','ShoulderLength','ShankLength','return','readback','profile','holder','save'])
def test_uncertain_failure_never_replays_or_unexpectedly_saves(batch,stage):
    batch.control.fail=stage;r=run(batch);assert r['readback_verified'] is False
    assert batch.control.saved==(1 if stage=='save' else 0)
    if r['mutation_attempted']:
        with pytest.raises(ValueError):run(batch)
    assert batch.control.bound==[273]


@pytest.mark.parametrize('kind',['prior_tool','old_path','assignment'])
def test_protected_18_tools_and_5_paths_block_save(batch,kind):
    def drift(label,out):
        if label!='corrected':return
        if kind=='prior_tool':out['tools'][0]['CutDiameter']+=.1
        elif kind=='old_path':out['route']['operations'][6]['toolpath_record_counts']=[31195]
        elif kind=='assignment':out['route']['operations'][7]['assigned_tool']['native_id']=273
    batch.control.drift=drift;r=run(batch);assert r['readback_verified'] is False and batch.control.saved==0


@pytest.mark.parametrize('key,value',[('EffCutlength',4.),('ShoulderDia',1.9),('Protrusion',27.)])
def test_recipe_cannot_expand_two_field_scope(batch,key,value):
    batch.recipe['target'][key]=value
    with pytest.raises(ValueError):run(batch)
    assert batch.control.bound==[] and batch.control.saved==0


def test_pending_or_previously_saved_failure_cannot_continue(batch):
    batch.failed['actions']['property:ShoulderLength']['pending']=True
    with pytest.raises(ValueError):m.validate_failed(batch.failed)
    batch.failed['actions']['property:ShoulderLength']['pending']=False;batch.failed['save_stage']={}
    with pytest.raises(ValueError):m.validate_failed(batch.failed)


def test_native_entrypoint_has_no_factory_or_holder_fallback():
    backend=object.__new__(m.NativeBackend)
    with pytest.raises(ValueError):backend.create(None,None)
    with pytest.raises(ValueError):backend.attach_holder(None,None)
    with pytest.raises(ValueError):backend.property('Protrusion',27.,lambda:None)
