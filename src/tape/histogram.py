# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Histograms (class `histogram`)

A `histogram` counts the values of a property of its parent, or of the
objects of a group, in bins, and writes the counts to a CSV file.

Syntax
------

    module tape;
    object histogram {
        group "<find expression>";
        property "<name>[.<part>]";
        bins "<bin>[,...]";
        min <decimal>; max <decimal>; bin_count <integer>;
        samplerate <seconds>;
        countrate <seconds>;
        filename "<file>";
        limit <integer>;
    }

A bin is `[A .. B]`, `(A .. B)`, `[A-B)`, ... (`[` and `]` include a
bound, `(` and `)` exclude it, the lower bound is included by default),
`..B` (below B), or `A ..` (A and above); for enumerations and sets, a bin
is a keyword. `A..B` needs no spaces.

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `filename` | `char1024` | | the name of the file to write |
| `filetype` | `char8` | | the format to output a histogram in |
| `mode` | `char32` | `file` | the mode of file output |
| `group` | `char1024` | | the GridLAB-D group expression to use for this histogram |
| `bins` | `char1024` | | the specific bin values to use |
| `property` | `char256` | | the property to sample |
| `min` | `double` | `0` | the minimum value of the auto-sized bins to use |
| `max` | `double` | `-1` | the maximum value of the auto-sized bins to use |
| `samplerate` | `double[s]` | `-1 s` | the rate at which samples are read |
| `countrate` | `double[s]` | `-1 s` | the reate at which bins are counted and written |
| `bin_count` | `int32` | `-1` | the number of auto-sized bins to use |
| `limit` | `int32` | `0` | the number of samples to write |

Description
-----------

A histogram is expected to satisfy:

1. At initialization it finds the objects (its parent, else the group),
   checks that they have the property (with a part `real`, `imag`, `mag`,
   or `ang` (radians) for a complex property), makes the bins (`bin_count`
   equal bins from `min` to `max` when `min < max`, else `bins`), and
   opens the file with the header that `tape::csv_data_only` selects.
2. In the presync pass it adds the values to the bins every `samplerate`
   seconds (every pass for 0; with -1, when the last count is later than
   the clock), and writes a row of counts every `countrate` seconds
   (every pass for 0; with -1, whenever the clock passes the last row),
   then clears the counts. Counts are separated by commas.
3. After `limit` rows (or the first row when `limit` is 0 or less), or
   when the run ends, the file is closed with `# end of tape`.
4. It returns the next sample or count time.

Examples
--------

    >>> import os, tempfile
    >>> from arras import Model, Class, Runner
    >>> Class.reset()
    >>> csv = os.path.join(tempfile.mkdtemp(), "out.csv")
    >>> m = Model()
    >>> m.read_glm(f'''clock {{ timezone "UTC"; starttime "2020-01-01 00:00:00"; }}
    ... module tape {{ csv_header_type NONE; }}
    ... class load {{ double power; }}
    ... object load {{ power 1; }}
    ... object load {{ power 5; }}
    ... object load {{ power 7; }}
    ... object histogram {{ group "class=load"; property "power"; bins "0..4,4..8"; samplerate 10; countrate 10; limit 1; filename "{csv}"; }}
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> print(open(csv).read(), end="")
    2020-01-01 00:00:10 UTC,1,2
    # end of tape
    >>> Class.reset()

Caveats
-------

- A value equal to the bounds of adjacent bins is counted in each bin
  that includes it, as in gridlabd.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. Rows end with the last count; gridlabd writes a comma after every
   count, so its rows end with a comma.
2. `A..B` is a bin; gridlabd refuses it when `A` is an integer, because
   C's `strtod()` reads `A.` as the number, which leaves `.B` (write
   `A .. B` or `A-B` for gridlabd).
3. A file still open when the run ends is closed with `# end of tape`;
   gridlabd leaves it to the process exit, without the line.

References
----------

- `arras-energy/gridlabd`: `module/tape/histogram.cpp`, `histogram.h`,
  `module/tape_file/tape_file.cpp`
- [Histogram class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Tape/Histogram.md)
  (`docs/Module/Tape/Histogram.md`)
"""

import re
import sys
from typing import Any

from . import _file
from ._aggregate import find_group
from ._base import TapeClass, prop
from ._common import (TS_ZERO, TS_NEVER, TRL_PROTOTYPE, Prop, TapeError, gl_error, get_state,
    set_state, strtime, parent_of, is_named, to_double, angle)

DBL_MAX = sys.float_info.max
"""C `DBL_MAX`"""

class Bin: # pylint: disable=too-few-public-methods
    """A bin (gridlabd `BIN`)"""

    def __init__(self, low:float=0.0, high:float=0.0, low_inc:bool=True, high_inc:bool=False):
        self.low = low
        self.high = high
        self.low_inc = low_inc
        self.high_inc = high_inc

def _strtod(text:str, pos:int) -> tuple[float,int]:
    match = re.compile(r"\d+(?:\.(?!\.)\d*)?(?:[eE][-+]?\d+)?|\.(?!\.)\d+(?:[eE][-+]?\d+)?").match(text, pos)
    return (float(match.group(0)), match.end()) if match else (0.0, pos)

def parse_bin(text:str) -> Bin|None: # pylint: disable=too-many-branches
    """`parse_bin_val()`: a bin of values, or `None`"""
    pos = 0
    def white(p:int) -> int:
        while p < len(text) and text[p] in " \t":
            p += 1
        return p
    pos = white(pos)
    result = Bin(low_inc=True)
    if text[pos:pos+1] == "[":
        pos += 1
    elif text[pos:pos+1] == "(":
        pos += 1
        result.low_inc = False
    pos = white(pos)
    low_set = False
    if text[pos:pos+1].isdigit():
        result.low, pos = _strtod(text, pos)
        low_set = True
    elif text[pos:pos+2] == ".." or text[pos:pos+1] == "-":
        result.low = -DBL_MAX
        result.low_inc = False
    pos = white(pos)
    if text[pos:pos+2] == "..":
        pos += 2
    elif text[pos:pos+1] == "-":
        pos += 1
    else:
        gl_error("parse_bin failure")
        return None
    pos = white(pos)
    if text[pos:pos+1].isdigit():
        result.high, pos = _strtod(text, pos)
        if not low_set:
            result.high_inc = True
    else:
        result.high = DBL_MAX
    char = text[pos:pos+1]
    if char in ("", "\n", ","):
        return result
    if char == ")":
        result.high_inc = False
        return result
    if char == "]":
        result.high_inc = True
        return result
    return None

class HistogramState: # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """State of a histogram between handler calls (gridlabd `class histogram`)"""

    def __init__(self, model:Any, name:str):
        self.fp: Any = None
        self.fname = ""
        self.group = model.get_property(name, "group") or ""
        self.property = model.get_property(name, "property") or ""
        self.bins = model.get_property(name, "bins") or ""
        self.sampling_interval = to_double(model.get_property(name, "samplerate") or "-1", "s")
        self.counting_interval = to_double(model.get_property(name, "countrate") or "-1", "s")
        self.limit = int(model.get_property(name, "limit") or 0)
        self.bin_list: list[Bin] = []
        self.counts: list[int] = []
        self.members: list[str]|None = None
        self.part = ""
        self.next_count = self.t_count = self.next_sample = self.t_sample = TS_ZERO

def state(model:Any, name:str) -> HistogramState:
    """State of a histogram, created on first use"""
    st = get_state(model, name)
    if st is None:
        st = HistogramState(model, name)
        set_state(model, name, st)
    return st

class Histogram(TapeClass):
    """Class `histogram`; see the module documentation"""

    NAME = "histogram"
    PASSCONFIG = "PRETOPDOWN"
    TRL = TRL_PROTOTYPE
    PROPERTIES = (
        ("filename", "char1024", prop("the name of the file to write")),
        ("filetype", "char8", prop("the format to output a histogram in")),
        ("mode", "char32", prop("the mode of file output", "file")),
        ("group", "char1024", prop("the GridLAB-D group expression to use for this histogram")),
        ("bins", "char1024", prop("the specific bin values to use")),
        ("property", "char256", prop("the property to sample")),
        ("min", "double", prop("the minimum value of the auto-sized bins to use", "0")),
        ("max", "double", prop("the maximum value of the auto-sized bins to use", "-1")),
        ("samplerate[s]", "double", prop("the rate at which samples are read", "-1 s")),
        ("countrate[s]", "double", prop("the reate at which bins are counted and written", "-1 s")),
        ("bin_count", "int32", prop("the number of auto-sized bins to use", "-1")),
        ("limit", "int32", prop("the number of samples to write", "0")),
    )
    EVENTS = ("init", "presync", "finalize")

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool:
        """`histogram::init()`"""
        # pylint: disable=too-many-branches,too-many-return-statements,too-many-locals,too-many-statements
        st = state(model, name)
        label = name if is_named(model, name) else "(anon)"
        parent = parent_of(model, name)
        pname = st.property
        match = re.match(r"([^.\n\t ]+)\.(\S+)", pname)
        if match:
            part = match.group(2)
            for prefix, key in (("real", "real"), ("ima", "imag"), ("mag", "mag"), ("ang", "ang")):
                if part.startswith(prefix):
                    st.part = key
                    break
            else:
                gl_error(f"Unable to resolve complex part for '{pname}'")
            pname = match.group(1)
        if parent is None:
            if not st.group:
                gl_error("Histogram has no parent and no group")
                return False
            try:
                st.members = find_group(model, st.group)
            except TapeError:
                gl_error("Histogram group could not be parsed")
                return False
            if not st.members:
                gl_error("Histogram group is an empty set")
                return False
            for member in st.members:
                target = Prop(model, member, pname)
                if not target.is_valid:
                    gl_error(f"Histogram group is unable to find prop '{pname}' in class '{model.objects[member].oclass.name}' for group '{st.group}'")
                    return False
            first = Prop(model, st.members[0], pname)
        else:
            first = Prop(model, parent, pname)
            if not first.is_valid:
                pobj = model.objects[parent]
                gl_error(f"Histogram parent '{parent if is_named(model, parent) else '(anon)'}' of class '{pobj.oclass.name}' does not contain property '{pname}'")
                return False
        st.property = pname
        now = t
        if st.counting_interval > 0.0:
            st.next_count = now + int(st.counting_interval)
        if st.sampling_interval > 0.0:
            st.next_sample = now + int(st.sampling_interval)
        bin_count = int(model.get_property(name, "bin_count") or -1)
        low = to_double(model.get_property(name, "min") or "0")
        high = to_double(model.get_property(name, "max") or "-1")
        if bin_count > 0 and low < high:
            step = (high - low)/bin_count
            st.bin_list = [Bin(low + i*step, low + i*step + step, True, False) for i in range(bin_count)]
            st.bin_list[-1].high_inc = True
        elif st.bins:
            count = 1 + sum(1 for i, c in enumerate(st.bins) if c == "," and i + 1 < len(st.bins))
            tokens = [x for x in re.split(r"[,\t\r\n]+", st.bins) if x]
            if first.ptype in ("complex", "double", "int16", "int32", "int64", "float", "real"):
                for token in tokens[:count]:
                    item = parse_bin(token)
                    if item is None:
                        gl_error(f"Histogram unable to parse '{token}' in {name if is_named(model, name) else '(unnamed histogram)'}")
                        return False
                    st.bin_list.append(item)
            elif first.ptype in ("enumeration", "set"):
                if not first.keywords:
                    gl_error("parse_bin_enum error: property has no keywords")
                for token in tokens[:count]:
                    key = token.lstrip(" \t")
                    if key not in first.keywords:
                        gl_error(f"parse_bin_enum error: unable to find property '{key}'")
                        gl_error(f"Histogram unable to parse '{token}' in {name if is_named(model, name) else '(unnamed histogram)'}")
                        return False
                    value = float(first.keywords[key])
                    st.bin_list.append(Bin(value, value, True, True))
            if len(st.bin_list) < count:
                gl_error(f"Histrogram encountered a problem parsing bins for {name if is_named(model, name) else '(unnamed histogram)'}")
                return False
        else:
            gl_error("Histogram has neither bins or a bin range to work with")
            return False
        st.counts = [0]*len(st.bin_list)
        st.fname = model.get_property(name, "filename") or ""
        if st.fname == "":
            pobj = model.objects[parent or name]
            st.fname = f"{pobj.oclass.name}-{pobj.id}.{model.get_property(name, 'filetype') or ''}"
        if not _file.get_ftable(model.get_property(name, "mode") or "file"):
            return False
        _ = label
        return _file.open_histogram(model, name, st, st.fname)

    @staticmethod
    def feed(model:Any, st:HistogramState, obj:str) -> None:
        """`histogram::feed_bins()`: count the value of an object"""
        target = Prop(model, obj, st.property)
        if target.ptype in ("complex", "enduse"):
            value, _ = target.complex_value()
            if st.part == "real":
                x = value.real
            elif st.part == "imag":
                x = value.imag
            elif st.part == "mag":
                x = abs(value)
            elif st.part == "ang":
                x = angle(value)
            else:
                gl_error(f"Complex property with no part defined in {obj if is_named(model, obj) else '(unnamed)'}")
                x = 0.0
        elif target.ptype == "double":
            x = target.double()
        elif target.ptype in ("int16", "int32", "int64", "enumeration", "set"):
            x = float(target.integer())
        else:
            return
        for index, item in enumerate(st.bin_list):
            if item.low < x < item.high or (item.low_inc and item.low == x) or (item.high_inc and item.high == x):
                st.counts[index] += 1

    @classmethod
    def presync(cls, model:Any, name:str, t1:int) -> int:
        """`histogram::sync()`: count and write; returns the next sample or
        count time"""
        st = state(model, name)
        if st.fp is None and st.next_count == TS_NEVER:
            return TS_NEVER
        if (st.sampling_interval == -1.0 and st.t_count > t1) or st.sampling_interval == 0.0 \
                or (st.sampling_interval > 0.0 and t1 >= st.next_sample):
            parent = parent_of(model, name)
            for obj in ([parent] if st.members is None else st.members):
                cls.feed(model, st, obj) # type: ignore[arg-type]
            st.t_sample = t1
            st.next_sample = t1 + int(st.sampling_interval) if st.sampling_interval > 0.0001 else TS_NEVER
        if (st.counting_interval == -1.0 and st.t_count < t1) or st.counting_interval == 0.0 \
                or (st.counting_interval > 0.0 and t1 >= st.next_count):
            line = ",".join(str(count) for count in st.counts)
            _file.write_row(model, st, strtime(model, t1), line)
            st.counts = [0]*len(st.counts)
            st.t_count = t1
            st.next_count = st.t_count + int(st.counting_interval) if st.counting_interval > 0 else TS_NEVER
            st.limit -= 1
            if st.limit < 1:
                _file.close_histogram(st)
                st.next_count = TS_NEVER
                st.next_sample = TS_NEVER
        if st.next_count < st.next_sample and st.counting_interval > 0.0:
            return st.next_count
        return st.next_sample

    @classmethod
    def finalize(cls, model:Any, name:str, t:int) -> None: # pylint: disable=unused-argument
        """Close the file with the end-of-tape line when the run ends
        (gridlabd leaves it to the process exit)"""
        st = get_state(model, name)
        if st is not None:
            _file.close_histogram(st)
