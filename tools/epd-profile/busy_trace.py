"""Inspect bounded EPD_BUSY_TRACE GPIO observations without controlling a device."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from typing import Iterable

MARKERS = {0: "edge", 1: "begin", 2: "dtm_before", 3: "dtm_after",
           4: "ram_done", 5: "ref_before", 6: "ref_after",
           7: "wait_return", 8: "tail_return", 9: "dtm_ready"}

def parse_traces(lines: Iterable[str]) -> tuple[list[dict], list[dict]]:
    traces, errors = [], []
    for number, line in enumerate(lines, 1):
        token = "EPD_BUSY_TRACE "
        start = line.find(token)
        if start < 0:
            continue
        try:
            row, _ = json.JSONDecoder().raw_decode(line[start + len(token):].lstrip())
            if not isinstance(row, dict):
                raise ValueError("expected a JSON object")
            for key in ("overflow", "capture_complete"):
                if type(row.get(key)) is not bool:
                    raise ValueError(f"{key} must be boolean")
            for key in ("registration_err", "origin_us"):
                if type(row.get(key)) is not int:
                    raise ValueError(f"{key} must be integer")
            if type(row.get("initial_level")) is not int or row["initial_level"] not in (-1, 0, 1):
                raise ValueError("invalid initial level")
            if not isinstance(row.get("events"), list):
                raise ValueError("events must be a list")
            previous = -1
            for event in row["events"]:
                if not isinstance(event, list) or len(event) != 4 or any(type(x) is not int for x in event):
                    raise ValueError("events must contain integer [us, frame, marker, level]")
                us, frame, marker, level = event
                if us < previous or frame < 1 or marker not in MARKERS or level not in (0, 1):
                    raise ValueError("invalid or out-of-order event")
                previous = us
            traces.append(row)
        except (ValueError, TypeError) as error:
            errors.append(dict(line=number, error=str(error)))
    return traces, errors

def analyze_trace(row: dict) -> dict:
    events = row["events"]
    reasons = []
    if row["registration_err"]:
        reasons.append("GPIO registration failed")
    if row["overflow"]:
        reasons.append("capture overflowed")
    if not row["capture_complete"]:
        reasons.append("capture window incomplete")
    if row["initial_level"] < 0:
        reasons.append("capture did not start")
    frames = []
    ordinals = sorted({e[1] for e in events})
    for ordinal in ordinals:
        own = [e for e in events if e[1] == ordinal and e[2] != 0]
        by_marker = {e[2]: e for e in own}
        if 5 not in by_marker:
            continue
        required = (1, 2, 3, 9, 4, 5, 6, 7, 8)
        missing = [MARKERS[k] for k in required if k not in by_marker]
        if missing:
            reasons.append(f"frame {ordinal} missing markers: {', '.join(missing)}")
            continue
        starts = [e[0] for e in events if e[2] == 1 and e[1] == ordinal + 1]
        next_begin = starts[0] if starts else None
        if len(own) != len(by_marker) or [by_marker[k][0] for k in required] != sorted(by_marker[k][0] for k in required):
            reasons.append(f"frame {ordinal} duplicate or misordered markers")
            continue
        ref = by_marker[5][0]
        wait = by_marker[7][0]
        tail = by_marker[8][0]
        window_end = next_begin if next_begin is not None else tail
        edges = [e for e in events if e[2] == 0 and ref <= e[0] <= window_end]
        after_wait = [e for e in edges if e[0] > wait]
        highs = [e for e in edges if e[3] == 1]
        nearest_release = min(highs, key=lambda e: abs(e[0] - wait)) if highs else None
        frames.append(dict(
            frame=ordinal,
            marker_us={MARKERS[k]: by_marker[k][0] for k in required},
            marker_levels={MARKERS[k]: by_marker[k][3] for k in required},
            dtm_command_us=by_marker[3][0] - by_marker[2][0],
            dtm_busy_wait_us=by_marker[9][0] - by_marker[3][0],
            ram_after_ready_us=by_marker[4][0] - by_marker[9][0],
            ref_command_us=by_marker[6][0] - ref,
            ref_to_wait_return_us=wait - ref,
            tail_wait_us=tail - wait,
            next_begin_us=next_begin,
            next_begin_after_tail_us=None if next_begin is None else next_begin - tail,
            busy_edges_since_ref_us=[[e[0] - ref, e[3]] for e in edges],
            busy_edges_after_wait_us=[[e[0] - wait, e[3]] for e in after_wait],
            busy_low_edges_after_wait=sum(e[3] == 0 for e in after_wait),
            nearest_release_edge_to_wait_us=None if nearest_release is None else nearest_release[0] - wait,
        ))
    if len(frames) != 4:
        reasons.append(f"expected 4 complete frame windows, got {len(frames)}")
    return dict(
        scope="software_gpio_observation",
        capture_window="early four steady frames and following begin; no late-session trace",
        timer_unit="us",
        note="ISR timestamps observe GPIO levels, not optical settling; near-simultaneous marker/IRQ ordering has interrupt latency.",
        usable=not reasons,
        reasons=reasons,
        origin_us=row["origin_us"],
        initial_level=row["initial_level"],
        registration_err=row["registration_err"],
        overflow=row["overflow"],
        capture_complete=row["capture_complete"],
        event_count=len(events),
        frames=frames,
    )

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log", help="UTF-8 serial log")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        lines = Path(args.log).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError as error:
        print(error, file=sys.stderr)
        return 2
    rows, errors = parse_traces(lines)
    reports = [analyze_trace(row) for row in rows]
    result = dict(traces=reports, malformed=errors)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Software BUSY observations only; this does not measure optical frame completion.")
        for i, report in enumerate(reports, 1):
            print(f"capture {i}: usable={report['usable']}, records={report['event_count']}")
            for reason in report["reasons"]:
                print("  " + reason)
            for frame in report["frames"]:
                print(f"  frame {frame['frame']}: REF-to-return={frame['ref_to_wait_return_us']}us, "
                      f"tail={frame['tail_wait_us']}us, "
                      f"DTM-wait={frame['dtm_busy_wait_us']}us, "
                      f"busy-low edges after wait={frame['busy_low_edges_after_wait']}")
    if errors:
        return 1
    if not rows:
        return 2
    return 0 if any(r["usable"] for r in reports) and not any(
        r["event_count"] and not r["usable"] for r in reports) else 1

if __name__ == "__main__":
    raise SystemExit(main())
