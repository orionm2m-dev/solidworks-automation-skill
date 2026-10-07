import math
from types import SimpleNamespace
import pytest
from scripts.sw_face_translation import contained, validate_request, translate_faces_in_box


def test_full_containment_excludes_large_adjacent_face():
    assert contained([1,2,0,2,3,1], [0,0,-1,3,4,2])
    assert not contained([-1,2,0,2,3,1], [0,0,-1,3,4,2])


@pytest.mark.parametrize("box,delta,count", [
    ([0]*6,[0,1,0],8), ([0,0,0,1,1,1],[0,0,0],8),
    ([0,0,0,1,1,1],[0,math.nan,0],8), ([0,0,0,1,1,1],[0,1,0],0),
    ([0,0,0,1,1],[0,1,0],8)])
def test_rejects_invalid_request(box,delta,count):
    with pytest.raises(ValueError): validate_request(box,delta,count)


def test_face_count_mismatch_does_not_mutate():
    model=SimpleNamespace(GetType=lambda:1, GetConfigurationNames=lambda:['Default'],
        SketchManager=SimpleNamespace(ActiveSketch=None), GetBodies2=lambda *a:[])
    with pytest.raises(ValueError, match="面数不符"):
        translate_faces_in_box(model,[0,0,0,1,1,1],[0,1,0],8,'Move')


def test_dry_run_does_not_access_mutating_api():
    face=SimpleNamespace(GetBox=lambda:[0,0,0,.001,.001,.001], GetArea=lambda:.000001)
    body=SimpleNamespace(GetFaces=lambda:[face], Check2=lambda:0, GetMassProperties=lambda _: [0,0,0,1e-9])
    model=SimpleNamespace(GetType=lambda:1, GetConfigurationNames=lambda:['Default'],
        SketchManager=SimpleNamespace(ActiveSketch=None), GetBodies2=lambda *a:[body])
    r=translate_faces_in_box(model,[-.1,-.1,-.1,1.1,1.1,1.1],[0,1,0],1,'Move')
    assert r['dry_run'] and r['success'] and r['health_before']['volume_mm3']==1
