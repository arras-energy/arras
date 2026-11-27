# pylint: disable=line-too-long
"""@private Parts shared by the scheduled load classes (`agricultural`,
`industrial`, `public_service`) and `building`: data files, property
sources, local time, the load schedule, the ZIP form on the load's phases,
and the load meter (see `powerflow.agricultural` for their description)"""

import math
import os
import re
from dataclasses import dataclass
from typing import Any

from ._base import prop
from ._common import PHASE_A, PHASE_B, PHASE_C, object_state, get_int, get_double, set_double, PowerflowError

TS_DAY0 = 3*86400
"""gridlabd `TS_DAY0`: 1970-01-01 is a Thursday, so the meter intervals
are counted from Sunday 1970-01-04 (local time)"""

DATADIR = os.path.join(os.path.dirname(__file__), "data")
"""Data files installed with the package"""

def find_data_file(name:str) -> str|None:
    """A data file in the search path (`arras.folders.findfile()`), else
    in the package's `data` folder"""
    from arras.folders import findfile # pylint: disable=import-outside-toplevel
    path = findfile(name)
    if path is None:
        candidate = os.path.join(DATADIR, os.path.basename(name))
        path = candidate if os.path.isfile(candidate) else None
    return path

#
# Property sources (gridlabd `gld_property(name)`)
#
def source_property(model:Any, spec:str) -> tuple[str|None,str]|None:
    """`(object, property)` of an `object.property` source, `(None,
    global)` for a global variable, or `None` when it is not found"""
    spec = str(spec or "").strip().strip('"')
    if "." in spec:
        obj, prop_ = spec.split(".", 1)
        if obj in model.objects and model.objects[obj].oclass.find_property(prop_) is not None:
            return obj, prop_
    if spec and model.globals.find(spec) is not None:
        return None, spec
    return None

def source_value(model:Any, source:tuple[str|None,str], unit:str|None=None) -> float:
    """Value of a source, in `unit` when it is given (and the source has a
    unit)"""
    from pypower._common import _units # pylint: disable=import-outside-toplevel
    obj, prop_ = source
    if obj is None:
        var = model.globals.find(prop_)
        value = model.globals.getvalue(prop_)
        have = getattr(var, "unit", None)
        try:
            value = float(value)
        except (TypeError, ValueError):
            from pypower._common import text_to_double # pylint: disable=import-outside-toplevel
            return text_to_double(value, unit)
    else:
        value = get_double(model, obj, prop_)
        have = model.objects[obj].oclass.find_property(prop_).unit
    if unit and have and have != unit:
        value = _units().convert(value, have, unit)
    return value

#
# Local time
#
def local_time(model:Any, t:int) -> Any:
    """Local date and time (`datetime`) of a timestamp"""
    from tape._common import localtime # pylint: disable=import-outside-toplevel
    return localtime(model, t)

def interval_offset(model:Any, t:int) -> int:
    """gridlabd `tzoffset + TS_DAY0` at time `t`: a time is on a meter
    interval of `step` seconds when `(t - offset) % step == 0`"""
    return -int(local_time(model, t).utcoffset().total_seconds()) + TS_DAY0

def on_interval(model:Any, t:int, step:float) -> bool:
    """Whether time `t` is on a multiple of `step` seconds (local, from
    Sunday 1970-01-04)"""
    return step > 0 and (t - interval_offset(model, t)) % int(step) == 0

def next_interval(model:Any, t:int, step:float) -> int|None:
    """The next time after `t` on a multiple of `step` seconds"""
    if step <= 0:
        return None
    step = int(step)
    offset = interval_offset(model, t)
    return t + step - (t - offset) % step

#
# Load schedule
#
@dataclass
class Composition: # pylint: disable=too-many-instance-attributes
    """Load composition of one hour of the schedule"""
    aggregate: bool = True
    total: float = 0.0
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    d: float = 0.0
    e: float = 0.0
    z: float = 0.0
    i: float = 0.0
    pf: float = 1.0

RANGE = re.compile(r"\s*\d+\s*-\s*\d+\s*")

def schedule_records(text:str) -> list[str]:
    """The records of a schedule text: separated by `;` or new lines, and
    by `,` where repeated `schedule` values were joined (a record starts
    with three `M-M,D-D,H-H` ranges)"""
    records = []
    for chunk in re.split(r"[;\n]", str(text or "").strip().strip('"')):
        if not chunk.strip():
            continue
        fields = chunk.split(",")
        current: list[str] = []
        for k, field in enumerate(fields):
            if len(current) >= 4 and all(RANGE.fullmatch(x) for x in fields[k:k+3]) and k + 3 <= len(fields):
                records.append(",".join(current))
                current = []
            current.append(field.strip())
        records.append(",".join(current))
    return records

def parse_schedule(text:str, default_pf:float, totals:bool=True) -> dict[tuple[int,int,int],Composition]: # pylint: disable=too-many-locals
    """The schedule table `(month 0-11, weekday 0-6 (Monday 0), hour)` of
    a schedule text (gridlabd `schedule()`): `M-M,D-D,H-H,` then `Pt`,
    `Pt,Pf`, `A,B,C,D,E,Z,I`, or `A,B,C,D,E,Z,I,Pf`; raises
    `PowerflowError`. With `totals`, a composite record's total is the sum
    of its parts (gridlabd's `industrial` leaves it 0)."""
    table: dict[tuple[int,int,int],Composition] = {}
    for record in schedule_records(text):
        match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*,\s*(\d+)\s*-\s*(\d+)\s*,\s*(\d+)\s*-\s*(\d+)\s*((?:,[^,]*)*)", record)
        values = []
        if match:
            try:
                values = [float(x) for x in match.group(7).split(",")[1:]]
            except ValueError:
                values = []
        if not match or len(values) not in (1, 2, 7, 8):
            raise PowerflowError(f"composition '{record}': missing required value(s)")
        m0, m1, d0, d1, h0, h1 = (int(x) for x in match.groups()[:6])
        if m0 < 1 or m1 > 12 or m0 > m1:
            raise PowerflowError(f"composition '{record}': month {m0}-{m1} is invalid")
        if d1 > 6 or d0 > d1:
            raise PowerflowError(f"composition '{record}': weekday {d0}-{d1} is invalid")
        if h1 > 23 or h0 > h1:
            raise PowerflowError(f"composition '{record}': hours {h0}-{h1} is invalid")
        if len(values) <= 2:
            item = Composition(True, values[0], pf=values[1] if len(values) == 2 else default_pf)
        else:
            a, b, c, d, e, z, i = values[:7]
            item = Composition(False, a + b + c + d + e + z + i if totals else 0.0, a, b, c, d, e, z, i,
                values[7] if len(values) == 8 else default_pf)
        for month in range(m0 - 1, m1):
            for day in range(d0, d1 + 1):
                for hour in range(h0, h1 + 1):
                    table[(month, day, hour)] = item
    return table

def schedule_text(text:str) -> str:
    """A schedule's records joined by `;`, as gridlabd writes it"""
    return ";".join(schedule_records(text))

#
# ZIP form on the load's phases
#
PHASES = (PHASE_A, PHASE_B, PHASE_C)

def phase_count(model:Any, name:str) -> int:
    """Number of phases A, B, C of a load"""
    phases = get_int(model, name, "phases")
    return sum(1 for bit in PHASES if phases & bit)

def apparent(real:float, pf:float) -> complex:
    """Apparent power of a real power at a power factor (negative: leading),
    as `load` computes it from `base_power` (0: the real power is
    reactive)"""
    if pf == 0:
        return complex(0.0, real)
    reactive = abs(real)*math.sqrt(max(1/(pf*pf) - 1, 0.0))
    return complex(real, -reactive if pf < 0 else reactive)

def set_zip(model:Any, name:str, parts:tuple[float,float,float], pf:float) -> complex: # pylint: disable=too-many-locals
    """Set the load's ZIP form on its phases from the total impedance,
    current, and power parts (real power, W) at a power factor: each phase
    gets an equal share, with `base_power_X` the apparent power whose real
    part is that share; return the total apparent power"""
    z, i, p = parts
    total = z + i + p
    phases = get_int(model, name, "phases")
    n = phase_count(model, name)
    share = total/n if n else 0.0
    base = share/abs(pf) if pf != 0 else share
    for x, bit in zip("ABC", PHASES):
        on = bool(phases & bit)
        set_double(model, name, f"base_power_{x}", base if on else 0.0)
        for kind, part in (("impedance", z), ("current", i), ("power", p)):
            set_double(model, name, f"{kind}_fraction_{x}", part/total if on and total != 0 else 0.0)
            set_double(model, name, f"{kind}_pf_{x}", pf if on else 0.0)
    return apparent(share, pf)*n

#
# Load meter
#
METER_PROPERTIES = (
    ("measured_real_power[W]", "double", prop("metered real power demand", flags="OUTPUT")),
    ("measured_reactive_power[VAr]", "double", prop("metered reactive power demand", flags="OUTPUT")),
    ("measured_real_energy[Wh]", "double", prop("cumulative metered real energy consumption", flags="OUTPUT")),
    ("measured_real_energy_delta[Wh]", "double", prop("metered real energy interval consumption", flags="OUTPUT")),
    ("measured_reactive_energy[Wh]", "double", prop("cumulative metered reactive energy consumption", flags="OUTPUT")),
    ("measured_reactive_energy_delta[Wh]", "double", prop("metered reactive energy interval consumption", flags="OUTPUT")),
    ("measured_energy_delta_timestep[s]", "double", prop("energy metering interval", "3600 s", flags="OUTPUT")),
    ("measured_demand[W]", "double", prop("maximum metered real power interval demand", flags="OUTPUT")),
    ("measured_demand_timestep[s]", "double", prop("maximum power metering interval", "3600 s", flags="OUTPUT")),
)
"""The meter's properties"""

def meter_update(model:Any, name:str, t0:int, power:complex) -> None:
    """Meter a load's power at time `t0` (after each solution): at a new
    time, the energy since the last one at the power then; the power; at
    each energy interval, the energy deltas over it; at each demand
    interval, the largest real power over it"""
    state = object_state(model, name).setdefault("meter", {"t": None, "power": 0j, "energy": 0j, "start": 0j,
        "peak": None, "delta_t": None, "demand_t": None})
    if state["t"] is not None and t0 > state["t"]:
        state["energy"] += state["power"]*(t0 - state["t"])/3600
        state["peak"] = state["power"].real if state["peak"] is None else max(state["peak"], state["power"].real)
        set_double(model, name, "measured_real_energy", state["energy"].real)
        set_double(model, name, "measured_reactive_energy", state["energy"].imag)
    state["t"], state["power"] = t0, power
    set_double(model, name, "measured_real_power", power.real)
    set_double(model, name, "measured_reactive_power", power.imag)
    if state["delta_t"] != t0 and on_interval(model, t0, get_double(model, name, "measured_energy_delta_timestep")):
        state["delta_t"] = t0
        delta = state["energy"] - state["start"]
        state["start"] = state["energy"]
        set_double(model, name, "measured_real_energy_delta", delta.real)
        set_double(model, name, "measured_reactive_energy_delta", delta.imag)
    if state["demand_t"] != t0 and on_interval(model, t0, get_double(model, name, "measured_demand_timestep")):
        state["demand_t"] = t0
        set_double(model, name, "measured_demand", state["peak"] or 0.0)
        state["peak"] = None

def meter_events(model:Any, name:str, t0:int) -> list[int]:
    """The next energy and demand interval times"""
    events = [next_interval(model, t0, get_double(model, name, x)) for x in ("measured_energy_delta_timestep", "measured_demand_timestep")]
    return [t for t in events if t is not None]

def meter_check(name:str, model:Any) -> None:
    """The meter intervals must not be negative; raises `PowerflowError`"""
    for prop_ in ("measured_energy_delta_timestep", "measured_demand_timestep"):
        if get_double(model, name, prop_) < 0:
            raise PowerflowError(f"{name}: {prop_} must be non-negative")
