"""Bounded filled planar polygon differences without repair, snapping or buffering."""
import math
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.validation import explain_validity

def require(ok,message):
 if not ok:raise ValueError(message)
def valid(geometry):
 require(geometry.geom_type in('Polygon','MultiPolygon','GeometryCollection','LineString','MultiLineString','Point','MultiPoint')and geometry.is_valid,'Invalid filled planar geometry: '+explain_validity(geometry))
 require(math.isfinite(geometry.area)and geometry.area>=0,'Finite nonnegative area required')
 return geometry
def filled_even_odd(loops,max_loops=64,max_vertices=50000):
 require(type(loops)is list and 0<len(loops)<=max_loops,'Bounded nonempty loops required')
 require(sum(len(v)for v in loops)<=max_vertices,'Polygon vertex bound exceeded')
 polygons=[]
 for loop in loops:
  require(len(loop)>=4 and list(loop[0])==list(loop[-1]),'Closed explicit loop required')
  require(all(len(p)==2 and all(type(x)in(int,float)and math.isfinite(x)for x in p)for p in loop),'Finite XY vertices required')
  p=valid(Polygon(loop));require(not p.is_empty and p.area>0,'Nonempty simple polygon required');polygons.append(p)
 for i,p in enumerate(polygons):
  for q in polygons[:i]:
   require(not p.boundary.intersects(q.boundary),'Touching/crossing loops are not repaired')
   require(p.disjoint(q)or p.within(q)or q.within(p),'Loops must be disjoint or strictly nested')
 polygons.sort(key=lambda p:p.area,reverse=True);out=polygons[0]
 for p in polygons[1:]:out=valid(out.symmetric_difference(p))
 return valid(out)
def summarize(shape):
 valid(shape)
 nonarea=[]
 def parts(g):
  if g.is_empty:return []
  if g.geom_type=='Polygon':return [g]
  if hasattr(g,'geoms'):return [p for child in g.geoms for p in parts(child)]
  nonarea.append(dict(geometry_type=g.geom_type,length_mm=g.length));return []
 values=parts(shape)
 return dict(valid=True,geometry_type=shape.geom_type,area_mm2=shape.area,polygon_count=len(values),hole_count=sum(len(p.interiors)for p in values),empty=shape.is_empty,zero_area_components=nonarea,components=[dict(area_mm2=p.area,bounds_xy_mm=list(p.bounds),centroid_xy_mm=list(p.centroid.coords)[0])for p in values])
def compare(nominal,previous,current):
 for shape in (nominal,previous,current):valid(shape)
 removed=valid(previous.difference(current));added=valid(current.difference(previous));missing=valid(nominal.difference(current));remaining=valid(current.difference(nominal));new_missing=valid(nominal.intersection(removed));kept=valid(nominal.intersection(current))
 # This is arithmetic checking only; it does not alter geometry or add a tolerance band.
 guard=1e-9+1e-10*max(nominal.area,previous.area,current.area,1.)
 checks=dict(nominal_partition_error_mm2=abs(nominal.area-missing.area-kept.area),current_partition_error_mm2=abs(current.area-remaining.area-kept.area),old_new_balance_error_mm2=abs(previous.area-current.area-removed.area+added.area),new_missing_subset_excess_mm2=max(0.,new_missing.area-removed.area))
 require(all(x<=guard for x in checks.values()),'Filled area algebra failed')
 shapes=dict(removed=removed,added=added,missing=missing,remaining=remaining,new_missing=new_missing)
 return dict(arithmetic_guard_mm2=guard,algebra_checks=checks,all_algebra_checks_passed=True,metrics={k:summarize(v)for k,v in shapes.items()}),shapes
