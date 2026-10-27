import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent))
from summarize import DURATIONS, main, parse_sessions, summarize_sessions

def session(**updates):
    row = dict(path="mono", scope="mono_session", unit="us", sample_count=3, ok_samples=3,
               error_samples=0, dropped_samples=2, first_started_us=1000, last_started_us=301000,
               interval_count=2, interval_min_us=140000, interval_p50_us=150000.0,
               interval_max_us=160000, interval_sum_us=300000, total_min_us=90000,
               total_max_us=110000, total_sum_us=300000, bytes_sum=520818, ram_bytes_sum=518400,
               ram_transactions_sum=360, stages_sum=3, timeouts=0, spi_errors=0,
               sum_us={key: 0 for key in DURATIONS}, ok=True)
    row["sum_us"].update(ram_us=120000, ref_us=180000)
    row.update(updates)
    return row

class SessionSummaryTest(unittest.TestCase):
    def test_session_only_cli_and_real_intervals(self):
        line = "I HAL_EPD: EPD_PROFILE_SESSION " + json.dumps(session())
        rows, errors = parse_sessions([line])
        self.assertFalse(errors)
        report = summarize_sessions(rows)[0]
        self.assertEqual(report["samples"], 3)
        self.assertEqual(report["mean_phase_us"]["ram_us"], 40000)
        self.assertEqual(report["mean_ram_transactions"], 120)
        self.assertAlmostEqual(report["observed_start_rate_per_second"], 1e6 / 150000)
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(line)), contextlib.redirect_stdout(output):
            self.assertEqual(main(["--json"]), 0)
        self.assertEqual(json.loads(output.getvalue())["sessions"][0]["samples"], 3)

    def test_failed_session_never_invents_successful_timings(self):
        bad = session(ok_samples=0, error_samples=5, timeouts=1, total_sum_us=0, ok=False)
        report = summarize_sessions([bad])[0]
        self.assertEqual(report["failed"], 3)
        self.assertEqual(report["observed_error_samples"], 5)
        self.assertNotIn("total_us", report)
        with patch("sys.stdin", io.StringIO("EPD_PROFILE_SESSION " + json.dumps(bad))), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--json"]), 1)

    def test_truncation_and_invalid_count_not_accepted_as_measurement(self):
        for text in ['EPD_PROFILE_SESSION {"path":"mono"', "EPD_PROFILE_SESSION " + json.dumps(session(sample_count=0))]:
            with self.subTest(text=text):
                rows, errors = parse_sessions([text])
                self.assertEqual(rows, [])
                self.assertTrue(errors)
                with patch("sys.stdin", io.StringIO(text)), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["--json"]), 2)

if __name__ == "__main__":
    unittest.main()
