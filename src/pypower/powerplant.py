# pylint: disable=line-too-long
"""Class `powerplant`: a power plant on a bus or a generator

Syntax
------

    object pypower.powerplant {
        parent <bus|gen>;
        city "<text>";
        county "<text>";
        state "<text>";
        zipcode "<text>";
        country "<text>";
        naics_code "<text>";
        naics_description "<text>";
        plant_code "<text>";
        generator {UNKNOWN,HT,ST,AT,IC,FW,WT,ES,CT,PV,CC,CS}[|...];
        fuel {ELEC,WIND,SUN,GEO,COKE,WASTE,BIO,OIL,UNKNOWN,WOOD,OTHER,GAS,NUC,WATER,COAL,NG}[|...];
        status {OFFLINE,ONLINE};
        operating_capacity <real> MW;
        summer_capacity <real> MW;
        winter_capacity <real> MW;
        capacity_factor <real> pu;
        substation_1 "<text>";
        substation_2 "<text>";
        storage_capacity <real> MWh;
        charging_capacity <real> MW;
        storage_efficiency <real> pu;
        state_of_charge <real> pu;
        S <complex> MVA;
        controller "<function>";
        startup_cost <real> $;
        shutdown_cost <real> $;
        fixed_cost <real> $/h;
        variable_cost <real> $/MWh;
        scarcity_cost <real> $/MW^2/h;
        energy_rate <real> MWh/unit;
        ramp_rate <real> MW/min;
        total_cost <real> $;
        emissions_rate <real> tonne/MWh;
        total_emissions <real> tonne;
        Pg <real> MW;
        Qg <real> MW;
        Tnominal <real> degC;
        derating <real> pu/degC;
        Tcutoff <real> degC;
        weather <weather>;
    }

Description
-----------

A powerplant on a bus is a negative load of the bus (its output is
subtracted from the bus's `Pd` and `Qd`); a powerplant on a generator is
dispatchable: it adds its output and capacity to the generator. Given a
model, a powerplant is expected to:

1. refuse a parent that is missing or is neither a pypower bus nor a
   pypower gen; on a generator, register with it (and warn when it has a
   storage capacity, which cannot be dispatched);
2. find the `gencost` object whose parent is its parent, if any, and the
   `controller` function (as a `load` does); make a negative `ramp_rate`
   positive with a warning; warn when a fuel that burns has no variable
   cost (and no emissions rate when `pypower::with_emissions` is true);
3. with a `weather` object and nonzero `derating` and `Tcutoff`, refuse a
   weather object that is not a pypower weather object, a `Tcutoff` not
   above `Tnominal`, and a negative `derating`;
4. at each precommit, unless `OFFLINE`: after its first time, take the
   generator's output as its setpoint `S` (its OPF setpoints `Ps`, `Qs`
   when the OPF is not enabled, its `Pg`, `Qg` when it is), move `Pg` and
   `Qg` toward `S` by at most `ramp_rate` per minute (or set them to `S`
   without a ramp rate), and, with a storage capacity, add the energy
   charged (`S.real` limited to `charging_capacity`, times the hours since
   the last precommit and `storage_efficiency`) to `state_of_charge`
   (limited to 0..1); then derate the capacity `operating_capacity` by
   `derating` per degree of the weather's `Td` above `Tnominal` (0 above
   `Tcutoff`), and post its costs to its gencost (`POLYNOMIAL`, startup and
   shutdown costs, and `scarcity_cost,variable_cost,fixed_cost`);
5. at each presync, unless `OFFLINE`, add the derated capacity and the
   change of `Pg` and `Qg` since its last presync to the generator (which
   sets its reactive limits), or subtract `Pg` and `Qg` from the bus's
   demand; an `OFFLINE` powerplant removes the output it added to its
   generator;
6. at each sync, call its controller, if any, as
   `controller(NAME, city=, state=, zipcode=, country=, naics_code=,
   naics_description=, plant_code=, generator=, fuel=,
   operating_capacity=, summer_capacity=, winter_capacity=,
   capacity_factor=, substation_1=, substation_2=, S=, Vm=, Va=, controller=,
   t=, Pg=, Qg=, gen_cf=)` (`Vm` and `Va` only on a bus) and set the
   properties it returns, as a load does; its `t` is the time of the next
   event;
7. at each commit, add to `total_cost` the startup cost (times
   `operating_capacity`) when its output starts, the shutdown cost (times
   `operating_capacity`) when it stops, and the fixed, variable, and
   scarcity costs of the energy of the previous output over the hours
   since the previous commit; with `pypower::with_emissions`, add
   `emissions_rate` times that energy to `total_emissions`.

Caveats
-------

- `Qg` is published in MW and described as reactive power, as in
  gridlabd.
- The ramp computes the changes `DS = min(ramp_rate, |S| - |Pg+jQg|)`,
  `DQ = min(DS, Qg - S.imag)`, `DP = min(sqrt(DS^2-DQ^2), Pg - S.real)`
  and moves `Pg`, `Qg` by `sign(Pg-S.real) DP` and `sign(Qg-S.imag) DQ`,
  as gridlabd does.
- The generator's `Pg` and `Qg` that a dispatchable powerplant takes as
  its setpoint are the totals of all its powerplants.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A powerplant on a generator adds the change of its output at each
   presync, and removes it when it goes `OFFLINE`; gridlabd adds its
   whole output at each presync, so the generator's totals grow with the
   iterations of a time step (see `pypower.gen`,
   arras-energy/gridlabd#410).
2. `emissions_rate` and `total_emissions` are their own values. gridlabd
   publishes them at the addresses of `energy_rate` and `total_cost`, so
   they read and write those properties.
3. Costs accumulate over the hours since the previous commit, as a
   decimal number. gridlabd computes the hours from the time of the last
   precommit, which is the commit time, with integer division, so only
   startup and shutdown costs accumulate.
4. `total_emissions` accumulates `emissions_rate` times the energy;
   gridlabd sets it to `emissions_rate` times the energy times the hours
   (0, see 3) at each commit.
5. A controller exception is written as one error line (gridlabd prints
   the Python traceback).

References
----------

- `arras-energy/gridlabd`: `module/pypower/powerplant.cpp`, `powerplant.h`
"""

import math
from typing import Any

from ._base import PypowerClass, prop, keywords, msg
from ._common import (TS_NEVER, TS_INVALID, MODULE, object_state, global_value, isa, parent_of, ref,
    get_double, get_complex, get_int, get_text, set_double, set_complex, set_int, set_text, fdiv, csqrt)
from ._module import ensure_init
from . import _controller
from .gen import Gen, add_powerplant, add_output, add_pmax
from .gencost import CM_POLYNOMIAL
from .load import clock

GENERATOR_TYPES = (("UNKNOWN", 0x0001), ("HT", 0x0002), ("ST", 0x0004), ("AT", 0x0008), ("IC", 0x0010),
    ("FW", 0x0020), ("WT", 0x0040), ("ES", 0x0080), ("CT", 0x0100), ("PV", 0x0200), ("CC", 0x0400),
    ("CS", 0x0800))
"""Generator type keywords in publication order"""

FUEL_TYPES = (("ELEC", 0x0001), ("WIND", 0x0002), ("SUN", 0x0004), ("GEO", 0x0008), ("COKE", 0x0010),
    ("WASTE", 0x0020), ("BIO", 0x0040), ("OIL", 0x0080), ("UNKNOWN", 0x0100), ("WOOD", 0x0200),
    ("OTHER", 0x0400), ("GAS", 0x0800), ("NUC", 0x1000), ("WATER", 0x2000), ("COAL", 0x4000),
    ("NG", 0x8000))
"""Fuel keywords in publication order"""

FT_ELECTRICITY = 0x0001
FT_BURNING = (0x0010, 0x0040, 0x0080, 0x0200, 0x0800, 0x8000, 0x4000)
"""Coke, biomass, oil, wood, gas, natural gas, coal"""

GS_OFFLINE, GS_ONLINE = 0, 1

class Powerplant(PypowerClass):
    """Behavior of class `powerplant`"""

    NAME = "powerplant"
    PASSCONFIG = "PRETOPDOWN|BOTTOMUP|AUTOLOCK|OBSERVER"
    PROPERTIES = (
        ("city", "char32", prop("City in which powerplant is located")),
        ("county", "char32", prop("County in which powerplant is located")),
        ("state", "char32", prop("State in which powerplant is located")),
        ("zipcode", "char32", prop("Zipcode in which powerplant is located")),
        ("country", "char32", prop("Country in which powerplant is located")),
        ("naics_code", "char32", prop("Powerplant NAICS code")),
        ("naics_description", "char256", prop("Powerplant NAICS description")),
        ("plant_code", "char32", prop("Generator plant code number")),
        ("generator", "set", prop("Generator type", keywords=keywords(*GENERATOR_TYPES))),
        ("fuel", "set", prop("Generator fuel type", keywords=keywords(*FUEL_TYPES))),
        ("status", "enumeration", prop("Generator status", keywords=keywords(("OFFLINE", GS_OFFLINE), ("ONLINE", GS_ONLINE)))),
        ("operating_capacity[MW]", "double", prop("Generator normal operating capacity (MW)")),
        ("summer_capacity[MW]", "double", prop("Generator summer operating capacity (MW)")),
        ("winter_capacity[MW]", "double", prop("Generator winter operating capacity (MW)")),
        ("capacity_factor[pu]", "double", prop("Generator capacity factor (pu)")),
        ("substation_1", "char256", prop("Substation 1 id")),
        ("substation_2", "char256", prop("Substation 2 id")),
        ("storage_capacity[MWh]", "double", prop("Energy storage capacity (MWh)")),
        ("charging_capacity[MW]", "double", prop("Energy storage charging capacity (MW)")),
        ("storage_efficiency[pu]", "double", prop("Energy storage round-trip efficiency (pu)", "1 pu")),
        ("state_of_charge[pu]", "double", prop("Energy storage state of charge (pu)")),
        ("S[MVA]", "complex", prop("power generation setpoint (MVA)")),
        ("controller", "char256", prop("controller python function name")),
        ("startup_cost[$]", "double", prop("generator startup cost ($)")),
        ("shutdown_cost[$]", "double", prop("generator shutdown cost ($)")),
        ("fixed_cost[$/h]", "double", prop("generator fixed cost ($/h)")),
        ("variable_cost[$/MWh]", "double", prop("generator variable cost ($/MWh)")),
        ("scarcity_cost[$/MW^2/h]", "double", prop("generator scarcity cost ($/MW^2h)")),
        ("energy_rate[MWh/unit]", "double", prop("generator heat rate/fuel efficiency (MWh/unit)")),
        ("ramp_rate[MW/min]", "double", prop("generator ramp rate (MWH/min)")),
        ("total_cost[$]", "double", prop("generator total operating cost ($)")),
        ("emissions_rate[tonne/MWh]", "double", prop("generator heat rate/fuel efficiency (tonne/MWh)")),
        ("total_emissions[tonne]", "double", prop("generator total operating cost (tonne)")),
        ("Pg[MW]", "double", prop("generator actual real power output (MW)")),
        ("Qg[MW]", "double", prop("generator actual reactive power output (MW)")),
        ("Tnominal[degC]", "double", prop("powerplant nominal operating temperature (degC)")),
        ("derating[pu/degC]", "double", prop("powerplant temperature derating constant (pu/degC)")),
        ("Tcutoff[degC]", "double", prop("powerplant cutoff temperature (degC)")),
        ("weather", "object", prop("weather object")),
    )
    EVENTS = ("init", "precommit", "presync", "sync", "commit")

    @classmethod
    def state(cls, model:Any, name:str) -> dict[str,Any]:
        """State of a powerplant: `controller`, `is_dynamic` (on a
        generator), `last_t` (last precommit), `last_commit`, `last_Sm`
        (output magnitude at the last commit), `gen_cf`, `weather`,
        `costobj`, `pmax` (derated capacity), `added` (output added to the
        generator)"""
        return object_state(model, name, lambda: {"controller": None, "is_dynamic": False, "last_t": 0,
            "last_commit": None, "last_Sm": 0.0, "gen_cf": 1.0, "weather": None, "costobj": None, "pmax": 0.0,
            "added": (0.0, 0.0)})

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`powerplant::init()`"""
        # pylint: disable=too-many-return-statements,too-many-branches
        if not ensure_init(model):
            return False
        out = msg(model, name)
        state = cls.state(model, name)
        parent = parent_of(model, name)
        if parent is None:
            out.error("powerplant must have a bus or gen parent")
            return False
        if isa(model, parent, "gen"):
            state["is_dynamic"] = True
            add_powerplant(model, parent, name)
            if get_double(model, name, "storage_capacity") > 0:
                out.warning("energy storage devices cannot be dynamically dispatchable (parent is a generator)")
        elif isa(model, parent, "bus"):
            state["is_dynamic"] = False
        else:
            out.error(f"parent '{parent}' is not a pypower bus or gen object")
            return False
        for obj in model.objects:
            if isa(model, obj, "gencost"):
                if parent_of(model, obj) == parent:
                    state["costobj"] = obj
                    break
        ramp = get_double(model, name, "ramp_rate")
        if ramp < 0:
            out.warning("negative ramp rate is fixed by making it positive")
            set_double(model, name, "ramp_rate", abs(ramp))
        controller = _controller.find(model, name)
        if controller is False:
            return False
        state["controller"] = controller
        fuel = get_int(model, name, "fuel")
        if fuel in FT_BURNING:
            if global_value(model, f"{MODULE}::with_emissions") and get_double(model, name, "emissions_rate") == 0.0:
                out.warning("no emissions rate given for a unit that should have a non-zero emissions")
        if fuel in FT_BURNING or fuel == FT_ELECTRICITY:
            if get_double(model, name, "variable_cost") == 0.0:
                out.warning("no variable cost given for a unit that should have a non-zero fuel cost")
        weather = ref(model, name, "weather")
        derating, tcutoff, tnominal = get_double(model, name, "derating"), get_double(model, name, "Tcutoff"), get_double(model, name, "Tnominal")
        if weather is not None and derating != 0 and tcutoff != 0:
            out.verbose(f"linking powerplant performance to '{weather}.Td'")
            if not isa(model, weather, "weather"):
                out.error(f"object '{weather}' is not a pypower weather object")
                return False
            state["weather"] = weather
            if tnominal >= tcutoff:
                out.error("Tcutoff is not greater than Tnominal")
                return False
            if derating < 0:
                out.error("derating must be non-negative")
                return False
            if derating*(tcutoff-tnominal) > 1.0:
                out.warning(f"derating cutoff is actually {1/derating+tnominal:.1f} degC not {tcutoff:.1f}")
        return True

    @classmethod
    def precommit(cls, model:Any, name:str, t:int) -> int:
        """`powerplant::precommit()`"""
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        if get_int(model, name, "status") == GS_OFFLINE:
            return TS_NEVER
        out = msg(model, name)
        state = cls.state(model, name)
        if state["last_t"] > 0:
            setpoint = get_complex(model, name, "S")
            if state["is_dynamic"]:
                parent = parent_of(model, name)
                state["gen_cf"] = fdiv(get_double(model, name, "operating_capacity"), get_double(model, parent, "Pmax"))
                if global_value(model, f"{MODULE}::enable_opf"):
                    setpoint = complex(get_double(model, parent, "Pg"), get_double(model, parent, "Qg"))
                else:
                    gen = Gen.state(model, parent)
                    setpoint = complex(gen["Ps"], gen["Qs"])
                set_complex(model, name, "S", setpoint)
            pg, qg = get_double(model, name, "Pg"), get_double(model, name, "Qg")
            ramp = get_double(model, name, "ramp_rate")
            if ramp > 0 and pg != setpoint.real:
                out.debug(f"ramping from {pg:.1f}{qg:+.1f}j MVA to {setpoint.real:.1f}{setpoint.imag:+.1f}j MVA")
                ds = min(ramp, abs(setpoint) - math.sqrt(pg*pg+qg*qg))
                dq = min(ds, qg-setpoint.imag)
                dp = min(csqrt(ds*ds-dq*dq), pg-setpoint.real)
                pg += _sign(pg-setpoint.real)*dp
                qg += _sign(qg-setpoint.imag)*dq
                out.debug(f"ramping delta-t is {ds/ramp*60:.0f} seconds")
            else:
                pg, qg = setpoint.real, setpoint.imag
            set_double(model, name, "Pg", pg)
            set_double(model, name, "Qg", qg)
            capacity = get_double(model, name, "storage_capacity")
            if capacity > 0:
                hours = (t - state["last_t"])/3600.0
                charging = get_double(model, name, "charging_capacity")
                energy = min(max(setpoint.real, -charging), charging)
                total = capacity*get_double(model, name, "state_of_charge") + energy*hours*get_double(model, name, "storage_efficiency")
                if total > capacity:
                    set_double(model, name, "state_of_charge", 1.0)
                elif total < 0:
                    set_double(model, name, "state_of_charge", 0.0)
                else:
                    set_double(model, name, "state_of_charge", total/capacity)
        state["last_t"] = t
        pmax = get_double(model, name, "operating_capacity")
        weather = state["weather"]
        if weather is not None:
            td, tnominal = get_double(model, weather, "Td"), get_double(model, name, "Tnominal")
            if td > tnominal:
                if td > get_double(model, name, "Tcutoff"):
                    pmax = 0.0
                else:
                    pmax = max(pmax*(1 - (td - tnominal)*get_double(model, name, "derating")), 0.0)
                out.verbose(f"powerplant rating at {td:.1f} degC is {pmax:.1f} MW")
        state["pmax"] = pmax
        cost = state["costobj"]
        if cost is not None:
            set_int(model, cost, "model", CM_POLYNOMIAL)
            set_double(model, cost, "startup", get_double(model, name, "startup_cost"))
            set_double(model, cost, "shutdown", get_double(model, name, "shutdown_cost"))
            set_text(model, cost, "costs", f"{get_double(model, name, 'scarcity_cost'):f},{get_double(model, name, 'variable_cost'):f},{get_double(model, name, 'fixed_cost'):f}")
        return TS_NEVER

    @classmethod
    def presync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`powerplant::presync()`: add the output to the parent"""
        state = cls.state(model, name)
        parent = parent_of(model, name)
        if get_int(model, name, "status") == GS_OFFLINE:
            if state["is_dynamic"] and state["added"] != (0.0, 0.0):
                add_output(model, parent, -state["added"][0], -state["added"][1])
                state["added"] = (0.0, 0.0)
            return TS_NEVER
        pg, qg = get_double(model, name, "Pg"), get_double(model, name, "Qg")
        if state["is_dynamic"]:
            last_pg, last_qg = state["added"]
            add_output(model, parent, pg - last_pg, qg - last_qg)
            state["added"] = (pg, qg)
            add_pmax(model, parent, state["pmax"])
        else:
            set_double(model, parent, "Pd", get_double(model, parent, "Pd") - pg)
            set_double(model, parent, "Qd", get_double(model, parent, "Qd") - qg)
        return TS_NEVER

    @classmethod
    def sync(cls, model:Any, name:str, t:int) -> int:
        """`powerplant::sync()`: call the controller"""
        state = cls.state(model, name)
        controller = state["controller"]
        if controller is None:
            return TS_NEVER
        kwargs: dict[str,Any] = {}
        for key in ("city", "state", "zipcode", "country", "naics_code", "naics_description", "plant_code"):
            kwargs[key] = get_text(model, name, key)
        for key in ("generator", "fuel"):
            kwargs[key] = get_int(model, name, key)
        for key in ("operating_capacity", "summer_capacity", "winter_capacity", "capacity_factor"):
            kwargs[key] = get_double(model, name, key)
        for key in ("substation_1", "substation_2"):
            kwargs[key] = get_text(model, name, key)
        kwargs["S"] = get_complex(model, name, "S")
        parent = parent_of(model, name)
        if isa(model, parent, "bus"):
            kwargs["Vm"] = get_double(model, parent, "Vm")
            kwargs["Va"] = get_double(model, parent, "Va")
        kwargs["controller"] = get_text(model, name, "controller")
        kwargs["t"] = float(clock(model))
        kwargs["Pg"] = get_double(model, name, "Pg")
        kwargs["Qg"] = get_double(model, name, "Qg")
        kwargs["gen_cf"] = state["gen_cf"]
        result = _controller.call(model, name, controller, kwargs, t, on_set="quiet")
        if result is None:
            return TS_INVALID
        return result[0]

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int:
        """`powerplant::commit()`: costs and emissions"""
        state = cls.state(model, name)
        last = state["last_commit"]
        hours = (t - last)/3600.0 if last is not None else 0.0
        pg, qg = get_double(model, name, "Pg"), get_double(model, name, "Qg")
        magnitude = math.sqrt(pg*pg+qg*qg)
        capacity = get_double(model, name, "operating_capacity")
        total = get_double(model, name, "total_cost")
        if state["last_Sm"] == 0 and magnitude != 0:
            total += get_double(model, name, "startup_cost")*capacity
        elif state["last_Sm"] != 0 and magnitude == 0:
            total += get_double(model, name, "shutdown_cost")*capacity
        energy = state["last_Sm"]*hours
        total += get_double(model, name, "fixed_cost")*hours + (get_double(model, name, "variable_cost") + get_double(model, name, "scarcity_cost")*energy)*energy
        set_double(model, name, "total_cost", total)
        if global_value(model, f"{MODULE}::with_emissions"):
            set_double(model, name, "total_emissions", get_double(model, name, "total_emissions") + get_double(model, name, "emissions_rate")*energy)
        state["last_commit"] = t
        state["last_Sm"] = magnitude
        return TS_NEVER

def _sign(value:float) -> float:
    return -1.0 if value < 0 else (1.0 if value > 0 else 0.0)
