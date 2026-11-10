import unittest
from workbench.domain import *

class DomainBoundaryTests(unittest.TestCase):
    def test_boundaries(self):
        source={'a':1,'b':2};self.assertEqual(patch(source,{'a':3}),{'a':3,'b':2});self.assertEqual(source,{'a':1,'b':2})
        with self.assertRaises(ValueError):patch(source,{'c':1})
        self.assertEqual(differences(source,source),{})
        self.assertEqual(differences({'a':1},{}),{'a':{'before':1,'after':None}})
