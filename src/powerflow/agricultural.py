# pylint: disable=line-too-long
"""Class `agricultural`: a scheduled agricultural load with a linear sensitivity

Syntax
------

    object agricultural {
        phases {A,B,C}[D|N];
        nominal_voltage <real> V;
        P0 <real> W;                    // nameplate power
        Pz <real> pu;                   // load composition: also Pi, Ma, Mb, Mc, Md, Pe
        Pf <real> pu;                   // power factor (default 1)
        schedule "<M-M>,<D-D>,<H-H>,<values>;...";
        sensitivity_source "<object>.<property>";   // or a global
        sensitivity_base <real>;
        sensitivity_value <real>;
        measured_energy_delta_timestep <real> s;     // default 1 h
        measured_demand_timestep <real> s;           // default 1 h
        // and the other properties of load
    }

Outputs: `measured_real_power` (W), `measured_reactive_power` (VAr),
`measured_real_energy`, `measured_reactive_energy` (Wh), their
`_delta` over the last energy interval, and `measured_demand` (W).

Description
-----------

An `agricultural` object (gridlabd `PT_INHERIT "load"`) is a load whose
ZIP form follows a schedule of fractions of its nameplate power `P0`, as
gridlabd's `agricultural` does. The classes `public_service` and
`industrial` work the same way, with a threshold or an industry
composition in place of the sensitivity.

The schedule is given by one or more `schedule` values, each with records
separated by `;` (or new lines): `M-M,D-D,H-H,` (closed ranges of months
1-12, weekdays 0-6 with Monday 0, and hours 0-23), then the total load
`Pt` (per unit `P0`), `Pt,Pf` with its power factor, the fractions of the
components `A,B,C,D,E,Z,I` (motors A to D, power electronics, impedance,
current), or `A,B,C,D,E,Z,I,Pf`; a later record overrides an earlier one,
and the hours no record covers have no load. The power factor is `Pf`
when a record has none (1 for `industrial`); a negative one is leading.

At the top of each hour (an event the object asks for), for the local
month, weekday, and hour, the load's real power parts are (with the
composition `Pz` ... `Pe` normalized to sum to 1 when it initializes)

- for a total `Pt`: `Z = Pz Pt P0`, `I = Pi Pt P0`, and `P = (Ma + Mb + Mc
  + Md + Pe) Pt P0`;
- for components: `Z = Pz z P0`, `I = Pi i P0`, and `P = (Ma a + Mb b + Mc
  c + Md d + Pe e) P0`;
- with a `sensitivity_source`, the three parts are scaled by `(S + value x
  + base) / S`, with `S = Z + I + P` and `x` the source's value.

Each phase of the load (`A`, `B`, `C` of its phases) takes an equal share
of the parts as the `load` ZIP form: `base_power_X` is the share over the
power factor's magnitude (so its real part is the share), the fractions
are the parts' shares of the total, and the three power factors are the
schedule's.

The meter, after each solution: `measured_real_power` and
`measured_reactive_power` are the scheduled load (the total real power and
its reactive power at the power factor); at each new time, the energy
since the last time is added at the power metered then; at each
`measured_energy_delta_timestep` (local time, counted from Sunday
1970-01-04, as gridlabd counts them), the energy deltas over the interval
are written; and at each `measured_demand_timestep`, `measured_demand`
is the largest real power metered over the interval. The interval times
are events too.

When it initializes, an agricultural load fails when `P0` is not
positive, when the composition sums to 0, when the sensitivity source is
not an object property or a global, and when a schedule record is
invalid; it warns when the composition does not sum to 1 (and normalizes
it), for each hour whose total is out of 0 to 1 or whose power factor is
out of -1 to 1, and when the schedule has no load.

Caveats
-------

- The meter reports the scheduled load, not the load drawn at the solved
  voltage, as in gridlabd.
- The sensitivity can make the load negative (a generator), as in
  gridlabd.
- The loads change only at the top of the hour (UTC multiples of 3600 s),
  so a run that starts within an hour has no load until the next one.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. Weekdays are numbered from Monday (0) to Sunday (6), as gridlabd's
   documentation says; gridlabd's code uses its weekday numbers, Sunday 0
   to Saturday 6, so a record for weekdays 0-4 covers Sunday to Thursday.
2. The meter works: gridlabd does not export the class's `commit()`, so
   it never runs, the energy is never accumulated, and `measured_demand`
   stays 0. The energy is added at each new time; gridlabd's
   `postsync()` would add it only at the energy intervals. The demand is
   the largest power over each demand interval; gridlabd's never resets.
3. The meter's power and demand are updated after each solution;
   gridlabd updates the power only at the energy intervals.
4. `base_power_X` is the share of the real power over the power factor's
   magnitude, so the load draws the scheduled real power; gridlabd sets
   it to the share, so the load draws `|Pf|` times it while the meter
   reports the scheduled power.
5. A load with fewer than three phases takes the whole load on its
   phases; gridlabd gives each of `A`, `B`, `C` a third, so a
   single-phase load draws a third of its schedule.
6. The meter's reactive power of a leading power factor is negative;
   gridlabd's `(pf<0?-1:1)*tan(acos(pf))` makes it positive.
7. An invalid sensitivity source fails the initialization; gridlabd
   writes the error and reads the invalid property in each hour.
8. Schedule records are read when the object initializes, with the
   final `Pf` as their default power factor; gridlabd reads each record
   as the property is set, with `Pf` as it is then.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/agricultural.cpp`,
  `agricultural.h`, `docs/Module/Powerflow/Agricultural.md`,
  `module/powerflow/autotest/test_agricultural.glm`
"""

from typing import Any

from ._base import prop
from ._common import TRL_PROVEN, msg, object_state, get_double, set_double, set_text, PowerflowError
from .load import Load
from .scheduled_load import (METER_PROPERTIES, Composition, local_time, meter_check, meter_events, meter_update,
    parse_schedule, schedule_text, set_zip, source_property, source_value)

COMPONENTS = ("Pz", "Pi", "Ma", "Mb", "Mc", "Md", "Pe")
"""Load composition fractions"""

COMPOSITION_PROPERTIES = (
    ("Pz[pu]", "double", prop("constant impedance load fraction")),
    ("Pi[pu]", "double", prop("constant current load fraction")),
    ("Ma[pu]", "double", prop("motor type A load fraction")),
    ("Mb[pu]", "double", prop("motor type B load fraction")),
    ("Mc[pu]", "double", prop("motor type C load fraction")),
    ("Md[pu]", "double", prop("motor type D load fraction")),
    ("Pe[pu]", "double", prop("power electronics load fraction")),
)

def schedule_property() -> tuple:
    """The `schedule` method property"""
    return ("schedule", "method", prop("load schedule specification (<month>,<weekday>,<hour>-<hour>,<float>;...)", flags="REQUIRED"))

def nameplate_property(kind:str) -> tuple:
    """The `P0` property"""
    return ("P0[W]", "double", prop(f"{kind} load nameplate power", flags="REQUIRED"))

class ScheduledLoad(Load):
    """Behavior shared by `agricultural`, `public_service`, and
    `industrial` (not a registered class)"""

    PARENT = "load"
    TRL = TRL_PROVEN
    PASSCONFIG = "PRETOPDOWN|BOTTOMUP|POSTTOPDOWN|UNSAFE_OVERRIDE_OMIT|AUTOLOCK|OBSERVER"
    TOTALS = True
    """Whether a composite record's total is the sum of its parts"""

    @classmethod
    def default_pf(cls, model:Any, name:str) -> float:
        """Power factor of a record without one"""
        return get_double(model, name, "Pf")

    @classmethod
    def init_composition(cls, model:Any, name:str) -> None:
        """Check and normalize the composition; raises `PowerflowError`"""
        values = [get_double(model, name, x) for x in COMPONENTS]
        total = sum(values)
        if total == 0:
            raise PowerflowError(f"{name}: load components sum to zero")
        if abs(total - 1.0) > 1e-3:
            msg(model, name).warning(f"load components do not sum to 1.0 (sum={total:.4g}), normalizing automatically ")
        for key, value in zip(COMPONENTS, values):
            set_double(model, name, key, value/total)

    @classmethod
    def init_source(cls, model:Any, name:str) -> None:
        """Find the class's source property; raises `PowerflowError`"""

    @classmethod
    def check_schedule(cls, model:Any, name:str, table:dict) -> None:
        """Warn about invalid hours and a schedule without load"""
        total = 0.0
        out = msg(model, name)
        for month in range(12):
            for day in range(7):
                for hour in range(24):
                    item = table.get((month, day, hour), Composition(pf=0.0))
                    if item.total < 0 or item.total > 1:
                        out.warning(f"invalid load schedule {'aggregated' if item.aggregate else 'disaggregated'} total {item.total:.4g} for month {month}, weekday {day}, hour {hour}")
                    elif item.pf < -1 or item.pf > 1:
                        out.warning(f"invalid load schedule power factor {item.pf:.4g} for month {month}, weekday {day}, hour {hour}")
                    else:
                        total += item.total
        if total == 0:
            out.warning("missing or null load schedule")

    @classmethod
    def init_node(cls, model:Any, name:str) -> None:
        """`agricultural::init()`; raises `PowerflowError`"""
        if get_double(model, name, "P0") <= 0:
            raise PowerflowError(f"{name}: nameplate power P0 must be positive")
        meter_check(name, model)
        cls.init_composition(model, name)
        cls.init_source(model, name)
        text = str(model.get_property(name, "schedule") or "")
        try:
            table = parse_schedule(text, cls.default_pf(model, name), cls.TOTALS)
        except PowerflowError as err:
            raise PowerflowError(f"{name}: {err}") from err
        set_text(model, name, "schedule", schedule_text(text))
        object_state(model, name)["schedule"] = table
        if cls.TOTALS:
            cls.check_schedule(model, name, table)
        super().init_node(model, name)

    @classmethod
    def parts(cls, model:Any, name:str, item:Composition) -> tuple[float,float,float]:
        """The impedance, current, and power parts (W) of an hour"""
        p0 = get_double(model, name, "P0")
        pz, pi, ma, mb, mc, md, pe = (get_double(model, name, x) for x in COMPONENTS)
        if item.aggregate:
            return pz*item.total*p0, pi*item.total*p0, (ma + mb + mc + md + pe)*item.total*p0
        return pz*item.z*p0, pi*item.i*p0, (ma*item.a + mb*item.b + mc*item.c + md*item.d + pe*item.e)*p0

    @classmethod
    def adjust(cls, model:Any, name:str, parts:tuple[float,float,float]) -> tuple[float,float,float]: # pylint: disable=unused-argument
        """The parts after the class's sensitivity or threshold"""
        return parts

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        """At the top of the hour, the ZIP form of the hour; then the
        load's values"""
        state = object_state(model, name)
        if "schedule" in state:
            state["t"] = t0
            if t0 % 3600 == 0:
                when = local_time(model, t0)
                item = state["schedule"].get((when.month - 1, when.weekday(), when.hour), Composition(pf=0.0))
                parts = cls.adjust(model, name, cls.parts(model, name, item))
                state["power"] = set_zip(model, name, parts, item.pf)
        super().before_solve(model, name, t0)

    @classmethod
    def after_solve(cls, model:Any, name:str, t0:int) -> bool:
        """The meter, then the measured voltages"""
        state = object_state(model, name)
        if "schedule" in state:
            meter_update(model, name, t0, state.get("power", 0j))
        return super().after_solve(model, name, t0)

    @classmethod
    def next_event(cls, model:Any, name:str) -> int|None:
        """The next hour and meter interval"""
        t0 = object_state(model, name).get("t")
        if t0 is None:
            return None
        return min([(t0//3600 + 1)*3600] + meter_events(model, name, t0))

class Agricultural(ScheduledLoad):
    """Behavior of class `agricultural`"""

    NAME = "agricultural"
    PROPERTIES = (
        schedule_property(),
        nameplate_property("agricultural"),
        ("sensitivity_source", "char256", prop("source for sensitivity value")),
        ("sensitivity_base", "double", prop("load sensitivity constant")),
        ("sensitivity_value", "double", prop("load sensitivity slope")),
        *COMPOSITION_PROPERTIES,
        ("Pf[pu]", "double", prop("power factor", "+1 pu")),
        *METER_PROPERTIES,
    )

    @classmethod
    def init_source(cls, model:Any, name:str) -> None:
        """The sensitivity source"""
        text = str(model.get_property(name, "sensitivity_source") or "").strip('"')
        source = None
        if text:
            source = source_property(model, text)
            if source is None:
                raise PowerflowError(f"{name}: sensitivity source '{text}' is not valid")
        object_state(model, name)["source"] = source

    @classmethod
    def adjust(cls, model:Any, name:str, parts:tuple[float,float,float]) -> tuple[float,float,float]:
        """The sensitivity scaling"""
        source = object_state(model, name).get("source")
        total = sum(parts)
        if source is None or total == 0:
            return parts
        x = source_value(model, source)
        scale = (total + get_double(model, name, "sensitivity_value")*x + get_double(model, name, "sensitivity_base"))/total
        return tuple(part*scale for part in parts)

__all__ = ["Agricultural", "ScheduledLoad"]
