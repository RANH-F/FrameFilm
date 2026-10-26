"""Summarize opt-in Ark EPD_PROFILE serial records without touching a device."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import sys
from typing import Iterable

DURATIONS = ("init_us", "lut_us", "ram_us", "ref_us", "pon_us", "pof_us", "other_us")
PATHS = {"mono", "color_fast", "color_qual"}


def parse_records(lines: Iterable[str]) -> tuple[list[dict], list[dict]]:
    records, errors = [], []
    for number, line in enumerate(lines, 1):
        marker = line.find("EPD_PROFILE ")
        if marker < 0:
            continue
        try:
            value, _ = json.JSONDecoder().raw_decode(line[marker + 12:].lstrip())
            if not isinstance(value, dict):
                raise ValueError("expected a JSON object")
            if value.get("path") not in PATHS or value.get("scope") != "driver_call":
                raise ValueError("unsupported path or scope")
            if value.get("unit") != "us":
                raise ValueError("expected microseconds")
            for key in ("first_prepare", "mono_session", "ok"):
                if type(value.get(key)) is not bool:
                    raise ValueError(f"{key} must be a boolean")
            for key in ("total_us", "started_us", "timeouts", "spi_errors", "bytes", "stages", *DURATIONS):
                if type(value.get(key)) is not int or value[key] < 0:
                    raise ValueError(f"{key} must be a non-negative integer")
            if "ram_transactions" in value and (type(value["ram_transactions"]) is not int or value["ram_transactions"] < 0):
                raise ValueError("ram_transactions must be a non-negative integer")
            if value["total_us"] == 0:
                raise ValueError("total_us must be positive")
            records.append(value)
        except (ValueError, TypeError) as error:
            errors.append({"line": number, "error": str(error)})
    return records, errors


def summarize(records: list[dict], errors: list[dict]) -> dict:
    buckets = defaultdict(list)
    for record in records:
        key = (record["path"], record["first_prepare"], record["mono_session"])
        buckets[key].append(record)
    groups = []
    for (path, prepare, session), values in sorted(buckets.items()):
        good = [row for row in values if row["ok"]]
        group = {
            "path": path, "first_prepare": prepare, "mono_session": session,
            "samples": len(values), "successful": len(good),
            "failed": len(values) - len(good),
            "timeouts": sum(row["timeouts"] for row in values),
            "spi_errors": sum(row["spi_errors"] for row in values),
        }
        if good:
            totals = sorted(row["total_us"] for row in good)
            mean = statistics.fmean(totals)
            phase_means = {key: round(statistics.fmean(row[key] for row in good), 2) for key in DURATIONS}
            group.update({
                "total_us": {"min": totals[0], "median": statistics.median(totals),
                             "mean": round(mean, 2), "max": totals[-1]},
                "mean_phase_us": phase_means,
                "largest_phase": max(phase_means, key=phase_means.get),
                "mean_driver_call_capacity_per_second": round(1_000_000 / mean, 3),
                "mean_bytes": round(statistics.fmean(row["bytes"] for row in good), 2),
                "mean_refresh_stages": round(statistics.fmean(row["stages"] for row in good), 2),
            })
        if good and all("ram_transactions" in row for row in good):
            group["mean_ram_transactions"] = statistics.fmean(row["ram_transactions"] for row in good)
        groups.append(group)
    return {
        "scope": "driver_call",
        "unit": "us",
        "note": "Driver elapsed time only; reciprocal is not observed animation FPS. Failed samples are excluded from timing means. Session-end power-off is outside frame records.",
        "records": len(records), "malformed": errors, "groups": groups,
    }



def parse_sessions(lines: Iterable[str]) -> tuple[list[dict], list[dict]]:
    """Read bounded Mono session aggregates, never treating them as one frame."""
    sessions, errors = [], []
    for number, line in enumerate(lines, 1):
        marker = "EPD_PROFILE_SESSION "
        start = line.find(marker)
        if start < 0:
            continue
        try:
            row, _ = json.JSONDecoder().raw_decode(line[start + len(marker):].lstrip())
            if row.get("path") != "mono" or row.get("scope") != "mono_session" or row.get("unit") != "us":
                raise ValueError("unsupported session scope or unit")
            keys = ("sample_count", "ok_samples", "error_samples", "dropped_samples",
                    "first_started_us", "last_started_us", "interval_count", "interval_min_us",
                    "interval_max_us", "interval_sum_us", "total_min_us", "total_max_us",
                    "total_sum_us", "bytes_sum", "ram_bytes_sum", "ram_transactions_sum",
                    "stages_sum", "timeouts", "spi_errors")
            for key in keys:
                if type(row.get(key)) is not int or row[key] < 0:
                    raise ValueError(f"{key} must be a non-negative integer")
            if type(row.get("interval_p50_us")) not in (int, float) or row["interval_p50_us"] < 0:
                raise ValueError("interval_p50_us must be non-negative")
            if row["sample_count"] < 1 or row["ok_samples"] > row["sample_count"]:
                raise ValueError("invalid sample counts")
            if row["interval_count"] > row["sample_count"] - 1:
                raise ValueError("invalid interval count")
            for key in DURATIONS:
                value = row.get("sum_us", {}).get(key)
                if type(value) is not int or value < 0:
                    raise ValueError(f"sum_us.{key} must be a non-negative integer")
            if row["ok_samples"] and row["total_sum_us"] == 0:
                raise ValueError("successful timings cannot be zero")
            sessions.append(row)
        except (ValueError, TypeError, AttributeError) as error:
            errors.append({"line": number, "error": str(error)})
    return sessions, errors


def summarize_sessions(sessions: list[dict]) -> list[dict]:
    groups = []
    for row in sessions:
        count = row["ok_samples"]
        group = {
            "path": "mono", "scope": "mono_session", "first_prepare": False, "mono_session": True,
            "samples": row["sample_count"], "successful": count,
            "failed": row["sample_count"] - count,
            "observed_error_samples": row["error_samples"],
            "dropped_samples": row["dropped_samples"],
            "timeouts": row["timeouts"], "spi_errors": row["spi_errors"],
            "first_started_us": row["first_started_us"], "last_started_us": row["last_started_us"],
        }
        if count:
            mean = row["total_sum_us"] / count
            phases = {key: round(row["sum_us"][key] / count, 2) for key in DURATIONS}
            group.update(
                total_us={"min": row["total_min_us"], "mean": round(mean, 2), "max": row["total_max_us"]},
                mean_phase_us=phases, largest_phase=max(phases, key=phases.get),
                mean_bytes=row["bytes_sum"] / count,
                mean_ram_bytes=row["ram_bytes_sum"] / count,
                mean_ram_transactions=row["ram_transactions_sum"] / count,
                mean_refresh_stages=row["stages_sum"] / count,
                mean_driver_call_capacity_per_second=round(1_000_000 / mean, 3),
            )
        intervals = row["interval_count"]
        if intervals:
            median = row["interval_p50_us"]
            group["observed_start_interval_us"] = {
                "samples": intervals, "min": row["interval_min_us"], "median": median,
                "mean": row["interval_sum_us"] / intervals, "max": row["interval_max_us"],
            }
            if median > 0:
                group["observed_start_rate_per_second"] = 1_000_000 / median
            if row["interval_sum_us"] > 0:
                group["observed_mean_start_rate_per_second"] = 1_000_000 * intervals / row["interval_sum_us"]
        groups.append(group)
    return groups

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", nargs="?", default="-", help="UTF-8 serial log, or - for stdin")
    parser.add_argument("--json", action="store_true", help="write a machine-readable summary to stdout")
    args = parser.parse_args(argv)
    try:
        if args.log == "-":
            lines = list(sys.stdin)
        else:
            lines = Path(args.log).read_text(encoding="utf-8-sig", errors="replace").splitlines()
        records, errors = parse_records(lines)
        sessions, session_errors = parse_sessions(lines)
        errors.extend(session_errors)
    except OSError as error:
        print(f"Cannot read serial log: {error}", file=sys.stderr)
        return 2
    if not records and not sessions:
        print("No complete EPD_PROFILE records. Enable CONFIG_ARK_EPD_PROFILE, capture a refresh, then retry.", file=sys.stderr)
        for error in errors:
            print(f"line {error['line']}: {error['error']}", file=sys.stderr)
        return 2
    report = summarize(records, errors)
    if sessions:
        report["sessions"] = summarize_sessions(sessions)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("Driver timing is not animation FPS; session start intervals measure observed calls.")
        for group in report["groups"] + report.get("sessions", []):
            state = "prepare" if group["first_prepare"] else "steady"
            print(f"{group['path']} / {state} / session={group['mono_session']}: "
                  f"{group['successful']}/{group['samples']} successful")
            if "total_us" in group:
                total = group["total_us"]
                print(f"  mean {total['mean'] / 1000:.2f} ms; largest phase {group['largest_phase']}")
                print("  " + ", ".join(f"{key[:-3]}={value / 1000:.2f} ms"
                                      for key, value in group["mean_phase_us"].items()))
            if "observed_start_rate_per_second" in group:
                print(f"  observed median-interval rate {group['observed_start_rate_per_second']:.3f}/s "
                      f"({group['observed_start_interval_us']['samples']} intervals)")
            if group["failed"] or group.get("observed_error_samples"):
                print(f"  failures={group['failed']}, observed errors={group.get('observed_error_samples', group['failed'])}, "
                      f"timeouts={group['timeouts']}, SPI errors={group['spi_errors']}")
    for error in errors:
        print(f"line {error['line']}: incomplete or invalid profile record: {error['error']}", file=sys.stderr)
    return 1 if errors or any(not row["ok"] for row in records) or any(
        row["error_samples"] or row["timeouts"] or row["spi_errors"] for row in sessions) else 0


if __name__ == "__main__":
    raise SystemExit(main())
