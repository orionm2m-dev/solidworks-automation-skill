"""纯几何回归测试；不调用 CAD 或修改模型文件。"""
from copy import deepcopy
import json
import math
import random
import unittest

import importlib.util
from pathlib import Path
import sys
_source=Path(__file__).with_name('sw_cam_mill_units_geometry.py')
if not _source.is_file():_source=Path(__file__).resolve().parents[1]/'scripts'/_source.name
_spec=importlib.util.spec_from_file_location('scripts.sw_cam_mill_units_geometry',_source)
_module=importlib.util.module_from_spec(_spec);sys.modules[_spec.name]=_module;_spec.loader.exec_module(_module)
GeometryProofError=_module.GeometryProofError
prove_mill_units_geometry=_module.prove_mill_units_geometry


SKETCH = [[0.,0.,0.],[.017,0.,0.],[.017,.029,0.],[0.,.029,0.]]


def rotate(point, angles=(.31,.72,-.43)):
    x,y,z=point
    a,b,c=angles
    y,z=math.cos(a)*y-math.sin(a)*z,math.sin(a)*y+math.cos(a)*z
    x,z=math.cos(b)*x+math.sin(b)*z,-math.sin(b)*x+math.cos(b)*z
    x,y=math.cos(c)*x-math.sin(c)*y,math.sin(c)*x+math.cos(c)*y
    return [x,y,z]


def points(width=17.,length=29.,z=0.,offset=(103.,-42.,87.),angles=(.31,.72,-.43)):
    return [[a+b for a,b in zip(rotate(p,angles),offset)]
            for p in ([0.,0.,z],[width,0.,z],[width,length,z],[0.,length,z])]


def chain(vertices,shift=0,reverse=False):
    ordered=[vertices[(shift+(-1 if reverse else 1)*i)%4] for i in range(4)]
    return [[list(ordered[i]),list(ordered[(i+1)%4])] for i in range(4)]


def proof(top=None,bottom=None,depth=3,sketch=None,**kwargs):
    return prove_mill_units_geometry(SKETCH if sketch is None else sketch,
        chain(points()) if top is None else top,
        chain(points(z=-3.)) if bottom is None else bottom,depth,**kwargs)


class GeometryProofTests(unittest.TestCase):
    def assertRejected(self, code=None, **kwargs):
        with self.assertRaises(GeometryProofError) as failure:proof(**kwargs)
        if code is not None:self.assertEqual(failure.exception.code,code)
        return failure.exception

    def test_actual_geometry_calibrates_two_edge_pairs_and_diagonal(self):
        result=proof()
        self.assertEqual(result['status'],'ok')
        self.assertAlmostEqual(result['native_units_per_mm'],1.,places=12)
        self.assertEqual(len(result['scale_estimates']),6)
        self.assertEqual({r['dimension'] for r in result['scale_estimates']},{'short','long','diagonal'})
        self.assertAlmostEqual(result['measured_separation_native'],3.,places=12)
        self.assertAlmostEqual(result['measured_separation_mm_using_in_plane_scale'],3.,places=12)
        self.assertEqual(result['requested_depth_native'],3)
        self.assertEqual(result['independent_in_plane_dimensions'],2)
        self.assertEqual(result['diagonal_role'],'redundant_geometric_cross_check')
        json.dumps(result,allow_nan=False)

    def test_all_cyclic_and_reversed_native_correspondences(self):
        for top_shift in range(4):
            for top_reverse in (False,True):
                for bottom_shift in range(4):
                    for bottom_reverse in (False,True):
                        with self.subTest(top=(top_shift,top_reverse),bottom=(bottom_shift,bottom_reverse)):
                            result=proof(top=chain(points(),top_shift,top_reverse),bottom=chain(points(z=3),bottom_shift,bottom_reverse))
                            self.assertEqual(sorted(result['correspondence']['bottom_indices_for_top']),[0,1,2,3])
                            self.assertTrue(result['top_bottom_normal_translation_verified'])

    def test_arbitrary_relative_world_frames_do_not_set_absolute_frame(self):
        rng=random.Random(17)
        for index in range(40):
            angles=tuple(rng.uniform(-math.pi,math.pi) for _ in range(3))
            offset=tuple(rng.uniform(-1e3,1e3) for _ in range(3))
            top=chain(points(offset=offset,angles=angles))
            bottom=chain(points(z=3,offset=offset,angles=angles))
            sketch=[[a+b for a,b in zip(rotate(p,(.8,-.5,.4)),[.1,-.2,.3])] for p in SKETCH]
            result=proof(top=top,bottom=bottom,sketch=sketch)
            self.assertAlmostEqual(result['native_units_per_mm'],1.,places=11)
            self.assertEqual(result['absolute_native_frame'],'unknown')

    def test_uniform_scale_is_measured_not_rejected_or_forced_to_one(self):
        for scale in (.001,.1,2.,25.4,1000.):
            result=proof(top=chain(points(width=17*scale,length=29*scale)),
                bottom=chain(points(width=17*scale,length=29*scale,z=3.)))
            self.assertAlmostEqual(result['native_units_per_mm'],scale,places=10)
            self.assertAlmostEqual(result['measured_separation_mm_using_in_plane_scale'],3/scale,places=7)
            self.assertTrue(result['uniform_native_scale_is_measured_not_assumed_one'])
            self.assertFalse(result['global_native_units_verified'])

    def test_one_contour_scaled_is_rejected(self):
        self.assertRejected('INCONSISTENT_NATIVE_SCALE_OR_RECTANGLE_DIMENSIONS',bottom=chain(points(width=18.7,length=31.9,z=3)))

    def test_anisotropic_scaling_of_both_contours_is_rejected(self):
        self.assertRejected('INCONSISTENT_NATIVE_SCALE_OR_RECTANGLE_DIMENSIONS',
            top=chain(points(width=18.7)),bottom=chain(points(width=18.7,z=3)))

    def test_wrong_aspect_ratio_is_not_a_units_measurement(self):
        self.assertRejected('INCONSISTENT_NATIVE_SCALE_OR_RECTANGLE_DIMENSIONS',
            top=chain(points(width=11,length=37)),bottom=chain(points(width=11,length=37,z=3)))

    def test_warped_skew_and_degenerate_contours_fail(self):
        warped=points();warped[2][2]+=.4
        skew=[[0,0,0],[17,0,0],[19,29,0],[2,29,0]]
        repeated=points();repeated[1]=repeated[0]
        for contour in (warped,skew,repeated):
            with self.subTest(contour=contour):self.assertRejected(top=chain(contour))

    def test_square_has_no_two_distinct_dimensions(self):
        self.assertRejected('ASYMMETRIC_RECTANGLE_REQUIRED',sketch=[[0,0,0],[.01,0,0],[.01,.01,0],[0,.01,0]])
        self.assertRejected('ASYMMETRIC_RECTANGLE_REQUIRED',top=chain(points(width=17,length=17)))

    def test_open_chain_does_not_get_silently_closed(self):
        top=chain(points());top[-1][1][0]+=.01
        self.assertRejected('CHAIN_NOT_CLOSED',top=top)

    def test_crossed_or_unordered_segments_are_not_sorted_into_a_rectangle(self):
        top=chain(points());top[1],top[2]=top[2],top[1]
        self.assertRejected('CHAIN_NOT_CLOSED',top=top)
        vertices=points();vertices[1],vertices[2]=vertices[2],vertices[1]
        self.assertRejected(top=chain(vertices))

    def test_parallel_equal_rectangles_with_lateral_shift_fail(self):
        bottom=points(z=3)
        lateral=rotate([.1,0,0])
        shifted=[[a+b for a,b in zip(point,lateral)] for point in bottom]
        self.assertRejected('TOP_BOTTOM_LATERAL_SHIFT',bottom=chain(shifted))

    def test_equal_rectangles_twisted_about_common_normal_fail(self):
        base=[[0,0,0],[17,0,0],[17,29,0],[0,29,0]]
        angle=.1;c,s=math.cos(angle),math.sin(angle)
        bottom=[[c*(x-8.5)-s*(y-14.5)+8.5,s*(x-8.5)+c*(y-14.5)+14.5,3.] for x,y,z in base]
        self.assertRejected('TOP_BOTTOM_NOT_UNIQUE_NORMAL_TRANSLATION',top=chain(base),bottom=chain(bottom))

    def test_nonparallel_rectangles_fail_even_with_equal_edge_lengths(self):
        top=chain(points(offset=(0,0,0),angles=(0,0,0)))
        bottom=chain(points(offset=(0,0,3),angles=(.1,0,0)))
        self.assertRejected('TOP_BOTTOM_PLANES_NOT_PARALLEL',top=top,bottom=bottom)

    def test_depth_is_measured_from_real_bottom_not_echoed_request(self):
        failure=self.assertRejected('MEASURED_SEPARATION_DIFFERS_FROM_REQUESTED_DEPTH',depth=4)
        self.assertAlmostEqual(failure.details['measured_separation_native'],3.)
        self.assertEqual(failure.details['requested_depth_native'],4)
        self.assertRejected('DISTINCT_TOP_BOTTOM_PLANES_REQUIRED',bottom=chain(points()))
        self.assertRejected(bottom={'depth':3})

    def test_signed_native_plane_direction_does_not_become_global_axis_claim(self):
        for sign in (-1,1):
            result=proof(bottom=chain(points(z=sign*3)))
            self.assertAlmostEqual(result['measured_separation_native'],3.)
            self.assertEqual(result['absolute_native_frame'],'unknown')
            self.assertFalse(result['depth_axis_metric_independently_verified'])

    def test_depth_strict_positive_integer_qualification_policy(self):
        for depth in (True,False,0,-1,3.,'3',None,2147483648):
            with self.subTest(depth=depth):self.assertRejected('STRICT_POSITIVE_INTEGER_QUALIFICATION_DEPTH_REQUIRED',depth=depth)

    def test_raw_shapes_and_nonfinite_values_reject(self):
        for top in ([],chain(points())*2,{'points':points()},[points()]*4):
            with self.subTest(top=top):self.assertRejected(top=top)
        for value in (True,'1',float('nan'),float('inf'),10**1000):
            top=chain(points());top[0][0][0]=value
            with self.subTest(value=repr(value)[:30]):self.assertRejected('FINITE_JSON_NUMBER_REQUIRED',top=top)

    def test_tolerances_explicit_bounded_and_strict(self):
        for key in ('relative_tolerance','sketch_absolute_tolerance_m','native_absolute_tolerance','angular_tolerance'):
            for value in (True,'1e-6',float('nan'),0,-1,1):
                with self.subTest(key=key,value=value):self.assertRejected(**{key:value})
        result=proof(relative_tolerance=1e-7,native_absolute_tolerance=1e-9)
        self.assertEqual(result['tolerances']['relative_tolerance'],1e-7)
        self.assertEqual(result['tolerances']['native_absolute_tolerance'],1e-9)

    def test_small_bounded_numeric_noise_and_large_drift(self):
        top=chain(points());top[-1][1][0]+=1e-8
        result=proof(top=top)
        self.assertGreater(result['closure_residuals_native']['top'][-1],0)
        top[-1][1][0]+=.01
        self.assertRejected('CHAIN_NOT_CLOSED',top=top)

    def test_input_untouched_and_no_provenance_or_global_unit_claim(self):
        top,bottom=chain(points()),chain(points(z=3))
        before=deepcopy((top,bottom,SKETCH))
        result=proof(top=top,bottom=bottom)
        self.assertEqual((top,bottom,SKETCH),before)
        self.assertEqual(result['native_segments_raw'],{'top':top,'bottom':bottom})
        for field in ('native_curve_line_types_verified','native_execution_verified','coordinate_provenance_verified',
                'global_native_units_verified','feed_units_verified','qualification_complete','may_continue'):
            self.assertFalse(result[field],field)
        self.assertTrue(result['depth_mm_uses_in_plane_scale'])


if __name__=='__main__':unittest.main(verbosity=2)
