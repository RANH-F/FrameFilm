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
        groups.append(group)
    return {
        "scope": "driver_call",
        "unit": "us",
        "note": "Driver elapsed time only; reciprocal is not observed animation FPS. Failed samples are excluded from timing means. Session-end power-off is outside frame records.",
        "records": len(records), "malformed": errors, "groups": groups,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", nargs="?", default="-", help="UTF-8 serial log, or - for stdin")
    parser.add_argument("--json", action="store_true", help="write a machine-readable summary to stdout")
    args = parser.parse_args(argv)
    try:
        if args.log == "-":
            records, errors = parse_records(sys.stdin)
        else:
            with Path(args.log).open(encoding="utf-8-sig", errors="replace") as stream:
                records, errors = parse_records(stream)
    except OSError as error:
        print(f"Cannot read serial log: {error}", file=sys.stderr)
        return 2
    if not records:
        print("No complete EPD_PROFILE records. Enable CONFIG_ARK_EPD_PROFILE, capture a refresh, then retry.", file=sys.stderr)
        for error in errors:
            print(f"line {error['line']}: {error['error']}", file=sys.stderr)
        return 2
    report = summarize(records, errors)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("Driver timing only; these values are not observed animation FPS.")
        for group in report["groups"]:
            state = "prepare" if group["first_prepare"] else "steady"
            print(f"{group['path']} / {state} / session={group['mono_session']}: "
                  f"{group['successful']}/{group['samples']} successful")
            if "total_us" in group:
                total = group["total_us"]
                print(f"  median {total['median'] / 1000:.2f} ms; mean {total['mean'] / 1000:.2f} ms; "
                      f"largest phase {group['largest_phase']}")
                print("  " + ", ".join(f"{key[:-3]}={value / 1000:.2f} ms"
                                      for key, value in group["mean_phase_us"].items()))
            if group["failed"]:
                print(f"  failures={group['failed']}, timeouts={group['timeouts']}, SPI errors={group['spi_errors']}")
    for error in errors:
        print(f"line {error['line']}: incomplete or invalid profile record: {error['error']}", file=sys.stderr)
    return 1 if errors or any(not row["ok"] for row in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
