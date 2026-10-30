"""Legacy-tool preservation from actual mixed inventory; fake COM, real decoder."""
from copy import deepcopy
import importlib.util,os,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ['SOLIDWORKS_SKILL_ROOT']).resolve();sys.path.insert(0,str(RUNTIME))
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value);return value
module('scripts.sw_cam_taper_profile',STAGE/'scripts/sw_cam_taper_profile.py')
m=module('legacy_taper_reader_under_test',STAGE/'scripts/sw_cam_taper_tool_candidate.py')
ACTUAL_TYPES=[(253,6),(257,3),(258,9),(259,18),(260,19),(261,20),(197,6),(198,2)]
class Native:
    def __init__(self,**values):self.values=values
class Fixture:
    def __init__(self,tid=253,kind=6):
        self.reads=[];self.qis=[];self.fault=None
        self.generic=dict(native_id=tid,tool_type_raw=kind,CutDiameter=6.,Protrusion=22.5,StnNo=6.)
        def chain():
            a=Native(GetCoordinates=[.5,0.,0.]);b=Native(GetCoordinates=[.5,0.,10.])
            curve=Native(GetTypeOfCurve=0,GetStart=a,GetEnd=b)
            return Native(IGetNumChains=1,GetNumOfCurves=1,GetCurveAtIndex=curve,IGetNextChain=None)
        self.tool_profile,self.shank_profile,self.holder_profile=chain(),chain(),chain()
        self.holder=Native(GetHolderId=301,GetName='existing.mh',GetHolderNumber='1',GetHolderShape='round',GetHolderType='mill',GetHolderSpec='fixture',GetHolderTopDia=10.,GetHolderBottomDia=5.,GetHolderOverallLength=30.,GetHolderBottomLength=10.,GetProtrusion=22.5,GetHolderProfile=self.holder_profile)
        self.tool=Native(ToolType=kind,IsMillTool=True,CutDiameter=6.,Protrusion=22.5,StnNo=6.,ToolIdentifier='existing',ToolVendor='vendor',ToolDescription='saved',GetToolProfile=self.tool_profile,GetShankProfile=self.shank_profile,IGetMillToolHolder=self.holder)
        self.doc=Native(GetCWObjectID=(tid,True));self.diag={}
    def read(self,obj,name,*args):
        self.reads.append(name)
        if self.fault==name:raise RuntimeError('injected getter failure '+name)
        return obj.values[name]
    def typed(self,obj,name):
        self.qis.append(name)
        assert name in {'ICWTool','ICWMillToolHolder','ICWSegChain','ICWCurve','ICWPosition','ICWUnitVector','ICWArc','ICWCircle','ICWSpline'},'No subtype QI permitted'
        if obj is None:raise ValueError('Null native holder is not a profile absence')
        return obj
    def run(self):return m.read_generic_preserved_tool(self.tool,generic=self.generic,doc=self.doc,read=self.read,typed=self.typed,diagnostic=self.diag)
@pytest.mark.parametrize('tid,kind',ACTUAL_TYPES)
def test_actual_legacy_types_get_complete_profiles_without_subtype_qi(tid,kind):
    f=Fixture(tid,kind);r=f.run()
    assert r['geometry_read_complete'] is True and r['profile_complete'] is True
    assert r['subtype_settings_read'] is False and r['physical_tool_qualified'] is False and r['production_qualified'] is False
    assert r['catalogue']==f.generic and f.diag['capture_complete'] is True
    assert not {'ICWMillTool','ICWMillUDTool','ICWTaperTool'}&set(f.qis)
    assert {'GetToolProfile','GetShankProfile','IGetMillToolHolder','GetHolderProfile'}<=set(f.reads)
@pytest.mark.parametrize('which',['tool','shank','holder'])
def test_actual_null_profile_is_explicit_absence_not_full_geometry(which):
    f=Fixture(260,19)
    if which=='holder':f.holder.values['GetHolderProfile']=None
    else:f.tool.values['GetToolProfile' if which=='tool' else 'GetShankProfile']=None
    r=f.run();assert r['geometry_read_complete'] is True and r['profile_complete'] is False and r['explicit_native_profile_absence'] is True
    p=r['holder']['profile'] if which=='holder' else r['profiles'][which]
    assert p==dict(status='observed_not_available',declared_chain_count=None,chains=[])
@pytest.mark.parametrize('member',['GetToolProfile','GetShankProfile','GetHolderProfile','GetCurveAtIndex','GetCoordinates'])
def test_decoder_failure_does_not_become_absence_or_completion(member):
    f=Fixture();f.fault=member
    with pytest.raises(RuntimeError):f.run()
    assert f.diag.get('capture_complete') is not True
    assert f.diag['state']['geometry_read_complete'] is False

def test_null_holder_is_failure_not_allowed_profile_absence():
    f=Fixture();f.tool.values['IGetMillToolHolder']=None
    with pytest.raises(ValueError):f.run()
    assert f.diag['state']['geometry_read_complete'] is False

@pytest.mark.parametrize('change',['unknown_curve','missing_chain','extra_chain','bool_curve_count','nonfinite'])
def test_native_invalid_chain_is_not_accepted(change):
    f=Fixture();chain=f.tool_profile
    if change=='unknown_curve':chain.values['GetCurveAtIndex'].values['GetTypeOfCurve']=999
    elif change=='missing_chain':chain.values['IGetNumChains']=2
    elif change=='extra_chain':chain.values['IGetNextChain']=chain
    elif change=='bool_curve_count':chain.values['GetNumOfCurves']=True
    else:chain.values['GetCurveAtIndex'].values['GetEnd'].values['GetCoordinates']=[float('nan'),0.,0.]
    with pytest.raises(ValueError):f.run()
    assert f.diag['state']['geometry_read_complete'] is False

@pytest.mark.parametrize('change',['id','type','bool_type','not_mill','catalogue','metadata'])
def test_identity_scalar_or_metadata_mismatch_stops(change):
    f=Fixture()
    if change=='id':f.doc.values['GetCWObjectID']=(999,True)
    elif change=='type':f.tool.values['ToolType']=2
    elif change=='bool_type':f.tool.values['ToolType']=True
    elif change=='not_mill':f.tool.values['IsMillTool']=1
    elif change=='catalogue':f.tool.values['CutDiameter']=7.
    else:f.tool.values['ToolVendor']=None
    with pytest.raises(ValueError):f.run()
    assert f.diag['state']['geometry_read_complete'] is False

@pytest.mark.parametrize('kind',[0,-1,True])
def test_invalid_raw_type_stops_before_profile(kind):
    f=Fixture(kind=kind)
    with pytest.raises(ValueError):f.run()
    assert 'GetToolProfile' not in f.reads

def test_unknown_positive_type_retained_without_subtype_claim():
    f=Fixture(kind=999);r=f.run()
    assert r['catalogue']['tool_type_raw']==999 and r['subtype_settings_read'] is False and not r['physical_tool_qualified']

def test_profile_and_holder_changes_are_detectable_in_preserved_record():
    f=Fixture();before=f.run()
    f.shank_profile.values['GetCurveAtIndex'].values['GetEnd'].values['GetCoordinates'][2]=11.
    assert not m.group.exact(before,f.run())
    f.shank_profile.values['GetCurveAtIndex'].values['GetEnd'].values['GetCoordinates'][2]=10.
    f.holder.values['GetHolderBottomDia']=6.
    assert not m.group.exact(before,f.run())

@pytest.mark.parametrize('profile',[{},dict(status='reading'),dict(status='observed_not_available',declared_chain_count=1,chains=[]),dict(status='observed_not_available',declared_chain_count=None,chains=[{}]),dict(status='observed',declared_chain_count=True,chains=[{}]),dict(status='observed',declared_chain_count=1,chains=[dict(read_complete=False,declared_curve_count=1,curves=[dict(read_complete=True)])]),dict(status='observed',declared_chain_count=1,chains=[dict(read_complete=True,declared_curve_count=1,curves=[dict(read_complete=False)])])])
def test_partial_decoder_records_fail_closed(profile):
    with pytest.raises(ValueError):m.observed_profile_complete(profile)

def test_actual17_crib_has_bounded_chunk_budget():
    b=m.profile_read_budget(17)
    assert b['profile_batches']==5 and b['tools_per_batch']==4
    assert b['max_total_native_calls']==28000 and b['per_batch_limit']<=6000 and b['limit_is_stop_not_partial_acceptance'] is True
@pytest.mark.parametrize('count',[True,-1,129,1.5])
def test_chunk_budget_never_accepts_unbounded_count(count):
    with pytest.raises(ValueError):m.profile_read_budget(count)
