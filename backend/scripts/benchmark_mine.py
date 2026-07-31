"""Benchmark app.ingestion.miner.mine_repo against a real local clone.

Usage:
    python backend/scripts/benchmark_mine.py /path/to/local/clone

Prints commits/sec, total wall time, peak RSS, and file count. Intended to be
run against a real repo you've already cloned (e.g. `git clone
https://github.com/pallets/flask /tmp/flask`) -- this script never clones
anything itself, so cloning time never pollutes the mining measurement.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import ClassVar

# Allow running this script directly (`python backend/scripts/benchmark_mine.py`)
# without having installed the package first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.miner import mine_repo

try:
    import resource

    def _peak_rss_mb() -> float:
        # ru_maxrss is KB on Linux, bytes on macOS -- KB is the common case
        # for the ubuntu-latest CI runner this budget targets.
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

except ImportError:  # Windows has no `resource` module
    import ctypes

    class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_: ClassVar[list[tuple[str, object]]] = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    # ctypes defaults a function's restype to c_int (32-bit) when it isn't
    # set explicitly. GetCurrentProcess returns a pointer-sized pseudo
    # handle -- left at the c_int default, it gets truncated on 64-bit
    # Windows and GetProcessMemoryInfo silently fails on the corrupted
    # handle (returns 0, counters stay zeroed). Both restype/argtypes must
    # be declared correctly or this reports a bogus 0.0 MB every time.
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
        ctypes.c_ulong,
    ]

    def _peak_rss_mb() -> float:
        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        if not ok:
            return float("nan")
        return counters.PeakWorkingSetSize / (1024 * 1024)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_path", help="Path to an already-cloned local git repository")
    args = parser.parse_args()

    repo_path = str(Path(args.repo_path).resolve())

    start = time.perf_counter()
    mined = mine_repo(repo_path)
    elapsed = time.perf_counter() - start

    commit_count = len(mined.commits)
    file_count = len(mined.files)
    commits_per_sec = commit_count / elapsed if elapsed > 0 else float("inf")
    peak_rss_mb = _peak_rss_mb()

    print(f"repo:            {repo_path}")
    print(f"commits mined:   {commit_count}")
    print(f"files mined:     {file_count}")
    print(f"wall time:       {elapsed:.2f}s")
    print(f"commits/sec:     {commits_per_sec:.1f}")
    print(f"peak RSS:        {peak_rss_mb:.1f} MB")


if __name__ == "__main__":
    main()
