# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Collectors (class `collector`)

A `collector` writes aggregates of a property over a group of objects to
a CSV file, one row per sample.

Syntax
------

    module tape;
    object collector {
        group "<find expression>";
        property "<aggregator>(<property>[.<part>][[<unit>]])[,...]";
        file "<file>";
        interval <seconds>;
        limit <integer>;
        flush <integer>;
        trigger "<op><value>";
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `trigger` | `char32` | | condition to start recording |
| `file` | `char1024` | | file in which to record data |
| `limit` | `int32` | `0` | limit on number of rows to record (0=none) |
| `group` | `char256` | | objects to aggregate (find expression) |
| `flush` | `int32` | `0` | row flush mode (-1=when full, 0=every row, >0=interval in seconds) |
| `interval` | `double[s]` | `-1 s` | sampling interval |
| `property` | `method` | | list of aggregates |

Description
-----------

A collector behaves as a `tape.recorder` that records aggregates instead
of properties of its parent, and is expected to satisfy:

1. Each aggregate is `AGGREGATOR(PROPERTY)`, or `AGGREGATOR|PROPERTY|`
   for the aggregate of absolute values, where `AGGREGATOR` is `min`,
   `max`, `avg`, `mean`, `std`, `var`, `sum`, `prod` (which sums, as in
   gridlabd), `mbe`, `count`, or `gamma` (`skew` and `kur` are not
   implemented, as in gridlabd). A complex property needs a part: `real`,
   `imag`, `mag`, `ang` (degrees), or `arg` (radians). A unit
   (`PROPERTY[UNIT]`) converts `double` values.
2. The aggregates are taken over the objects of `group` (header terms of
   the find language: `class`, `isa`, `groupid`, `module`, `id`, `name`,
   `parent`, `rank`) that are in service, and written with the
   `double_format` global.
3. The default file name is the group with characters other than
   letters, digits, `-`, and `.` replaced by `_`, and the extension `txt`.
   `FILE` may also be `TYPE:FILE[:FLAGS]`; only the `file` type is
   supported.
4. The file has the header that `tape::csv_data_only` selects; when the
   run ends, the last sample of a positive `interval` is written and the
   file is closed with `# end of tape` (unless `csv_data_only` is set).
5. Sampling starts at the first time, before the file opens, so the
   first row is the first sample and a trigger compares the values sampled
   at each time. Recording stops after `limit` rows.

Examples
--------

    >>> import os, tempfile
    >>> from arras import Model, Class, Runner
    >>> Class.reset()
    >>> csv = os.path.join(tempfile.mkdtemp(), "out.csv")
    >>> m = Model()
    >>> m.read_glm(f'''clock {{ timezone "UTC"; starttime "2020-01-01 00:00:00"; stoptime "2020-01-01 02:00:00"; }}
    ... module tape {{ csv_header_type NAME; }}
    ... class load {{ double power[kW]; }}
    ... object load {{ power 1; }}
    ... object load {{ power 3; }}
    ... object collector {{ group "class=load"; property "sum(power),max(power[W])"; file "{csv}"; interval 3600; }}
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> print(open(csv).read(), end="")
    timestamp,sum(power),max(power[W])
    2020-01-01 00:00:00 UTC,+4,+3000
    2020-01-01 01:00:00 UTC,+4,+3000
    2020-01-01 02:00:00 UTC,+4,+3000
    >>> Class.reset()

Caveats
-------

- Groups support the header terms of the find language only (decision
  8.6); other terms make the aggregate not valid.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A collector samples from the first time: it reads its `interval` when
   it is created. gridlabd reads it only when the file opens, so before
   that it samples nothing: its first row is its second sample, and a
   trigger, which compares values that were never sampled, never opens
   the file (and gridlabd then adds `TS_NEVER` to the clock, which
   overflows).
2. `limit` rows are written; gridlabd writes `limit`+1.
3. When the run ends, the last sample of a positive `interval` is
   written and the file is closed with `# end of tape`; gridlabd loses the
   last sample and leaves the file to the process exit, without the line.
4. An aggregate that divides by zero (`avg` of no object in service,
   `std` of one) is `nan`, or an infinity of the sign of the numerator;
   gridlabd writes what the C library gives.

References
----------

- `arras-energy/gridlabd`: `module/tape/collector.cpp`, `tape.h`,
  `module/tape_file/tape_file.cpp`, `source/aggregate.cpp`
- [Collector class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Tape/Collector.md)
  (`docs/Module/Tape/Collector.md`)
"""

import re
from typing import Any

from . import _file
from ._aggregate import Aggregate
from ._base import TapeClass, prop
from ._common import (TS_NEVER, TS_INIT, TS_OPEN, TS_DONE, TS_ERROR, TRL_PROVEN, TapeError,
    gl_error, get_state, set_state, clock, cprintf, to_double, strtime)
from .recorder import compare

class CollectorState: # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """State of a collector between handler calls (gridlabd `struct collector`)"""

    def __init__(self, model:Any, name:str):
        self.status = TS_INIT
        self.fp: Any = None
        self.file = model.get_property(name, "file") or ""
        self.group = model.get_property(name, "group") or ""
        self.property = model.get_property(name, "property") or None
        self.trigger = model.get_property(name, "trigger") or ""
        self.limit = int(model.get_property(name, "limit") or 0)
        self.flush = int(model.get_property(name, "flush") or 0)
        self.interval = int(to_double(model.get_property(name, "interval") or "-1", "s"))
        self.last_ts = -1
        self.last_value = ""
        self.samples = 0
        self.clock = 0
        self.aggregates: list[Aggregate]|None = None

def state(model:Any, name:str) -> CollectorState:
    """State of a collector, created on first use"""
    st = get_state(model, name)
    if st is None:
        st = CollectorState(model, name)
        set_state(model, name, st)
    return st

class Collector(TapeClass):
    """Class `collector`; see the module documentation"""

    NAME = "collector"
    PASSCONFIG = "POSTTOPDOWN|OBSERVER"
    TRL = TRL_PROVEN
    PROPERTIES = (
        ("trigger", "char32", prop(default="")),
        ("file", "char1024", prop()),
        ("limit", "int32", prop(default="0")),
        ("group", "char256", prop()),
        ("flush", "int32", prop(default="0")),
        ("interval[s]", "double", prop(default="-1 s")),
        ("property", "method", prop()),
    )
    EVENTS = ("postsync", "finalize")

    @staticmethod
    def link(model:Any, st:CollectorState) -> list[Aggregate]|None:
        """`link_aggregates()`: the aggregates of `property`"""
        result = []
        for item in [x for x in (st.property or "").split(",") if x]:
            try:
                result.append(Aggregate(model, item, st.group))
            except TapeError:
                return None
        return result or None

    @staticmethod
    def read(model:Any, st:CollectorState, size:int=1024) -> str|None:
        """`read_aggregates()`: the aggregates as text"""
        fmt = model.globals.get("double_format") or "%+lg"
        values: list[str] = []
        count = 0
        for aggregate in st.aggregates or []:
            try:
                text = cprintf(fmt, aggregate.value())
            except TapeError as err:
                gl_error(str(err))
                return None
            if count + len(text) >= size:
                gl_error("tape/collector.c:read_aggregates(): buffer too small to handle output size")
                return None
            count += len(text) + (1 if values else 0)
            values.append(text)
        return ",".join(values) if values else None

    @classmethod
    def open(cls, model:Any, name:str, st:CollectorState) -> bool:
        """`collector_open()`: open the file and write the header"""
        if st.property is None:
            gl_error("at least one property must be specified")
            return False
        st.interval = int(to_double(model.get_property(name, "interval") or "-1", "s"))
        kind, fname = "file", st.file
        parts = st.file.split(":")
        if len(parts) > 1:
            kind, fname = parts[0][:32], parts[1]
        if fname == "":
            fname = re.sub(r"[^A-Za-z0-9.-]", "_", f"{st.group}.txt")
        if not _file.get_ftable(kind):
            return False
        return _file.open_collector(model, st, fname)

    @staticmethod
    def close(model:Any, st:CollectorState) -> None:
        """`close_collector()`"""
        _file.close_recorder(model, st)

    @classmethod
    def write(cls, model:Any, st:CollectorState) -> None:
        """`collector_write()`: write the last sample"""
        ts = strtime(model, st.last_ts)
        if (0 < st.limit <= st.samples) or not _file.write_row(model, st, ts, st.last_value):
            cls.close(model, st)
            st.status = TS_DONE
        else:
            st.samples += 1
            if st.flush == 0 or (st.flush > 0 and clock(model) % st.flush == 0):
                _file.flush(st)

    @classmethod
    def postsync(cls, model:Any, name:str, t0:int) -> int|None:
        """`sync_collector()`: aggregate and write; returns the next sample
        time"""
        # pylint: disable=too-many-branches,too-many-return-statements
        st = state(model, name)
        oid = model.objects[name].id
        if st.status == TS_DONE:
            return TS_NEVER
        buffer = ""
        if st.aggregates is None:
            st.aggregates = cls.link(model, st)
        if st.aggregates is None:
            buffer = f"'{st.property}' contains an aggregate that is not found in the group '{st.group}'"
            st.status = TS_ERROR
        else:
            if st.status == TS_OPEN and t0 > st.clock:
                st.clock = t0
                if st.interval > 0 and st.last_ts < t0 and st.last_value:
                    cls.write(model, st)
                    st.last_value = ""
            if st.interval in (0, -1) or (st.interval > 0 and (t0 >= st.last_ts + st.interval or t0 == st.last_ts)):
                text = cls.read(model, st)
                if text is None:
                    buffer = f"unable to read aggregate '{st.property}' of group '{st.group}'"
                    cls.close(model, st)
                    st.status = TS_ERROR
                else:
                    buffer = text
                if st.interval > 0:
                    st.last_ts = t0
        if st.status != TS_ERROR:
            if st.trigger:
                if not compare(buffer, st.trigger) or (st.status == TS_INIT and not cls.open(model, name, st)):
                    return TS_NEVER if st.interval in (0, -1) else min(t0 + st.interval, TS_NEVER)
            elif st.status == TS_INIT and not cls.open(model, name, st):
                cls.close(model, st)
                return TS_NEVER
            if st.last_ts < 1 and st.interval != -1:
                st.last_ts = t0
            if st.status == TS_OPEN:
                if st.interval == 0 or (st.interval == -1 and st.last_ts != t0 and buffer != st.last_value):
                    st.last_value = buffer[:4999]
                    st.last_ts = t0
                    cls.write(model, st)
                elif st.interval > 0 and st.last_ts == t0:
                    st.last_value = buffer[:4999]
        if st.status == TS_ERROR:
            gl_error(f"collector {oid} {buffer}")
            st.status = TS_DONE
            return 0
        return TS_NEVER if st.interval in (0, -1) else st.last_ts + st.interval

    @classmethod
    def finalize(cls, model:Any, name:str, t:int) -> None: # pylint: disable=unused-argument
        """Write the last sample of a positive interval and close the file
        with the end-of-tape line (gridlabd leaves it to the process exit)"""
        st = get_state(model, name)
        if st is not None:
            if st.status == TS_OPEN and st.interval > 0 and st.last_value:
                cls.write(model, st)
                st.last_value = ""
            cls.close(model, st)
