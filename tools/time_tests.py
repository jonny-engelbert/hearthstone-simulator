"""Run the full unittest suite and report its 15 slowest individual tests."""

import json
from pathlib import Path
import time
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TimedResult(unittest.TextTestResult):
    timings = None

    def startTest(self, test):
        self.started = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        self.timings.append((time.perf_counter() - self.started, test.id()))
        super().stopTest(test)


if __name__ == '__main__':
    TimedResult.timings = []
    suite = unittest.defaultTestLoader.discover('tests')
    started = time.perf_counter()
    result = unittest.TextTestRunner(resultclass=TimedResult, verbosity=0).run(suite)
    report = dict(
        tests=result.testsRun,
        seconds=time.perf_counter() - started,
        successful=result.wasSuccessful(),
        slowest=sorted(TimedResult.timings, reverse=True)[:15],
    )
    destination = Path('outputs/test-timing.json')
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(not result.wasSuccessful())
