# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Multiplayers (class `multiplayer`)

A `multiplayer` writes the columns of a CSV file into properties of its
parent (or global variables) at the times of the first column.

Syntax
------

    module tape;
    object multiplayer {
        parent <object>;
        file "<file>";
        indexname "<column>";
        property "<name>[[<unit>]][,...]";
        on_error {IGNORE,WARN,STOP};
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `status` | `enumeration` | `INIT` | status of multiuplayer (`INIT`, `OK`, `DONE`, `ERROR`) |
| `indexname` | `char32` | `timestamp` | name of index column |
| `on_error` | `enumeration` | `WARN` | error handling (IGNORE, WARN, STOP) |
| `file` | `method` | | data source |
| `property` | `method` | | target property or object:property |

Description
-----------

A multiplayer is expected to satisfy:

1. At initialization it opens `file` and reads its header line, whose
   first column must be `indexname`. Without `property`, the other columns
   of the header name the properties; a name `NAME[UNIT]` reads the
   column's values in `UNIT` and converts them to the property's unit.
   The values due at the start time are written.
2. At each precommit, when the clock reaches the time of the next row,
   the rows due are written: `double` and `complex` values with a unit
   conversion, others as text.
3. A value that cannot be written, a missing value, or an extra value is
   ignored (`IGNORE`), writes a warning and sets `status` to `ERROR`
   (`WARN`), or fails the run (`STOP`). Rows must be in time order.
4. The sync pass returns the time of the next row.

Examples
--------

    >>> import os, tempfile
    >>> from arras import Model, Class, Runner
    >>> Class.reset()
    >>> csv = os.path.join(tempfile.mkdtemp(), "data.csv")
    >>> with open(csv, "w") as fh:
    ...     _ = fh.write("timestamp,power[MW]\\n2020-01-01 00:00:00 UTC,1.5\\n2020-01-01 01:00:00 UTC,2.5\\n")
    >>> m = Model()
    >>> m.read_glm(f'''clock {{ timezone "UTC"; starttime "2020-01-01 00:00:00"; stoptime "2020-01-01 02:00:00"; }}
    ... module tape;
    ... class load {{ double power[kW]; }}
    ... object load {{ name "L"; object multiplayer {{ file "{csv}"; }}; }}
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> m.get_property("L", "power")
    '2500.0 kW'
    >>> Class.reset()

Caveats
-------

- The `file` and `property` methods are read at initialization; gridlabd
  opens the file and finds the properties when they are set.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A `double` or `complex` value that cannot be read is not written;
   gridlabd writes an uninitialized value.
2. A `double` in another unit is converted with the unit's offset (e.g.
   `degF` to `degC`); gridlabd multiplies by the conversion of 1.

References
----------

- `arras-energy/gridlabd`: `module/tape/multiplayer.cpp`, `multiplayer.h`
- [Multiplayer class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Tape/Multiplayer.md)
  (`docs/Module/Tape/Multiplayer.md`)
"""

import re
from typing import Any

from ._base import TapeClass, prop, keywords
from ._common import (TS_ZERO, TS_NEVER, TS_INVALID, TRL_PROVEN, Prop, TapeError, gl_error,
    gl_warning, get_state, set_state, find_unit, unit_scale, parent_of, is_named, scan_double,
    to_timestamp, fmt, convert)

STATUS = keywords("INIT", "OK", "DONE", "ERROR")
"""Keywords of `status`"""

ON_ERROR = keywords("IGNORE", "WARN", "STOP")
"""Keywords of `on_error`"""

class MultiplayerState: # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """State of a multiplayer between handler calls"""

    def __init__(self):
        self.fp: Any = None
        self.fname = ""
        self.line = ""
        self.next_t = TS_ZERO
        self.targets: list[tuple[Prop,float]] = []
        self.names: list[str] = []
        self.status = "INIT"

def state(model:Any, name:str) -> MultiplayerState:
    """State of a multiplayer, created on first use"""
    st = get_state(model, name)
    if st is None:
        st = MultiplayerState()
        set_state(model, name, st)
    return st

class Multiplayer(TapeClass):
    """Class `multiplayer`; see the module documentation"""

    NAME = "multiplayer"
    PASSCONFIG = "BOTTOMUP|AUTOLOCK|OBSERVER"
    TRL = TRL_PROVEN
    PROPERTIES = (
        ("status", "enumeration", prop("status of multiuplayer", "INIT", keywords=STATUS)),
        ("indexname", "char32", prop("name of index column", "timestamp")),
        ("on_error", "enumeration", prop("error handling (IGNORE, WARN, STOP)", "WARN", keywords=ON_ERROR)),
        ("file", "method", prop("data source")),
        ("property", "method", prop("target property or object:property")),
    )
    EVENTS = ("init", "precommit", "sync")

    @staticmethod
    def _label(model:Any, name:str) -> str:
        return name if is_named(model, name) else f"{model.objects[name].oclass.name}:{model.objects[name].id}"

    @classmethod
    def error(cls, model:Any, name:str, message:str) -> None:
        """`gld_object::error()`"""
        gl_error(f"{cls._label(model, name)}: {message}")

    @classmethod
    def warning(cls, model:Any, name:str, message:str) -> None:
        """`gld_object::warning()`"""
        gl_warning(f"{cls._label(model, name)}: {message}")

    @staticmethod
    def _set_status(model:Any, name:str, st:MultiplayerState, status:str) -> None:
        st.status = status
        model.objects[name]["status"] = status

    @classmethod
    def add_properties(cls, model:Any, name:str, st:MultiplayerState, text:str) -> bool:
        """`multiplayer::property()`: add targets"""
        parent = parent_of(model, name)
        for item in [x for x in text.split(",") if x]:
            match = re.match(r"([^[]{1,63})(?:\[([^]]{1,63})\])?", item)
            pname = match.group(1) if match else item
            uname = match.group(2) if match else None
            if uname is not None and find_unit(uname) is None:
                cls.error(model, name, f"unit '{uname}' is not valid")
                return False
            target = Prop(model, parent, pname) if parent is not None else Prop(model, None, pname)
            if not target.is_valid:
                cls.error(model, name, f"property '{pname}' is not found")
                return False
            scale = 0.0
            if target.native is not None:
                scale = 1.0
                if uname is not None:
                    factor = unit_scale(uname, target.native)
                    if factor is None:
                        cls.error(model, name, f"unit '{uname}' cannot be converted to '{target.native}'")
                        return False
                    scale = factor
            target.unit = uname
            st.targets.append((target, scale))
            st.names.append(pname)
        return True

    @classmethod
    def read(cls, model:Any, name:str, st:MultiplayerState) -> bool:
        """`multiplayer::read()`: read the next row and its time"""
        line = st.fp.readline()
        if not line:
            st.next_t = TS_NEVER
            return True
        st.line = line[:-1] if line.endswith("\n") else line
        last_t = st.next_t
        try:
            st.next_t = to_timestamp(model, st.line.split(",", 1)[0])
        except TapeError:
            st.next_t = TS_ZERO
        if st.next_t in (TS_ZERO, TS_INVALID):
            st.next_t = last_t
            return True
        if st.next_t <= last_t:
            cls.error(model, name, f"invalid index (out of order) at '{st.line}'")
            cls._set_status(model, name, st, "ERROR")
            return False
        return True

    @classmethod
    def _problem(cls, model:Any, name:str, st:MultiplayerState, stop:str, warn:str) -> bool:
        """An `on_error` case; `False` stops"""
        mode = model.get_property(name, "on_error") or "WARN"
        if mode == "STOP":
            cls.error(model, name, stop)
            return False
        if mode == "WARN":
            cls.warning(model, name, warn)
            cls._set_status(model, name, st, "ERROR")
        else:
            cls._set_status(model, name, st, "OK" if st.next_t < TS_NEVER else "DONE")
        return True

    @classmethod
    def update(cls, model:Any, name:str, st:MultiplayerState) -> bool:
        """`multiplayer::update()`: write the values of the row read"""
        # pylint: disable=too-many-branches,too-many-locals,too-many-return-statements
        tokens = [x for x in st.line.split(",") if x]
        if not tokens and st.targets:
            cls.error(model, name, f"no data on record at index '{st.line}'")
            return False
        stamp, values = (tokens[0], tokens[1:]) if tokens else ("", [])
        for index, (target, scale) in enumerate(st.targets):
            if index >= len(values):
                owner = target.name or "global"
                return cls._problem(model, name, st, f"missing data for '{owner}.{target.prop}' at index '{stamp}'",
                    f"ignoring missing data for '{owner}.{target.prop}' at index '{stamp}'")
            text = values[index]
            if scale != 0:
                if target.ptype == "double":
                    result = scan_double(text)
                    if result is None:
                        if not cls._problem(model, name, st, f"double value '{text}' is invalid", f"double value '{text}' is invalid"):
                            return False
                    else:
                        value = result[0]*scale
                        if target.unit is not None:
                            converted = convert(result[0], target.unit, target.native) # type: ignore[arg-type]
                            value = value if converted is None else converted
                        cls._write(target, f"{fmt(value)} {target.native}")
                elif target.ptype == "complex":
                    match = re.match(r"\s*([-+]?[\d.eE+-]+?)([-+][\d.eE]+)([ijrd])", text)
                    first = scan_double(text)
                    if first is None or (match is None and first[1].strip()):
                        if not cls._problem(model, name, st, f"complex value '{text}' is invalid", f"complex value '{text}' is invalid"):
                            return False
                    else:
                        cls._write(target, f"{cls._complex(text, scale)} {target.native}")
                else:
                    owner = target.name or "global"
                    if not cls._problem(model, name, st, f"unit conversion of '{text}' not possible for '{owner}.{target.prop}'",
                            f"unit conversion '{text}' not possible for '{owner}.{target.prop}'"):
                        return False
            elif not cls._write(target, text):
                owner = target.name or "global"
                if not cls._problem(model, name, st, f"unable to set '{owner}.{target.prop}' to value '{text}'",
                        f"ignoring unable to set '{owner}.{target.prop}' to value '{text}'"):
                    return False
        if len(values) > len(st.targets):
            return cls._problem(model, name, st, f"extra data '{values[len(st.targets)]}' at index '{stamp}'",
                f"ignoring extra data '{values[len(st.targets)]}' at index '{stamp}'")
        return True

    @staticmethod
    def _complex(text:str, scale:float) -> str:
        first = scan_double(text)
        real, rest = first # type: ignore[misc]
        second = scan_double(rest) if rest[:1] in "+-" else None
        if second is None:
            return f"{fmt(real*scale)}+0i"
        imag, rest = second
        notation = rest[:1] or "i"
        if notation in "dr":
            return f"{fmt(real*scale)}{'+' if imag >= 0 else ''}{fmt(imag)}{notation}"
        return f"{fmt(real*scale)}{'+' if imag*scale >= 0 else ''}{fmt(imag*scale)}{notation}"

    @staticmethod
    def _write(target:Prop, text:str) -> bool:
        """Write a value without messages (`gld_property::from_string()`)"""
        try:
            if target.name is None:
                target.model.globals.set(target.prop, text)
            else:
                target.model.set_property(target.name, target.prop, text.strip())
            return True
        except Exception: # pylint: disable=broad-exception-caught
            return False

    @classmethod
    def advance(cls, model:Any, name:str, st:MultiplayerState, t:int) -> bool:
        """`multiplayer::advance()`: write the rows due at `t`"""
        while st.next_t <= t:
            if not cls.update(model, name, st) or not cls.read(model, name, st):
                break
        return st.status != "ERROR"

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool:
        """`multiplayer::init()`"""
        st = state(model, name)
        st.fname = model.get_property(name, "file") or ""
        if st.fname:
            try:
                st.fp = open(st.fname, "r", encoding="utf-8") # pylint: disable=consider-using-with
            except OSError:
                cls.error(model, name, f"file '{st.fname}' not found")
                return False
        else:
            cls.error(model, name, "no input file specified")
            cls.error(model, name, "unable to load file '(null)'")
            return False
        plist = model.get_property(name, "property") or ""
        if plist and not cls.add_properties(model, name, st, plist):
            return False
        if not cls.load(model, name, st):
            cls.error(model, name, f"unable to load file '{st.fname}'")
            return False
        if not st.targets:
            cls.error(model, name, "no targets specified")
        model.objects[name]["property"] = ",".join(st.names) if st.names else model.objects[name].get("property", "")
        return cls.advance(model, name, st, t)

    @classmethod
    def load(cls, model:Any, name:str, st:MultiplayerState) -> bool:
        """`multiplayer::load()`: read the header and the first row"""
        st.fp.seek(0)
        line = st.fp.readline()
        line = line[:-1] if line.endswith("\n") else line
        if not st.targets:
            columns = [x for x in line.split(",") if x]
            indexname = model.get_property(name, "indexname") or "timestamp"
            if not columns or columns[0] != indexname:
                cls.error(model, name, f"column '{columns[0] if columns else '0'}' is not '{indexname}' as specified by indexname property")
                return False
            for column in columns[1:]:
                if not cls.add_properties(model, name, st, column):
                    cls.error(model, name, "file load failed")
                    return False
        return cls.read(model, name, st)

    @classmethod
    def precommit(cls, model:Any, name:str, t1:int) -> int:
        """`multiplayer::precommit()`"""
        st = state(model, name)
        if st.fp is None:
            return TS_NEVER
        if t1 < st.next_t:
            return st.next_t
        return TS_NEVER if cls.advance(model, name, st, t1) else TS_INVALID

    @classmethod
    def sync(cls, model:Any, name:str, t1:int) -> int: # pylint: disable=unused-argument
        """`multiplayer::sync()`: the time of the next row"""
        st = state(model, name)
        return st.next_t if st.fp is not None else TS_NEVER
