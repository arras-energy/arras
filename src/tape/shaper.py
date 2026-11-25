# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Shapers (class `shaper`)

A `shaper` writes a periodic shape, read from a file, into a property of
each object of a group, either directly or as random events.

Syntax
------

    module tape;
    object shaper {
        file "<file>";
        group "<find expression>";
        property "<name>";
        magnitude <decimal>;
        events <decimal>;
    }

Shape files hold blocks of cron-like lines `MINUTE HOUR DAY MONTH
WEEKDAY,VALUE`:

    shape {
        * 0-5 * * *,1.0
        * 6-23 * * *,2.0
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `file` | `char1024` | | shape file |
| `filetype` | `char8` | `txt` | extension of the default file name |
| `mode` | `char32` | `file` | tape mode (only `file` is supported) |
| `group` | `char256` | | objects to shape (find expression) |
| `property` | `char256` | | property to shape (`double`) |
| `magnitude` | `double` | `1.0` | magnitude of a queue event |
| `events` | `double` | `0.0` | queue events per interval (0 shapes directly) |

Description
-----------

A shaper is expected to satisfy:

1. The shape file is read when the shaper first synchronizes (presync).
   Each line gives a value to the hours (0 to 23), days of the month (1 to
   31), months (1 to 12), and weekdays (0 is Sunday) its fields select (`*`, numbers, `A-B` spans that wrap, `;` to end a span); the
   minute field must be `*`. At the `}` of a block the values are scaled
   so the peak is 255, and the shape's scale is `peak/255/sum`.
2. With `events` 0, the property of every object of `group` gets
   `magnitude * shape * scale` for the local hour, and the shaper asks to
   run again at the next hour.
3. With `events` greater than 0, each object accumulates
   `shape * scale * events` per hour and starts events of `magnitude`
   with that probability, lasting `event_size * 3600 * 24 / magnitude`
   seconds, as gridlabd's queue does (random draws from the object's
   seeded generator).
4. Event times are soft events (negative times).

Examples
--------

    >>> import os, tempfile
    >>> from arras import Model, Class, Runner
    >>> Class.reset()
    >>> shape = os.path.join(tempfile.mkdtemp(), "shape.txt")
    >>> with open(shape, "w") as fh:
    ...     _ = fh.write("shape {\\n* 0-11 * * *,1\\n* 12-23 * * *,2\\n}\\n")
    >>> m = Model()
    >>> m.read_glm(f'''clock {{ timezone "UTC"; starttime "2020-01-01 13:00:00"; stoptime "2020-01-01 13:00:00"; }}
    ... module tape;
    ... class load {{ double power; }}
    ... object load {{ name "L"; }}
    ... object shaper {{ file "{shape}"; group "class=load"; property "power"; }}
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> round(float(m.get_property("L", "power")), 6)
    0.666667
    >>> Class.reset()

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A direct shaper (`events` 0) asks to run again at the next hour (the
   intent of gridlabd's commented-out code); gridlabd never sets the time
   of the next change, returns 0, and the run fails.
2. Local time is that of the model's time zone; gridlabd uses the time
   zone of the process (`localtime()`).
3. Months are numbered 1 to 12 and days 1 to 31, as in cron. gridlabd
   uses the file's numbers as array indexes that it reads from 0: its
   month `1` is February (and `12` is lost), its day 0 is never used, and
   it reads past the end of its array for day 31.
4. Random draws come from Python's generator seeded with `randomseed` and
   the object id, so queue events differ from gridlabd's.

References
----------

- `arras-energy/gridlabd`: `module/tape/shaper.cpp`, `tape.h`,
  `module/tape_file/tape_file.cpp`
- [Shaper class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Tape/Shaper.md)
  (`docs/Module/Tape/Shaper.md`)
"""

import random
from typing import Any

from . import _file
from ._aggregate import find_group
from ._base import TapeClass, prop
from ._common import (TS_NEVER, TS_INIT, TS_OPEN, TS_DONE, TRL_QUALIFIED, Prop, TapeError,
    gl_error, gl_warning, get_state, set_state, localtime, parent_of, to_double, fmt)

class ShaperState: # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """State of a shaper between handler calls (gridlabd `struct shaper`)"""

    def __init__(self, model:Any, name:str):
        self.status = TS_INIT
        self.lasterr = ""
        self.shape: dict[tuple[int,int,int,int],int] = {}
        self.scale = 1.0
        self.step = 3600
        self.interval = 24
        self.magnitude = to_double(model.get_property(name, "magnitude") or "1")
        self.events = to_double(model.get_property(name, "events") or "0")
        self.targets: list[dict[str,Any]]|None = None
        seed = int(model.globals.getvalue("randomseed") or 0)
        self.rng = random.Random(seed*1000003 + model.objects[name].id)

def state(model:Any, name:str) -> ShaperState:
    """State of a shaper, created on first use"""
    st = get_state(model, name)
    if st is None:
        st = ShaperState(model, name)
        set_state(model, name, st)
    return st

class Shaper(TapeClass):
    """Class `shaper`; see the module documentation"""

    NAME = "shaper"
    PASSCONFIG = "PRETOPDOWN"
    TRL = TRL_QUALIFIED
    PROPERTIES = (
        ("file", "char1024", prop()),
        ("filetype", "char8", prop(default="txt")),
        ("mode", "char32", prop(default="file")),
        ("group", "char256", prop()),
        ("property", "char256", prop()),
        ("magnitude", "double", prop(default="1.0")),
        ("events", "double", prop(default="0.0")),
    )
    EVENTS = ("presync",)

    @classmethod
    def open(cls, model:Any, name:str, st:ShaperState) -> bool:
        """`shaper_open()`: read the shape file"""
        fname = model.get_property(name, "file") or ""
        if fname == "":
            pobj = model.objects[parent_of(model, name) or name]
            fname = f"{pobj.oclass.name}-{pobj.id}.{model.get_property(name, 'filetype') or ''}"
        if not _file.get_ftable(model.get_property(name, "mode") or "file"):
            return False
        if _file.open_shaper(st, fname):
            return True
        gl_error(st.lasterr or "unknown error")
        return False

    @staticmethod
    def _shape(model:Any, st:ShaperState, t0:int) -> int:
        local = localtime(model, t0)
        return st.shape.get((local.month, local.day, (local.weekday() + 1) % 7, local.hour), 0)

    @classmethod
    def read(cls, model:Any, st:ShaperState, t0:int, target:dict[str,Any]) -> int:
        """`shaper_read()`: the value for the hour of `t0`; returns the time
        of the next change"""
        shape = cls._shape(model, st, t0)
        if st.events <= 0:
            target["value"] = st.magnitude * shape * st.scale
            target["ts"] = (t0 // st.step + 1) * st.step
        else:
            target["value"] += shape * st.scale * st.events
            target["ts"] = t0 + int(st.rng.uniform(0, st.step))
        return target["ts"]

    @classmethod
    def update(cls, model:Any, st:ShaperState, t0:int, target:dict[str,Any]) -> int:
        """`shaper_update()`: write the value or start or end an event;
        returns the time the event ends, or `TS_NEVER`"""
        t1 = TS_NEVER
        current = target["prop"].double()
        if st.events <= 0:
            target["prop"].set(fmt(target["value"]))
        elif current == 0 and st.rng.random() < target["value"]:
            size = st.rng.uniform(0, 1)
            target["prop"].set(fmt(st.magnitude))
            t1 = target["ts"] = t0 + int(size*st.step*st.interval/st.magnitude)
            target["value"] -= size
        elif current != 0 and t0 == target["ts"]:
            t1 = cls.read(model, st, t0, target)
            target["prop"].set("0")
        return t1

    @classmethod
    def presync(cls, model:Any, name:str, t0:int) -> int:
        """`sync_shaper()`: shape the targets; returns the next change as a
        soft event"""
        # pylint: disable=too-many-branches
        st = state(model, name)
        t1 = TS_NEVER
        if st.status == TS_INIT:
            if not cls.open(model, name, st):
                st.status = TS_DONE
        group = model.get_property(name, "group") or ""
        pname = model.get_property(name, "property") or ""
        if st.status == TS_OPEN:
            if st.targets is None and group:
                try:
                    members = find_group(model, group)
                except TapeError:
                    members = []
                if not members:
                    gl_warning(f"shaper group '{group}' is empty")
                    st.status = TS_DONE
                    return TS_NEVER
                st.targets = []
                obj = model.objects[name]
                for member in members:
                    target = Prop(model, member, pname)
                    if not target.is_valid:
                        mobj = model.objects[member]
                        gl_error(f"object {obj.oclass.name}:{obj.id} property {pname} not found in object {mobj.oclass.name}:{mobj.id}")
                    elif target.ptype != "double":
                        mobj = model.objects[member]
                        gl_warning(f"object {mobj.oclass.name}:{mobj.id} property {pname} is not a double")
                    else:
                        item = {"prop": target, "ts": 0, "value": 0.0}
                        st.targets.append(item)
                        t1 = min(t1, cls.read(model, st, t0, item))
                        if st.events <= 0:
                            cls.update(model, st, t0, item)
            for item in st.targets or []:
                tn = TS_NEVER
                if item["ts"] == t0 and st.events <= 0:
                    tn = cls.read(model, st, t0, item)
                    cls.update(model, st, t0, item)
                elif item["ts"] == t0:
                    tn = cls.update(model, st, t0, item)
                    if tn == TS_NEVER:
                        tn = cls.read(model, st, t0, item)
                elif item["ts"] < t1:
                    tn = item["ts"]
                t1 = min(t1, tn)
        if t1 == 0:
            obj = model.objects[name]
            gl_error(f"shaper:{obj.id} will return t1==0 ~ check the shaper's target property, \"{pname}\"")
        return -t1 if t1 != TS_NEVER else TS_NEVER
