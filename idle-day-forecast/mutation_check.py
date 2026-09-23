# -*- coding: utf-8 -*-
"""Break idle_day_forecast.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. Each mutation below is a mistake a forecaster
of this kind plausibly makes: counting an assigned issue as free, ignoring blockers, forecasting
from a history that is cut short, rounding the day down. The script runs the suite against each
mutated copy and reports any mutation the suite lets through. Exit code 0 means every one was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "idle_day_forecast.py"
BAK = HERE / "idle_day_forecast.py.mutation-backup"

MUTATIONS = [
    ("M1  an assigned issue counted as pickable",
     "        if not self.ignore_assignee and x.assigned_at(t):\n            return False",
     "        if False:\n            return False"),
    ("M2  blockers ignored",
     "            if bt.created <= t and self.cats.get(bt.status_at(t)) != \"done\":\n                return False",
     "            if False:\n                return False"),
    ("M3  a blocker counted by its state today, not on that day",
     "            if bt.created <= t and self.cats.get(bt.status_at(t)) != \"done\":",
     "            if bt.created <= t and self.cats.get(bt.status_v[-1]) != \"done\":"),
    ("M4  links unwound the wrong way",
     "    for t, k, d in reversed(events):\n        if d > 0:\n            initial.discard(k)\n        else:\n            initial.add(k)",
     "    for t, k, d in reversed(events):\n        if d > 0:\n            initial.add(k)\n        else:\n            initial.discard(k)"),
    ("M5  search total not checked",
     "        if total is not None and total != len(issues):",
     "        if False:"),
    ("M6  a cut-short changelog accepted",
     "    if cl.get(\"total\", len(hist)) > len(hist) or cl.get(\"complete\") is False:",
     "    if False:"),
    ("M7  unknown status names accepted",
     "        if unknown:\n            problems.append(\"status names",
     "        if False:\n            problems.append(\"status names"),
    ("M8  a history that does not reach today's status accepted",
     "    if prev != now_status:\n        problems.append(",
     "    if False:\n        problems.append("),
    ("M9  blockers outside the file accepted",
     "        if missing and unreadable == \"refuse\":\n            problems.append(\"blocked by issues",
     "        if False:\n            problems.append(\"blocked by issues"),
    ("M10 the forecast day rounded down",
     "        return math.ceil(n / rate)",
     "        return math.floor(n / rate)"),
    ("M11 pace taken over the wrong span",
     "    drain = (counts[c - window] - n) / window",
     "    drain = (counts[c - window + 1] - n) / window"),
    ("M12 day ends in UTC whatever --tz says",
     "                inst = dt.datetime(nxt.year, nxt.month, nxt.day, tzinfo=self.tz).timestamp() - 1e-6",
     "                inst = dt.datetime(nxt.year, nxt.month, nxt.day, tzinfo=dt.timezone.utc).timestamp() - 1e-6"),
    ("M13 a future start date ignored",
     "        if x.start is not None and x.start > dt.datetime.fromtimestamp(t, self.tz).date():",
     "        if False:"),
    ("M14 an issue counted before it was created",
     "        if x.entered > t:\n            return False\n        if x.status_at",
     "        if False:\n            return False\n        if x.status_at"),
    ("M23 an issue moved in from another project counted from its creation",
     "    entered = max(created, moves[-1][0]) if moves else created",
     "    entered = created"),
    ("M15 backtest forecasts from the last day instead of the cut (sees the future)",
     "        f = forecast_at(counts, c, window)\n        pred",
     "        f = forecast_at(counts, len(counts) - 1, window)\n        pred"),
    ("M16 a flat backlog forecast as emptying",
     "        if rate <= 0:\n            return None",
     "        if rate < 0:\n            return None"),
    ("M17 --fail-within ignored",
     "        hit = a.fail_within is not None and f[\"days\"] <= a.fail_within",
     "        hit = False"),
    ("M18 --ready typo accepted",
     "            if bad:\n                problems.append(\"--ready",
     "            if False:\n                problems.append(\"--ready"),
    ("M19 a history with a gap accepted",
     "        if it.get(\"fromString\") != prev:",
     "        if False:"),
    ("M20 slowest week taken as the fastest",
     "    slow = min(weeks) if weeks else drain",
     "    slow = max(weeks) if weeks else drain"),
    ("M21 a false alarm scored as right",
     "        elif actual is None:\n            kind = \"false-alarm\"",
     "        elif actual is None:\n            kind = \"quiet-right\""),
    ("M22 timestamp offset ignored",
     "        tz = dt.timezone(sign * dt.timedelta(hours=int(off[1:3]), minutes=int(off[3:5])))\n    return t.replace",
     "        tz = dt.timezone.utc\n    return t.replace"),
]


def run_tests():
    r = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_idle_day_forecast"], cwd=str(HERE),
                       capture_output=True, text=True)
    return r.returncode == 0


def main():
    original = SRC.read_text(encoding="utf-8")
    if not run_tests():
        print("the unmodified suite fails; fix that first")
        return 2
    shutil.copyfile(SRC, BAK)
    survived = []
    try:
        for name, old, new in MUTATIONS:
            if original.count(old) != 1:
                print("SKIP  %s  (pattern found %d times)" % (name, original.count(old)))
                survived.append(name + " (pattern not unique)")
                continue
            SRC.write_text(original.replace(old, new), encoding="utf-8")
            caught = not run_tests()
            print("%s  %s" % ("caught  " if caught else "SURVIVED", name))
            if not caught:
                survived.append(name)
    finally:
        shutil.copyfile(BAK, SRC)
        BAK.unlink()
    print("")
    print("%d of %d mutations caught" % (len(MUTATIONS) - len(survived), len(MUTATIONS)))
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
