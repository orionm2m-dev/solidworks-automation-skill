import math
import pytest
from scripts.sw_sketch_circles import match_circles, resize_sketch_circles


def circle(x,y,r): return {"center_mm":[x,y,0],"radius_mm":r}


def test_exact_targets_ignore_unrelated_radius():
    rows=[circle(1,2,1),circle(3,4,2),circle(5,6,1)]
    assert match_circles(rows,[[5,6],[1,2]],1)==[2,0]


@pytest.mark.parametrize('targets,r', [([[1,2]],2),([[1,3]],1),([[1,2],[1,2]],1),([[math.nan,2]],1),([[1]],1),([],1)])
def test_missing_duplicate_and_invalid_fail_closed(targets,r):
    with pytest.raises(ValueError):match_circles([circle(1,2,1)],targets,r)


def test_ambiguous_geometry_rejected():
    with pytest.raises(ValueError):match_circles([circle(1,2,1),circle(1,2,1)],[[1,2]],1)


@pytest.mark.parametrize('r',[-1,0,math.inf,math.nan])
def test_new_radius_checked_before_com(r):
    with pytest.raises(ValueError):resize_sketch_circles(None,'Sketch',[[0,0]],1,r)


def test_reference_conversion_requires_explicit_opt_in(monkeypatch):
    from types import SimpleNamespace
    import scripts.sw_sketch_circles as m
    model=SimpleNamespace(GetType=lambda:1,GetConfigurationNames=lambda:['Default'],
        SketchManager=SimpleNamespace(ActiveSketch=None),IsOpenedReadOnly=lambda:False)
    before={'circles':[circle(1,2,1)],'has_dimensions':False,'relation_count':0,'editable':False}
    monkeypatch.setattr(m,'_read',lambda *a:(before,None,None))
    monkeypatch.setattr(m,'_health',lambda *a:{'solid_count':1,'body_checks':[0],'volume_mm3':1})
    with pytest.raises(ValueError,match='make_reference_editable'):
        m.resize_sketch_circles(model,'Sketch',[[1,2]],1,1.2,dry_run=False)


def test_packed_circle_reader_avoids_segment_enumeration():
    from types import SimpleNamespace as N
    import scripts.sw_sketch_circles as m
    row=[0]*6+[.002,.002,0]+[.002,.002,0]+[.001,.002,0]+[1]
    sketch=N(Is3D=lambda:False,GetArcs2=lambda:row,GetArcCount=lambda:1,
        GetLines2=lambda _:[],RelationManager=N(GetRelationsCount=lambda _:0),IsSketchEditable=lambda:True)
    feature=N(GetTypeName2=lambda:'ProfileFeature',GetSpecificFeature2=lambda:sketch,
        GetFirstDisplayDimension=lambda:None,IsSuppressed=lambda:False)
    model=N(FeatureByName=lambda _:feature,GetActiveSketch2=lambda:None)
    r,_,_=m._read(model,'Sketch')
    assert r['circles']==[circle(1,2,1)]
