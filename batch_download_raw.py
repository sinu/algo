"""Batch download by running live_v17_direct.py per day.

Captures the full V17 output (signals, trade results, session summary)
and saves to v17_raw_data/YYYY-MM-DD.txt — same output as running
'python live_v17_direct.py 2026-XX-XX' manually.

Usage:
    python batch_download_raw.py                        # Dec 3 2025 to Jun 23 2026
    python batch_download_raw.py 2026-01-05 2026-01-10  # Custom range
"""
import sys
import os
import subprocess
from datetime import datetime, timedelta, date

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v17_raw_data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_SCRIPT = os.path.join(SCRIPT_DIR, "live_v17_direct.py")


def get_market_days(start_date, end_date):
    """Generate weekday dates (Mon-Fri) in range."""
    days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def main():
    if len(sys.argv) >= 3:
        start_date = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
        end_date = datetime.strptime(sys.argv[2], '%Y-%m-%d').date()
    else:
        start_date = date(2025, 12, 3)
        end_date = date(2026, 6, 23)

    market_days = get_market_days(start_date, end_date)
    print(f"Batch download (V17 output): {start_date} to {end_date}")
    print(f"Market days (weekdays): {len(market_days)}")
    print(f"Output: {OUTPUT_DIR}")
    print("=" * 60)

    # Skip days already downloaded (must have SESSION SUMMARY to be complete)
    existing = set()
    for f in os.listdir(OUTPUT_DIR):
        if f.endswith('.txt'):
            fpath = os.path.join(OUTPUT_DIR, f)
            if os.path.getsize(fpath) > 100:
                with open(fpath, 'rb') as fh:
                    content = fh.read()
                if b'SESSION SUMMARY' in content:
                    existing.add(f.replace('.txt', ''))
    pending = [d for d in market_days if d.strftime('%Y-%m-%d') not in existing]
    print(f"Already downloaded: {len(existing)}")
    print(f"Remaining: {len(pending)}")
    print("=" * 60)

    if not pending:
        print("All days already downloaded.")
        return

    success = 0
    failed = 0

    for i, day in enumerate(pending):
        date_str = day.strftime('%Y-%m-%d')
        out_path = os.path.join(OUTPUT_DIR, f"{date_str}.txt")

        try:
            result = subprocess.run(
                [sys.executable, LIVE_SCRIPT, date_str],
                capture_output=True,
                timeout=90,
                cwd=SCRIPT_DIR,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            output = result.stdout

            if b'SESSION SUMMARY' not in output:
                print(f"  [{i+1}/{len(pending)}] {date_str}: NO SUMMARY (incomplete)")
                failed += 1
                continue

            with open(out_path, 'wb') as f:
                f.write(output)

            sig_count = output.count(b'V17 SIGNAL')
            print(f"  [{i+1}/{len(pending)}] {date_str}: OK ({sig_count} signals)")
            success += 1

        except subprocess.TimeoutExpired:
            print(f"  [{i+1}/{len(pending)}] {date_str}: TIMEOUT")
            failed += 1
        except Exception as e:
            print(f"  [{i+1}/{len(pending)}] {date_str}: ERROR ({e})")
            failed += 1

    print("\n" + "=" * 60)
    print(f"DONE: {success} downloaded, {failed} failed")
    print(f"Files saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
