import copy,hashlib,math,os,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_explicit_island_sketch as m


def loops():
    ri,ro,w,z=3.,5.,1.,7.
    result=[]
    for angle in (20.,110.,200.,290.):
        t=math.radians(angle)
        def p(u,v):return [u*math.cos(t)-v*math.sin(t),u*math.sin(t)+v*math.cos(t),z]
        a,b,c,d=p(math.sqrt(ro*ro-w*w),-w),p(math.sqrt(ro*ro-w*w),w),p(math.sqrt(ri*ri-w*w),w),p(math.sqrt(ri*ri-w*w),-w)
        result.append(dict(angle_deg=angle,edges=[dict(kind='Circle',start=a,end=b,centre=[0.,0.,z],radius_mm=ro,ccw=True),dict(kind='Line',start=b,end=c),dict(kind='Circle',start=c,end=d,centre=[0.,0.,z],radius_mm=ri,ccw=False),dict(kind='Line',start=d,end=a)]))
    return result


def compile_(data=None,**kwargs):
    args=dict(plane_z_mm=7.,sketch_names=['IslandA','IslandB','IslandC','IslandD'],plane_names=['PlaneA','PlaneB','PlaneC','PlaneD']);args.update(kwargs)
    return m.compile_loops(loops()if data is None else data,**args)


def observed(spec):
    rows=[]
    for s in spec['profile']['segments']:
        row=dict(type=s['kind'],points_model_m=[[v/1000 for v in s[k]]for k in ('start_model_mm','end_model_mm')],mid_model_m=[v/1000 for v in s['mid_model_mm']],length_m=m.mixed.length(s)/1000)
        if s['kind']=='arc':row.update(center_model_m=[v/1000 for v in s['center_model_mm']],radius_m=s['radius_mm']/1000,native_trim=dict(independent_native_length_verified=True,underlying_curve_trim_used=False))
        rows.append(row)
    return dict(entities=rows,expected_segment_to_native_index=list(range(4)),model_to_sketch_transform=[1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.],readback_tolerance_m=1e-8,arc_interval_midpoint_verified=True,native_rotation_direction_assumed=False,native_rotation_direction_qualified=True,underlying_curve_trim_used=False)


def test_four_distinct_closed_minor_arc_loops_without_coordinate_changes():
    source=loops();out=compile_(source)
    assert len(out)==4
    for raw,spec in zip(source,out):
        segs=spec['profile']['segments'];assert len(segs)==4
        assert [x['start_model_mm']for x in segs]==[x['start']for x in raw['edges']]
        assert segs[0]['sweep_radians']>0 and segs[2]['sweep_radians']<0
        assert abs(segs[0]['sweep_radians']-2*math.asin(.2))<1e-12
        assert abs(segs[2]['sweep_radians']+2*math.asin(1/3))<1e-12
        assert m.verify_readback(spec,observed(spec))['closed_mixed_profile_verified']is True


@pytest.mark.parametrize('change',[lambda x:x.pop(),lambda x:x[0]['edges'].pop(),lambda x:x[0]['edges'][0].update(ccw=False),lambda x:x[0]['edges'][0].update(ccw=1),lambda x:x[0]['edges'][1]['start'].__setitem__(0,0.),lambda x:x[1].update(angle_deg=x[0]['angle_deg']),lambda x:x[0]['edges'][0].update(extra=1),lambda x:x[0]['edges'][0].update(radius_mm=float('nan'))])
def test_bad_footprints_rejected(change):
    x=loops();change(x)
    with pytest.raises(ValueError):compile_(x)


@pytest.mark.parametrize('kwargs',[dict(plane_z_mm=7.1),dict(plane_z_mm=True),dict(sketch_names=['X']*4),dict(plane_names=['IslandA','P2','P3','P4'])])
def test_plane_or_name_binding_rejected(kwargs):
    with pytest.raises(ValueError):compile_(**kwargs)


def test_actual_segment_writer_uses_only_four_lines_and_arcs_and_metre_transform():
    calls=[]
    def local(p):return [-p[1]/1000,p[0]/1000,(p[2]-7)/1000]
    def mutate(owner,name,*args):calls.append((owner,name,args));return object()
    manager=object();spec=compile_()[0]
    m.mixed.create_segments(manager,spec['profile'],local=local,mutate=mutate)
    assert [x[1]for x in calls]==['Create3PointArc','CreateLine','Create3PointArc','CreateLine']
    assert all(x[0]is manager for x in calls)
    assert all(all(abs(x)<.01 for x in args)for _,_,args in calls)
    assert all(args[2]==args[5]==0 for _,_,args in calls)
    assert math.isclose(math.hypot(*calls[0][2][6:8]),.005,abs_tol=1e-12)


def test_native_null_stops_before_next_entity():
    calls=[]
    def mutate(_,name,*args):calls.append(name);return None
    with pytest.raises(ValueError):m.mixed.create_segments(object(),compile_()[0]['profile'],local=lambda p:[x/1000 for x in p],mutate=mutate)
    assert calls==['Create3PointArc']


def test_native_readback_unordered_and_reversed_endpoints_accepted():
    spec=compile_()[0];r=observed(spec);r['entities'].reverse()
    for row in r['entities']:row['points_model_m'].reverse()
    r['expected_segment_to_native_index']=[3,2,1,0]
    assert m.verify_readback(spec,r)['segment_mapping']==[3,2,1,0]


@pytest.mark.parametrize('change',[lambda r:r['entities'][0]['mid_model_m'].__setitem__(0,0.),lambda r:r['entities'][0].update(radius_m=.006),lambda r:r.update(native_rotation_direction_assumed=True),lambda r:r['entities'][0]['native_trim'].update(independent_native_length_verified=False),lambda r:r['model_to_sketch_transform'].__setitem__(12,1000.)])
def test_wrong_native_shape_trim_or_units_rejected(change):
    spec=compile_()[0];r=observed(spec);change(r)
    with pytest.raises(ValueError):m.verify_readback(spec,r)


def setup_create(monkeypatch,tmp_path,*,fail=None):
    spec=compile_()[0];path=tmp_path/'part.sldprt';path.write_bytes(b'CAD');sha=hashlib.sha256(b'CAD').hexdigest();trace=[];report={}
    before=dict(pid=123,path=str(path),saved_file_sha256=sha,needs_save=False,features=[dict(name='Existing',type='RefPlane')],planes=[],solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[1.,2.,3.,4.])],spec=spec)
    after=copy.deepcopy(before);after['needs_save']=True;after['features']+=[dict(name=spec['plane_name'],type='RefPlane'),dict(name=spec['sketch_name'],type='ProfileFeature')]
    reads=iter([before,after]);model=object()
    monkeypatch.setattr(m.core,'_identity',lambda *a:model)
    monkeypatch.setattr(m.core,'_snapshot',lambda *a:(copy.deepcopy(next(reads)),model,[]))
    monkeypatch.setattr(m.core,'_select_plane',lambda *a:None)
    def create(sw,model,state,refs,check,r):
        trace.append('create');check()
        if fail=='native':raise RuntimeError('native failure')
        r.update(sketch_readback=observed(spec),sketch_edit_exited=True)
        return [spec['plane_name'],spec['sketch_name']]
    monkeypatch.setattr(m.sketch,'_create',create)
    def claim():
        trace.append('claim')
        if fail=='claim':raise RuntimeError('consumed marker')
    return dict(sw=object(),process_id=123,document_path=str(path),source_sha256=sha,expected_needs_save=False,spec=spec,check=lambda:trace.append('check'),claim=claim,persist=lambda:trace.append('persist'),report=report),trace


def test_real_component_claims_before_existing_builder_and_no_CAM_or_Save(monkeypatch,tmp_path):
    args,trace=setup_create(monkeypatch,tmp_path);r=m.create_one(**args)
    assert trace.index('claim')<trace.index('create')
    assert r['native_readback_verified']is True and r['geometry_proof']['CAM_island_association_verified']is False
    assert all(r[k]is False for k in ('Save_attempted','CAM_feature_creation_attempted','AddIsland_attempted','GOP_attempted','GTP_attempted'))


@pytest.mark.parametrize('failure',['claim','native'])
def test_component_no_replay_after_failure(monkeypatch,tmp_path,failure):
    args,trace=setup_create(monkeypatch,tmp_path,fail=failure)
    with pytest.raises(RuntimeError):m.create_one(**args)
    assert trace.count('create')==(failure=='native')
    assert args['report']['native_readback_verified']is False
    assert args['report']['status']==('uncertain'if failure=='native'else'error')


def test_component_changed_source_stops_before_claim(monkeypatch,tmp_path):
    args,trace=setup_create(monkeypatch,tmp_path);Path(args['document_path']).write_bytes(b'changed')
    with pytest.raises(ValueError):m.create_one(**args)
    assert 'claim'not in trace and 'create'not in trace

def test_final_receipt_failure_revokes_component_acceptance(monkeypatch,tmp_path):
    args,trace=setup_create(monkeypatch,tmp_path)
    def persist():
        if args['report'].get('status')=='sketch_observed':raise OSError('receipt write failed')
    args['persist']=persist
    with pytest.raises(OSError):m.create_one(**args)
    assert args['report']['status']=='uncertain'
    assert args['report']['mutation_attempted']is True
    assert args['report']['native_readback_verified']is False
    assert args['report']['receipt_write_failed']is True
