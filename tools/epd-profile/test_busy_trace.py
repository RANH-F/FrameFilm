import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).parent))
from busy_trace import analyze_trace, parse_traces, parse_recent

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

    def test_tail_last_four_frames_and_final_idle_edges(self):
        raw = sample()
        raw["window"] = "tail"
        raw["end_us"] = 800100
        raw["end_level"] = 1
        raw["partial_frame"] = None
        raw["frames"] = []
        for ordinal in range(1, 5):
            raw["frames"].append(dict(frame=ordinal + 100, overflow=False,
                events=[[e[0], e[2], e[3]] for e in raw["events"] if e[1] == ordinal]))
        raw.pop("events")
        raw["frames"][-1]["events"].extend([[799000, 0, 0], [800000, 0, 1]])
        rows, errors = parse_traces(["EPD_BUSY_TRACE " + json.dumps(raw)])
        self.assertEqual(errors, [])
        report = analyze_trace(rows[0])
        self.assertTrue(report["usable"])
        self.assertEqual(report["window"], "tail")
        self.assertEqual(report["frames"][-1]["frame"], 104)
        self.assertEqual(report["frames"][-1]["busy_low_edges_after_wait"], 1)
        self.assertIsNone(report["frames"][-1]["next_begin_us"])
        raw["frames"][-1]["overflow"] = True
        rows, errors = parse_traces(["EPD_BUSY_TRACE " + json.dumps(raw)])
        self.assertEqual(errors, [])
        self.assertFalse(analyze_trace(rows[0])["usable"])

    def test_recent_retains_late_cadence_and_rejects_truncated_rows(self):
        raw = dict(unit="us", calls_seen=1000, errors=0, timeouts=0, spi_errors=0,
            calls=[[999,1000000,100000,58000,41000,1,False,True,0,0],
                   [1000,1100000,100000,58000,41000,1,False,True,0,0]],
            steady=dict(count=999,ok_count=999,errors=0,timeouts=0,spi_errors=0,
                first_started_us=1000,last_started_us=1100000,total_sum_us=100000000,
                phase_sum_us=[1000000,0,0,58000000,41000000,0,0],
                min_ref_us=41000,min_ref_frame=1000,min_ref_started_us=1100000))
        rows, errors = parse_recent(["EPD_MONO_RECENT " + json.dumps(raw)])
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["recent_start_intervals_us"], [100000])
        self.assertIn("do not establish optical", rows[0]["note"])
        raw["calls"][-1] = raw["calls"][-1][:-1]
        rows, errors = parse_recent(["EPD_MONO_RECENT " + json.dumps(raw)])
        self.assertEqual(rows, [])
        self.assertTrue(errors)

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
