"""Holder profile and one-shot reference regression tests; no native connections."""
from copy import deepcopy
import json,hashlib
from types import SimpleNamespace
import pytest
from scripts import sw_cam_shared_holder_geometry as h

def build_case(tmp_path):
    raw=b'# CWToolGen Version: <1.0>\nline 0 0 1 0\narc 1 0 2 1 1 1 0\nline 2 1 0 1\n'
    f=tmp_path/'holder.mh';f.write_bytes(raw)
    rec=[dict(kind='line',start_rz=[0,0],end_rz=[1,0]),
         dict(kind='arc',start_rz=[1,0],end_rz=[2,1],center_rz=[1,1],native_file_direction_flag=0),
         dict(kind='line',start_rz=[2,1],end_rz=[0,1])]
    sha=hashlib.sha256(raw).hexdigest()
    doc=dict(source_sha256=sha,coordinate_order=['radius','axial_z'],record_count=3,records=rec)
    p=tmp_path/'nominal.json';p.write_text(json.dumps(doc))
    recipe=h.read_holder_recipe(str(f),sha,str(p),hashlib.sha256(p.read_bytes()).hexdigest())
    curves=[dict(read_complete=True,curve_type=0,start_native=[0,0,20],end_native=[1,0,20]),
      dict(read_complete=True,curve_type=1,start_native=[1,0,20],end_native=[2,0,21],
           centre_native=[1,0,21],radius_native=1,mid_native=[1.7071067811865475,0,20.292893218813454]),
      dict(read_complete=True,curve_type=0,start_native=[2,0,21],end_native=[0,0,21])]
    profile=dict(status='observed',declared_chain_count=1,chains=[dict(read_complete=True,declared_curve_count=3,curves=curves)])
    return recipe,profile

def test_complete_profile_and_reversed_order(case):
    r,p=case
    out=h.verify_holder_profile(p,r,20)
    assert out['native_holder_shape_verified'] and not out['production_qualified']
    for c in p['chains'][0]['curves']:c['start_native'],c['end_native']=c['end_native'],c['start_native']
    p['chains'][0]['curves'].reverse()
    assert h.verify_holder_profile(p,r,20)['curve_count']==3

@pytest.mark.parametrize('fault',['major_arc','radius','centre','missing','extra','offset','nan','incomplete','bool_kind'])
def test_wrong_holder_geometry_rejected(case,fault):
    r,p=case;c=p['chains'][0]['curves'];arc=c[1]
    if fault=='major_arc':arc['mid_native']=[0.2928932188134525,0,21.707106781186546]
    if fault=='radius':arc['radius_native']=2
    if fault=='centre':arc['centre_native'][0]+=1
    if fault=='missing':c.pop()
    if fault=='extra':c.append(deepcopy(c[0]))
    if fault=='offset':c[0]['start_native'][2]+=0.1
    if fault=='nan':arc['mid_native'][0]=float('nan')
    if fault=='incomplete':arc['read_complete']=False
    if fault=='bool_kind':arc['curve_type']=True
    with pytest.raises(ValueError):h.verify_holder_profile(p,r,20)

def test_changed_asset_rejected(case):
    r,_=case
    from pathlib import Path
    Path(r['file_path']).write_bytes(b'changed')
    with pytest.raises(ValueError):h.check_holder_pins(r)

@pytest.mark.parametrize('fault',['ok','persist','guard','wrong_path','bad_hresult','exception'])
def test_single_reference_assignment(case,fault):
    r,_=case;holder=SimpleNamespace(name='old.mh');calls=[];report={}
    def read(obj,name):assert name=='GetName';return obj.name
    def invoke(obj,name,value):
        assert name=='SetFilePathForUserDefinedHolder';calls.append(value)
        if fault=='exception':raise RuntimeError('native failed')
        obj.name='wrong.mh' if fault=='wrong_path' else value
        return 1 if fault=='bad_hresult' else 0
    def persist():
        if fault=='persist':raise OSError('disk')
    def guard():
        if fault=='guard':raise ValueError('session changed')
    args=dict(read=read,invoke=invoke,guard=guard,persist=persist,report=report)
    if fault=='ok':
        h.apply_holder_reference(holder,r,**args)
        assert report['holder_reference']['readback_verified']
    else:
        with pytest.raises((ValueError,OSError,RuntimeError)):h.apply_holder_reference(holder,r,**args)
    assert len(calls)==(0 if fault in ('persist','guard') else 1)

@pytest.fixture
def case(tmp_path):
    return build_case(tmp_path)
