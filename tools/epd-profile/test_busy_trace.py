import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).parent))
from busy_trace import analyze_trace, parse_traces

def sample():
    events = []
    for frame in range(1, 5):
        base = (frame - 1) * 200000
        relative = [(0,1,1),(400,2,1),(430,3,1),(440,9,1),(64000,4,1),
                    (64020,5,1),(64060,6,1),(64080,0,0),(180000,0,1),
                    (180010,7,1),(190000,8,1)]
        events.extend([[base+us,frame,marker,level] for us,marker,level in relative])
    events.append([800000,5,1,1])
    return dict(initial_level=1,registration_err=0,overflow=False,capture_complete=True,
                origin_us=1000000,events=events)

class BusyTraceTest(unittest.TestCase):
    def test_four_frames_preserve_real_wait_and_tail_times(self):
        raw = sample()
        rows, errors = parse_traces(["I HAL: EPD_BUSY_TRACE " + json.dumps(raw)])
        self.assertEqual(errors, [])
        result = analyze_trace(rows[0])
        self.assertTrue(result["usable"])
        frame = result["frames"][0]
        self.assertEqual(frame["dtm_busy_wait_us"], 10)
        self.assertEqual(frame["ram_after_ready_us"], 63560)
        self.assertEqual(frame["ref_to_wait_return_us"], 115990)
        self.assertEqual(frame["tail_wait_us"], 9990)
        self.assertEqual(frame["nearest_release_edge_to_wait_us"], -10)

    def test_reassertion_after_wait_is_reported_not_hidden(self):
        raw = sample()
        raw["events"].extend([[185000,1,0,0],[188000,1,0,1]])
        raw["events"].sort(key=lambda e:e[0])
        result = analyze_trace(raw)
        self.assertTrue(result["usable"])
        self.assertEqual(result["frames"][0]["busy_low_edges_after_wait"], 1)
        self.assertEqual(result["frames"][0]["busy_edges_after_wait_us"], [[4990,0],[7990,1]])
        self.assertIn("not optical", result["note"])

    def test_overflow_registration_failure_and_missing_markers_are_not_usable(self):
        for updates in (dict(overflow=True),dict(registration_err=258),dict(capture_complete=False)):
            raw = sample();raw.update(updates)
            self.assertFalse(analyze_trace(raw)["usable"])
        raw = sample()
        raw["events"] = [e for e in raw["events"] if not (e[1]==1 and e[2]==7)]
        self.assertFalse(analyze_trace(raw)["usable"])

    def test_truncated_and_out_of_order_capture_do_not_invent_data(self):
        rows, errors = parse_traces(['EPD_BUSY_TRACE {"initial_level":1'])
        self.assertEqual(rows, [])
        self.assertTrue(errors)
        raw = sample();raw["events"][1][0] = -1
        rows, errors = parse_traces(["EPD_BUSY_TRACE " + json.dumps(raw)])
        self.assertEqual(rows, [])
        self.assertTrue(errors)

if __name__ == "__main__":
    unittest.main()
