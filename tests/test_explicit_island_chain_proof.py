from pathlib import Path
import copy,importlib.util,json,math
import pytest
S=Path(__file__).resolve().parents[1]
loader=importlib.util.spec_from_file_location('pure_chain',S/'scripts/sw_cam_explicit_island_chain_proof.py');core=importlib.util.module_from_spec(loader);loader.loader.exec_module(core)

@pytest.fixture
def data():
    specs=json.loads((S/'tests/fixtures/signed_specs.json').read_bytes())
    old=json.loads((S/'tests/fixtures/old_indexed_before.json').read_bytes())
    outer={'plane_axis':'Z','plane_offset_mm':25.8,'sketch_name':'OUTER','plane_name':'OP','profile':{'kind':'circle','center_model_mm':[0,0,25.8],'radius_mm':23.35}}
    names=[outer['sketch_name']]+[s['sketch_name']for s in specs]
    old['headers']['sketch_names'].update(value=names,observed_name_count=5,matches_sketch_count=True)
    for i,r in enumerate(old['indexed_chains']):
        r['expected_sketch_name']=names[i];r['name_observation']['value']=[names[i]]
        if not i:continue
        rows=[];shift=[100*i,-7*i,-80+i]
        def tr(p):return [p[k]+shift[k]for k in range(3)]
        for j,s in enumerate(specs[i-1]['profile']['segments']):
            d={'index':j,'read_complete':True,'curve_type':0 if s['kind']=='line'else 1,'start_native':tr(s['start_model_mm']),'end_native':tr(s['end_model_mm'])}
            if s['kind']=='arc':d.update(mid_native=tr(s['mid_model_mm']),centre_native=tr(s['center_model_mm']),radius_native=s['radius_mm'],normal_native=[0,0,1],sense_raw=987)
            rows.append(d)
        r['contour']['chains'][0]['curves']=rows
    return old,outer,specs

def verify(d,**kw):return core.verify_indexed(*d,length_scale_to_mm=kw.get('scale',1.0))
def rows(d,i=1):return d[0]['indexed_chains'][i]['contour']['chains'][0]['curves']

def test_translated_shapes_pass_no_world_claim(data):
    proof=verify(data);assert proof['indexed_chain_binding_verified']is True
    assert proof['world_placement_verified']is proof['axial_semantics_verified']is proof['machining_eligible']is False
    assert proof['islands'][0]['radii_mm']==[13.2,16.2]
    assert all(abs(x-2.5)<1e-12 for x in proof['islands'][0]['line_distances_from_arc_center_mm'])

@pytest.mark.parametrize('reverse,shift',[(r,s)for r in(False,True)for s in range(4)])
def test_cyclic_and_reverse_traversal(data,reverse,shift):
    for i in range(1,5):
        q=rows(data,i)
        if reverse:q=[dict(x,start_native=x['end_native'],end_native=x['start_native'])for x in reversed(q)]
        q=q[shift:]+q[:shift]
        for j,r in enumerate(q):r['index']=j
        data[0]['indexed_chains'][i]['contour']['chains'][0]['curves']=q
    assert verify(data)['indexed_chain_binding_verified']

@pytest.mark.parametrize('change',['outer_radius','name','name_observation','index_bool','curve_bool','count','read_incomplete','midpoint','broken_close','nonconcentric','tilted_normal','nan','yaw','scale','signed_sweep'])
def test_reject_narrow_faults(data,change):
    obs,outer,specs=data;q=rows(data)
    if change=='outer_radius':rows(data,0)[0]['radius_native']-=.5
    elif change=='name':obs['headers']['sketch_names']['value'][1]='different'
    elif change=='name_observation':obs['indexed_chains'][1]['name_observation']['value']=['wrong']
    elif change=='index_bool':obs['indexed_chains'][1]['native_index']=True
    elif change=='curve_bool':q[1]['curve_type']=True
    elif change=='count':obs['headers']['island_count']=3
    elif change=='read_incomplete':q[1]['read_complete']=False
    elif change=='midpoint':q[1]['mid_native'][0]+=.1
    elif change=='broken_close':q[0]['end_native'][0]+=.01
    elif change=='nonconcentric':q[1]['centre_native'][0]+=.01
    elif change=='tilted_normal':q[1]['normal_native']=[1e-4,0,1]
    elif change=='nan':q[1]['radius_native']=float('nan')
    elif change=='signed_sweep':specs[0]['profile']['segments'][1]['sweep_radians']*=-1
    elif change=='yaw':
        for r in q:
            for k in('start_native','end_native','mid_native','centre_native'):
                if k in r:r[k]=[-r[k][1],r[k][0],r[k][2]]
    with pytest.raises(ValueError):verify(data,scale=.001 if change=='scale'else 1.)

def test_actual_old_top_profiles_rejected_by_geometry(data):
    old=json.loads((S/'tests/fixtures/old_indexed_before.json').read_bytes())
    for i in range(1,5):data[0]['indexed_chains'][i]['contour']=old['indexed_chains'][i]['contour']
    with pytest.raises(ValueError,match='Relative island geometry'):verify(data)

def test_missing_explicit_scale_rejected(data):
    with pytest.raises(TypeError):core.verify_indexed(*data)

def test_inputs_unchanged(data):
    before=copy.deepcopy(data);verify(data);assert data==before
