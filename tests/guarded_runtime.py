"""Benchmark-only audit boundary; the scorer runs in a different process."""
import os
from pathlib import Path
import runpy
import sys


def reject_truth_access(event, args):
    if event != 'open' or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
        return
    raw = os.fsdecode(args[0])
    if 'truth' in raw.casefold():
        raise PermissionError('BENCHMARK_TRUTH_ACCESS_DENIED')
    # Resolve links too, so an innocently named link cannot expose the oracle.
    if 'truth' in str(Path(raw).resolve()).casefold():
        raise PermissionError('BENCHMARK_TRUTH_ACCESS_DENIED')


if __name__ == '__main__':
    target = sys.argv[1]
    sys.argv = sys.argv[1:]
    sys.addaudithook(reject_truth_access)
    runpy.run_path(target, run_name='__main__')
