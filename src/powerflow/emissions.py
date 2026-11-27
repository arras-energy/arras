# pylint: disable=line-too-long
"""Class `emissions`: generation mix and emissions of a meter's energy

Syntax
------

    object emissions {
        parent <meter>;
        cycle_interval <real> s;
        <Source>_Order <real>;               // 0 disables the source
        <Source>_Max_Out <real> kWh;
        <Source>_Conv_Eff <real> Btu/kWh;
        <Source>_CO2 <real> lb/Btu;
        <Source>_SO2 <real> lb/Btu;
        <Source>_NOx <real> lb/Btu;
    }

with `<Source>` one of `Nuclear`, `Hydroelectric`, `Solarthermal`,
`Biomass`, `Wind`, `Coal`, `Naturalgas`, `Geothermal`, `Petroleum`.

Outputs: `<Source>_Out` (kWh), `<Source>_emissions_CO2`, `_SO2`, `_NOx`
(lb), `Total_energy_out` (kWh), and `Total_emissions_CO2`, `_SO2`, `_NOx`
(lb).

Description
-----------

An `emissions` object dispatches the energy its parent `meter` measures
to a merit order of generation sources, as gridlabd's `emissions` does
(published, like it, without the `powerflow_object` properties). After
each solution of a new time (its `postsync`), it adds the real power the
meter measured at the previous time (`measured_power_A + _B + _C`, kW)
times the time elapsed to its energy. At the end of each
`cycle_interval` (900 s by default) it dispatches that energy to the
sources in order 1 to 9: each source produces up to its maximum output
in the cycle (`<Source>_Max_Out` per hour, times `cycle_interval /
3600`) and the last one needed the rest; its emissions are its output
times `<Source>_Conv_Eff` times each emission rate; sources not needed,
and those of order 0, produce nothing. Energy left after every source is
added to `Coal_Out`, with coal's emissions. Then the totals are summed
and the energy restarts from 0. The end of the cycle is a soft event.

When it initializes, it is expected to fail unless its parent is a
`meter`, to set `cycle_interval` to 900 s when it is 0 and fail when it is
negative, and to note each disabled source (order 0) in verbose output.

Caveats
-------

- Exported (negative) energy is not meaningful to the dispatch: the
  sources produce its magnitude while the outputs are subtracted from it,
  as in gridlabd.
- `Region` is published and not used, as in gridlabd.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A source's maximum output in a cycle is `<Source>_Max_Out` times
   `cycle_interval / 3600` at every cycle, and `<Source>_Max_Out` is not
   changed; gridlabd multiplies `<Source>_Max_Out` by
   `cycle_interval / 3600` in place at every new time, so the limits
   shrink (or grow) geometrically during a run.
2. Energy left after every source has coal's emissions; gridlabd adds it
   to `Coal_Out` without them.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/emissions.cpp`,
  `emissions.h`
"""

from typing import Any

from ._base import PowerflowClass, prop
from ._common import TS_NEVER, isa, ref, msg, object_state, get_double, get_complex, set_double, PowerflowError

SOURCES = ("Naturalgas", "Coal", "Biomass", "Geothermal", "Hydroelectric", "Nuclear", "Wind", "Petroleum", "Solarthermal")
"""Generation sources, in gridlabd's order of their outputs"""

DISPATCH = ("Nuclear", "Hydroelectric", "Solarthermal", "Biomass", "Wind", "Coal", "Naturalgas", "Geothermal", "Petroleum")
"""Order gridlabd tests the sources in for each dispatch position (and
their default orders 1 to 9)"""

GASES = ("CO2", "SO2", "NOx")

LABELS = {"Nuclear": "nuclear", "Hydroelectric": "hydro", "Solarthermal": "solar", "Biomass": "biomass", "Wind": "wind",
    "Coal": "coal", "Naturalgas": "natural gas", "Geothermal": "geothermal", "Petroleum": "petroleum"}

class Emissions(PowerflowClass):
    """Behavior of class `emissions`"""

    NAME = "emissions"
    TRL = 0 # TRL_UNKNOWN: gridlabd sets none
    PASSCONFIG = "POSTTOPDOWN|AUTOLOCK"
    EVENTS = ("init", "postsync")
    PROPERTIES = (
        *((f"{x}_Order", "double", prop(default=str(DISPATCH.index(x) + 1))) for x in DISPATCH),
        *((f"{x}_Max_Out[kWh]", "double", prop()) for x in SOURCES),
        *((f"{x}_Out[kWh]", "double", prop()) for x in SOURCES),
        *((f"{x}_Conv_Eff[Btu/kWh]", "double", prop()) for x in SOURCES),
        *((f"{x}_{gas}[lb/Btu]", "double", prop()) for gas in GASES for x in SOURCES),
        *((f"{x}_emissions_{gas}[lb]", "double", prop()) for x in SOURCES for gas in GASES),
        *((f"Total_emissions_{gas}[lb]", "double", prop()) for gas in GASES),
        ("Total_energy_out[kWh]", "double", prop()),
        ("Region", "double", prop()),
        ("cycle_interval[s]", "double", prop()),
    )

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`emissions::init()`"""
        from ._common import runner # pylint: disable=import-outside-toplevel
        out = msg(model, name)
        obj = model.objects[name]
        try:
            parent = ref(model, name, "parent")
            if parent is None or not isa(model, parent, "meter"):
                raise PowerflowError(f"emissions:{name} must be parented to a three-phase meter to work!")
            if get_double(model, name, "cycle_interval") == 0:
                set_double(model, name, "cycle_interval", 900.0)
            if get_double(model, name, "cycle_interval") <= 0:
                raise PowerflowError(f"emissions:{name} must have a positive cycle_interval time")
        except PowerflowError as err:
            label = name if name != f"{obj.oclass.name}:{obj.id}" else "unnamed"
            runner().error(f"{label} {obj.oclass.name} (id={obj.id}): {err}")
            return False
        for source in DISPATCH:
            if get_double(model, name, f"{source}_Order") == 0:
                out.verbose(f"Emissions:{name} has {LABELS[source]} disabled.")
        object_state(model, name).update(interval=int(get_double(model, name, "cycle_interval")), prev=0, curr=0,
            next_cycle=0, energy=0.0, power=0.0)
        return True

    @classmethod
    def dispatch(cls, model:Any, name:str, energy:float) -> None:
        """Dispatch a cycle's energy (kWh) to the sources"""
        hours = get_double(model, name, "cycle_interval")/3600
        left, needed = energy, True
        for position in range(10):
            for source in DISPATCH:
                if get_double(model, name, f"{source}_Order") != position:
                    continue
                limit = get_double(model, name, f"{source}_Max_Out")*hours
                if position != 0 and needed and limit < abs(left):
                    output = limit
                    left -= limit
                elif position != 0 and needed:
                    output = abs(left)
                    needed = False
                    left -= output
                else:
                    output = 0.0
                cls.produce(model, name, source, output)
        if abs(left) > 0:
            coal = get_double(model, name, "Coal_Out") + abs(left)
            cls.produce(model, name, "Coal", coal)
        set_double(model, name, "Total_energy_out", sum(get_double(model, name, f"{x}_Out") for x in SOURCES))
        for gas in GASES:
            set_double(model, name, f"Total_emissions_{gas}", sum(get_double(model, name, f"{x}_emissions_{gas}") for x in SOURCES))

    @classmethod
    def produce(cls, model:Any, name:str, source:str, output:float) -> None:
        """A source's output (kWh) and emissions (lb)"""
        set_double(model, name, f"{source}_Out", output)
        efficiency = get_double(model, name, f"{source}_Conv_Eff")
        for gas in GASES:
            set_double(model, name, f"{source}_emissions_{gas}", output*efficiency*get_double(model, name, f"{source}_{gas}"))

    @classmethod
    def postsync(cls, model:Any, name:str, t:int) -> int:
        """`emissions::postsync()`"""
        state = object_state(model, name)
        if "interval" not in state:
            return TS_NEVER
        if state["prev"] == 0 and t != 0:
            state["next_cycle"] = t + state["interval"]
        if state["prev"] != t:
            state["curr"] = t
            state["energy"] += state["power"]*(t - state["prev"])/3600
            state["prev"] = t
        if state["curr"] == t:
            parent = ref(model, name, "parent")
            state["power"] = sum(get_complex(model, parent, f"measured_power_{x}") for x in "ABC").real/1000.0
        if state["curr"] >= state["next_cycle"]:
            cls.dispatch(model, name, state["energy"])
            state["energy"] = 0.0
            state["next_cycle"] += state["interval"]
        return -state["next_cycle"]

__all__ = ["Emissions"]
