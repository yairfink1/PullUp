#!/usr/bin/env python3
"""
read_fit_reps.py

Reads a Garmin FIT activity file and extracts repetition metrics,
including:
- Total Reps from the Activity Session (standard or developer field)
- Reps per Set / Lap (standard or developer field)
"""

import sys
import os
from typing import List, Dict, Any, Optional

try:
    import fitdecode
except ImportError:
    sys.exit("Error: 'fitdecode' is not installed. Please install it using 'pip install fitdecode'.")


def is_rep_field(name: Optional[str]) -> bool:
    """Check if the field name refers to repetition counts."""
    if not name:
        return False
    lower_name = name.lower()
    return "rep" in lower_name and "unconfirmed" not in lower_name


def parse_fit_reps(file_path: str) -> Dict[str, Any]:
    """
    Parses the FIT file and returns a dictionary with session and lap repetition data.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    session_reps: Optional[int] = None
    lap_reps: List[Dict[str, Any]] = []
    set_reps: List[Dict[str, Any]] = []

    with fitdecode.FitReader(file_path) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue

            # 1. Check Session Message (overall workout summary)
            if frame.name == "session":
                for field in frame.fields:
                    if is_rep_field(field.name) and field.value is not None:
                        session_reps = field.value
                        break

            # 2. Check Lap Messages (per-set or interval data)
            elif frame.name == "lap":
                lap_info: Dict[str, Any] = {
                    "lap_index": len(lap_reps) + 1,
                    "reps": None
                }
                for field in frame.fields:
                    if is_rep_field(field.name) and field.value is not None:
                        lap_info["reps"] = field.value
                        break
                lap_reps.append(lap_info)

            # 3. Check Set Messages (strength training sets if present)
            elif frame.name == "set":
                set_info: Dict[str, Any] = {
                    "set_index": len(set_reps) + 1,
                    "reps": None
                }
                for field in frame.fields:
                    if is_rep_field(field.name) and field.value is not None:
                        set_info["reps"] = field.value
                        break
                set_reps.append(set_info)

    # Fallback / aggregation:
    # If session_reps wasn't explicitly present, try summing laps or sets if available
    if session_reps is None:
        valid_laps = [lap["reps"] for lap in lap_reps if lap["reps"] is not None]
        if valid_laps:
            session_reps = sum(valid_laps)
        else:
            valid_sets = [s["reps"] for s in set_reps if s["reps"] is not None]
            if valid_sets:
                session_reps = sum(valid_sets)

    return {
        "file": file_path,
        "total_reps": session_reps,
        "laps": lap_reps,
        "sets": set_reps,
    }


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {os.path.basename(sys.argv[0])} <path_to_fit_file>")
        sys.exit(1)

    fit_path = sys.argv[1]

    try:
        data = parse_fit_reps(fit_path)
    except Exception as e:
        sys.exit(f"Error reading {fit_path}: {e}")

    print("=" * 40)
    print(f"FIT File: {data['file']}")
    print("=" * 40)

    if data["total_reps"] is not None:
        print(f"Total Reps: {data['total_reps']}")
    else:
        print("Total Reps: Not found in file")

    if data["laps"]:
        print("\nLap / Set Breakdown:")
        for lap in data["laps"]:
            reps_str = f"{lap['reps']} reps" if lap["reps"] is not None else "N/A"
            print(f"  Lap {lap['lap_index']}: {reps_str}")

    if data["sets"]:
        print("\nStrength Sets Breakdown:")
        for s in data["sets"]:
            reps_str = f"{s['reps']} reps" if s["reps"] is not None else "N/A"
            print(f"  Set {s['set_index']}: {reps_str}")

    print("=" * 40)


if __name__ == "__main__":
    main()
