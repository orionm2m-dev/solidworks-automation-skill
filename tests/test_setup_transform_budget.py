from copy import deepcopy
import pytest
from test_setup_transform_observation import setup_env
from test_mill_operation_geometry import collection,env
from scripts import sw_cam_mill_operation_geometry as core
from scripts import sw_cam_setup_transform_observation as setup


def full_inventory(e,monkeypatch):
    """Exercise the real capture loop with 26 operations and four selected targets."""
    # Existing fixture bypasses five admitted type-info reads per object.
    # Charge the same five admission slots through allowed mocked QI calls;
    # existing metadata tests independently exercise the actual type-info ABI.
    original=setup.metadata_reader.metadata
    def charged_metadata(obj,*,typed,raw_call,boundary,row):
        for _ in range(5):typed(obj,'ICWVector')
        return original(obj,typed=typed,raw_call=raw_call,boundary=boundary,row=row)
    monkeypatch.setattr(setup.metadata_reader,'metadata',charged_metadata)
    machine=e['doc']['IGetMachine']; source=e['op0']; tool=e['tool']; features={}; ops={}; fs=[]; os=[]
    state=e['loaded']['state']; state['feature_setups']=[];state['operation_setups']=[];state['operations']=[]
    for si,count in enumerate((9,9,8)):
        sid=40+si;oid=50+si; fsetup={'_id':sid}; owned=[]; orows=[]
        for j in range(count):
            index=len(ops);fid=100+index;opid=200+index
            feature={'_id':fid,'Suppressed':False,'GetOwner':fsetup};features[fid]=feature;owned.append(feature)
            operation=dict(source,_id=opid,IGetAllFeatures=collection([feature]),IGetEnumToolpaths=collection([{'RecordCount':50}]),GetIsToolpathGenerated=True)
            ops[opid]=operation;orows.append(operation)
            row=dict(setup_index=si,setup_native_id=oid,operation_index=j,native_id=opid,mill_operation_type=0,base_operation_type=0,
                     suppressed=False,toolpath_generated=True,linked_feature_ids=[fid],toolpath_record_counts=[50],
                     assigned_tool=dict(native_id=20,is_mill_tool=True,native_read_complete=True,units_verified=False,holder_geometry_verified=False,
                                        tool_type_raw=1,cut_diameter_native=8.,protrusion_native=25.))
            state['operations'].append(row)
        fsetup['IGetEnumFeatures']=collection(owned);fs.append(fsetup)
        os.append(dict(_id=oid,IGetEnumOperations=collection(orows),GetSetup=fsetup))
        state['feature_setups'].append(dict(index=si,native_id=sid,feature_ids=[f['_id'] for f in owned]))
        state['operation_setups'].append(dict(index=si,native_id=oid,operation_count=count))
    state['operation_count']=26
    machine['IGetEnumSetups']=collection(fs);machine['IGetEnumOpSetups']=collection(os)
    e['doc']['GetCWObjectFromID']=lambda kind,fid:(features[fid],True)
    e['args']['anchor_operation_native_id']=200
    e['args']['targets']=[dict(operation_native_id=i,feature_native_id=100+i-200,feature_setup_native_id=40+(i-200)//9,operation_setup_native_id=50+(i-200)//9,mill_operation_type=0) for i in (200,209,218,225)]


def test_26_operation_four_target_complete_real_capture_budget(setup_env,monkeypatch):
    e=setup_env;full_inventory(e,monkeypatch)
    r=e['run'](observation_mode='setup_transform')
    assert r['readback_verified'] and r['setup_transform_complete'],r
    assert r['native_read_limit']==4096
    assert r['before']==r['after'] and len(r['after']['selected'])==4
    assert r['native_read_count']>2048 and r['native_read_count']<=4096
    assert e['calls'].count(setup.RAW_SETUP)==8
    assert not any(x.startswith(('Set','Save','Insert','Generate')) for x in e['calls'])


def test_prior_budget_reproduces_bounded_failure_without_replay(setup_env,monkeypatch):
    e=setup_env;full_inventory(e,monkeypatch);monkeypatch.setattr(core,'MAX_SETUP_TRANSFORM_READS',2048)
    r=e['run'](observation_mode='setup_transform')
    assert r['status']=='error' and not r['readback_verified'] and not r['setup_transform_complete']
    assert r['native_read_count']==2048 and r['native_read_limit']==2048
    assert r['messages']['disconnected'] and not r['mutation_attempted']


@pytest.mark.parametrize('mode',['tp_geometry','virtual_features'])
def test_other_modes_retain_2048_limit(setup_env,mode):
    e=setup_env
    if mode=='virtual_features':e['args']['targets']=e['args']['targets'][:1]
    r=e['run'](observation_mode=mode)
    assert r['native_read_limit']==2048


def test_five_targets_rejected_before_bootstrap(setup_env,monkeypatch):
    e=setup_env;full_inventory(e,monkeypatch);e['args']['targets'].append(dict(e['args']['targets'][0]))
    r=e['run'](observation_mode='setup_transform')
    assert r['status']=='error' and not e['calls'] and r['native_read_count']==0


@pytest.mark.parametrize('mode,limit',[('setup_transform',4096),('tp_geometry',2048),('virtual_features',2048)])
def test_actual_admission_stops_before_dispatch_at_mode_limit(setup_env,monkeypatch,mode,limit):
    e=setup_env
    if mode=='virtual_features':
        e['args']['targets']=e['args']['targets'][:1]
        monkeypatch.setattr(setup.metadata_reader,'preflight',lambda path:{'native_calls':0})
    def capture(app,loaded,v,*,read,typed,raw_call,boundary,state):
        for index in range(limit+1):read({'budget_probe':1},'budget_probe')
    monkeypatch.setattr(core,'capture',capture)
    r=e['run'](observation_mode=mode)
    assert r['status']=='error' and r['native_read_count']==limit and r['native_read_limit']==limit
    assert e['calls'].count('budget_probe')==limit
    assert r['messages']['disconnected'] and not r['mutation_attempted'] and not r['readback_verified']
