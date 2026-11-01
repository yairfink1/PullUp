#!/usr/bin/env python3
"""
read_fit_reps.py

Reads a Garmin FIT activity file and extracts repetition and exercise type metrics,
including:
- Total Reps from the Activity Session (standard or developer field)
- Pull-Up Reps and Chin-Up Reps from the Activity Session
- Reps per Set / Lap and Exercise Type (0=Pull-Up, 1=Chin-Up)
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
    Parses the FIT file and returns a dictionary with session and lap repetition data
    and user-confirmed exercise type (Pull-Up vs. Chin-Up).
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    session_reps: Optional[int] = None
    pullup_reps: Optional[int] = None
    chinup_reps: Optional[int] = None
    lap_reps: List[Dict[str, Any]] = []
    set_reps: List[Dict[str, Any]] = []

    with fitdecode.FitReader(file_path) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue

            # 1. Check Session Message (overall workout summary)
            if frame.name == "session":
                for field in frame.fields:
                    if not field.name or field.value is None:
                        continue
                    fname_lower = field.name.lower()
                    if "pull" in fname_lower and "rep" in fname_lower:
                        pullup_reps = int(field.value)
                    elif "chin" in fname_lower and "rep" in fname_lower:
                        chinup_reps = int(field.value)
                    elif is_rep_field(field.name) and session_reps is None:
                        session_reps = int(field.value)

            # 2. Check Lap Messages (per-set or interval data)
            elif frame.name == "lap":
                lap_info: Dict[str, Any] = {
                    "lap_index": len(lap_reps) + 1,
                    "reps": None,
                    "exercise_type": None,
                }
                for field in frame.fields:
                    if not field.name or field.value is None:
                        continue
                    fname_lower = field.name.lower()
                    if "exercise" in fname_lower:
                        ex_val = int(field.value)
                        lap_info["exercise_type"] = "CHIN UP" if ex_val == 1 else "PULL UP"
                    elif is_rep_field(field.name) and lap_info["reps"] is None:
                        lap_info["reps"] = int(field.value)
                lap_reps.append(lap_info)

            # 3. Check Set Messages (strength training sets if present)
            elif frame.name == "set":
                set_info: Dict[str, Any] = {
                    "set_index": len(set_reps) + 1,
                    "reps": None
                }
                for field in frame.fields:
                    if is_rep_field(field.name) and field.value is not None:
                        set_info["reps"] = int(field.value)
                        break
                set_reps.append(set_info)

    # Fallback / aggregation:
    if session_reps is None:
        valid_laps = [lap["reps"] for lap in lap_reps if lap["reps"] is not None]
        if valid_laps:
            session_reps = sum(valid_laps)
        else:
            valid_sets = [s["reps"] for s in set_reps if s["reps"] is not None]
            if valid_sets:
                session_reps = sum(valid_sets)

    exercise_type: Optional[str] = None
    if chinup_reps is not None and chinup_reps > 0 and (pullup_reps is None or pullup_reps == 0):
        exercise_type = "CHIN UP"
    elif pullup_reps is not None and pullup_reps > 0 and (chinup_reps is None or chinup_reps == 0):
        exercise_type = "PULL UP"
    elif lap_reps and lap_reps[0].get("exercise_type") is not None:
        exercise_type = lap_reps[0]["exercise_type"]

    return {
        "file": file_path,
        "total_reps": session_reps,
        "pullup_reps": pullup_reps,
        "chinup_reps": chinup_reps,
        "exercise_type": exercise_type,
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

    if data["exercise_type"] is not None:
        print(f"Confirmed Exercise: {data['exercise_type']}")
    if data["pullup_reps"] is not None:
        print(f"Pull-Up Reps: {data['pullup_reps']}")
    if data["chinup_reps"] is not None:
        print(f"Chin-Up Reps: {data['chinup_reps']}")

    if data["laps"]:
        print("\nLap / Set Breakdown:")
        for lap in data["laps"]:
            reps_str = f"{lap['reps']} reps" if lap["reps"] is not None else "N/A"
            ex_str = f" ({lap['exercise_type']})" if lap.get("exercise_type") else ""
            print(f"  Lap {lap['lap_index']}: {reps_str}{ex_str}")

    if data["sets"]:
        print("\nStrength Sets Breakdown:")
        for s in data["sets"]:
            reps_str = f"{s['reps']} reps" if s["reps"] is not None else "N/A"
            print(f"  Set {s['set_index']}: {reps_str}")

    print("=" * 40)


if __name__ == "__main__":
    main()
