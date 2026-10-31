"""Offline regressions for rounded half-turn axial CL records."""
import importlib.util
import math
from pathlib import Path
import unittest
from copy import deepcopy

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("rounded_cl_reader",ROOT/"scripts/sw_cam_generic_cl_reader.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class RoundedHelixTests(unittest.TestCase):
    def setUp(self):
        self.c=dict(start_raw=[19.840328,-.247697,-12.3375],center_raw=[20.526868,-.974788,-12.3375],radius_raw=1.,normal_raw=[0.,0.,1.],direction_token="COUNTERCLOCKWISE")
        self.end=[21.213409,-1.701879,-12.3875]
    def run_arc(self,c=None,end=None,q=1e-6):
        return m.validate_axial_helix_endpoint(c or self.c,end or self.end,[0.,0.,1.],coordinate_quantum=q)
    def test_actual_half_turn_raw_angle_preserved(self):
        r=self.run_arc()
        self.assertTrue(r["rounded_antipodal_arc"])
        self.assertGreater(r["angle_raw_rad"],math.pi)
        self.assertAlmostEqual(r["angle_excess_over_pi_raw"],7.270915940438272e-7,places=14)
        self.assertFalse(r["coordinates_snapped"])
        self.assertFalse(r["extra_turns_verified"])
    def test_same_record_without_observed_quantum_rejected(self):
        with self.assertRaises(ValueError):self.run_arc(q=None)
    def test_true_major_arc_rejected(self):
        c=deepcopy(self.c);c.update(start_raw=[1.,0.,0.],center_raw=[0.,0.,0.])
        a=math.pi+.001
        with self.assertRaises(ValueError):self.run_arc(c,[math.cos(a),math.sin(a),-.05])
    def test_excess_radial_error_rejected(self):
        end=self.end.copy();end[0]+=.000005
        with self.assertRaises(ValueError):self.run_arc(end=end)
    def test_zero_full_or_hidden_turn_not_inferred(self):
        end=self.c["start_raw"][:];end[2]-=.1
        with self.assertRaises(ValueError):self.run_arc(end=end)
    def test_upward_and_clockwise_rejected(self):
        end=self.end.copy();end[2]=self.c["start_raw"][2]+.05
        with self.assertRaises(ValueError):self.run_arc(end=end)
        c=deepcopy(self.c);c["direction_token"]="CLOCKWISE"
        with self.assertRaises(ValueError):self.run_arc(c)
    def test_exact_minor_unchanged(self):
        c=deepcopy(self.c);c.update(start_raw=[1.,0.,0.],center_raw=[0.,0.,0.])
        r=self.run_arc(c,[0.,1.,-.025],q=None)
        self.assertAlmostEqual(r["angle_raw_rad"],math.pi/2)
        self.assertNotIn("rounded_antipodal_arc",r)
        self.assertFalse(r["extra_turns_verified"])
    def test_precision_syntax_explicit(self):
        self.assertTrue(m.six_decimal_coordinates("1.000000,-0.000000,2.123456",3))
        for text in ("1,0,2","1.0000000,0.000000,2.000000","1e0,0.000000,2.000000"):
            self.assertFalse(m.six_decimal_coordinates(text,3))

if __name__=="__main__":unittest.main()
