# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Recorders (class `recorder`)

A `recorder` writes properties of its parent (or global variables) to a
CSV file, one row per sample.

Syntax
------

    module tape;
    object recorder {
        parent <object>;
        property "<name>[[<unit>[:<format>]]][,...]";
        file "<file>";
        interval <seconds>;
        limit <integer>;
        flush <integer>;
        trigger "<op><value>";
        format <bool>;
        strftime_format "<format>";
        header_units {DEFAULT,ALL,NONE};
        line_units {DEFAULT,ALL,NONE};
        multifile "<file>";
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `trigger` | `char32` | | condition to trigger recorder |
| `file` | `char1024` | | file in which to record data (required) |
| `filetype` | `char8` | `txt` | file type to use when storing data |
| `mode` | `char32` | `file` | recorder operating mode (only `file` is supported) |
| `multifile` | `char1024` | | multi-run file that each run adds columns to |
| `limit` | `int32` | `0` | limit on number of rows to record (0=none) |
| `plotcommands`, `xdata`, `columns` | `char1024`, `char32`, `char32` | | plot options (not used, see Caveats) |
| `flush` | `int32` | `-1` | row flush mode (-1=when full, 0=every row, >0=interval in seconds) |
| `format` | `bool` | `FALSE` | write timestamps as seconds |
| `interval` | `double[s]` | `-1 s` | sampling interval |
| `strftime_format` | `char256` | | date/time format |
| `property` | `method` | | list of properties to sample (required) |
| `output` | `enumeration` | `SCREEN` | plot output (not used) |
| `header_units` | `enumeration` | `DEFAULT` | header option for output of units |
| `line_units` | `enumeration` | `DEFAULT` | inline option for output of units |

Description
-----------

A recorder is expected to satisfy:

1. It samples in the postsync pass. With `interval` 0 it writes a row at
   each time, from the first; with `interval` -1 it writes a row when the values differ
   from the last row written (once per time); with a positive `interval`
   it samples every `interval` seconds and writes each sample when the
   clock passes its time, and the last sample when the run ends. An `interval` less than -1 is an error; one
   shorter than `minimum_timestep` is raised to it with a warning.
2. Each row is `TIME,VALUE[,...]`. `TIME` is the local date and time
   (`gl_strtime()`), `strftime_format` when given, or seconds when
   `format` is true. Values are written as gridlabd's `gl_get_value()`
   writes them: `double` with the `double_format` global, `complex` with
   `complex_format`, keywords for enumerations and sets.
3. A property `NAME[UNIT]` is written in `UNIT` with the unit; `NAME` is
   written without a unit unless `line_units` is `ALL`; `line_units NONE`
   writes no units. `NAME[UNIT:PF]` writes a `double` with the C format
   `%.PF` (`P` a digit, `F` one of `aefgAEFG`) and a `complex` with a
   third letter: `i` or `j` (rectangular), `d` or `r` (polar), `M`
   (magnitude), `D` or `R` (angle), `X` (real), or `Y` (imaginary).
   `NAME.real` and `NAME.imag` are parts of a complex property, and
   `::NAME` (or `NAME::VAR`) is a global variable.
4. The file starts with the header that `tape::csv_data_only` selects
   (`FULL` comment lines, `NONE`, or a `NAME` header line); the column
   names follow `header_units`. The file ends with `# end of tape` when
   the run ends, unless `csv_data_only` is set.
5. Recording starts when the trigger (`<`, `=`, or `>` and a value
   compared as text with the first values) is met, and stops after
   `limit` rows. `flush` 0 flushes every row and a positive `flush`
   flushes rows written when the clock is a multiple of it.
6. With `multifile`, the rows also go to a temporary file with a column
   per property for this run (`NAME(N)` for run `N`) added to the rows of
   the multi-run file read, which the temporary file replaces at the end.

Examples
--------

    >>> import os, tempfile
    >>> from arras import Model, Class, Runner
    >>> Class.reset()
    >>> csv = os.path.join(tempfile.mkdtemp(), "out.csv")
    >>> m = Model()
    >>> m.read_glm(f'''clock {{ timezone "UTC"; starttime "2020-01-01 00:00:00"; stoptime "2020-01-01 02:00:00"; }}
    ... module tape {{ csv_header_type NAME; }}
    ... class load {{ double power[kW]; complex current[A]; }}
    ... object load {{ power 1.5; current 2+1j; object recorder {{ property "power,power[W],current"; file "{csv}"; interval 3600; }}; }}
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> print(open(csv).read(), end="")
    timestamp,power,power[W],current
    2020-01-01 00:00:00 UTC,+1.5,+1500 W,+2+1j
    2020-01-01 01:00:00 UTC,+1.5,+1500 W,+2+1j
    2020-01-01 02:00:00 UTC,+1.5,+1500 W,+2+1j
    >>> Class.reset()

Caveats
-------

- The plot properties (`plotcommands`, `xdata`, `columns`, `output`) are
  published but not used: the `plot` tape mode is not supported, nor is
  the `memory` mode.
- As in gridlabd, the time zone, user, and host comment lines of the
  `FULL` header come from the environment of the process.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A `double` recorded in another unit (`NAME[UNIT]`) is converted to that
   unit; gridlabd's `convert_from_double()` converts it but writes the
   number in the property's unit with the other unit's name.
2. `strftime_format` uses the model's time zone; gridlabd uses the time
   zone of the process (`localtime()`).
3. Deltamode is not run: a recorder with the `DELTAMODE` flag behaves as
   one without it.
4. The column names of the file header follow `header_units`, as
   `docs/Module/Tape/Recorder.md` says (decision 1.3); gridlabd computes
   them but writes the property list as given.
5. A `double` with an output format in another unit is converted with the
   unit's offset (e.g. `degF` to `degC`); gridlabd multiplies by the
   conversion of 1.
6. The trigger compares the sign of `strcmp()`; gridlabd compares the
   value `strcmp()` returns, which the C library need not limit to -1,
   0, and 1.
7. With `interval` 0 a row is written at the first time; gridlabd writes
   none then, because it sets the time of the last row before the file
   opens.
8. With a positive `interval`, the last sample is written when the run
   ends; gridlabd writes a sample only when the clock passes it, so the
   last sample of a run is lost.
9. `limit` rows are written; gridlabd writes `limit`+1.

References
----------

- `arras-energy/gridlabd`: `module/tape/recorder.cpp`, `tape.h`,
  `module/tape_file/tape_file.cpp`, `source/convert.cpp`
- [Recorder class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Tape/Recorder.md)
  (`docs/Module/Tape/Recorder.md`)
"""

import os
import re
import math
from typing import Any

from . import _file
from ._base import TapeClass, prop, keywords
from ._common import (TS_ZERO, TS_NEVER, TS_INIT, TS_OPEN, TS_DONE, TS_ERROR, TRL_PROVEN, Prop,
    TapeError, gl_error, gl_warning, get_state, set_state, find_unit, unit_scale,
    strtime, localtime, clock, parent_of, is_named, angle, cprintf, atoi, convert)

OUTPUT = keywords("SCREEN", "EPS", "GIF", "JPG", "PDF", "PNG", "SVG")
"""Keywords of `output`"""

UNITS = keywords("DEFAULT", "ALL", "NONE")
"""Keywords of `header_units` and `line_units`"""

BUFFER_SIZE = 1024
"""Size of the value buffer of `sync_recorder()`"""

class RecorderState: # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """State of a recorder between handler calls (gridlabd `struct recorder`)"""

    def __init__(self, model:Any, name:str):
        self.status = TS_INIT
        self.fp: Any = None
        self.file = model.get_property(name, "file") or ""
        self.property = model.get_property(name, "property") or None
        self.trigger = model.get_property(name, "trigger") or ""
        self.limit = int(model.get_property(name, "limit") or 0)
        flush = model.get_property(name, "flush") if model.objects[name].oclass.find_property("flush") else None
        self.flush = int(flush) if flush not in (None, "") else 0
        self.interval = 0
        self.last_ts = -1
        self.last_ns = -1
        self.last_value = ""
        self.samples = 0
        self.clock = 0
        self.targets: list[Prop]|None = None
        self.formats: list[str|None] = []
        self.scalars: list[float] = []
        self.multifp: Any = None
        self.inputfp: Any = None
        self.multitempfile = ""

def state(model:Any, name:str) -> RecorderState:
    """State of a recorder, created on first use"""
    st = get_state(model, name)
    if st is None:
        st = RecorderState(model, name)
        set_state(model, name, st)
    return st

def keyword(model:Any, name:str, prop_:str) -> int:
    """Value of an enumeration property"""
    text = model.get_property(name, prop_) or "0"
    values = model.objects[name].oclass.find_property(prop_).keywords
    return values[text] if text in values else int(text, 0)

def bool_value(model:Any, name:str, prop_:str) -> bool:
    """Value of a bool (or integer) property"""
    text = str(model.get_property(name, prop_) or "0").strip().upper()
    return text == "TRUE" or (text.lstrip("-").isdigit() and int(text) != 0)

def timestamp_text(model:Any, ts:int, as_seconds:bool, strftime_format:str="") -> str:
    """Timestamp of a row: `0` for `INIT`, local date and time, the
    `strftime` format, or seconds"""
    if as_seconds:
        return str(ts)
    if ts <= TS_ZERO:
        return "0"
    if strftime_format:
        try:
            text = localtime(model, ts).strftime(strftime_format)
        except ValueError:
            text = ""
        if text:
            return text[:63]
    return strtime(model, ts)

def compare(buffer:str, trigger:str) -> bool:
    """`True` when the trigger (`<`, `=`, `>` and a value) is met by the
    values (`strcmp()`), or when there is no trigger"""
    if not trigger:
        return True
    desired = {"<": -1, "=": 0, ">": 1}.get(trigger[0], -2)
    actual = (buffer > trigger[1:]) - (buffer < trigger[1:])
    return actual == desired

def property_header(model:Any, name:str, plist:str, target:str|None, header_units:int) -> str|None:
    """`out_property` of `recorder_open()`: the column names for
    `header_units` (`None` after an error)"""
    oid = model.objects[name].id
    if header_units == UNITS["DEFAULT"]:
        return plist
    names = []
    for token in [x for x in plist.split(",") if x]:
        match = re.match(r"([A-Za-z0-9_.]+)(?:\[([^]\n,]+)\])?", token)
        propstr = match.group(1) if match else ""
        unitstr = match.group(2) if match and match.group(2) else ""
        if header_units == UNITS["NONE"]:
            if not propstr:
                gl_error(f"invalid property/format specification '{token}'")
                return None
            names.append(propstr)
            continue
        unit = None
        if unitstr:
            unitstr = unitstr.split(":", 1)[0]
            if find_unit(unitstr) is None:
                gl_error(f"recorder:{oid}: unable to find unit '{unitstr}' for property '{propstr}'")
                return None
            unit = unitstr
        found = Prop(model, target, propstr) if target is not None else None
        if found is None or not found.is_valid:
            gl_error(f"recorder:{oid}: property '{propstr}' not found in parent")
            return None
        if found.native is not None and unit is None:
            unit = found.native
        names.append(f"{propstr}[{unitstr or unit}]" if unit is not None else propstr)
    return ",".join(names)

def multirun_header(model:Any, st:Any, oid:int, target:str|None, name_props:list[str], kind:str="recorder") -> None: # pylint: disable=too-many-arguments,too-many-positional-arguments
    """Open the multi-run files and write the header of the temporary file
    (`recorder_open()` and `multi_recorder_open()`)"""
    # pylint: disable=too-many-branches,too-many-locals,too-many-statements
    prefix = "" if kind == "recorder" else "multirecorder: "
    temp = f"temp_{st.file}"
    st.multitempfile = temp
    try:
        st.multifp = open(temp, "w", encoding="utf-8") # pylint: disable=consider-using-with
    except OSError:
        gl_error(f"{prefix}unable to open '{temp}' for multi-run output")
        return
    try:
        st.inputfp = open(st.multifile, "r", encoding="utf-8") # pylint: disable=consider-using-with
    except OSError:
        st.inputfp = None
    lines = [f"# file...... {st.file}", f"# date...... {_file.asctime()}",
        f"# user...... {_file.getenv('USER')}", f"# host...... {_file.getenv('HOST')}"]
    if target is not None:
        tobj = model.objects[target]
        lines.append(f"# target.... {tobj.oclass.name} {tobj.id}")
    lines += [f"# trigger... {st.trigger or '(none)'}", f"# interval.. {st.interval}",
        f"# limit..... {st.limit}", f"# flush..... {st.flush}", f"# property.. {st.property}"]
    st.multifp.write("\n".join(lines) + "\n")
    if st.inputfp is None:
        st.multifp.write("# repetition 0\n# timestamp" + "".join(f",{x}(0)" for x in name_props) + "\n")
        return
    get_col = False
    line = ""
    while True:
        line = st.inputfp.readline(1022)
        if not line:
            gl_error(f"error reading multi-read input file '{st.multifile}'")
            break
        line = line.split("\n", 1)[0]
        data = line[len("# file...... "):]
        if line.startswith("# target") and target is not None:
            tobj = model.objects[target]
            here = f"{tobj.oclass.name} {tobj.id}"
            if not here.startswith(data):
                gl_error(f"recorder:{oid}: re-recording target mismatch: was {data}, now {here}")
        elif line.startswith("# interval") and atoi(data) != st.interval:
            gl_error(f"recorder:{oid}: re-recording interval mismatch: was {atoi(data)}, now {st.interval}")
        elif line.startswith("# limit") and atoi(data) != st.limit:
            gl_error(f"recorder:{oid}: re-recording limit mismatch: was {atoi(data)}, now {st.limit}")
        elif line.startswith("# property"):
            if not data.startswith(st.property or ""):
                gl_error(f"recorder:{oid}: re-recording property mismatch: was {data}, now {st.property}")
            get_col = True
        if not line.startswith("#") or get_col:
            break
    line = st.inputfp.readline(1022)
    if line:
        rep = 0
        if line.startswith("# repetition"):
            rep = atoi(line[len("# repetition")+1:]) + 1
            st.multifp.write(f"# repetition {rep}\n")
            line = st.inputfp.readline(1022).split("\n", 1)[0]
        else:
            st.multifp.write("# repetition 0\n")
        st.multifp.write(line.rstrip("\n") + "".join(f",{x}({rep})" for x in name_props) + "\n")

def multirun_close(st:Any, kind:str="recorder") -> None:
    """Close the multi-run files: the temporary file replaces the multi-run
    file"""
    prefix = "" if kind == "recorder" else "multirecorder: "
    if st.multifp is None:
        return
    st.multifp.close()
    st.multifp = None
    if st.inputfp is not None:
        st.inputfp.close()
        st.inputfp = None
        try:
            os.remove(st.multifile)
        except OSError:
            gl_error(f"{prefix}unable to remove out-of-data multi-run file '{st.multifile}'")
    try:
        os.replace(st.multitempfile, st.multifile)
    except OSError:
        gl_error(f"{prefix}unable to rename multi-run file '{st.multitempfile}' to '{st.multifile}'")

def multirun_write(st:Any, ts:str) -> int|None:
    """Write a row to the multi-run temporary file: the row read from the
    multi-run file followed by this run's values; `TS_NEVER` when the
    multi-run file ends"""
    if st.multifp is None:
        return None
    if st.inputfp is not None:
        while True:
            line = st.inputfp.readline(1022)
            if not line:
                return TS_NEVER
            if line[0] != "#":
                break
        parts = line.split("\n", 1)[0].split(",", 1)
        in_ts = parts[0] if parts[0] else None
        in_tok = parts[1] if len(parts) > 1 else "(null)"
        if in_ts is None:
            gl_error("unable to indentify a timestamp within the line read from ")
        elif in_ts != ts:
            gl_warning("timestamp mismatch between current input line and simulation time")
        out = f"{in_tok},{st.last_value}"
    else:
        out = st.last_value
    st.multifp.write(f"{ts},{out}\n")
    return None

class Recorder(TapeClass):
    """Class `recorder`; see the module documentation"""

    NAME = "recorder"
    PASSCONFIG = "POSTTOPDOWN|OBSERVER"
    TRL = TRL_PROVEN
    PROPERTIES = (
        ("trigger", "char32", prop("condition to trigger recorder", "")),
        ("file", "char1024", prop("file in which to record data", flags="REQUIRED")),
        ("filetype", "char8", prop("file type to use when storing data", "txt")),
        ("mode", "char32", prop("recorder operating mode", "file")),
        ("multifile", "char1024", prop()),
        ("limit", "int32", prop("limit on number of rows to record (0=none)", "0")),
        ("plotcommands", "char1024", prop()),
        ("xdata", "char32", prop()),
        ("columns", "char32", prop()),
        ("flush", "int32", prop("row flush mode (-1=when full, 0=every row, >0=interval in seconds)", "-1")),
        ("format", "bool", prop(default="0")),
        ("interval[s]", "double", prop("sampling interval", "-1 s")),
        ("strftime_format", "char256", prop("date/time format")),
        ("property", "method", prop("list of properties to sample", flags="REQUIRED")),
        ("output", "enumeration", prop(keywords=OUTPUT)),
        ("header_units", "enumeration", prop("header option for output of units", "DEFAULT", keywords=UNITS)),
        ("line_units", "enumeration", prop("inline option for output of units", "DEFAULT", keywords=UNITS)),
    )
    EVENTS = ("postsync", "finalize")

    @classmethod
    def link(cls, model:Any, name:str, st:RecorderState, target:str) -> list[Prop]|None:
        """`link_properties()`: the properties of `target` (or globals) to
        record, with their output formats"""
        # pylint: disable=too-many-branches
        oid = model.objects[target].id
        line_units = keyword(model, name, "line_units")
        targets = []
        st.formats = []
        st.scalars = []
        for item in [x for x in (st.property or "").split(",") if x]:
            item = item.lstrip()
            unit = fmt_ = None
            match = re.match(r"([A-Za-z0-9_.]{1,255})\[([^]\n,]{1,255})\]", item)
            if match:
                ustr = match.group(2)
                if ":" in ustr:
                    ustr, fmt_ = ustr.split(":", 1)
                    if len(fmt_) < 2 or fmt_[0] not in "0123456789" or fmt_[1] not in "aefgAEFG" or (len(fmt_) > 2 and fmt_[2] not in "ijdrMDRXY"):
                        gl_error(f"recorder:{model.objects[name].id}: invalid double/complex format '{fmt_}'")
                        return None
                if ustr:
                    if find_unit(ustr) is None:
                        gl_error(f"recorder:{oid}: unable to find unit '{ustr}' for property '{match.group(1)}'")
                        return None
                    unit = ustr
                item = match.group(1)
            part = None
            if "." in item and item.split(".", 1)[1] in ("real", "imag"):
                item, part = item.split(".", 1)
            if "::" in item:
                found = Prop(model, None, item[2:] if item.startswith("::") else item, part)
            else:
                found = Prop(model, target, item, part)
            if not found.is_valid:
                gl_error(f"recorder: property or global '{item}' not found")
                return None
            if unit is not None and found.native is None:
                gl_error(f"recorder:{oid}: property '{item}' is unitless, ignoring unit conversion")
            elif unit is not None and unit_scale(found.native, unit) is None: # type: ignore[arg-type]
                gl_error(f"recorder:{oid}: unable to convert property '{item}' units to '{unit}'")
                return None
            found.unit = unit if unit is not None else (found.native if line_units == UNITS["ALL"] else None)
            targets.append(found)
            st.formats.append(fmt_)
            st.scalars.append(0.0)
        return targets

    @classmethod
    def read(cls, model:Any, name:str, st:RecorderState, size:int=BUFFER_SIZE) -> str|None:
        """`read_properties()`: the values as text, or `None` after an
        error"""
        # pylint: disable=too-many-branches
        line_units = keyword(model, name, "line_units")
        values: list[str] = []
        count = 0
        for index, target in enumerate(st.targets or []):
            fmt_ = st.formats[index] if index < len(st.formats) else None
            try:
                if fmt_ is not None:
                    text = cls._formatted(st, index, target, fmt_)
                    if text is None:
                        return None
                elif target.ptype in ("double",) or target.part:
                    if line_units == UNITS["NONE"]:
                        text = target.to_string(target.unit).rsplit(" ", 1)[0] if target.unit else target.to_string(None)
                    else:
                        text = target.to_string(target.unit)
                else:
                    text = target.to_string(target.unit)
            except TapeError as err:
                gl_error(str(err))
                return None
            if count + len(text) >= size:
                gl_error("tape/recorder.c:read_aggregates(): buffer too small to handle output size")
                return None
            count += len(text) + (1 if values else 0)
            values.append(text)
        return ",".join(values)

    @staticmethod
    def _formatted(st:RecorderState, index:int, target:Prop, fmt_:str) -> str|None: # pylint: disable=too-many-return-statements
        prec, kind = fmt_[0], fmt_[1]
        part = fmt_[2] if len(fmt_) > 2 else ""
        unit = target.unit or ""
        if target.unit is not None and st.scalars[index] == 0.0:
            st.scalars[index] = (unit_scale(target.native, target.unit) or 1.0) if target.native else 1.0
        scalar = st.scalars[index]
        suffix = f" {unit}"
        if target.ptype == "double":
            if part:
                gl_error(f"output format part '{part}' is not valid for property {target.prop}")
                return None
            value = target.double()
            if target.unit is not None and target.native is not None:
                converted = convert(value, target.native, target.unit)
                value = value*scalar if converted is None else converted
            return cprintf(f"%.{prec}{kind}", value) + suffix
        if target.ptype == "complex":
            if not part:
                gl_error(f"output format part required missing complex specifier for property {target.prop}")
                return None
            value = target.complex_value()[0]*scalar
            pair = f"%.{prec}{kind}%+.{prec}{kind}{part}"
            one = f"%.{prec}{kind}"
            if part in "ij":
                return cprintf(pair, value.real, value.imag) + suffix
            if part == "r":
                return cprintf(pair, abs(value), angle(value)) + suffix
            if part == "d":
                return cprintf(pair, abs(value), angle(value)*180/math.pi) + suffix
            single = {"M": abs(value), "D": angle(value)*180/math.pi, "R": angle(value), "X": value.real, "Y": value.imag}
            return cprintf(one, single[part]) + suffix
        gl_error(f"output format is not valid for property type {target.ptype}")
        return None

    @classmethod
    def open(cls, model:Any, name:str, st:RecorderState) -> bool:
        """`recorder_open()`: check the interval, open the files, and write
        the headers"""
        oid = model.objects[name].id
        if st.property is None:
            gl_error("at least one property must be specified")
            return False
        st.interval = int(float((model.get_property(name, "interval") or "-1").split()[0]))
        if st.interval < -1:
            gl_error(f"invalid interval value ({st.interval})")
            return False
        mts = int(model.globals.getvalue("minimum_timestep") or 0)
        if 0 < mts and 0 < st.interval < mts:
            gl_warning(f"{name if is_named(model, name) else '(unnamed)'} <recorder:{oid}> interval {st.interval} is less than minimum timestep, setting interval to {mts}")
            st.interval = mts
        parent = parent_of(model, name)
        if st.file == "":
            pobj = model.objects[parent or name]
            st.file = f"{pobj.oclass.name}-{pobj.id}.{model.get_property(name, 'filetype') or ''}"
        st.multifile = model.get_property(name, "multifile") or ""
        if st.multifile:
            if st.interval < 1:
                gl_error("transient recorders cannot use multi-run output files")
                return False
            multirun_header(model, st, oid, parent, [t.prop for t in st.targets or []])
        if not _file.get_ftable(model.get_property(name, "mode") or "file"):
            return False
        header = property_header(model, name, st.property, parent, keyword(model, name, "header_units"))
        if header is None:
            return False
        return _file.open_recorder(model, name, st, st.file, header)

    @classmethod
    def close(cls, model:Any, st:RecorderState) -> None:
        """`close_recorder()`"""
        _file.close_recorder(model, st)
        multirun_close(st)

    @classmethod
    def write(cls, model:Any, name:str, st:RecorderState) -> int:
        """`recorder_write()`: write the last sample"""
        ts = timestamp_text(model, st.last_ts, bool_value(model, name, "format"), model.get_property(name, "strftime_format") or "")
        if (0 < st.limit <= st.samples) or not _file.write_row(model, st, ts, st.last_value):
            cls.close(model, st)
            st.status = TS_DONE
        else:
            st.samples += 1
            now = clock(model)
            if (st.flush == 0 or (st.flush > 0 and now % st.flush == 0)):
                _file.flush(st)
        multirun_write(st, ts)
        return TS_NEVER

    @classmethod
    def postsync(cls, model:Any, name:str, t0:int) -> int:
        """`sync_recorder()`: sample and write; returns the next sample
        time"""
        # pylint: disable=too-many-branches,too-many-statements,too-many-return-statements
        st = state(model, name)
        oid = model.objects[name].id
        buffer = ""
        if st.status == TS_DONE:
            cls.close(model, st)
            return TS_NEVER
        parent = parent_of(model, name)
        if parent is None:
            buffer = f"'{name if is_named(model, name) else f'recorder:{oid}'}' lacks a parent object"
            cls.close(model, st)
            st.status = TS_ERROR
        else:
            if st.last_ts < 1 and st.interval != -1:
                st.last_ts, st.last_ns = t0, 0
            if st.targets is None:
                st.targets = cls.link(model, name, st, parent)
            pobj = model.objects[parent]
            if st.targets is None:
                buffer = f"'{st.property}' contains a property of {pobj.oclass.name} {pobj.id} that is not found"
                cls.close(model, st)
                st.status = TS_ERROR
        if st.status != TS_ERROR:
            if st.status == TS_OPEN and t0 > st.clock:
                st.clock = t0
                if st.interval > 0 and st.last_ts < t0 and st.last_value:
                    if st.last_ns == 0:
                        cls.write(model, name, st)
                    st.last_value = ""
            pobj = model.objects[parent] # type: ignore[index]
            if st.interval <= 0:
                text = cls.read(model, name, st)
                if text is None:
                    buffer = f"unable to read property '{st.property}' of {pobj.oclass.name} {pobj.id}"
                    cls.close(model, st)
                    st.status = TS_ERROR
                else:
                    buffer = text
            elif t0 >= st.last_ts + st.interval or (t0 == st.last_ts and st.last_ns == 0):
                text = cls.read(model, name, st)
                if text is None:
                    buffer = f"unable to read property '{st.property}' of {pobj.oclass.name} {pobj.id}"
                    cls.close(model, st)
                    st.status = TS_ERROR
                else:
                    buffer = text
                st.last_ts, st.last_ns = t0, 0
        if st.status != TS_ERROR:
            if st.trigger:
                if not compare(buffer, st.trigger) or (st.status == TS_INIT and not cls.open(model, name, st)):
                    return TS_NEVER if st.interval in (0, -1) else t0 + st.interval
            elif st.status == TS_INIT and not cls.open(model, name, st):
                cls.close(model, st)
                return TS_NEVER
            if st.last_ts < 1 and st.interval not in (0, -1):
                st.last_ts, st.last_ns = t0, 0
            if st.status == TS_OPEN:
                if st.interval == 0 or (st.interval == -1 and st.last_ts != t0 and buffer != st.last_value):
                    st.last_value = buffer[:4999]
                    if st.last_ts < t0:
                        st.last_ts, st.last_ns = t0, 0
                        cls.write(model, name, st)
                elif st.interval > 0 and st.last_ts == t0 and st.last_ns == 0:
                    st.last_value = buffer[:4999]
        if st.status == TS_ERROR:
            gl_error(f"recorder {oid} {buffer}\n".rstrip("\n"))
            cls.close(model, st)
            st.status = TS_DONE
            return TS_NEVER
        if st.interval in (0, -1):
            return TS_NEVER
        return st.last_ts + st.interval

    @classmethod
    def finalize(cls, model:Any, name:str, t:int) -> None: # pylint: disable=unused-argument
        """`finalize_recorder()`: write the last sample of a positive
        interval, then close the files"""
        st = get_state(model, name)
        if st is not None:
            if st.status == TS_OPEN and st.interval > 0 and st.last_value and st.last_ns == 0:
                cls.write(model, name, st)
                st.last_value = ""
            cls.close(model, st)
