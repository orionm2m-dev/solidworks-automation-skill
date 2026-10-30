import pytest
from scripts.sw_cam_compound_step_probe import read_interior_step

def run(kind=1, count=3, raw=None, xyz=None, repeat=None):
    calls=[]
    if raw is None:raw=[46.7,13.2,'position'] if kind==1 else [46.7,47.1,0.2,0.2,'position',False,0.785398]
    if xyz is None:xyz=[0.,0.,25.8]
    def read(obj,name,*args):
        calls.append((name,args))
        if name=='GetTypeAtStep':return kind if len(calls)==1 or repeat is None else repeat
        if name in ('GetCylParams','GetConeParams'):return raw
        if name=='GetCoordinates':return xyz
        raise AssertionError(name)
    result=read_interior_step('step',count=count,read=read,typed=lambda o,t:o)
    return result,calls

@pytest.mark.parametrize('kind',[1,2])
def test_only_observed_type_is_read_once_at_interior_index(kind):
    result,calls=run(kind)
    methods=[x[0] for x in calls]
    assert methods==['GetTypeAtStep','GetCylParams' if kind==1 else 'GetConeParams','GetCoordinates','GetTypeAtStep']
    assert all(args==(1,) for name,args in calls if name!='GetCoordinates')
    assert result['observed_steps'][0]['index']==1
    assert result['step_dimensions_read'] is True
    assert result['complete_step_coverage'] is False and result['index_base_verified'] is False

@pytest.mark.parametrize('args',[
 dict(count=2),dict(count=True),dict(count=65),dict(kind=0),dict(kind=True),dict(kind=3),
 dict(raw=[1,2]),dict(raw=[float('nan'),2,'p']),dict(raw=[-9999000,2,'p']),
 dict(raw=[1,True,'p']),dict(raw=[1,2,None]),dict(xyz=[0,0]),
 dict(xyz=[0,0,float('inf')]),dict(repeat=2),dict(repeat=True),
 dict(kind=2,raw=[1,2,3,4,'p',0,5]),dict(kind=2,raw=[1,2,3,4,'p',False]),
])
def test_malformed_or_unsupported_step_stops_without_fallback(args):
    with pytest.raises(ValueError):run(**args)

def test_target_controller_passes_interior_mode_without_catalogue_reads(monkeypatch):
    from types import SimpleNamespace
    from test_sw_cam_mill_compound_strategy import calls_fixture
    from scripts import sw_cam_mill_compound_strategy as m
    from scripts import sw_cam_generation as g
    f=calls_fixture()
    f.doc.GetDocType=lambda:1
    f.raw.GetTypeAtStep=lambda i:1
    f.raw.GetCylParams=lambda i:(46.7,13.2,SimpleNamespace(GetCoordinates=lambda:(0.,0.,25.8)))
    def forbidden():raise AssertionError('Unchanged catalogue must not be read')
    f.raw.IGetAllAttributes=forbidden
    f.raw.IGetAllAttributes2=forbidden
    monkeypatch.setattr(g,'_typed',lambda raw,name,path:raw)
    diag={}
    m.capture_compound_target(SimpleNamespace(IGetActiveDoc=lambda:f.doc),'unused',
        identity=lambda:{'path':'p','type':1,'needs_save':False},check=lambda:None,diagnostic=diag,
        feature_id=64,owner_id=69,step_count=3,expected_header=f.header,observation='interior_step_1')
    detail=diag['operation_details']['compound_strategy']
    assert detail['observed_steps'][0]['diameter_native']==46.7
    assert detail['step_dimensions_read'] and not detail['complete_step_coverage']
    assert diag['capture_complete'] and diag['native_read_count']<60

def test_three_step_read_has_unique_coverage_and_no_extra_indices():
    from scripts.sw_cam_compound_step_probe import read_three_step_profile
    from types import SimpleNamespace
    calls=[]
    def read(obj,name,*args):
        if name=='GetCoordinates':return obj.GetCoordinates()
        calls.append((name,args))
        i=args[0]
        assert i in (0,1,2)
        if name=='GetTypeAtStep':return 1 if i==1 else 2
        pos=SimpleNamespace(GetCoordinates=lambda:(0.,0.,(26.,25.8,12.6)[i]))
        if name=='GetCylParams':return (46.7,13.2,pos)
        if name=='GetConeParams':return (46.7,47.1,0.2,0.2,pos,False,0.7854) if i==0 else (45.6,46.7,0.3,0.3,pos,False,1.0714)
        raise AssertionError(name)
    out=read_three_step_profile('p',count=3,read=read,typed=lambda x,t:x)
    assert [x['index'] for x in out['observed_steps']]==[0,1,2]
    assert out['index_base_verified'] and out['complete_step_coverage']
    assert len(calls)==9 and out['units_verified'] is False

@pytest.mark.parametrize('count',[2,4,True])
def test_three_step_requires_exact_count_before_native_call(count):
    from scripts.sw_cam_compound_step_probe import read_three_step_profile
    def forbidden(*args):raise AssertionError('No native call allowed')
    with pytest.raises(ValueError):
        read_three_step_profile('p',count=count,read=forbidden,typed=forbidden)
