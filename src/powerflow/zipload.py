# pylint: disable=line-too-long
"""Class `zipload`: a load whose ZIP components follow the weather and a schedule

Syntax
------

    object zipload {
        phases {A,B,C}[D|N];
        nominal_voltage <real> V;
        weather <climate object>;
        Theat <real> degF;            // heating and cooling balance points
        Tcool <real> degF;
        Pz <real> W;                  // constant terms, and the _H, _C, _S,
        Qz <real> VAr;                //   _W, _R sensitivities, of the
        Pi <real> W;                  //   impedance (z), current (i), and
        Qi <real> VAr;                //   power (p) real and reactive parts
        Pp <real> W;
        Qp <real> VAr;
        scalar <real> pu.W;
        schedule "<months> <days> <hours> <value>;...";
        load_class {U,R,C,I,A,T,P};   // with load_type: parameters from
        load_type <string>;           //   powerflow::zipload_data
        // and the other properties of load
    }

Description
-----------

A `zipload` is a `load` (gridlabd `PT_INHERIT "load"`) whose ZIP form
(`base_power_X`, `X_fraction_X`, `X_pf_X`) is computed before each
solution, as gridlabd's `zipload::sync()` does:

- the inputs are the heating degrees `H = max(Theat - T, 0)` and cooling
  degrees `C = max(T - Tcool, 0)` of the weather object's temperature
  `T`, its solar flux `S`, wind speed `W`, and rainfall `R` (properties
  named by the globals `powerflow::zipload_temperature` ... `_rain`, with
  an optional `[unit]`), and 1 for the constant terms; without a weather
  object the inputs stay as set;
- the impedance, current, and power parts are the sums of the
  sensitivities times the inputs, scaled by `scalar` and by the schedule
  value of the hour (month 1-12, day 1-7 Sunday to Saturday and 8 for
  holidays, hour 1-24 for the hour starting at 0:00 to 23:00, `*` for all,
  ranges `a-b` wrapping when `b < a`, lists `a,b`) divided by 3 (one third
  on each phase); they are published as `Z`, `I`, `P` (complex powers);
- each phase's `base_power_X` is the magnitude of their sum when the
  phase's voltage is within `powerflow::maximum_voltage_deviation` (per
  unit of `nominal_voltage`) of nominal, else 0; the fractions are their
  magnitudes over it, and the power factors their real parts over their
  magnitudes, negative when their reactive part is not positive.

With `load_class` (not `U`) and `load_type` set, the sensitivities, balance
points, and schedule are read at initialization from the CSV file
`powerflow::zipload_data` (columns `geocode`, `load_class`, `load_type`,
`Theat`, `Tcool`, `Pz_H` ... `Qp`, `schedule`), for the object's (or its
nearest parent's) geohash of `powerflow::geocode_find` characters (the
nearest geohash in the file when it is 0, no geohash when it is negative,
the file's empty geohash when it is not in the file).

When it initializes, a zipload is expected to link its weather object
(an error for each missing property), build its schedule, read its load
data, then initialize as a `load`.

Caveats
-------

- The schedule uses the model's local time (`timezone_locale`).

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The voltage check is in per unit of `nominal_voltage`; gridlabd
   compares the voltage in volts less 1 with the per-unit deviation, so
   its zipload has no base power at any realistic voltage.
2. A schedule list or range is the set of values it names; gridlabd's
   parser skips a range that does not start right after the previous
   value (`9-17` alone names nothing).
3. An invalid schedule or a missing load data row fails the
   initialization; gridlabd writes the error and goes on with a partial
   schedule (or throws from the table lookup).
4. The nearest geohash is the nearest by great-circle distance; gridlabd
   passes degrees to `cos()`.
5. A zero total (no load) gives no base power; gridlabd divides by it.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/zipload.cpp`, `zipload.h`
"""

import csv
import math
import os
from typing import Any

from ._base import prop
from ._common import g, msg, ref, object_state, get_int, get_double, get_complex, get_text, set_complex, set_double, text_to_double, PowerflowError
from .load import Load

TRL_PROTOTYPE = 7
"""Technology readiness level `TRL_PROTOTYPE`"""

INPUTS = ("H", "C", "S", "W", "R")
"""Weather inputs: heating and cooling degrees, solar, wind, rain"""

PARTS = (("z", "p", "Pz", "W"), ("z", "q", "Qz", "VAr"), ("i", "p", "Pi", "W"), ("i", "q", "Qi", "VAr"), ("p", "p", "Pp", "W"), ("p", "q", "Qp", "VAr"))
"""ZIP parts: component, real or reactive, property prefix, unit"""

SENSITIVITY_UNITS = {
    "Pz": ("W/degF", "W/degF", "m^2", "W/mph", "W*h/in", "W"), "Qz": ("VAr/degF", "VAr/degF", "VAr*h/Btu", "VAr/mph", "VAr*h/in", "VAr"),
    "Pi": ("W/degF", "W/degF", "m^2", "W/mph", "W*h/in", "W"), "Qi": ("VAr/degF", "VAr/degF", "m^2", "VAr/mph", "VAr*h/in", "VAr"),
    "Pp": ("W/degF", "W/degF", "m^2", "W/mph", "W*h/in", "W"), "Qp": ("VAr/degF", "VAr/degF", "m^2", "VAr/mph", "VAr*h/in", "VAr"),
}
"""Units gridlabd publishes for the sensitivities `_H`, `_C`, `_S`, `_W`,
`_R` and the constant term (kept as published)"""

def zip_properties() -> tuple:
    """The properties gridlabd's `zipload` and `triplex_zipload` publish"""
    result = [("load_type", "char32", prop("load type for zipload load parameter look-up")),
        ("weather", "object", prop()),
        ("Theat[degF]", "double", prop(default="60 degF")),
        ("Tcool[degF]", "double", prop(default="70 degF"))]
    for _, _, name, _ in PARTS:
        for suffix, unit in zip(("_H", "_C", "_S", "_W", "_R", ""), SENSITIVITY_UNITS[name]):
            result.append((f"{name}{suffix}[{unit}]", "double", prop()))
    result.append(("scalar[pu.W]", "double", prop(default="1 pu.W")))
    for name, unit in zip(INPUTS, ("degF", "degF", "kW", "mph", "in/h")):
        result.append((f"{name}[{unit}]", "double", prop(access="REFERENCE")))
    for name, unit in (("Z", "ohm"), ("I", "A"), ("P", "VA")):
        result.append((f"{name}[{unit}]", "complex", prop(access="REFERENCE")))
    result.append(("schedule", "char1024", prop(default="* * * 1.0;")))
    return tuple(result)

def schedule_values(field:str, low:int, high:int, entry:str, kind:str) -> list[int]:
    """Values named by a schedule field: `*`, numbers, ranges (wrapping
    when the end is before the start), comma lists; raises
    `PowerflowError`"""
    if field == "*":
        return list(range(low, high + 1))
    values = []
    for token in field.split(","):
        try:
            if "-" in token:
                first, last = (int(x) for x in token.split("-", 1))
                values += list(range(first, last + 1)) if first <= last else list(range(first, high + 1)) + list(range(low, last + 1))
            else:
                values.append(int(token))
        except ValueError as err:
            raise PowerflowError(f"schedule '{entry}' is not valid") from err
    for value in values:
        if not low <= value <= high:
            raise PowerflowError(f"invalid {kind} in schedule '{entry}'")
    return values

def build_schedule(text:str) -> list[list[list[float]]]:
    """Schedule values `[month][day][hour]` (0-based) of a schedule text;
    raises `PowerflowError`"""
    scale = [[[0.0]*24 for _ in range(8)] for _ in range(12)]
    for entry in (x.strip() for x in text.split(";")):
        if not entry:
            continue
        fields = entry.split(None, 4)
        try:
            months, days, hours, value = fields[0], fields[1], fields[2], float(fields[3])
        except (IndexError, ValueError) as err:
            raise PowerflowError(f"schedule '{entry}' is not valid") from err
        for hour in schedule_values(hours, 1, 24, entry, "hour"):
            for day in schedule_values(days, 1, 8, entry, "day"):
                for month in schedule_values(months, 1, 12, entry, "month"):
                    scale[month-1][day-1][hour-1] = value
    return scale

def _distance(a:tuple[float,float], b:tuple[float,float]) -> float:
    lat1, lon1, lat2, lon2 = (math.radians(x) for x in (*a, *b))
    return math.sin((lat2 - lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2 - lon1)/2)**2

class ZipModel:
    """Weather, schedule, and load data of `zipload` and `triplex_zipload`
    (mixed into their behavior classes)"""

    DIVISOR = 3.0
    """Divisor of the schedule value"""

    @classmethod
    def zip_init(cls, model:Any, name:str) -> None:
        """`init()` before the load's: weather, schedule, load data"""
        state = object_state(model, name)
        weather = ref(model, name, "weather")
        names = {}
        if weather is not None:
            for key in ("temperature", "humidity", "solar", "wind", "rain"):
                spec = str(g(model, f"zipload_{key}") or "")
                prop_, _, unit = spec.partition("[")
                if model.objects[weather].oclass.find_property(prop_):
                    names[key] = (prop_, unit.rstrip("]") or None)
                else:
                    msg(model, name).error(f"unable to find '{spec}' property in weather object")
        if get_int(model, name, "load_class") != 0 and get_text(model, name, "load_type"):
            cls.read_loadtype(model, name)
        state.update(weather=weather, weather_names=names, scale=build_schedule(get_text(model, name, "schedule") or ""))

    @classmethod
    def read_loadtype(cls, model:Any, name:str) -> None:
        """The parameters of the object's load class and type from the load
        data file (gridlabd `read_loadtype()`); raises `PowerflowError`"""
        # pylint: disable=too-many-locals
        path = str(g(model, "zipload_data") or "ziploads.csv")
        if not os.path.exists(path):
            raise PowerflowError(f"zipload data file '{path}' not found")
        with open(path, newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))
        resolution = int(g(model, "geocode_find") or 0)
        code = ""
        if resolution >= 0:
            code = cls.geocode(model, name, resolution if resolution > 0 else 12)
            codes = {row.get("geocode", "")[:resolution] if resolution > 0 else row.get("geocode", "") for row in rows}
            if resolution == 0:
                code = cls.nearest(code, codes)
            elif code not in codes:
                msg(model, name).warning(f"geocode [{code}] not found in {path}, using default load data for null geocode")
                code = ""
        load_class = model.get_property(name, "load_class")
        load_type = get_text(model, name, "load_type")
        for row in rows:
            row_code = row.get("geocode", "")
            row_code = row_code[:resolution] if resolution > 0 else row_code
            if row_code == code and row.get("load_class") == load_class and row.get("load_type") == load_type:
                break
        else:
            raise PowerflowError(f"no load data for geocode '{code}', load_class '{load_class}', load_type '{load_type}' in {path}")
        def value(key:str) -> float:
            return text_to_double(row.get(key) or "0")
        set_double(model, name, "Theat", value("Theat"))
        set_double(model, name, "Tcool", value("Tcool"))
        for _, _, prefix, _ in PARTS:
            for suffix in ("_H", "_C", "_S", "_W", "_R", ""):
                set_double(model, name, f"{prefix}{suffix}", value(f"{prefix}{suffix}"))
        model.objects[name]["schedule"] = row.get("schedule") or ""

    @classmethod
    def geocode(cls, model:Any, name:str, resolution:int) -> str:
        """Geohash of the object or its nearest parent with a location"""
        from arras.globals import geocode_encode # pylint: disable=import-outside-toplevel
        current: str|None = name
        while current is not None:
            lat, lon = (model.objects[current].get(key) for key in ("latitude", "longitude"))
            try:
                return geocode_encode(float(lat), float(lon), resolution)
            except (TypeError, ValueError):
                current = ref(model, current, "parent")
        return ""

    @classmethod
    def nearest(cls, code:str, codes:set[str]) -> str:
        """The geohash in `codes` nearest to `code`"""
        from arras.globals import geocode_decode # pylint: disable=import-outside-toplevel
        origin = geocode_decode(code) if code else None
        if origin is None:
            return ""
        here = tuple(float(x) for x in origin.split(","))
        best, found = math.inf, ""
        for other in codes:
            where = geocode_decode(other) if other else None
            if where is None:
                continue
            distance = _distance(here, tuple(float(x) for x in where.split(","))) # type: ignore[arg-type]
            if distance < best:
                best, found = distance, other
        return found

    @classmethod
    def zip_inputs(cls, model:Any, name:str) -> None:
        """`precommit()`: the weather inputs"""
        state = object_state(model, name)
        weather, names = state.get("weather"), state.get("weather_names", {})
        if weather is None:
            return
        def read(key:str) -> float|None:
            if key not in names:
                return None
            prop_, unit = names[key]
            return text_to_double(model.get_property(weather, prop_), unit)
        temperature = read("temperature")
        if temperature is not None:
            set_double(model, name, "H", max(get_double(model, name, "Theat") - temperature, 0.0))
            set_double(model, name, "C", max(temperature - get_double(model, name, "Tcool"), 0.0))
        for key, input_ in (("solar", "S"), ("wind", "W"), ("rain", "R")):
            value = read(key)
            if value is not None:
                set_double(model, name, input_, value)

    @classmethod
    def zip_parts(cls, model:Any, name:str, t0:int) -> tuple[complex,complex,complex]:
        """`Z`, `I`, `P` at time `t0` (gridlabd `sync()`)"""
        # pylint: disable=too-many-locals
        from tape._common import localtime # pylint: disable=import-outside-toplevel
        inputs = [get_double(model, name, x) for x in INPUTS] + [1.0]
        outputs = []
        for _, _, prefix, _ in PARTS:
            outputs.append(sum(get_double(model, name, f"{prefix}{suffix}")*value for suffix, value in zip(("_H", "_C", "_S", "_W", "_R", ""), inputs) if value != 0))
        when = localtime(model, t0)
        scale = object_state(model, name)["scale"][when.month - 1][(when.weekday() + 1) % 7][when.hour]
        factor = scale/cls.DIVISOR*get_double(model, name, "scalar")
        z, i, p = (complex(outputs[k], outputs[k+1])*factor for k in (0, 2, 4))
        for key, value in (("Z", z), ("I", i), ("P", p)):
            set_complex(model, name, key, value)
        return z, i, p

    @staticmethod
    def pf(value:complex) -> float:
        """gridlabd's power factor of a ZIP part"""
        return (1 if value.imag > 0 else -1)*value.real/abs(value) if value != 0 else 0.0

class ZipLoad(ZipModel, Load):
    """Behavior of class `zipload`"""

    NAME = "zipload"
    PARENT = "load"
    TRL = TRL_PROTOTYPE
    PROPERTIES = zip_properties()

    @classmethod
    def init_node(cls, model:Any, name:str) -> None:
        """`zipload::init()`"""
        cls.zip_init(model, name)
        super().init_node(model, name)

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        """The inputs and the ZIP form, then the load's values"""
        # pylint: disable=too-many-locals
        if "scale" in object_state(model, name):
            cls.zip_inputs(model, name)
            z, i, p = cls.zip_parts(model, name, t0)
            total = abs(z + i + p)
            deviation = float(g(model, "maximum_voltage_deviation") or 0.5)
            nominal = get_double(model, name, "nominal_voltage")
            for x in "ABC":
                v = abs(get_complex(model, name, f"voltage_{x}"))
                set_double(model, name, f"base_power_{x}", total if total > 0 and nominal > 0 and abs(v/nominal - 1) < deviation else 0.0)
                for kind, part in (("impedance", z), ("current", i), ("power", p)):
                    set_double(model, name, f"{kind}_fraction_{x}", abs(part)/total if total > 0 else 0.0)
                    set_double(model, name, f"{kind}_pf_{x}", cls.pf(part))
        super().before_solve(model, name, t0)

__all__ = ["ZipLoad", "ZipModel", "zip_properties", "build_schedule"]
