import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from summarize import DURATIONS, main, parse_records, summarize


def sample(**updates):
    record = dict(path="mono", scope="driver_call", unit="us", started_us=1000,
                  total_us=410000, first_prepare=False, mono_session=True, ok=True,
                  timeouts=0, spi_errors=0, bytes=173599, stages=1)
    record.update({key: 0 for key in DURATIONS})
    record.update(ram_us=35000, ref_us=375000)
    record.update(updates)
    return record


class ProfileSummaryTest(unittest.TestCase):
    def test_noise_prefix_and_truncated_record(self):
        records, errors = parse_records([
            "normal boot log\n", "I (11) HAL_EPD: EPD_PROFILE " + json.dumps(sample()) + "\x1b[0m\n",
            'EPD_PROFILE {"path":"mono"\n',
        ])
        self.assertEqual(len(records), 1)
        self.assertEqual(errors[0]["line"], 3)

    def test_separates_prepare_and_failures(self):
        records = [sample(), sample(total_us=430000), sample(first_prepare=True, total_us=3350000),
                   sample(ok=False, timeouts=1, total_us=60000000)]
        report = summarize(records, [])
        steady = next(group for group in report["groups"] if not group["first_prepare"])
        self.assertEqual(steady["total_us"]["mean"], 420000)
        self.assertEqual(steady["failed"], 1)
        self.assertEqual(steady["timeouts"], 1)
        self.assertEqual(steady["largest_phase"], "ref_us")
        self.assertEqual(len(report["groups"]), 2)

    def test_empty_log_does_not_report_zero_as_measurement(self):
        with patch("sys.stdin", io.StringIO("")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([]), 2)

    def test_rejects_boolean_duration_and_wrong_unit(self):
        records, errors = parse_records(["EPD_PROFILE " + json.dumps(sample(total_us=True)),
                                        "EPD_PROFILE " + json.dumps(sample(unit="ms"))])
        self.assertEqual(records, [])
        self.assertEqual(len(errors), 2)


if __name__ == "__main__":
    unittest.main()
