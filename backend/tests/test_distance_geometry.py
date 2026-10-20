"""PYTHON REFERENCE ONLY: tests contracts and regressions, never real Voxblox."""
import importlib.util
from pathlib import Path
import math
import sys
import unittest
p=Path(__file__).parents[1]/'scripts/distance_geometry.py'
spec=importlib.util.spec_from_file_location('distance_geometry',p)
g=importlib.util.module_from_spec(spec);sys.modules[spec.name]=g;spec.loader.exec_module(g)


class GeometryReferenceTests(unittest.TestCase):
    def test_plane_sign_and_projective_is_not_euclidean(self):
        # Plane x=1, sensor at 0, oblique ray (.6,.8,0).
        for t in (1.5,2.):
            projected=1/.6-t
            euclidean=1-.6*t
            self.assertAlmostEqual(euclidean,.6*projected)
            self.assertNotAlmostEqual(euclidean,projected)
            self.assertEqual(math.copysign(1,projected),math.copysign(1,euclidean))
        samples=[g.Sample((x,.25,.25),1-x,2) for x in (.25,.75,1.25)]
        mapped=g.canonical_samples(samples,.5,.5)
        self.assertGreater(mapped[(0,0,0)].sdf_m,0)
        self.assertLess(mapped[(2,0,0)].sdf_m,0)

    def test_center_indices_and_native_sampling_are_different_conventions(self):
        for index in [(-17,0,3),(-1,-1,-1),(0,0,0),(16,17,32)]:
            center=g.target_center(index,.05)
            self.assertEqual(g.center_index(center,.05),index)
        # MrHash inverse rounds native centers at i*h, Voxblox centers at (i+.5)*h.
        self.assertEqual(g.target_index((0.,0.,0.),.05),(0,0,0))
        self.assertEqual(g.target_center((0,0,0),.05),(.025,.025,.025))
        with self.assertRaisesRegex(ValueError,'resampling'):g.center_index((0.,0.,0.),.05)

    def test_old_collision_and_new_duplicate_rejection(self):
        self.assertEqual(g.target_index((.01,.025,.025),.05),g.target_index((.04,.025,.025),.05))
        sample=g.Sample((.025,.025,.025),.2,2)
        with self.assertRaisesRegex(ValueError,'duplicate'):g.canonical_samples([sample,sample],.05,.05)

    def test_resolution_and_adaptive_levels_rejected(self):
        sample=g.Sample((.025,.025,.025),.2,2)
        with self.assertRaisesRegex(ValueError,'different resolutions'):g.canonical_samples([sample],.05,.1)
        with self.assertRaisesRegex(ValueError,'levels'):g.canonical_samples([g.Sample(sample.point,.2,2,1)],.05,.05)

    def test_unknown_is_absent_and_low_weight_is_not_free(self):
        kept=g.Sample((.025,.025,.025),-.2,2)
        low=g.Sample((.075,.025,.025),.2,1)
        mapped=g.canonical_samples([kept,low],.05,.05)
        self.assertNotIn((1,0,0),mapped)
        self.assertIsNone(mapped.get((2,0,0)))
        self.assertEqual(mapped[(0,0,0)].sdf_m,-.2)

    def test_bad_numbers_weights_and_empty(self):
        for weight in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):g.canonical_samples([g.Sample((.025,)*3,.2,weight)],.05,.05)
        for value in (float('nan'),float('inf')):
            with self.assertRaises(ValueError):g.canonical_samples([g.Sample((value,.025,.025),.2,2)],.05,.05)
            with self.assertRaises(ValueError):g.canonical_samples([g.Sample((.025,)*3,value,2)],.05,.05)
        with self.assertRaises(ValueError):g.canonical_samples([],.05,.05)
        with self.assertRaises(ValueError):g.canonical_samples([g.Sample((.025,)*3,.2,1)],.05,.05)

    def test_first_enqueue_is_not_shortest_path(self):
        # a discovers c with cost sqrt(3); b pops later, offers 0.2+1 < sqrt(3).
        best=g.graph_shortest_paths({'a':0,'b':.2},{'a':[('c',math.sqrt(3))],'b':[('c',1)]})
        self.assertAlmostEqual(best['c'],1.2)
