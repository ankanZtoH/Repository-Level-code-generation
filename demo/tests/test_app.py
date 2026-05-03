import unittest
from math_ops import multiply, divide

class TestMathOps(unittest.TestCase):
    def test_multiply(self):
        self.assertEqual(multiply(2, 3), 6)
    def test_divide(self):
        self.assertEqual(divide(10, 5), 2)

def main():
    unittest.main()
