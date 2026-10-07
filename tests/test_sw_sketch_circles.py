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
