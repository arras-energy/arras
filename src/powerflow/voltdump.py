# pylint: disable=line-too-long
"""Class `voltdump`: dump of the node voltages to a CSV file

Syntax
------

    object voltdump {
        filename "<file>";
        group "<groupid>";          // all nodes when empty
        runtime <timestamp>;        // NEVER: the first time step
        interval <real> s;          // 0: at runtime only
        maxcount <integer>;
        mode {rect,polar};
        filemode "<w|a>";
        version {1,2};
    }

Output: `runcount`, the number of dumps written.

Description
-----------

A `voltdump` writes the voltages of the powerflow nodes (of group
`group`, when it is set) to `filename`, as gridlabd's `voltdump` does,
when a time step is committed (gridlabd's `commit()`):

- with `interval` 0, at the first committed time at or after `runtime`
  (any time when it is `NEVER`; `runtime` 0 means the first time), until
  it has written `maxcount` dumps (1 by default; negative for no limit);
  its sync asks for an event at `runtime`;
- with `interval` positive, at each committed time that is a multiple of
  `interval`, its sync asking for an event at the next one, until it has
  written `maxcount` dumps (0, the default, for no limit).

Each dump opens the file with `filemode` (`w` by default with no
interval, `a` with one): version 2 (the default) writes the header
`node_name,datetime,voltA_real,...` and a row per node with its name, the
time, and its three voltages (the node's `voltage_A`, `_B`, `_C`, or
`voltage_1`, `_2`, `_N` of a triplex node) as real and imaginary parts
(`rect`) or magnitudes and angles in radians (`polar`), with six
decimals; version 1 writes the comment `# <file> run at <time> on <n>
nodes` and the header without `datetime`, and rows without the time.

When it initializes, a voltdump deletes `filename`, fails on a negative
`interval`, and reports an error for a `version` other than 0, 1, or 2
(0 means 2).

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. With an interval, the dumps stop after `maxcount` of them; gridlabd
   goes on dumping at any committed multiple of the interval.
2. With an interval, the sync asks for an event at the next multiple, so
   the dumps happen on their own; gridlabd returns the next multiple from
   `commit()`, whose result does not schedule events (`commit_all()`), so
   its interval dumps happen only when other objects have events at the
   multiples.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/voltdump.cpp`, `voltdump.h`
"""

import cmath
import os
from typing import Any, Iterable

from ._base import PowerflowClass, prop, keywords
from ._common import TS_NEVER, isa, msg, object_state, get_int, get_double, get_complex, set_int, gl_error

RECT, POLAR = 0, 1
"""`mode` values"""

def runtime_of(model:Any, name:str) -> int:
    """The `runtime` timestamp of a dump object"""
    text = str(model.get_property(name, "runtime") or "NEVER")
    try:
        return int(model.globals.timestamp_from_string(text))
    except Exception: # pylint: disable=broad-exception-caught
        return TS_NEVER if text.strip().strip("'\"").upper() in ("NEVER", "") else int(float(text))

def powerflow_objects(model:Any, group:str) -> list[str]:
    """Names of the powerflow objects (of a group, when it is set), in
    creation order (gridlabd `gl_find_objects()`)"""
    result = []
    for name, obj in model.objects.items():
        module = getattr(obj.oclass, "module", None)
        if str(getattr(module, "name", module)) != "powerflow":
            continue
        if group and str(obj.get("groupid") or "").strip('"') != group:
            continue
        result.append(name)
    return result

class Dump(PowerflowClass):
    """Behavior shared by `voltdump` and `currdump`"""

    PASSCONFIG = "BOTTOMUP|AUTOLOCK"
    EVENTS = ("init", "sync", "commit")
    KIND = "node"
    """The objects dumped"""
    COLUMNS = ("volt", "node_name")
    """Column prefix and name column"""
    WHAT = "voltage"
    MODES = ("rect", "polar")

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`init()`: delete the file, defaults by interval, the version"""
        filename = str(model.get_property(name, "filename") or "").strip('"')
        if filename and os.path.exists(filename):
            os.unlink(filename)
        interval = get_double(model, name, "interval")
        filemode = str(model.get_property(name, "filemode") or "").strip('"')
        if interval < 0:
            gl_error("negative interval is not permitted")
            return False
        if interval > 0:
            if get_int(model, name, "maxcount") < 0:
                set_int(model, name, "maxcount", 0)
            model.objects[name]["filemode"] = filemode or "a"
            model.objects[name]["runtime"] = "NEVER"
        else:
            if get_int(model, name, "maxcount") < 0:
                set_int(model, name, "maxcount", 1)
            model.objects[name]["filemode"] = filemode or "w"
        version = get_int(model, name, "version")
        if version < 0 or version > 2:
            gl_error(f"format version {version} is invalid")
        elif version == 0:
            set_int(model, name, "version", 2)
        object_state(model, name)["interval"] = interval
        return True

    @classmethod
    def sync(cls, model:Any, name:str, t:int) -> int:
        """`sync()`: an event at `runtime`, or with an interval at its next
        multiple while dumps remain"""
        interval = object_state(model, name).get("interval", 0.0)
        if interval > 0:
            maxcount = get_int(model, name, "maxcount")
            if 0 < maxcount <= get_int(model, name, "runcount"):
                return TS_NEVER
            return (t//int(interval) + 1)*int(interval)
        runtime = runtime_of(model, name)
        return runtime if runtime > t else TS_NEVER

    @classmethod
    def values(cls, model:Any, name:str) -> list[complex]:
        """The three values dumped for an object"""
        from ._module import behavior # pylint: disable=import-outside-toplevel
        return [get_complex(model, name, prop_) for prop_ in behavior(model, name).VOLTAGES]

    @classmethod
    def dump(cls, model:Any, name:str, t:int) -> None:
        """`dump()`"""
        out = msg(model, name)
        group = str(model.get_property(name, "group") or "").strip('"')
        found = powerflow_objects(model, group)
        if not found:
            out.warning(f"no {cls.KIND}s were found to dump")
            return
        filename = str(model.get_property(name, "filename") or "").strip('"')
        filemode = str(model.get_property(name, "filemode") or "w").strip('"')
        if filemode == "a":
            out.verbose(f"{cls.NAME} is appending data to {filename}")
        try:
            outfile = open(filename, filemode, encoding="utf-8") # pylint: disable=consider-using-with
        except OSError:
            gl_error(f"{cls.NAME} unable to open {filename} for output")
            return
        items = [x for x in found if isa(model, x, cls.KIND)]
        timestr = model.globals.timestamp_to_string(t)
        prefix, label = cls.COLUMNS
        with outfile:
            if get_int(model, name, "version") < 2:
                outfile.write(f"# {filename} run at {timestr} on {len(items)} {cls.KIND}s\n{label},")
            else:
                outfile.write(f"{label},datetime,")
            polar = get_int(model, name, "mode") == POLAR
            parts = ("mag", "angle") if polar else ("real", "imag")
            outfile.write(",".join(f"{prefix}{x}_{p}" for x in "ABC" for p in parts) + "\n")
            for item in items:
                row = [item]
                if get_int(model, name, "version") > 1:
                    row.append(timestr)
                for value in cls.values(model, item):
                    row += [f"{abs(value):f}", f"{cmath.phase(value):f}"] if polar else [f"{value.real:f}", f"{value.imag:f}"]
                outfile.write(",".join(row) + "\n")

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int:
        """`commit()`"""
        state = object_state(model, name)
        interval = state.get("interval", 0.0)
        count, maxcount = get_int(model, name, "runcount"), get_int(model, name, "maxcount")
        if interval != 0:
            dt = int(interval)
            if t % dt == 0 and (maxcount <= 0 or count < maxcount):
                cls.dump(model, name, t)
                count += 1
                set_int(model, name, "runcount", count)
            return TS_NEVER if 0 < maxcount <= count else (t//dt + 1)*dt
        runtime = runtime_of(model, name)
        if runtime == 0:
            model.objects[name]["runtime"] = model.globals.timestamp_to_string(t)
            runtime = t
        if (t >= runtime or runtime == TS_NEVER) and (count < maxcount or maxcount < 0):
            cls.dump(model, name, t)
            set_int(model, name, "runcount", count + 1)
        return TS_NEVER

def dump_properties(what:str, kind:str, mode_keywords:Iterable[str], mode_default:str, maxcount:str, filemode:str) -> tuple: # pylint: disable=too-many-arguments,too-many-positional-arguments
    """The properties of `voltdump` and `currdump`"""
    rect, polar = mode_keywords
    return (
        ("group", "char32", prop(f"the group ID to output data for (all {kind}s if empty)")),
        ("runtime", "timestamp", prop(f"the time to check {what} data", "NEVER")),
        ("filename", "char256", prop(f"the file to dump the {what} data into", flags="REQUIRED")),
        ("runcount", "int32", prop("the number of times the file has been written to", "0", access="REFERENCE")),
        ("maxcount", "int32", prop("the maximum number of times the file is written", maxcount)),
        ("mode", "enumeration", prop(f"dumps the {what}s in either polar or rectangular notation", mode_default,
            keywords=keywords((rect, RECT), (polar, POLAR)))),
        ("filemode", "char8", prop("sets the file write mode", filemode)),
        ("version", "int32", prop("dump format version", "0")),
        ("interval[s]", "double", prop(f"interval at which {kind.replace('node', 'volt').replace('link', 'curr')}dump runs", "0 s")),
    )

class VoltDump(Dump):
    """Behavior of class `voltdump`"""

    NAME = "voltdump"
    TRL = 9 # TRL_PROVEN
    PROPERTIES = dump_properties("voltage", "node", ("rect", "polar"), "rect", "-1", "")

__all__ = ["VoltDump", "Dump", "powerflow_objects", "runtime_of"]
