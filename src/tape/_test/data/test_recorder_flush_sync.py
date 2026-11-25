"""Commit handler of the ported `test_recorder_flush_*.glm` autotests

Checks that the rows of `test_recorder_flush_0.csv` that are on disk at each
commit are those the recorder's `flush` property promises: all of them when
`flush` is 0, and none of the buffered ones when it is -1. Rewritten from
gridlabd's `test_recorder_flush_sync.py`, which used `pandas` and
`gldcore`; a failed check returns 0, which stops the run (gridlabd's handler
returned `None`, which gridlabd reports as an error).
"""

import os
import weakref

from arras.runner import Runner

_COUNT: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()

def test_commit(obj:str, t:int) -> int|None: # pylint: disable=unused-argument
    """Compare the number of commits with the rows on disk"""
    model = Runner.current().model
    srcdir = os.getenv("DIR") or "."
    try:
        with open(f"{srcdir}/test_recorder_flush_0.csv", encoding="utf-8") as fh:
            rows = max(0, len([x for x in fh.read().splitlines() if x]) - 1)
    except OSError:
        rows = 0
    flush = int(model.get_property("recorder", "flush")) or 1
    count = _COUNT[model] = _COUNT.get(model, 0) + 1
    if int(count/flush) != int(rows/flush):
        return 0
    return None
