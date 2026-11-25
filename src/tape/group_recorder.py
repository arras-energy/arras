# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Group recorders (class `group_recorder`)

A `group_recorder` writes one property of every object of a group to a
CSV file, one column per object.

Syntax
------

    module tape;
    object group_recorder {
        group "<find expression>";
        property "<name>";
        file "<file>";
        interval <seconds>;
        flush_interval <seconds>;
        limit <integer>;
        strict <bool>;
        print_units <bool>;
        format <bool>;
        complex_part {NONE,REAL,IMAG,MAG,ANG_DEG,ANG_RAD};
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `file` | `char1024` | | output file name |
| `group` | `char1024` | | group definition string |
| `interval` | `double[s]` | `0 s` | recordering interval (0 'every iteration', -1 'on change') |
| `flush_interval` | `double[s]` | `0 s` | file flush interval (0 never, negative on samples) |
| `strict` | `bool` | `FALSE` | causes the group_recorder to stop the simulation should there be a problem opening or writing with the group_recorder |
| `print_units` | `bool` | `FALSE` | flag to append units to each written value, if applicable |
| `property` | `char256` | | property to record |
| `limit` | `int32` | `0` | the maximum number of lines to write to the file |
| `format` | `bool` | `FALSE` | determines whether output timestamp is formatted to be formatted as human-readable (default) or epoch |
| `complex_part` | `enumeration` | `NONE` | the complex part to record if complex properties are gathered |

Description
-----------

A group recorder is expected to satisfy:

1. At initialization it finds the objects of `group`, checks that each
   has `property`, opens `file` (named `group_recorder-ID.csv` when empty,
   with a warning), and writes the header that `tape::csv_data_only`
   selects, with a column per object named by its name (or `CLASS:ID`).
   Problems write warnings and turn the recorder off, or fail the
   initialization (or the commit) when `strict` is true.
2. With `interval` 0 it writes a row in each postsync pass; with a
   positive `interval` it writes a row at the commit of each time that is
   `interval` seconds after the last row (and asks for that time); with
   -1 it writes a row at each commit where the values changed.
3. Values are written as gridlabd's `gl_get_value()` writes them, with
   units only when `print_units` is true; a complex value is written as
   the part `complex_part` selects (`%f`) unless it is `NONE`.
4. The timestamp is the local date and time, or seconds when `format` is
   true. After `limit` rows the file ends with `# end of file`.

Examples
--------

    >>> import os, tempfile
    >>> from arras import Model, Class, Runner
    >>> Class.reset()
    >>> csv = os.path.join(tempfile.mkdtemp(), "out.csv")
    >>> m = Model()
    >>> m.read_glm(f'''clock {{ timezone "UTC"; starttime "2020-01-01 00:00:00"; stoptime "2020-01-01 01:00:00"; }}
    ... module tape {{ csv_header_type NAME; }}
    ... class load {{ complex power[kVA]; }}
    ... object load {{ name "L1"; power 1+1j; }}
    ... object load {{ name "L2"; power 2+0j; }}
    ... object group_recorder {{ group "class=load"; property "power"; complex_part MAG; file "{csv}"; interval 3600; }}
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> print(open(csv).read(), end="")
    timestamp,L1,L2
    2020-01-01 00:00:00 UTC,1.414214,2.000000
    2020-01-01 01:00:00 UTC,1.414214,2.000000
    >>> Class.reset()

Caveats
-------

- As in gridlabd, `flush_interval` greater than 0 does not flush.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. Rows have every value: gridlabd writes each value with
   `snprintf(line_buffer+index, sizeof(line_buffer)-index-1, ...)`, where
   `sizeof` is that of a pointer, which truncates the first value and
   ends the row after it.
2. `interval -1` writes a row when the values change; gridlabd's commit
   writes no row (it writes only when reading the values fails twice).
3. The default file name has no padding; gridlabd's `%256s-%16i` pads the
   class name and the id with spaces.

References
----------

- `arras-energy/gridlabd`: `module/tape/group_recorder.cpp`,
  `group_recorder.h`
- [Group_recorder class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Tape/Group_recorder.md)
  (`docs/Module/Tape/Group_recorder.md`)
"""

import math
from typing import Any

from . import _file
from ._aggregate import find_group
from ._base import TapeClass, prop, keywords
from ._common import (TS_NEVER, TS_INIT, TS_OPEN, TS_DONE, TS_ERROR, TS_ZERO, Prop, TapeError,
    gl_error, gl_warning, get_state, set_state, strtime, clock, to_double, angle, is_named)
from .recorder import bool_value, keyword

COMPLEX_PART = keywords("NONE", "REAL", "IMAG", "MAG", "ANG_DEG", "ANG_RAD")
"""Keywords of `complex_part`"""

class GroupRecorderState: # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """State of a group recorder between handler calls"""

    def __init__(self):
        self.status = TS_INIT
        self.fp: Any = None
        self.targets: list[Prop] = []
        self.write_interval = 0
        self.flush_interval = 0
        self.write_count = 0
        self.last_write = TS_ZERO
        self.next_write = TS_ZERO
        self.last_flush = TS_ZERO
        self.interval_write = False
        self.line = ""
        self.prev_line = ""

def state(model:Any, name:str) -> GroupRecorderState:
    """State of a group recorder, created on first use"""
    st = get_state(model, name)
    if st is None:
        st = GroupRecorderState()
        set_state(model, name, st)
    return st

class GroupRecorder(TapeClass):
    """Class `group_recorder`; see the module documentation"""

    NAME = "group_recorder"
    PASSCONFIG = "POSTTOPDOWN"
    PROPERTIES = (
        ("file", "char1024", prop("output file name")),
        ("group", "char1024", prop("group definition string")),
        ("interval[s]", "double", prop("recordering interval (0 'every iteration', -1 'on change')")),
        ("flush_interval[s]", "double", prop("file flush interval (0 never, negative on samples)")),
        ("strict", "bool", prop("causes the group_recorder to stop the simulation should there be a problem opening or writing with the group_recorder")),
        ("print_units", "bool", prop("flag to append units to each written value, if applicable")),
        ("property", "char256", prop("property to record")),
        ("limit", "int32", prop("the maximum number of lines to write to the file")),
        ("format", "bool", prop("determines whether output timestamp is formatted to be formatted as human-readable (default) or epoch")),
        ("complex_part", "enumeration", prop("the complex part to record if complex properties are gathered", keywords=COMPLEX_PART)),
    )
    EVENTS = ("init", "postsync", "commit", "finalize")

    @classmethod
    def _problem(cls, model:Any, name:str, st:GroupRecorderState, message:str) -> bool:
        """An error that fails in strict mode, else a warning that turns the
        recorder off"""
        if bool_value(model, name, "strict"):
            gl_error(message)
            return False
        gl_warning(message)
        st.status = TS_ERROR
        return True

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`group_recorder::init()`"""
        # pylint: disable=too-many-return-statements
        st = state(model, name)
        group = model.get_property(name, "group") or ""
        if not group:
            return cls._problem(model, name, st, "group_recorder::init(): no group defined")
        fname = model.get_property(name, "file") or ""
        if not fname:
            if bool_value(model, name, "strict"):
                gl_error("group_recorder::init(): no filename defined in strict mode")
                return False
            fname = f"{cls.NAME}-{model.objects[name].id}.csv"
            model.objects[name]["file"] = fname
            gl_warning(f"group_recorder::init(): no filename defined, auto-generating '{fname}'")
        st.write_interval = int(to_double(model.get_property(name, "interval") or "0", "s"))
        if st.write_interval < -1:
            gl_error(f"group_recorder::init(): invalid write_interval of {st.write_interval}, must be -1 or greater")
            return False
        st.flush_interval = int(to_double(model.get_property(name, "flush_interval") or "0", "s"))
        try:
            members = find_group(model, group)
        except TapeError:
            return cls._problem(model, name, st, "group_recorder::init(): unable to construct a set with group definition")
        if not members:
            return cls._problem(model, name, st, "group_recorder::init(): the defined group returned an empty set")
        try:
            st.fp = open(fname, "w", encoding="utf-8") # pylint: disable=consider-using-with
        except OSError:
            return cls._problem(model, name, st, f"group_recorder::init(): unable to open file '{fname}' for writing")
        pname = model.get_property(name, "property") or ""
        print_units = bool_value(model, name, "print_units")
        for member in members:
            target = Prop(model, member, pname)
            if not target.is_valid:
                gl_error(f"group_recorder::init(): unable to find property '{pname}' in an object of type '{model.objects[member].oclass.name}'")
                return False
            target.unit = target.native if print_units else None
            st.targets.append(target)
        st.status = TS_OPEN
        cls.header(model, name, st, fname, group, pname)
        return True

    @staticmethod
    def header(model:Any, name:str, st:GroupRecorderState, fname:str, group:str, pname:str) -> None: # pylint: disable=too-many-arguments,too-many-positional-arguments
        """`group_recorder::write_header()`"""
        mode = _file.csv_data_only(model)
        if mode == 0:
            st.fp.write(f"# file...... {fname}\n# date...... {_file.asctime()}\n"
                f"# user...... {_file.getenv('USER')}\n# host...... {_file.getenv('HOST')}\n"
                f"# group..... {group}\n# property.. {pname}\n"
                f"# limit..... {int(model.get_property(name, 'limit') or 0)}\n"
                f"# interval.. {st.write_interval}\n# timestamp")
        elif mode == 2:
            st.fp.write("timestamp")
        if mode != 1:
            for target in st.targets:
                obj = model.objects[target.name] # type: ignore[index]
                st.fp.write(f",{target.name}" if is_named(model, target.name) else f",{obj.oclass.name}:{obj.id}") # type: ignore[arg-type]
            st.fp.write("\n")

    @classmethod
    def read(cls, model:Any, name:str, st:GroupRecorderState) -> bool:
        """`group_recorder::read_line()`: read the values into `st.line`"""
        if st.status != TS_OPEN:
            return False
        part = keyword(model, name, "complex_part")
        if st.write_interval == -1:
            st.prev_line = st.line
        values = []
        for target in st.targets:
            if target.ptype == "complex" and part != COMPLEX_PART["NONE"]:
                value, _ = target.complex_value()
                x = {COMPLEX_PART["REAL"]: value.real, COMPLEX_PART["IMAG"]: value.imag,
                    COMPLEX_PART["MAG"]: abs(value), COMPLEX_PART["ANG_DEG"]: angle(value)*180/math.pi,
                    COMPLEX_PART["ANG_RAD"]: angle(value)}[part]
                values.append(f"{x:f}")
            else:
                try:
                    values.append(target.to_string(target.unit)[:127])
                except TapeError as err:
                    gl_error(f"group_recorder::read_line(): unable to get value for '{target.prop}' in object '{target.name}' ({err})")
                    return False
        st.line = "".join(f",{x}" for x in values)
        return True

    @classmethod
    def write(cls, model:Any, name:str, st:GroupRecorderState, t1:int) -> bool:
        """`group_recorder::write_line()`"""
        if st.status != TS_OPEN:
            gl_error("group_recorder::write_line(): trying to write line when the tape is not open")
            return False
        stamp = str(t1) if bool_value(model, name, "format") else strtime(model, t1)
        st.fp.write(f"{stamp}{st.line}\n")
        st.write_count += 1
        return True

    @classmethod
    def postsync(cls, model:Any, name:str, t1:int) -> int:
        """`group_recorder::postsync()`"""
        st = state(model, name)
        if st.write_interval == 0:
            if not cls.read(model, name, st):
                if st.status == TS_OPEN:
                    gl_error("group_recorder::sync")
                    return 0
                return TS_NEVER
        elif st.write_interval > 0:
            if st.last_write + st.write_interval <= t1:
                st.interval_write = True
                st.last_write = t1
                st.next_write = t1 + st.write_interval
            now = clock(model)
            return st.next_write if st.next_write > now else now + 1
        else:
            return TS_NEVER
        if not cls.write(model, name, st, t1):
            gl_error("group_recorder::sync(): error when writing the values to the file")
            return 0
        if st.flush_interval < 0 and (st.write_count + 1) % (-st.flush_interval) == 0:
            st.fp.flush()
        return TS_NEVER

    @classmethod
    def commit(cls, model:Any, name:str, t1:int) -> int|None:
        """`group_recorder::commit()`"""
        # pylint: disable=too-many-branches,too-many-return-statements
        st = state(model, name)
        strict = bool_value(model, name, "strict")
        if st.status == TS_ERROR and strict:
            gl_error("group_recorder::commit(): the object has error'ed and is halting the simulation")
            return 0
        if st.status != TS_OPEN:
            return None
        if st.write_interval > 0 and st.interval_write:
            if not cls.read(model, name, st):
                gl_error("group_recorder::commit(): error when reading the values")
                return 0
            if not cls.write(model, name, st, t1):
                gl_error("group_recorder::commit(): error when writing the values to the file")
                return 0
            st.last_write = t1
            st.interval_write = False
        if st.write_interval == -1:
            if not cls.read(model, name, st):
                gl_error("group_recorder::commit(): error when reading the values")
                return 0
            if st.line != st.prev_line and not cls.write(model, name, st, t1):
                gl_error("group_recorder::commit(): error when writing the values to the file")
                return 0
        if st.flush_interval > 0:
            if st.last_flush + st.flush_interval <= t1:
                st.last_flush = t1
        elif st.flush_interval < 0 and (st.write_count + 1) % (-st.flush_interval) == 0:
            st.fp.flush()
        limit = int(model.get_property(name, "limit") or 0)
        if 0 < limit <= st.write_count:
            st.fp.write("# end of file\n")
            st.fp.close()
            st.fp = None
            st.status = TS_DONE
        return None

    @classmethod
    def finalize(cls, model:Any, name:str, t:int) -> None: # pylint: disable=unused-argument
        """Close the file when the run ends (gridlabd closes it when the
        process exits)"""
        st = get_state(model, name)
        if st is not None and st.fp is not None:
            st.fp.close()
            st.fp = None
