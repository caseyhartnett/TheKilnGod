import unittest

from lib.telemetry_math import avg, bool_pct, within_tolerance_pct, switch_count, switches_per_hour


class TestTelemetryMath(unittest.TestCase):
    def test_avg(self):
        self.assertEqual(avg([]), 0.0)
        self.assertEqual(avg([1, 2, 3]), 2.0)

    def test_bool_pct(self):
        self.assertEqual(bool_pct([]), 0.0)
        self.assertEqual(bool_pct([True, False, True, True]), 75.0)

    def test_within_tolerance_pct(self):
        values = [0, 2, -3, 6, -7, 5]
        self.assertAlmostEqual(within_tolerance_pct(values, 5), 4 / 6 * 100)
        self.assertAlmostEqual(within_tolerance_pct(values, 2), 2 / 6 * 100)

    def test_switch_count(self):
        self.assertEqual(switch_count([]), 0)
        self.assertEqual(switch_count([0]), 0)
        self.assertEqual(switch_count([0, 0, 0]), 0)
        self.assertEqual(switch_count([0, 1, 0, 1, 1, 0]), 4)

    def test_switches_per_hour(self):
        self.assertEqual(switches_per_hour(0, 0), 0.0)
        self.assertEqual(switches_per_hour(120, 3600), 120.0)
        self.assertEqual(switches_per_hour(60, 1800), 120.0)


if __name__ == '__main__':
    unittest.main()
