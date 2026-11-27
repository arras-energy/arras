# pylint: disable=line-too-long,too-many-locals
"""Class `building`: a building load with a thermal model, end-use loadshapes, solar, and storage

Syntax
------

    module powerflow {
        building_defaults "<file>";     // default building_defaults.csv
        building_loadshapes "<file>";   // default building_loadshapes.csv
        building_occupancy "<file>";    // default building_occupancy.csv
        inverter_settings "<file>";     // default inverter_settings.csv
    }
    object building {
        phases {A,B,C}[D|N];
        nominal_voltage <real> V;
        floor_area <real> m^2;
        building_type <type>;           // optional: defaults, loadshapes, occupancy
        UA <real> W/K;                  // thermal parameters: UA, CA, UI, CM, UM
        TH <real> degC;                 // heating and cooling design temperatures
        TC <real> degC;
        QH <real> W;                    // HVAC capacity (0: autosize)
        TS <real> degC;                 // thermostat setpoint
        temperature_source "<object>.<property>";   // also solar_source,
        heating_design "<object>.<property>";       //   cooling_design
        PV <real> m^2;                  // solar panels; also BS (J), PX, PG (W)
        IC {UNITY,IEEE1547,CARULE21,UL1741};
        // and the other properties listed below and those of load
    }

Outputs: `TA`, `TM` (degC), `M` (pu), `ES` (J), `QH` (when autosized),
the meter of `powerflow.agricultural`, and `measured_resource_power` (W).

Description
-----------

A `building` (gridlabd `PT_INHERIT "load"`) is a load computed from a
two-node (air and mass) thermal model of the building and its HVAC
system, as gridlabd's `building` does. With the state `x = [TA, TM, M]`
(indoor air and mass temperatures, HVAC mode per unit `QH`, negative when
cooling) and the inputs `u = [TO, (EU + ef NG/ee) eg, (1-ef) NG gg, NH o,
QS, TS]` (outdoor temperature; electric and gas end-use gains with the
electrification fraction `ef` and efficiency `ee` and the gain fractions
`eg` and `gg`; occupants `NH` times the occupancy fraction `o`;
insolation; setpoint), the model is `dx/dt = A x + B u` with

    A = [ -(UA+UI)/CA   UI/CA        QH/CA ]    B = [ UA/CA  F/CA  F/CA  (QO+QV)/CA  0      0 ]
        [  UI/CM       -(UM+UI)/CM   0     ]        [ UM/CM  0     0     0           SA/CM  0 ]
        [ -K            0            0     ]        [ 0      0     0     0           0      K ]

(`F` is the floor area in square feet), and the building is at its steady
state `x = -A^-1 B u` (so `TA = TS`), with `M` limited to -1 to 1 (with a
warning).

When it initializes, a building solves its model once (without changing
the battery's charge), so its outputs are set before the first time step;
the first time step solves it again with the solved voltage.

A building with a `building_type` reads its
parameters (`UA` ... `QPH`) from the type's row of
`powerflow::building_defaults` (the thermal parameters per unit floor
area, multiplied by `floor_area`), its electric and gas end-use
loadshapes from `powerflow::building_loadshapes` (by season, weekday or
weekend, and hour), and, when `occupancy` is positive, its weekday and
weekend occupancy fractions from `powerflow::building_occupancy`; these
files are found in the search path or among the package's data files.
`TH` and `TC` come from the `heating_design` and `cooling_design`
sources when they are set. With `QH` 0 the HVAC system is sized for the
larger of the heating load at `TH` and the cooling load at `TC` (with
gains `QE + QG + QO + QV + 1300 SA`), times `DF`; otherwise a warning
says when it is undersized for either.

At each `dt` (local time from Sunday 1970-01-04, an event the object asks
for), the inputs are updated (`TO` and `QS` from their sources, `EU` and
`NG` from the loadshapes), the state is solved, and the outputs are `y =
C x + D u`: the real power of the impedance, current, and power parts and
their reactive powers, with the HVAC power `PZM`, `PPM`, `QPM` times the
cooling capacity, or the heating capacity with `electric_heat`, the
end-use powers `PZE` ... `QPE` times the floor area in square feet, the
ventilation `PPH QH/10` and `QPH QH/100` per occupant, and the solar
power `PV QS` taken from the power part. With storage (`BS`), the battery
takes the power part's export (up to `PG` and its free capacity) or
supplies its import (up to `PG` and its charge). When the solar and
battery power is positive, the inverter control `IC` (settings from
`powerflow::inverter_settings`) changes the power part by its correction
for the average voltage magnitude per unit `nominal_voltage`.

Each phase of the building takes an equal share of each part as the
`load` ZIP form (`base_power_X` the sum of the parts' apparent powers,
each part's fraction and power factor its own); when the power part is
negative, the share of the net power (no less than `-PX`) is all
constant power at unity power factor. The meter is that of
`powerflow.agricultural`, of this load; `measured_resource_power` is the
solar and battery power.

When it initializes, a building fails when `K`, `dt`, `DF`,
`electrification_efficiency`, `electric_gain_fraction`, or
`gas_gain_fraction` is not positive, when `QH`, `PX`, `BS`, `PV`, `ES`, or
a meter interval is negative, when `electrification_fraction` is out of 0
to 1, when a source is not an object property or a global, and, with a
`building_type`, when `floor_area` is not positive, a data file is
missing or invalid, or the type is not in the defaults; it warns when a
meter interval is not a multiple of `dt`, when the demand interval is
shorter than the energy interval, and when `PZE + PIE + PPE` is not 1.

Caveats
-------

- The model is the steady state at each `dt`; gridlabd's dynamic solver
  is not implemented either.
- Without an occupancy schedule (no `building_type`, or `occupancy` 0)
  the occupancy fraction is 0, so `NH` has no effect, as in gridlabd.
- `TA` is `TS` even when `M` is limited, as in gridlabd.
- The loadshapes are read as W/sf (they are multiplied by the floor area
  in square feet), as in gridlabd; its documentation says W/m^2.
- The meter reports the building's load at nominal voltage.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The outputs use the limited `M`; gridlabd limits the `M` property but
   computes the HVAC power from the unlimited state.
2. Each part keeps its own power factor and the load draws the computed
   real and reactive powers; gridlabd sets `base_power_X` to the real
   power and each part's power factor to its real power over the total
   apparent power, so the load draws less than the model computes.
3. When the power part is negative, each phase takes its share of the
   net power; gridlabd gives each phase the whole net power.
4. The battery stores the export it can take (up to its free capacity
   and `PG`) and supplies the import it can; gridlabd fills it whenever
   the export exceeds what it can take (even when `PG` is the limit),
   takes in more than the export when it can, and removes its whole
   available energy when it supplies less.
5. The inverter's voltage is the average voltage magnitude of the
   building's phases; gridlabd uses the magnitude of their sum, which is
   about 0 on a balanced three-phase building.
6. The inverter makes no correction when `PX` is 0; gridlabd divides by
   0 and the loads become NaN when a building with solar has `PX` 0.
7. The meter reports the whole building load; gridlabd reports the
   node's constant-power accumulator, without the impedance and current
   parts.
8. The seasons of the loadshapes are winter (December to February),
   spring (March to May), summer (June to August), and fall (September to
   November); gridlabd's `int(month/4)` makes January to March winter,
   April to July spring, August to November summer, and December fall.
9. The meter intervals are checked as multiples of `dt`; gridlabd
   subtracts the time zone offset from the interval before the check.
   The model updates on local multiples of `dt`, also its events;
   gridlabd's events are UTC multiples.
10. Invalid sources, a missing data file, a building type not in the
    defaults, and a nonpositive floor area with a building type fail the
    initialization; gridlabd writes the error and goes on.
11. The inverter settings are kept by their standard's name; gridlabd
    keeps them by row number, so the file must list them in the order of
    `IC`.
12. The meter works and its intervals are those of
    `powerflow.agricultural` (differences 2 and 3 there).
13. Charging the battery adds to the power part and discharging takes
    from it; gridlabd subtracts the battery's load from the power part, so
    charging lowers the building's load and discharging raises it.
14. The battery is charged or discharged once at the first time step;
    gridlabd's `init()` and the first `sync()` both update it.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/building.cpp`, `building.h`,
  `docs/Module/Powerflow/Building.md`, `module/powerflow/data/`
"""

import cmath
import math
from typing import Any

import numpy as np

from ._base import prop, keywords
from ._common import TRL_PROVEN, g, msg, object_state, get_int, get_double, get_complex, set_double, gl_warning, PowerflowError
from .load import Load
from .scheduled_load import (METER_PROPERTIES, PHASES, find_data_file, local_time, meter_check, meter_events, meter_update,
    next_interval, on_interval, phase_count, source_property, source_value)

SF = 10.764
"""Square feet per square meter (gridlabd's factor)"""

STANDARDS = ("UNITY", "IEEE1547", "CARULE21", "UL1741")
"""Inverter control standards, by `IC` value"""

SEASONS = ("WINTER", "SPRING", "SUMMER", "FALL")

DEFAULT_FIELDS = ("UA", "CA", "UI", "CM", "UM", "DF", "K", "QE", "QG", "QO", "QV", "SA", "TS", "PZM", "PPM", "QPM",
    "PZE", "PIE", "PPE", "QZE", "QIE", "QPE", "PPH", "QPH")

_CACHE: dict[tuple[str,str],Any] = {}

def _read(path:str) -> list[str]:
    with open(path, encoding="utf-8") as file:
        return file.read().splitlines()

def data_file(model:Any, glob:str, default:str) -> str:
    """The path of a data file named by a module global; raises
    `PowerflowError`"""
    filename = str(g(model, glob) or default).strip('"')
    path = find_data_file(filename)
    if path is None:
        raise PowerflowError(f"unable to stat file '{filename}'")
    return path

def inverter_settings(path:str) -> dict[str,tuple[float,...]]:
    """The settings `(Vmin, Vmax, Qmin, Qmax, Slow, Shigh)` by standard;
    raises `PowerflowError`"""
    key = ("inverter", path)
    if key not in _CACHE:
        lines = [x for x in _read(path) if x.strip()]
        header = "standard,Vmin,Vmax,Qmin,Qmax,Slow,Shigh"
        if not lines or lines[0] != header:
            raise PowerflowError(f"{path}(1): invalid header line (expected '{header}')")
        result = {}
        for n, line in enumerate(lines[1:], 2):
            fields = line.split(",")
            try:
                values = tuple(float(x) for x in fields[1:7])
            except ValueError:
                values = ()
            if len(values) < 6:
                raise PowerflowError(f"{path}({n}): missing control settings data (expected 7 values but got {len(fields)} instead)")
            vmin, vmax, qmin, qmax, slow, shigh = values
            if vmax < vmin:
                raise PowerflowError(f"{path}({n}): voltage deadband is inverted (Vmin>Vmax)")
            if qmax < qmin:
                raise PowerflowError(f"{path}({n}): reactive power limits are inverted (Qmin>Qmax)")
            if slow < 0 or shigh < 0:
                raise PowerflowError(f"{path}({n}): control gains are inverted (Slow<0 or Shigh<0)")
            if fields[0] not in STANDARDS:
                raise PowerflowError(f"{path}({n}): inverter control '{fields[0]}' is not valid")
            result[fields[0]] = values
        _CACHE[key] = result
    return _CACHE[key]

def inverter_output(settings:tuple[float,...], dg:float, v:float, pmax:float) -> complex:
    """gridlabd `controller::output()`: the real and reactive power
    correction of the generation `dg` at voltage `v` (pu)"""
    vmin, vmax, qmin, qmax, slow, shigh = settings
    m = min(abs(dg), pmax)
    if m <= 0:
        return 0j
    if v < vmin:
        r = min((vmin - v)*slow, qmax)*m
        return dg - cmath.rect(m, math.asin(max(-1.0, min(1.0, r/m))))
    if v > vmax:
        r = max((vmax - v)*shigh, qmin)*m
        return dg - cmath.rect(m, -math.asin(max(-1.0, min(1.0, r/m))))
    return 0j

def loadshape(path:str, building_type:str, fuel:str) -> list[float]|None:
    """The 192 loads (season, weekend, hour) of a type and fuel, or `None`
    when there are none; raises `PowerflowError`"""
    key = (path, building_type, fuel)
    if ("shape",) + key not in _CACHE:
        lines = _read(path)
        header = "building_type,season,fuel,daytype,hour,load"
        if not lines or not lines[0].startswith(header):
            raise PowerflowError(f"file '{path}' header is incorrect (expected '{header}' but got '{lines[0][:len(header)] if lines else ''}')")
        values = [0.0]*192
        found = 0
        for n, line in enumerate(lines[1:], 2):
            fields = line.split(",")
            if not line.strip():
                break
            if len(fields) < 6:
                raise PowerflowError(f"input::get_loadshape('{building_type}','{fuel}'): error parsing line {n} (too few fields)")
            if fields[0] == building_type and fields[2] == fuel:
                found += 1
                season = SEASONS.index(fields[1]) if fields[1] in SEASONS else 0
                values[int(fields[4]) + (fields[3] == "WEEKEND")*24 + season*48] = float(fields[5])
        _CACHE[("shape",) + key] = values if found else None
    return _CACHE[("shape",) + key]

def occupancy_schedule(path:str, building_type:str) -> list[tuple[int,int,float,float]]|None:
    """The weekday and weekend `(start, stop, occupied, unoccupied)` of a
    type, or `None` when there is none; raises `PowerflowError`"""
    lines = _read(path)
    header = "building_type,daytype,start,stop,occupied,unoccupied"
    if not lines or not lines[0].startswith(header):
        raise PowerflowError(f"file '{path}' header is incorrect (expected '{header}' but got '{lines[0][:len(header)] if lines else ''}')")
    result = [(0, 0, 0.0, 0.0), (0, 0, 0.0, 0.0)]
    found = 0
    for n, line in enumerate(lines[1:], 2):
        fields = line.split(",")
        if not line.strip():
            break
        if fields[0] != building_type:
            continue
        start, stop, occupied, unoccupied = int(fields[2]), int(fields[3]), float(fields[4]), float(fields[5])
        if start > 24 or stop > 24 or stop < start or not 0 <= occupied <= 1 or not 0 <= unoccupied <= 1:
            raise PowerflowError(f"input::load_occupancy(): invalid schedule for daytype '{fields[1]}' on line {n}")
        if fields[1] not in ("WEEKDAY", "WEEKEND"):
            raise PowerflowError(f"input::load_occupancy(): invalid daytype '{fields[1]}' on line {n}")
        result[fields[1] == "WEEKEND"] = (start, stop, occupied, unoccupied)
        found += 1
    return result if found else None

def season_of(month:int) -> int:
    """Loadshape season of a month (1-12)"""
    return (month % 12)//3

class Building(Load):
    """Behavior of class `building`"""

    NAME = "building"
    PARENT = "load"
    TRL = TRL_PROVEN
    PASSCONFIG = "PRETOPDOWN|BOTTOMUP|POSTTOPDOWN|UNSAFE_OVERRIDE_OMIT|AUTOLOCK|OBSERVER"
    PROPERTIES = (
        ("dt[s]", "double", prop("timestep to use when modeling building response to inputs", "1h")),
        ("TA[degC]", "double", prop("indoor air temperature", flags="OUTPUT")),
        ("TM[degC]", "double", prop("building mass temperature", flags="OUTPUT")),
        ("M[pu]", "double", prop("system mode per unit system capacity", flags="OUTPUT")),
        ("ES[J]", "double", prop("stored energy", flags="OUTPUT")),
        ("UA[W/K]", "double", prop("conductance from interior air to outdoor air", flags="REQUIRED")),
        ("CA[J/K]", "double", prop("heat capacity of indoor air volume", flags="REQUIRED")),
        ("UI[W/K]", "double", prop("conductance from building mass to indoor air", flags="REQUIRED")),
        ("CM[J/K]", "double", prop("heat capacity of building mass", flags="REQUIRED")),
        ("UM[W/K]", "double", prop("conductance of building mass to outdoor air", flags="REQUIRED")),
        ("TH[degC]", "double", prop("heating design temperature", flags="REQUIRED")),
        ("TC[degC]", "double", prop("cooling design temperature", flags="REQUIRED")),
        ("DF[pu]", "double", prop("system over-design factor", "2.0 pu")),
        ("QH[W]", "double", prop("HVAC system capacity", flags="REQUIRED|OUTPUT")),
        ("QE[W/m^2]", "double", prop("nomimal enduse load capacity", flags="REQUIRED")),
        ("QG[W/m^2]", "double", prop("natural gas heat per unit nominal enduse capacity", flags="REQUIRED")),
        ("QO[W/unit]", "double", prop("heat gain per occupant", flags="REQUIRED")),
        ("QV[W/unit]", "double", prop("ventilation gain per occupant", flags="REQUIRED")),
        ("SA[m^2]", "double", prop("building mass area exposed to solar radiation", flags="REQUIRED")),
        ("PV[m^2]", "double", prop("area of photovoltaic rooftop panels")),
        ("BS[J]", "double", prop("battery storage capacity")),
        ("PX[W]", "double", prop("maximum export power")),
        ("PG[W]", "double", prop("maximum inverter power")),
        ("K[pu]", "double", prop("HVAC mode proportional control gain w.r.t indoor temperature", "1.0 pu")),
        ("IC", "enumeration", prop("inverter power factor control", "UNITY", keywords=keywords(*((x, k) for k, x in enumerate(STANDARDS))))),
        ("TO[degC]", "double", prop("outdoor air temperature")),
        ("EU[unit]", "double", prop("enduse load fraction")),
        ("NG[unit]", "double", prop("natural gas demand")),
        ("NH[unit]", "double", prop("building occupants")),
        ("QS[W/m^2]", "double", prop("insolation")),
        ("TS[degC]", "double", prop("thermostat setpoint", flags="REQUIRED")),
        ("PZM[pu]", "double", prop("constant impedance HVAC real power per unit system capacity", flags="OUTPUT")),
        ("PPM[pu]", "double", prop("constant power HVAC real power per unit system capacity", flags="OUTPUT")),
        ("QPM[pu]", "double", prop("constant power HVAC reactive power per unit system capacity", flags="OUTPUT")),
        ("PZE[pu]", "double", prop("constant impedance end-use real power fraction", flags="OUTPUT")),
        ("PIE[pu]", "double", prop("constant current end-use real power fraction", flags="OUTPUT")),
        ("PPE[pu]", "double", prop("constant power end-use real power fraction", flags="OUTPUT")),
        ("QZE[pu]", "double", prop("constant impedance end-use reactive fraction", flags="OUTPUT")),
        ("QIE[pu]", "double", prop("constant current end-use reactive fraction", flags="OUTPUT")),
        ("QPE[pu]", "double", prop("constant power end-use reactive fraction", flags="OUTPUT")),
        ("PPH[pu]", "double", prop("constant power ventilation real power per unit occupancy", flags="OUTPUT")),
        ("QPH[pu]", "double", prop("constant power ventilation reactive power per unit occupancy", flags="OUTPUT")),
        *METER_PROPERTIES,
        ("measured_resource_power[W]", "double", prop("measured net distributed generation production from solar and batteries", flags="OUTPUT")),
        ("temperature_source", "char256", prop("temperature weather object source property")),
        ("solar_source", "char256", prop("solar weather object source property")),
        ("cooling_design", "char256", prop("cooling design temperature source property")),
        ("heating_design", "char256", prop("heating design temperature source property")),
        ("building_type", "char32", prop("building type used to be lookup defaults and enduse loadshapes")),
        ("floor_area[m^2]", "double", prop("building floor area", flags="REQUIRED")),
        ("electric_gain_fraction[pu]", "double", prop("fraction of electric end-use heat gain to the building", "+1 pu", flags="REQUIRED")),
        ("gas_gain_fraction[pu]", "double", prop("fraction of gas end-use heat gain to the building", "+0.5 pu", flags="REQUIRED")),
        ("electrification_fraction[pu]", "double", prop("fraction of gas enduses that are converted to electricity", "+0 pu", flags="REQUIRED")),
        ("electrification_efficiency[pu]", "double", prop("performance of electric end-use relative to gas enduse", "+2 pu", flags="REQUIRED")),
        ("occupancy", "int32", prop("building occupancy")),
        ("electric_heat", "bool", prop("flag to specified whether heating is electric")),
    )

    #
    # Initialization
    #
    @classmethod
    def _v(cls, model:Any, name:str, *props:str) -> list[float]:
        return [get_double(model, name, x) for x in props]

    @classmethod
    def init_sources(cls, model:Any, name:str) -> dict[str,Any]:
        """The temperature and solar sources, and the design temperatures
        from theirs; raises `PowerflowError`"""
        sources = {}
        for prop_, label, target in (("temperature_source", "temperature source", None), ("solar_source", "solar source", None),
                ("heating_design", "heating design source", "TH"), ("cooling_design", "cooling design source", "TC")):
            text = str(model.get_property(name, prop_) or "").strip('"')
            if not text:
                continue
            source = source_property(model, text)
            if source is None:
                raise PowerflowError(f"{name}: {label} '{text}' is not valid")
            if target is None:
                sources[prop_] = source
            else:
                set_double(model, name, target, source_value(model, source, "degC"))
        return sources

    @classmethod
    def init_type(cls, model:Any, name:str, state:dict[str,Any]) -> None: # pylint: disable=too-many-branches
        """The building type's defaults, loadshapes, and occupancy; raises
        `PowerflowError`"""
        btype = str(model.get_property(name, "building_type") or "").strip('"')
        if not btype:
            return
        area = get_double(model, name, "floor_area")
        if area <= 0:
            raise PowerflowError(f"{name}: floor area must be positive")
        path = data_file(model, "building_defaults", "building_defaults.csv")
        lines = _read(path)
        if not lines or not lines[0].startswith("building_type,"):
            raise PowerflowError(f"{name}: file '{path}' header column 0 data is not building type index")
        fields = lines[0].split(",")[1:]
        for line in lines[1:]:
            values = line.split(",")
            if values[0] == btype:
                for field, value in zip(fields, values[1:]):
                    if model.objects[name].oclass.find_property(field) is None:
                        raise PowerflowError(f"{name}: {path}: field '{field}' is not valid")
                    set_double(model, name, field, float(value))
                if len(values) - 1 < len(fields):
                    raise PowerflowError(f"{name}: {path}: value for field '{fields[len(values) - 1]}' is missing")
                break
        else:
            raise PowerflowError(f"{name}: building type '{btype}' not found in '{path}'")
        for prop_ in ("UA", "CA", "UI", "CM", "UM"):
            set_double(model, name, prop_, get_double(model, name, prop_)*area)
        shapes = data_file(model, "building_loadshapes", "building_loadshapes.csv")
        for fuel, key in (("ELECTRIC", "electric"), ("GAS", "gas")):
            shape = loadshape(shapes, btype, fuel)
            if shape is None:
                gl_warning(f"loadshape for building type '{btype}' fuel '{fuel}' not found")
                shape = [0.0]*192
            state[key] = shape
        if get_int(model, name, "occupancy") < 0:
            raise PowerflowError(f"{name}: occupancy must be non-negative")
        if get_int(model, name, "occupancy") > 0:
            schedule = occupancy_schedule(data_file(model, "building_occupancy", "building_occupancy.csv"), btype)
            if schedule is None:
                gl_warning(f"occupancy schedule for building type '{btype}' not found")
            else:
                state["occupancy"] = schedule

    @classmethod
    def init_checks(cls, model:Any, name:str) -> None:
        """Parameter checks; raises `PowerflowError`"""
        out = msg(model, name)
        for prop_ in ("K", "dt", "DF"):
            if get_double(model, name, prop_) <= 0:
                raise PowerflowError(f"{name}: {prop_} must be positive")
        meter_check(name, model)
        if get_double(model, name, "QH") < 0:
            raise PowerflowError(f"{name}: QH must be non-negative")
        dt, energy, demand = cls._v(model, name, "dt", "measured_energy_delta_timestep", "measured_demand_timestep")
        if energy < dt or energy % dt != 0:
            out.warning("measured_energy_delta_timestep must a multiple of dt")
        if demand < dt or demand % dt != 0:
            out.warning("measured_demand_timestep must a multiple of dt")
        if demand < energy:
            out.warning("measured_demand_timestep must be greater than or equal to measured_energy_delta_timestep")
        if sum(cls._v(model, name, "PZE", "PIE", "PPE")) != 1.0:
            out.warning("real power output fractions must add to 1.0")
        for prop_ in ("electrification_efficiency", "electric_gain_fraction", "gas_gain_fraction"):
            if get_double(model, name, prop_) <= 0:
                raise PowerflowError(f"{name}: {prop_} must be positive")
        if not 0 <= get_double(model, name, "electrification_fraction") <= 1:
            raise PowerflowError(f"{name}: electrification fraction must be between 0 and 1")
        for prop_ in ("PX", "BS", "PV", "ES"):
            if get_double(model, name, prop_) < 0:
                raise PowerflowError(f"{name}: {prop_} must be non-negative")

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool:
        """`node::init()` at time `t`"""
        object_state(model, name)["init_t"] = t
        return super().init(model, name, t)

    @classmethod
    def init_node(cls, model:Any, name:str) -> None:
        """`building::init()`; raises `PowerflowError`"""
        state = object_state(model, name)
        state.update(cls.init_sources(model, name))
        cls.init_type(model, name, state)
        cls.init_checks(model, name)
        standard = STANDARDS[get_int(model, name, "IC")]
        settings = inverter_settings(data_file(model, "inverter_settings", "inverter_settings.csv"))
        if standard not in settings:
            raise PowerflowError(f"{name}: inverter control '{standard}' has no settings")
        state["inverter"] = settings[standard]
        cls.size_equipment(model, name)
        super().init_node(model, name)
        state["building"] = True
        energy = get_double(model, name, "ES")
        cls.update(model, name, state.get("init_t", 0))
        set_double(model, name, "ES", energy)
        state.pop("updated")

    #
    # Model
    #
    @classmethod
    def matrices(cls, model:Any, name:str) -> tuple[np.ndarray,np.ndarray]:
        """`A` and `B` of the thermal model"""
        ua, ca, ui, cm, um, qh, qo, qv, sa, k, area = cls._v(model, name, "UA", "CA", "UI", "CM", "UM", "QH", "QO", "QV", "SA", "K", "floor_area")
        a = np.array([[-(ua + ui)/ca, ui/ca, qh/ca], [ui/cm, -(um + ui)/cm, 0.0], [-k, 0.0, 0.0]])
        b = np.zeros((3, 6))
        b[0, :4] = (ua/ca, area*SF/ca, area*SF/ca, (qo + qv)/ca)
        b[1, 0], b[1, 4], b[2, 5] = um/cm, sa/cm, k
        return a, b

    @classmethod
    def size_equipment(cls, model:Any, name:str) -> None:
        """`building::update_equipment()`: autosize `QH` when it is 0, else
        check its size"""
        ua, ca, ui, cm, um, df, th, tc, ts, qe, qg, qo, qv, sa, qh = cls._v(model, name, "UA", "CA", "UI", "CM", "UM", "DF", "TH", "TC",
            "TS", "QE", "QG", "QO", "QV", "SA", "QH")
        if qh == 0:
            a = np.array([[ui/ca, 1/df/ca], [-(um + ui)/cm, 0.0]])
            heating = np.linalg.solve(a, -np.array([[ua/ca, -(ua + ui)/ca], [um/cm, ui/cm]]) @ np.array([th, ts]))
            cooling = np.linalg.solve(a, -np.array([[ua/ca, -(ua + ui)/ca, 0.0], [um/cm, ui/cm, (qe + qg + qo + qv + 1300*sa)/cm]]) @ np.array([tc, ts, 1.0]))
            set_double(model, name, "QH", max(-cooling[1], heating[1]))
            return
        a, b = cls.matrices(model, name)
        out = msg(model, name)
        mh = np.linalg.solve(a, -b @ np.array([th, 0, 0, 0, 0, ts]))[2]
        if mh > 1/df:
            out.warning(f"system is undersized for TH = {th:.1f} degC, MH = {mh:.2f}")
        mc = np.linalg.solve(a, -b @ np.array([tc, 1, 1, 1, 1, ts]))[2]
        if -mc > 1/df:
            out.warning(f"system is undersized for TC = {tc:.1f} degC, MC = {mc:.2f}")

    @classmethod
    def inputs(cls, model:Any, name:str, t:int) -> np.ndarray:
        """`building::update_input()`: the input vector at time `t`"""
        state = object_state(model, name)
        when = local_time(model, t)
        weekend = when.weekday() >= 5
        if "temperature_source" in state:
            set_double(model, name, "TO", source_value(model, state["temperature_source"], "degC"))
        if "solar_source" in state:
            set_double(model, name, "QS", source_value(model, state["solar_source"], "W/m^2"))
        offset = when.hour + weekend*24 + season_of(when.month)*48
        if "electric" in state:
            set_double(model, name, "EU", state["electric"][offset])
            set_double(model, name, "NG", state["gas"][offset])
        occupancy = 0.0
        if "occupancy" in state:
            start, stop, occupied, unoccupied = state["occupancy"][weekend]
            occupancy = occupied if start <= when.hour < stop else unoccupied
        to, eu, ng, nh, qs, ts, ef, ee, eg, gg = cls._v(model, name, "TO", "EU", "NG", "NH", "QS", "TS", "electrification_fraction",
            "electrification_efficiency", "electric_gain_fraction", "gas_gain_fraction")
        return np.array([to, (eu + ef*ng/ee)*eg, (1 - ef)*ng*gg, nh*occupancy, qs, ts])

    @classmethod
    def storage(cls, model:Any, name:str, p:float) -> float:
        """`building::update_storage()`: the battery's load (> 0) or supply
        (< 0) for the power part `p`"""
        bs, es, pg, dt = cls._v(model, name, "BS", "ES", "PG", "dt")
        r = (-min(-p, pg) if p < 0 else min(p, pg)) if pg > 0 else p
        dg = 0.0
        if p < 0 and es < bs:
            stored = min(-p*dt, bs - es, -r*dt)
            es += stored
            dg = stored/dt
        elif p > 0 and es > 0:
            supplied = min(es/dt, r, p)
            es -= supplied*dt
            dg = -supplied
        set_double(model, name, "ES", es)
        return dg

    @classmethod
    def outputs(cls, model:Any, name:str, x:np.ndarray, u:np.ndarray) -> np.ndarray:
        """`y = C x + D u`, then storage and the inverter"""
        qh, pzm, ppm, qpm, area, pze, pie, ppe, qze, qie, qpe, pph, qph, pv, px = cls._v(model, name, "QH", "PZM", "PPM", "QPM",
            "floor_area", "PZE", "PIE", "PPE", "QZE", "QIE", "QPE", "PPH", "QPH", "PV", "PX")
        m = x[2]
        qc = -qh if m < 0 else (qh if get_int(model, name, "electric_heat") else 0.0)
        c = np.zeros((6, 3))
        c[0, 2], c[2, 2], c[5, 2] = pzm*qc, ppm*qc, qpm*qc
        d = np.zeros((6, 6))
        f = area*SF
        d[0, 1], d[1, 1], d[2, 1], d[3, 1], d[4, 1], d[5, 1] = f*pze, f*pie, f*ppe, f*qze, f*qie, f*qpe
        d[2, 3], d[2, 4], d[5, 3] = pph*qh*0.1, -pv, qph*qh*0.01
        y = c @ x + d @ u
        dg = pv*u[4]
        if get_double(model, name, "BS") > 0:
            s = cls.storage(model, name, y[2])
            y[2] += s
            dg -= s
        if dg > 0:
            phases = get_int(model, name, "phases")
            from ._module import top_node # pylint: disable=import-outside-toplevel
            top = top_node(model, name)
            volts = [abs(get_complex(model, top, f"voltage_{x}")) for x, bit in zip("ABC", PHASES) if phases & bit]
            vnom = get_double(model, name, "nominal_voltage")
            v = sum(volts)/len(volts)/vnom if volts and vnom > 0 else 0.0
            ic = inverter_output(object_state(model, name)["inverter"], dg, v, px)
            y[2] += ic.real
            y[5] += ic.imag
        set_double(model, name, "measured_resource_power", dg)
        return y

    @classmethod
    def set_load(cls, model:Any, name:str, y:np.ndarray) -> complex:
        """The ZIP form of the outputs on the building's phases; return the
        total apparent power"""
        phases = get_int(model, name, "phases")
        n = phase_count(model, name) or 1
        if y[2] >= 0:
            parts = [complex(y[k], y[k + 3]) for k in range(3)]
            total = sum(abs(s) for s in parts)
            base = total/n
            fractions = [abs(s)/total if total > 0 else 0.0 for s in parts]
            pfs = [(-1 if s.imag < 0 else 1)*s.real/abs(s) if abs(s) > 0 else 1.0 for s in parts]
            power = sum(parts)
        else:
            net = max(y[0] + y[1] + y[2], -get_double(model, name, "PX"))
            base, fractions, pfs, power = net/n, [0.0, 0.0, 1.0], [1.0, 1.0, 1.0], complex(net, 0)
        for x, bit in zip("ABC", PHASES):
            if phases & bit:
                set_double(model, name, f"base_power_{x}", base)
                for kind, fraction, pf in zip(("impedance", "current", "power"), fractions, pfs):
                    set_double(model, name, f"{kind}_fraction_{x}", fraction)
                    set_double(model, name, f"{kind}_pf_{x}", pf)
        return power

    @classmethod
    def update(cls, model:Any, name:str, t:int) -> None:
        """Inputs, state, outputs, and load at time `t`"""
        state = object_state(model, name)
        a, b = cls.matrices(model, name)
        u = cls.inputs(model, name, t)
        x = np.linalg.solve(a, -b @ u)
        m = x[2]
        qh = get_double(model, name, "QH")
        if m < -1.0:
            msg(model, name).warning(f"cooling control saturation (M={m:.2f}, QH={qh/1000:.1f} kW)")
            x[2] = -1.0
        elif m > 1.0:
            msg(model, name).warning(f"heating control saturation (M={m:.2f}, QH={qh/1000:.1f} kW)")
            x[2] = 1.0
        for prop_, value in zip(("TA", "TM", "M"), x):
            set_double(model, name, prop_, value)
        state["power"] = cls.set_load(model, name, cls.outputs(model, name, x, u))
        state["updated"] = t

    #
    # Solution hooks
    #
    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        """At each `dt`, the model; then the load's values"""
        state = object_state(model, name)
        if "building" in state:
            state["t"] = t0
            if state.get("updated") != t0 and on_interval(model, t0, get_double(model, name, "dt")):
                cls.update(model, name, t0)
        super().before_solve(model, name, t0)

    @classmethod
    def after_solve(cls, model:Any, name:str, t0:int) -> bool:
        """The meter, then the measured voltages"""
        state = object_state(model, name)
        if "building" in state:
            meter_update(model, name, t0, state.get("power", 0j))
        return super().after_solve(model, name, t0)

    @classmethod
    def next_event(cls, model:Any, name:str) -> int|None:
        """The next `dt` and meter interval"""
        t0 = object_state(model, name).get("t")
        if t0 is None:
            return None
        events = [next_interval(model, t0, get_double(model, name, "dt"))] + meter_events(model, name, t0)
        return min(t for t in events if t is not None)

__all__ = ["Building", "inverter_output", "inverter_settings", "loadshape", "occupancy_schedule", "season_of"]
