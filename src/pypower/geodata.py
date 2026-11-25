# pylint: disable=line-too-long
"""Class `geodata`: values by location played into objects

Syntax
------

    object pypower.geodata {
        file "<file>";
        target "<class>::<property>|<object>.<property>[,...]";
        scale <real> pu;
    }

Description
-----------

A geodata object reads a CSV file whose header is `timestamp` followed by
geohash codes (one column per location) and whose rows are a timestamp
and one number per location, and writes the values times `scale` to the
target properties of the objects nearest each location. Given a model, a
geodata object is expected to:

1. read the file at initialization, keeping the rows from `starttime` to
   `stoptime` (rows before `starttime` are skipped; the first row after
   `stoptime` ends the read), and refuse a file that is missing, whose
   first column is not `timestamp`, that has a geohash that is not valid
   (trailing characters that are not geohash digits are removed first), a
   timestamp or number that is not valid, or a row with missing or extra
   values;
2. refuse an empty `target`, and take each comma-separated target:
   `CLASS::PROPERTY` for every object of the pypower class `CLASS`, or
   `OBJECT.PROPERTY` for one object; objects without `latitude` and
   `longitude` are skipped with a warning; a property that is not found is
   an error; a target property that is an output gets a warning;
3. attach each target to the nearest location (by squared
   latitude-longitude difference); a target named twice is attached once,
   with a warning;
4. at each precommit, move to the first row at or after the clock, write
   its values times `scale` to the targets, and ask to run again at the
   time of that row (no event after the last row).

Caveats
-------

- The values are written as numbers in the target property's unit; a
  `complex` target gets the value as its real part, as gridlabd writes the
  double to the property's address.
- `CLASS::PROPERTY` targets only pypower classes, as gridlabd's search of
  the module's classes does.

References
----------

- `arras-energy/gridlabd`: `module/pypower/geodata.cpp`, `geodata.h`
"""

import re
import math
from typing import Any

from ._base import PypowerClass, prop, msg
from ._common import (TS_NEVER, MODULE, object_state, get_double, get_complex, get_text, set_double,
    set_complex, isa, notation)
from ._module import ensure_init
from ._weather import parse_time

GEOCODE_DIGITS = "0123456789bcdefghjkmnpqrstuvwxyz"
"""Geohash digits"""

def geocode_decode(code:str) -> tuple[float,float]|None:
    """Latitude and longitude of the center of a geohash cell, or `None`
    when the code has a character that is not a geohash digit"""
    lat_interval, lon_interval = [-90.0, 90.0], [-180.0, 180.0]
    is_even = True
    for char in code:
        digit = GEOCODE_DIGITS.find(char.lower())
        if digit < 0:
            return None
        for mask in (16, 8, 4, 2, 1):
            interval = lon_interval if is_even else lat_interval
            interval[0 if digit & mask else 1] = (interval[0] + interval[1])/2
            is_even = not is_even
    return (lat_interval[0] + lat_interval[1])/2, (lon_interval[0] + lon_interval[1])/2

def _strip(code:str) -> str:
    """The code without trailing characters that are not geohash digits"""
    while code and code[-1] not in GEOCODE_DIGITS:
        code = code[:-1]
    return code

class Geodata(PypowerClass):
    """Behavior of class `geodata`"""

    NAME = "geodata"
    PROPERTIES = (
        ("file", "char1024", prop("geodata file name")),
        ("target", "char1024", prop("geodata target class and property, e.g., CLASS::PROPERTY or OBJECT.PROPERTY")),
        ("scale[pu]", "double", prop("scale to apply to geodata values in file before writing to target", "1 pu")),
    )
    EVENTS = ("init", "precommit")

    @classmethod
    def state(cls, model:Any, name:str) -> dict[str,Any]:
        """State of a geodata object: `locations` (dicts of `hash`,
        `latitude`, `longitude`, `values`: target `(object, property)`
        pairs), `data` (`(timestamp, values)` rows), `cur` (row in use)"""
        return object_state(model, name, lambda: {"locations": [], "data": [], "cur": 0})

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`geodata::init()`"""
        # pylint: disable=too-many-return-statements,too-many-branches
        if not ensure_init(model):
            return False
        out = msg(model, name)
        file = get_text(model, name, "file")
        if not cls._load(model, name, file):
            out.error(f"unable to load geodata file '{file}'")
            return False
        target = get_text(model, name, "target")
        if not target:
            out.error("target is not specified")
            return False
        for item in [x for x in target.split(",") if x]:
            match = re.fullmatch(r"([^:]+)::(.+)", item, re.DOTALL)
            if match:
                classname, propname = match.groups()
                if not any(c.name == classname and c.module == MODULE for c in _classes()):
                    out.error(f"class '{classname}' is not valid")
                    return False
                for obj, value in model.objects.items():
                    if value.oclass.name != classname or value.oclass.module != MODULE:
                        continue
                    if _located(model, obj):
                        if not cls._add_target(model, name, obj, propname):
                            out.error(f"unable to find property '{propname}' in object '{obj}'")
                            return False
                    else:
                        out.warning(f"object '{obj}' does not have any geodata to locate it")
                continue
            match = re.fullmatch(r"([^.]+)\.(.+)", item, re.DOTALL)
            if not match:
                out.error(f"target '{item}' is not valid")
                return False
            objname, propname = match.groups()
            if objname not in model.objects:
                out.error(f"object '{objname}' not found")
                return False
            if _located(model, objname):
                if not cls._add_target(model, name, objname, propname):
                    out.error(f"unable to find property '{propname}' in object '{objname}'")
                    return False
            else:
                out.warning(f"object '{objname}' does not have any geodata to locate it")
        return True

    @classmethod
    def _add_target(cls, model:Any, name:str, obj:str, propname:str) -> bool:
        """`geodata::add_target()`"""
        out = msg(model, name)
        spec = model.objects[obj].oclass.find_property(propname)
        if spec is None:
            return False
        if spec.has_flag("OUTPUT"):
            out.warning(f"writing to '{obj}' output '{propname}' may not work as expected")
        location = cls._find_location(model, name, _coord(model, obj, "latitude"), _coord(model, obj, "longitude"))
        if location is None:
            out.warning(f"ignoring object '{obj}', location cannot be found in geodata file")
            return True
        values = cls.state(model, name)["locations"][location]["values"]
        if (obj, propname) in values:
            out.warning(f"ignoring duplicate reference to object '{obj}.{propname}'")
            return True
        values.append((obj, propname))
        return True

    @classmethod
    def _find_location(cls, model:Any, name:str, lat:float, lon:float) -> int|None:
        """`geodata::find_location(lat, lon)`: the nearest location"""
        best, best_d2 = None, 0.0
        for n, loc in enumerate(cls.state(model, name)["locations"]):
            d2 = (loc["latitude"] - lat)**2 + (loc["longitude"] - lon)**2
            if best is None or d2 < best_d2:
                best, best_d2 = n, d2
        return best

    @classmethod
    def _load(cls, model:Any, name:str, file:str) -> bool:
        """`geodata::load_geodata()`"""
        # pylint: disable=too-many-return-statements,too-many-branches,too-many-locals
        out = msg(model, name)
        state = cls.state(model, name)
        try:
            fh = open(file, "r", encoding="utf-8", errors="replace") # pylint: disable=consider-using-with
        except OSError:
            out.error(f"file '{file}' is not {'specified' if not file else 'found'}")
            return False
        start = int(model.globals.getvalue("starttime"))
        stop = model.globals.getvalue("stoptime")
        stop = int(stop) if stop not in (None, 0) else TS_NEVER
        with fh:
            for line_no, line in enumerate(fh):
                tokens = [x for x in re.split(",+", line) if x]
                if not state["locations"]:
                    if not tokens or tokens[0] != "timestamp":
                        out.error(f"column 0 must be 'timestamp', but found '{tokens[0] if tokens else ''}' instead")
                        return False
                    for token in tokens[1:]:
                        code = _strip(token)
                        position = geocode_decode(code)
                        if position is None:
                            out.error(f"geocode '{code}' is not valid")
                            return False
                        state["locations"].append({"hash": code[:15], "latitude": position[0],
                            "longitude": position[1], "values": []})
                    continue
                if not tokens:
                    continue
                stamp = parse_time(model, tokens[0])
                if stamp is None:
                    out.error(f"({file}:{line_no}) invalid timestamp '{tokens[0]}'")
                    return False
                if stamp < start:
                    continue
                if stamp > stop:
                    return True
                values = []
                for token in tokens[1:]:
                    if len(values) >= len(state["locations"]):
                        out.error(f"({file}:{line_no}) unexpected extra data (location {len(values)} > n_locations {len(state['locations'])})")
                        return False
                    match = re.match(r"\s*([-+]?(?:(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|inf(?:inity)?|nan))", token, re.IGNORECASE)
                    if match is None:
                        out.error(f"({file}:{line_no}) invalid float value '{token}'")
                        return False
                    values.append(float(match.group(1)))
                if len(values) != len(state["locations"]):
                    out.error(f"({file}:{line_no}) missing data (location {len(values)} < n_locations {len(state['locations'])})")
                    return False
                state["data"].append((stamp, values))
        return True

    @classmethod
    def precommit(cls, model:Any, name:str, t:int) -> int:
        """`geodata::precommit()`: write the values of the row at or after
        the clock"""
        state = cls.state(model, name)
        data = state["data"]
        def get_time() -> int:
            return data[state["cur"]][0] if state["cur"] < len(data) else TS_NEVER
        if t == TS_NEVER:
            state["cur"] = len(data)
        else:
            while get_time() < t and state["cur"] < len(data):
                state["cur"] += 1
            if get_time() != TS_NEVER:
                scale = get_double(model, name, "scale")
                values = data[state["cur"]][1]
                for n, loc in enumerate(state["locations"]):
                    for obj, propname in loc["values"]:
                        _write(model, obj, propname, values[n]*scale)
        return get_time()

def _write(model:Any, obj:str, propname:str, value:float) -> None:
    """Write a double to a target as gridlabd writes it to the property's
    address (the real part of a `complex`)"""
    spec = model.objects[obj].oclass.find_property(propname)
    if spec is not None and spec.ptype == "complex":
        set_complex(model, obj, propname, complex(value, get_complex(model, obj, propname).imag), notation(model, obj, propname))
    else:
        set_double(model, obj, propname, value)

def _classes() -> list[Any]:
    from arras.oclass import Class # pylint: disable=import-outside-toplevel
    return list(Class.registry)

def _coord(model:Any, obj:str, prop_:str) -> float:
    value = model.objects[obj].get(prop_)
    try:
        return float(value) if value not in (None, "") else float("nan")
    except ValueError:
        return float("nan")

def _located(model:Any, obj:str) -> bool:
    """`True` when the object has a latitude and a longitude"""
    lat, lon = _coord(model, obj, "latitude"), _coord(model, obj, "longitude")
    return not (math.isnan(lat) or math.isnan(lon))

def is_target(model:Any, name:str) -> bool:
    """`True` for a pypower geodata object"""
    return isa(model, name, "geodata")
