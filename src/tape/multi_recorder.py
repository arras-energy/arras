# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Multi-recorders (class `multi_recorder`)

A `multi_recorder` writes properties of any objects (and global variables)
to a CSV file, one row per sample.

Syntax
------

    module tape;
    object multi_recorder {
        property "[<object>:]<name>[[<unit>]][,...]";
        file "<file>";
        interval <seconds>;
        limit <integer>;
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `interval` | `double[s]` | `-1 s` | sampling interval |
| `property` | `method` | | list of properties to sample (required) |
| `trigger` | `char32` | | condition to trigger recorder |
| `file` | `char1024` | | file in which to record data (required) |
| `filetype` | `char8` | | file type to use when storing data |
| `mode` | `char32` | `file` | recorder operating mode (only `file` is supported) |
| `multifile` | `char1024` | | multi-run file that each run adds columns to |
| `limit` | `int32` | `0` | limit on number of rows to record (0=none) |
| `plotcommands`, `xdata`, `columns` | `char1024`, `char32`, `char32` | | plot options (not used) |
| `format` | `char32` | `0` | timestamps as seconds when not `0` |
| `output` | `enumeration` | `SCREEN` | plot output (not used) |
| `header_units`, `line_units` | `enumeration` | `DEFAULT` | units in the header and the rows |

Description
-----------

A multi-recorder behaves as a `tape.recorder` with these differences, as
in gridlabd:

1. Each item of `property` is `OBJECT:NAME`, `NAME` (a property of the
   parent), or `::NAME` (a global variable). Items are separated by
   commas, spaces, or line ends. An item that is not found writes an error
   and is left out; the others are recorded.
2. A `double` (or `complex`) with a unit other than its own, or with
   `line_units NONE`, is written with `%g` (`%g%+g` and the notation),
   converted, with the unit unless `line_units` is `NONE`; other values
   are written as `gl_get_value()` writes them.
3. The parent is optional; the file has no `# target` line without one.
4. Rows are flushed at every row unless a `flush` property is published
   (gridlabd's `flush` member is never set).
5. There is no `strftime_format`; the file is closed at the end of the
   run without an `# end of tape` line (unless the limit closed it).

Examples
--------

    >>> import os, tempfile
    >>> from arras import Model, Class, Runner
    >>> Class.reset()
    >>> csv = os.path.join(tempfile.mkdtemp(), "out.csv")
    >>> m = Model()
    >>> m.read_glm(f'''clock {{ timezone "UTC"; starttime "2020-01-01 00:00:00"; stoptime "2020-01-01 01:00:00"; }}
    ... module tape {{ csv_header_type NAME; }}
    ... class load {{ double power[kW]; }}
    ... object load {{ name "L1"; power 1.5; }}
    ... object load {{ name "L2"; power 2.5; }}
    ... object multi_recorder {{ property "L1:power,L2:power[W]"; file "{csv}"; interval 3600; }}
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> print(open(csv).read(), end="")
    timestamp,L1:power,L2:power[W]
    2020-01-01 00:00:00 UTC,+1.5,2500 W
    >>> Class.reset()

Caveats
-------

- As in gridlabd, a property is written with a unit only when the
  property list gives one; `line_units ALL` has no effect.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The file header has the column names that `header_units` selects
   (see `tape.recorder`, difference 4).
2. A `double` in another unit is converted with the unit's offset (e.g.
   `degF` to `degC`); gridlabd multiplies by the conversion of 1, so
   0 degF is written as 0 degC.
3. When the run ends, the multi-run temporary file replaces the
   `multifile`; gridlabd does so only when the recorder stops at its
   limit.
4. Deltamode is not run.

References
----------

- `arras-energy/gridlabd`: `module/tape/multi_recorder.cpp`, `tape.h`,
  `module/tape_file/tape_file.cpp`
- [Multi_recorder class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Tape/Multi_recorder.md)
  (`docs/Module/Tape/Multi_recorder.md`)
"""

import re
from typing import Any

from . import _file
from ._base import TapeClass, prop
from ._common import (TS_NEVER, TS_INIT, TS_OPEN, TS_DONE, TS_ERROR, TRL_QUALIFIED, Prop,
    TapeError, gl_error, get_state, set_state, find_unit, unit_scale, clock, parent_of,
    is_named, cprintf, to_double, convert)
from .recorder import (OUTPUT, UNITS, RecorderState, keyword, timestamp_text, compare,
    multirun_header, multirun_close, multirun_write)

BUFFER_SIZE = 4096
"""Size of the value buffer of `sync_multi_recorder()`"""

def state(model:Any, name:str) -> RecorderState:
    """State of a multi-recorder, created on first use"""
    st = get_state(model, name)
    if st is None:
        st = RecorderState(model, name)
        st.interval = -1
        set_state(model, name, st)
    return st

class MultiRecorder(TapeClass):
    """Class `multi_recorder`; see the module documentation"""

    NAME = "multi_recorder"
    PASSCONFIG = "POSTTOPDOWN|OBSERVER"
    TRL = TRL_QUALIFIED
    PROPERTIES = (
        ("interval[s]", "double", prop("sampling interval", "-1 s")),
        ("property", "method", prop("list of properties to sample", flags="REQUIRED")),
        ("trigger", "char32", prop("condition to trigger recorder", "")),
        ("file", "char1024", prop("file in which to record data", flags="REQUIRED")),
        ("filetype", "char8", prop("file type to use when storing data", "txt")),
        ("mode", "char32", prop("recorder operating mode", "file")),
        ("multifile", "char1024", prop()),
        ("limit", "int32", prop("limit on number of rows to record (0=none)", "0")),
        ("plotcommands", "char1024", prop()),
        ("xdata", "char32", prop()),
        ("columns", "char32", prop()),
        ("format", "char32", prop(default="0")),
        ("output", "enumeration", prop(keywords=OUTPUT)),
        ("header_units", "enumeration", prop(keywords=UNITS)),
        ("line_units", "enumeration", prop(keywords=UNITS)),
    )
    EVENTS = ("postsync", "finalize")

    @classmethod
    def link(cls, model:Any, name:str, st:RecorderState) -> list[tuple[Prop,float]]|None:
        """`link_multi_properties()`: the properties to record, with their
        unit conversion factors; items not found are left out"""
        # pylint: disable=too-many-branches,too-many-locals,too-many-statements
        obj = model.objects[name]
        objname = name if is_named(model, name) else f"{obj.oclass.name}:{obj.id}"
        parent = parent_of(model, name)
        result = []
        for item in [x for x in re.split(r"[, \n]+", st.property or "") if x]:
            unit = None
            if "::" in item:
                gname = item[2:] if item.startswith("::") else item
                target = Prop(model, None, gname)
                if not target.is_valid:
                    gl_error(f"{objname}: unable to find global ''")
                    continue
            else:
                if ":" in item:
                    objstr, propstr = item.split(":", 1)
                    if objstr not in model.objects:
                        gl_error(f"{objname}: unable to find object '{objstr or '(parent)'}'")
                        continue
                    tname = objstr
                else:
                    if parent is None:
                        gl_error(f"{objname}: object has no parent for property '{item}'")
                        continue
                    tname, propstr = parent, item
                tobj = model.objects[tname]
                match = re.match(r"([A-Za-z0-9_.]{1,255})(?:\[([^]\n,]{1,255})\])?", propstr)
                pstr = match.group(1) if match else ""
                if match and match.group(2):
                    unit = match.group(2)
                    if find_unit(unit) is None:
                        gl_error(f"{objname}: unable to find unit '{unit}' for property '{pstr}' in object '{tobj.oclass.name} {tobj.id}'")
                        continue
                part = None
                if "." in pstr and pstr.split(".", 1)[1] in ("real", "imag"):
                    pstr, part = pstr.split(".", 1)
                target = Prop(model, tname, pstr, part)
            if not target.is_valid:
                if target.name is not None:
                    gl_error(f"{objname}: property '{item}' not found in object")
                else:
                    gl_error(f"{objname}: global '{item}' not found")
                continue
            scale = 1.0
            if unit is not None and target.native is None:
                gl_error(f"{objname}: property '{item}' is unitless, ignoring unit conversion")
            elif unit is not None:
                factor = unit_scale(target.native, unit) # type: ignore[arg-type]
                if factor is None:
                    gl_error(f"{objname}: unable to convert property '{item}' units to '{unit}'")
                    continue
                scale = factor
            target.unit = unit
            result.append((target, scale))
        return result or None

    @classmethod
    def read(cls, model:Any, name:str, st:RecorderState) -> str|None:
        """`read_multi_properties()`: the values as text, or `None` when
        there are none"""
        line_units = keyword(model, name, "line_units")
        values = []
        size = 0
        for target, scale in st.targets or []: # type: ignore[misc]
            if size >= BUFFER_SIZE - 33:
                break
            try:
                if target.ptype == "double" and (scale != 1.0 or line_units == UNITS["NONE"]):
                    value = target.double()
                    if target.unit is not None and target.native is not None:
                        value = convert(value, target.native, target.unit)
                    text = cprintf("%g", value)
                    if line_units != UNITS["NONE"] and target.unit is not None:
                        text += f" {target.unit}"
                elif target.ptype == "complex" and (scale != 1.0 or line_units == UNITS["NONE"]):
                    value, notation = target.complex_value()
                    value *= scale
                    text = cprintf("%g%+g%c", value.real, value.imag, notation)
                    if line_units != UNITS["NONE"] and target.unit is not None:
                        text += f" {target.unit}"
                else:
                    text = target.to_string(target.unit)
            except TapeError as err:
                gl_error(str(err))
                text = ""
            values.append(text)
            size += len(text) + 1
        if not values:
            return None
        return ",".join(values)

    @classmethod
    def header(cls, model:Any, name:str, st:RecorderState) -> str|None: # pylint: disable=too-many-locals
        """`out_property` of `multi_recorder_open()`: the column names for
        `header_units`"""
        header_units = keyword(model, name, "header_units")
        parent = parent_of(model, name)
        oid = model.objects[name].id
        if header_units == UNITS["DEFAULT"]:
            return st.property
        names = []
        for token in [x for x in (st.property or "").split(",") if x]:
            if header_units == UNITS["NONE"]:
                match = re.match(r"([A-Za-z0-9_:.]+)", token)
                names.append(match.group(1) if match else "")
                continue
            objstr, _, bigprop = token.rpartition(":") if ":" in token and "::" not in token else ("", "", token)
            target = objstr or parent
            if objstr and objstr not in model.objects:
                gl_error(f"multi_recorder:{oid}: unable to find object '{objstr}'")
                return None
            match = re.match(r"([A-Za-z0-9_.]+)(?:\[([^]\n,]+)\])?", bigprop.strip())
            propstr = match.group(1) if match else bigprop
            unit = match.group(2) if match else None
            if unit is not None and find_unit(unit) is None:
                gl_error(f"multi_recorder:{oid}: unable to find unit '{unit}' for property '{propstr}'")
                return None
            found = Prop(model, target, propstr) if target else None
            if found is None or not found.is_valid:
                gl_error(f"multi_recorder:{oid}: unable to find property '{propstr}' for object '{target}'")
                return None
            unit = unit or found.native
            label = f"{objstr}:{propstr}" if objstr and objstr != parent else propstr
            names.append(f"{label}[{unit}]" if unit else label)
        return ",".join(names)

    @classmethod
    def open(cls, model:Any, name:str, st:RecorderState) -> bool:
        """`multi_recorder_open()`: open the files and write the headers"""
        if st.property is None:
            gl_error("at least one property must be specified")
            return False
        st.interval = int(to_double(model.get_property(name, "interval") or "-1", "s"))
        fname = st.file
        if fname == "":
            pobj = model.objects[parent_of(model, name) or name]
            fname = st.file = f"{pobj.oclass.name}-{pobj.id}.{model.get_property(name, 'filetype') or ''}"
        st.multifile = model.get_property(name, "multifile") or ""
        if st.multifile:
            if st.interval < 1:
                gl_error("multirecorder: transient recorders cannot use multi-run output files")
                return False
            multirun_header(model, st, model.objects[name].id, parent_of(model, name),
                [t.prop for t, _ in st.targets or []], kind="multi_recorder") # type: ignore[misc]
        if not _file.get_ftable(model.get_property(name, "mode") or "file"):
            return False
        header = cls.header(model, name, st)
        if header is None:
            header = st.property
        return _file.open_recorder(model, name, st, fname, header) # type: ignore[arg-type]

    @classmethod
    def close(cls, model:Any, st:RecorderState) -> None:
        """`close_multi_recorder()`"""
        _file.close_recorder(model, st)
        multirun_close(st, kind="multi_recorder")

    @classmethod
    def write(cls, model:Any, name:str, st:RecorderState) -> None:
        """`multi_recorder_write()`: write the last sample"""
        text = model.get_property(name, "format") or "0"
        ts = timestamp_text(model, st.last_ts, text.strip() not in ("0", ""))
        if (0 < st.limit < st.samples) or not _file.write_row(model, st, ts, st.last_value):
            cls.close(model, st)
            st.status = TS_DONE
        else:
            st.samples += 1
        if st.flush == 0 or (st.flush > 0 and clock(model) % st.flush == 0):
            _file.flush(st)
        multirun_write(st, ts)

    @classmethod
    def postsync(cls, model:Any, name:str, t0:int) -> int:
        """`sync_multi_recorder()`: sample and write; returns the next
        sample time"""
        # pylint: disable=too-many-branches
        st = state(model, name)
        oid = model.objects[name].id
        if st.status == TS_DONE:
            cls.close(model, st)
            return TS_NEVER
        if st.last_ts < 1 and st.interval != -1:
            st.last_ts = t0
        if st.targets is None:
            st.targets = cls.link(model, name, st) # type: ignore[assignment]
        buffer = ""
        if st.targets is None:
            buffer = f"property '{st.property}' contains a reference that was not found" if st.property else "property reference is missing"
            cls.close(model, st)
            st.status = TS_ERROR
        else:
            if st.status == TS_OPEN and t0 > st.clock:
                st.clock = t0
                if st.interval > 0 and st.last_ts < t0 and st.last_value:
                    cls.write(model, name, st)
                    st.last_value = ""
            if st.interval in (0, -1) or t0 >= st.last_ts + st.interval or t0 == st.last_ts:
                text = cls.read(model, name, st)
                if text is None:
                    buffer = "unable to read a property"
                    cls.close(model, st)
                    st.status = TS_ERROR
                else:
                    buffer = text
                if st.interval > 0:
                    st.last_ts = t0
        if st.status != TS_ERROR:
            if st.trigger:
                if not compare(buffer, st.trigger) or (st.status == TS_INIT and not cls.open(model, name, st)):
                    return TS_NEVER if st.interval in (0, -1) else t0 + st.interval
            elif st.status == TS_INIT and not cls.open(model, name, st):
                cls.close(model, st)
                return TS_NEVER
            if st.last_ts < 1 and st.interval != -1:
                st.last_ts = t0
            if st.status == TS_OPEN:
                if st.interval == 0 or (st.interval == -1 and st.last_ts != t0 and buffer != st.last_value):
                    st.last_value = buffer[:4999]
                    st.last_ts = t0
                    cls.write(model, name, st)
                elif st.interval > 0 and st.last_ts == t0:
                    st.last_value = buffer[:4999]
        if st.status == TS_ERROR:
            gl_error(f"recorder {oid} {buffer}")
            cls.close(model, st)
            st.status = TS_DONE
            return TS_NEVER
        if st.interval in (0, -1):
            return TS_NEVER
        return st.last_ts + st.interval

    @classmethod
    def finalize(cls, model:Any, name:str, t:int) -> None: # pylint: disable=unused-argument
        """Close the files when the run ends (gridlabd closes them when
        the process exits)"""
        st = get_state(model, name)
        if st is not None:
            if st.fp is not None:
                st.fp.close()
                st.fp = None
            multirun_close(st, kind="multi_recorder")
