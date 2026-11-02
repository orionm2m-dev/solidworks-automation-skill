from pathlib import Path
import sys
import pytest
from shapely.geometry import Polygon,box
from scripts import planar_material_regions as m

def ring(x0,y0,x1,y1):return [[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]
def test_nested_hole_and_island_order_independent():
 loops=[ring(1.5,1.5,2,2),ring(0,0,4,4),ring(1,1,3,3)]
 value=m.filled_even_odd(loops);assert value.area==12.25
 assert m.summarize(value)['polygon_count']==2 and m.summarize(value)['hole_count']==1
def test_concave_stock_not_convex_hull():
 p=m.filled_even_odd([[[0,0],[3,0],[3,1],[1,1],[1,3],[0,3],[0,0]]]);assert p.area==5 and not p.contains(box(2,2,2.5,2.5))
@pytest.mark.parametrize('loops',[[[[0,0],[2,2],[0,2],[2,0],[0,0]]],[ring(0,0,2,2),ring(1,1,3,3)],[ring(0,0,2,2),ring(2,0,3,1)]])
def test_invalid_or_touching_loops_rejected(loops):
 with pytest.raises(ValueError):m.filled_even_odd(loops)
def test_material_partition_distinguishes_missing_and_remaining():
 r,s=m.compare(box(0,0,2,2),box(-1,-1,3,3),box(.25,0,2.5,2))
 assert r['all_algebra_checks_passed'] and s['missing'].area==.5 and s['remaining'].area==1 and s['new_missing'].area==.5
 assert s['added'].is_empty
