# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Players (class `player`)

A `player` writes values read from a file into properties of its parent
(or, without a parent, into its own `value` property) at the times the
file gives.

Syntax
------

    module tape;
    object player {
        parent <object>;
        property "<name>[[<unit>]][,...]";
        file "<file>";
        loop <integer>;
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `property` | `char256` | `(undefined)` | property to play values into (required) |
| `file` | `char1024` | | file from which to read values (required) |
| `filetype` | `char8` | `txt` | extension of the default file name |
| `mode` | `char32` | `file` | tape mode (only `file` is supported) |
| `loop` | `int32` | `0` | number of time to loop the player |

Description
-----------

Each line of the file is `TIME,VALUE[,VALUE...]`. Lines that start with
`#` and blank lines are skipped. `TIME` is one of:

| Form | Example | Meaning |
| ---- | ------- | ------- |
| date and time with a time zone | `2000-01-01 00:00:00 PST` | absolute, in the zone named |
| date and time | `2000-01-01 3:00:00` | absolute, in the model's time zone |
| a number with a unit `s`, `m`, `h`, or `d` | `+6h`, `86400s` | relative to the previous time with `+`, else absolute seconds |
| seconds | `946684800` | absolute (epoch seconds) |

The date order follows the `dateformat` global (`ISO`, `US`, or `EURO`).
A player is expected to satisfy:

1. On its first presync it opens the file (named `CLASS-ID.FILETYPE` of
   the parent when `file` is empty) and reads the first time. When
   `property` is `(undefined)`, the first line of the file is a CSV header
   whose names after the first column are the properties (and `property`
   is set to them).
2. At each presync, every line whose time is at or before the clock is
   written to the properties, in order: values are separated by commas,
   tabs, or line ends; each property gets the next value; a property
   `NAME.real` or `NAME.imag` gets a part of a complex property; a
   property `NAME[UNIT]` reads values in `UNIT` and converts them to the
   property's unit.
3. The presync returns the time of the next line, or `NEVER` after the
   last line. At the end of the file the player starts again from the
   beginning `loop` times; in the loops, only relative times are used.
4. Times with fractions of a second are passed over as gridlabd does
   outside deltamode: the value is written at the next whole second.

Examples
--------

    >>> import os, tempfile
    >>> from arras import Model, Class, Runner
    >>> Class.reset()
    >>> folder = tempfile.mkdtemp()
    >>> with open(os.path.join(folder, "load.player"), "w") as fh:
    ...     _ = fh.write("2020-01-01 00:00:00,1.5\\n+1h,2.5\\n")
    >>> m = Model()
    >>> m.read_glm(f'''clock {{ timezone "UTC"; starttime "2020-01-01 00:00:00"; stoptime "2020-01-01 02:00:00"; }}
    ... module tape;
    ... class load {{ double power[kW]; }}
    ... object load {{ name "L"; object player {{ property "power[MW]"; file "{folder}/load.player"; }}; }}
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> m.get_property("L", "power")
    '2500.0 kW'
    >>> Class.reset()

Caveats
-------

- The file name is used as given (relative to the working folder), as in
  gridlabd.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A property with a unit (`NAME[UNIT]`) converts values from `UNIT` to
   the property's unit, as `docs/Module/Tape/Player.md` says (decision
   1.3). gridlabd stores the number without conversion, and refuses a
   value with a unit for a property listed without one.
2. Deltamode is not run: a player with the `DELTAMODE` flag behaves as
   one without it.
3. A player that loops over a file whose first line is a CSV header skips
   the header when it starts again; gridlabd reads it again as data and
   writes a warning.
4. A time zone abbreviation is read only when it is `UTC`, `GMT`, or an
   abbreviation of the model's time zone (`arras` time zones are IANA
   names, #41).

References
----------

- `arras-energy/gridlabd`: `module/tape/player.cpp`, `tape.h`,
  `module/tape_file/tape_file.cpp`
- [Player class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Tape/Player.md)
  (`docs/Module/Tape/Player.md`)
"""

import re
from typing import Any

from . import _file
from ._base import TapeClass, prop
from ._common import (TS_ZERO, TS_NEVER, TS_INVALID, TS_INIT, TS_OPEN, TS_DONE, TS_ERROR,
    TRL_PROVEN, Prop, gl_error, gl_warning, get_state, set_state, find_unit, unit_scale,
    mktime, parent_of, is_named)

class PlayerState: # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """State of a player between handler calls (gridlabd `struct player`)"""

    def __init__(self, model:Any, name:str):
        self.status = TS_INIT
        self.fp: Any = None
        self.loop = int(model.get_property(name, "loop") or 0)
        self.loopnum = 0
        self.next_ts = TS_ZERO
        self.next_ns = 0
        self.next_value = ""
        self.delta_ts = TS_NEVER
        self.delta_ns = 0
        self.delta_value = ""
        self.targets: list[Prop]|None = None
        self.lasterr = ""
        self.header = False

def state(model:Any, name:str) -> PlayerState:
    """State of a player, created on first use"""
    st = get_state(model, name)
    if st is None:
        st = PlayerState(model, name)
        set_state(model, name, st)
    return st

_INT = r"\s*((?>[-+]?\d+))"
_DBL = r"\s*((?>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?))"
_TIMES = [
    re.compile(_INT + "-" + _INT + "-" + _INT + r"\s*" + _INT + ":" + _INT + ":" + _DBL + r"\s*(\S{1,4})"),
    re.compile(_INT + "-" + _INT + "-" + _INT + r"\s*" + _INT + "(?::" + _INT + "(?::" + _DBL + ")?)?"),
    re.compile(_INT + r"\s*(\S)"),
    re.compile(r"\s*((?>[-+]?(?:(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|inf|nan)))", re.IGNORECASE),
]
"""`sscanf()` formats of `player_read()`: date and time with a zone, date
and time, a number with a unit, and seconds"""

_SPLIT = re.compile(r"([^,]{1,32}),([^\n\r;]{1,1023})")
"""`sscanf(result,"%32[^,],%1023[^\\n\\r;]")`"""

def _trim(text:str) -> str:
    """gridlabd `trim()`: leading and trailing whitespace removed (but not
    the first character)"""
    text = text.lstrip()
    return text[:1] + text[1:].rstrip() if text else text

class Player(TapeClass):
    """Class `player`; see the module documentation"""

    NAME = "player"
    PASSCONFIG = "PRETOPDOWN"
    TRL = TRL_PROVEN
    PROPERTIES = (
        ("property", "char256", prop("property to play values into", "(undefined)", "REQUIRED")),
        ("file", "char1024", prop("file from which to read values", flags="REQUIRED")),
        ("filetype", "char8", prop(default="txt")),
        ("mode", "char32", prop(default="file")),
        ("loop", "int32", prop("number of time to loop the player", "0")),
    )
    EVENTS = ("presync",)

    @classmethod
    def link(cls, model:Any, name:str, st:PlayerState, target:str) -> list[Prop]|None:
        """`player_link_properties()`: the properties named by `property`
        (or the CSV header) in object `target`"""
        plist = model.get_property(name, "property") or ""
        pid = model.objects[target].id
        if plist and plist != "(undefined)":
            items = plist
        else:
            line = _file.read_player(st) if st.fp is not None else None
            if line is None:
                gl_error(f"player:{pid} missing either property list of CSV header")
                return None
            if "," not in line:
                gl_error(f"player:{pid} CSV header missing required property names")
                return None
            items = line[line.index(",")+1:].rstrip()
            model.objects[name]["property"] = items
            st.header = True
        targets = []
        for item in items.split(","):
            if not item:
                continue
            item = item.lstrip()
            unit = None
            match = re.match(r"([A-Za-z0-9_.]+)\[([^]\n,]+)\]", item)
            if match:
                unit = match.group(2)
                if find_unit(unit) is None:
                    gl_error(f"sync_player:{pid}: unable to find unit '{unit}' for property '{match.group(1)}'")
                    return None
                item = match.group(1)
            part = None
            if "." in item and item.split(".", 1)[1] in ("real", "imag"):
                item, part = item.split(".", 1)
            target_prop = Prop(model, target, item, part)
            if not target_prop.is_valid:
                gl_error(f"sync_player: property '{item}' not found")
                return None
            if unit is not None and target_prop.native is None:
                gl_error(f"sync_player:{pid}: property '{item}' is unitless, ignoring unit conversion")
                unit = None
            elif unit is not None and unit_scale(target_prop.native, unit) is None: # type: ignore[arg-type]
                gl_error(f"sync_player:{pid}: unable to convert property '{item}' units to '{unit}'")
                return None
            target_prop.unit = unit if unit is not None else target_prop.native
            targets.append(target_prop)
        return targets

    @staticmethod
    def write(model:Any, target:str, targets:list[Prop], buffer:str) -> int:
        """`player_write_properties()`: write the values of a line"""
        tokens = [x for x in re.split(r"[,\n\r\t]+", buffer[:1024]) if x]
        count = 0
        for index, target_prop in enumerate(targets):
            if index >= len(tokens):
                gl_error(f"sync_player:{model.objects[target].id}: not enough values on line: {buffer}")
                return count
            target_prop.set(tokens[index])
            count += 1
        return count

    @classmethod
    def read(cls, model:Any, name:str, st:PlayerState) -> int:
        """`player_read()`: read the next line; returns the time of the next
        value (one second later for a time with a fraction of a second)"""
        # pylint: disable=too-many-branches,too-many-statements,too-many-locals
        fmt = model.globals.get("dateformat") or "ISO"
        while True:
            if st.targets is None and parent_of(model, name) is not None:
                st.targets = cls.link(model, name, st, parent_of(model, name)) # type: ignore[arg-type]
                if st.targets is None:
                    obj = model.objects[name]
                    parent = parent_of(model, name)
                    label = (parent if is_named(model, parent) else "(unnamed)") if parent else "(no parent)" # type: ignore[arg-type]
                    gl_error(f"sync_player(obj='{name if is_named(model, name) else '(anon)'}' <{obj.oclass.name}:{obj.id}>): Unable to find property \"{model.get_property(name, 'property')}\" in object {label}")
                    st.status = TS_ERROR
            result = _file.read_player(st) if st.fp is not None and st.status != TS_DONE else None
            if result is None:
                if st.loopnum > 0:
                    _file.rewind_player(st)
                    if st.header:
                        _file.read_player(st)
                    st.loopnum -= 1
                    continue
                if st.fp is not None:
                    _file.close_player(st)
                st.status = TS_DONE
                st.next_ts = TS_NEVER
                st.next_ns = 0
                break
            if result[0] in "#\n":
                continue
            match = _SPLIT.match(result)
            if match is None:
                gl_warning(f"player was unable to split input string '{result}'")
                break
            timebuf, value = _trim(match.group(1)), _trim(match.group(2)).lstrip(" ")
            first = _TIMES[0].match(timebuf)
            second = None if first else _TIMES[1].match(timebuf)
            third = None if first or second else _TIMES[2].match(timebuf)
            if first or second:
                groups = (first or second).groups() # type: ignore[union-attr]
                y, m, d, hh = (int(x) for x in groups[:4])
                mm = int(groups[4]) if groups[4] else 0
                ss = float(groups[5]) if groups[5] else 0.0
                tz = groups[6] if first else ""
                if fmt == "US":
                    y, m, d = d, y, m
                elif fmt == "EURO":
                    y, d = d, y
                sec = int(ss)
                nsec = int(1e9*(ss - sec))
                t1 = mktime(model, (y, m, d, hh, mm, sec), tz)
                if t1 != TS_INVALID and st.loop == st.loopnum:
                    st.next_ts = t1
                    st.next_ns = nsec
                    st.next_value = value
            elif third:
                t1 = int(third.group(1))
                t1 *= {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(third.group(2), 1)
                if result[0] == "+":
                    st.next_ts += t1
                    st.next_value = value
                elif st.loop == st.loopnum:
                    st.next_ts = t1
                    st.next_value = value
            elif _TIMES[3].match(timebuf):
                seconds = float(_TIMES[3].match(timebuf).group(1)) # type: ignore[union-attr]
                if st.loop == st.loopnum:
                    st.next_ts = int(seconds)
                    st.next_ns = int(1e9*(seconds - st.next_ts))
                    st.next_value = value
            else:
                gl_warning(f"player was unable to parse timestamp '{result}'")
            break
        return st.next_ts if st.next_ns == 0 else st.next_ts + 1

    @classmethod
    def open(cls, model:Any, name:str, st:PlayerState) -> bool:
        """`player_open()`: open the file"""
        fname = model.get_property(name, "file") or ""
        if fname == "":
            parent = parent_of(model, name) or name
            pobj = model.objects[parent]
            fname = f"{pobj.oclass.name}-{pobj.id}.{model.get_property(name, 'filetype') or ''}"
        if not _file.get_ftable(model.get_property(name, "mode") or "file"):
            return False
        return _file.open_player(st, fname)

    @classmethod
    def presync(cls, model:Any, name:str, t0:int) -> int:
        """`sync_player()`: write the values due at or before `t0`; returns
        the time of the next value"""
        # pylint: disable=too-many-branches
        st = state(model, name)
        t1 = st.next_ts if st.status == TS_OPEN else TS_NEVER
        parent = parent_of(model, name)
        target = parent or name
        if st.status == TS_INIT:
            if st.targets is None and parent is None:
                value = Prop(model, name, "value")
                st.targets = [value] if value.is_valid else None
            if not cls.open(model, name, st):
                gl_error(f"sync_player: Unable to open player file '{model.get_property(name, 'file')}' for object '{name if is_named(model, name) else '(anon)'}'")
            else:
                t1 = cls.read(model, name, st)
        while st.status == TS_OPEN and t1 <= t0 and st.next_ns == 0:
            cls._ensure_targets(model, name, st)
            if st.targets is not None:
                cls.write(model, target, st.targets, st.next_value)
            st.delta_ns, st.delta_ts, st.delta_value = st.next_ns, st.next_ts, st.next_value
            t1 = cls.read(model, name, st)
        if st.targets is not None and st.delta_ts < t0 and st.delta_ns != 0:
            cls.write(model, target, st.targets, st.delta_value)
        if st.next_ns != 0 and st.status == TS_OPEN:
            temp_t = t1
            cls._ensure_targets(model, name, st)
            while st.next_ns != 0 and st.next_ts <= t0:
                if st.targets is not None and st.next_ts < t0:
                    cls.write(model, target, st.targets, st.next_value)
                st.delta_ns, st.delta_ts, st.delta_value = st.next_ns, st.next_ts, st.next_value
                temp_t = cls.read(model, name, st)
            t1 = temp_t
        if st.delta_ts != TS_NEVER and st.delta_ns != 0:
            temp_t = st.delta_ts + 1
            if t0 < temp_t < t1:
                t1 = temp_t
        return t1

    @classmethod
    def _ensure_targets(cls, model:Any, name:str, st:PlayerState) -> None:
        parent = parent_of(model, name)
        if st.targets is None and parent is not None:
            st.targets = cls.link(model, name, st, parent)
        if st.targets is None:
            gl_error(f"sync_player: Unable to find property \"{model.get_property(name, 'property')}\" in object {name if is_named(model, name) else '(anon)'}")
            st.status = TS_ERROR
