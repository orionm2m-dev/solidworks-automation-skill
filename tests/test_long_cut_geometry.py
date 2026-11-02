from pathlib import Path
from copy import deepcopy
import os,sys
import pytest
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]));sys.path.insert(0,str(ROOT))
import scripts
if not(ROOT/'scripts/sw_cam_long_cut_cutter_geometry.py').is_file():scripts.__path__.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from scripts import sw_cam_long_cut_cutter_geometry as g

def profile(shank=False,include_extension=True):
    lines=([((1.,6.),(1.,7.5))]if include_extension else[]) + [((1.,7.5),(2.,11.2)),((2.,11.2),(2.,40.))] if shank else [((1.,0.),(1.,6.)),((1.,6.),(1.,7.5)),((1.,7.5),(2.,11.2)),((2.,11.2),(2.,40.))]
    curves=[{'read_complete':True,'curve_type':0,'start_native':[a[0],0.,a[1]],'end_native':[b[0],0.,b[1]]}for a,b in lines]
    return {'status':'observed','declared_chain_count':1,'chains':[{'read_complete':True,'declared_curve_count':len(curves),'curves':curves}]}

@pytest.mark.parametrize('shank,extension',[(False,False),(True,False),(True,True)])
def test_manufacturer_cylinder_and_cone(shank,extension):
    assert g.verify_profile(profile(shank,extension),g.TARGET,shank_only=shank)['status']=='PASS'

@pytest.mark.parametrize('damage',['short_cut','false_neck','cone_early','cone_late','missing_extension','missing_shank','radius','unsupported_curve','missing_endpoint'])
def test_wrong_or_incomplete_profile_rejected(damage):
    p=profile();curves=p['chains'][0]['curves']
    if damage=='short_cut':curves[0]['end_native'][2]=5.99
    elif damage=='false_neck':curves[1]['start_native'][0]=.975
    elif damage=='cone_early':curves[2]['start_native'][2]=6.
    elif damage=='cone_late':curves[2]['end_native'][2]=11.3
    elif damage=='missing_extension':curves.pop(1);p['chains'][0]['declared_curve_count']-=1
    elif damage=='missing_shank':curves[-1]['end_native'][2]=39.
    elif damage=='radius':curves[-1]['end_native'][0]=2.01
    elif damage=='unsupported_curve':curves[0]['curve_type']=1
    elif damage=='missing_endpoint':curves[0].pop('end_native')
    with pytest.raises((ValueError,KeyError)):g.verify_profile(p,g.TARGET)

@pytest.mark.parametrize('field,value',[('EffCutlength',7.),('ShoulderLength',6.),('ShankLength',6.),('MillToolShankType',0),('NoOfFlutes',2),('Protrusion',20.)])
def test_only_actual_reviewed_recipe(field,value):
    with pytest.raises(ValueError):g.validate_target(dict(g.TARGET,**{field:value}))
