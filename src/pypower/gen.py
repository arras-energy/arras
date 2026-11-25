# pylint: disable=line-too-long
"""Class `gen`: a PYPOWER generator

Syntax
------

    object pypower.gen {
        parent <bus>;
        bus <integer>;
        Pg <real> MW;
        Qg <real> MVAr;
        Qmax <real> MVAr;
        Qmin <real> MVAr;
        Vg <real> pu.kV;
        mBase <real> MVA;
        status {IN_SERVICE,OUT_OF_SERVICE};
        Pmax <real> MW;
        Pmin <real> MW;
        Pc1 <real> MW;
        Pc2 <real> MW;
        Qc1min <real> MVAr;
        Qc1max <real> MVAr;
        Qc2min <real> MVAr;
        Qc2max <real> MVAr;
        ramp_agc <real> MW/min;
        ramp_10 <real> MW;
        ramp_30 <real> MW;
        ramp_q <real> MVAr/min;
        apf <real>;
    }

The OPF multipliers `mu_Pmax`, `mu_Pmin` (pu./MW), `mu_Qmax`, `mu_Qmin`
(pu./MVAr) are also published, and the module global
`pypower::default_reactive_power_fraction` (pu, 0.2).

Description
-----------

A generator is a row of PYPOWER's gen table. Given a model, a generator is
expected to:

1. refuse a parent that is missing or not a pypower bus;
2. take `bus` from its parent's `bus_i` when it is 0 (deferring until the
   bus has a number), and refuse a `bus` that differs from it;
3. when powerplants are attached (`powerplant` objects whose parent is the
   generator), reset `Pmax`, `Pg`, and `Qg` to 0 at each precommit; each
   powerplant then adds its output to `Pg` and `Qg` and its capacity to
   `Pmax`, which sets `Qmax` to `Pmax` times
   `pypower::default_reactive_power_fraction` and `Qmin` to `-Qmax`;
4. receive `Pg`, `Qg`, and `apf` from each solution, except that when the
   OPF runs and powerplants are attached, the solution's `Pg` and `Qg` are
   the powerplants' setpoints (members `Ps` and `Qs`, not published);
5. take the cost model of the first `gencost` object below it; a second
   `gencost` with a different model is an error.

Only generators whose `status` is `IN_SERVICE` are passed to PYPOWER.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The global is `pypower::default_reactive_power_fraction` with unit
   `pu`; gridlabd creates it as
   `pypower::default_reactive_power_fraction[pu]` (the unit is part of the
   name), so `default_reactive_power_fraction` in a `module pypower` block
   does not find it there.

References
----------

- `arras-energy/gridlabd`: `module/pypower/gen.cpp`, `gen.h`
"""

from typing import Any

from ._base import PypowerClass, prop, keywords, msg
from ._common import (TS_NEVER, MODULE, object_state, global_value, isa, parent_of, get_double,
    get_int, set_double, set_int)
from ._module import ensure_init

GS_OUTOFSERVICE, GS_INSERVICE = 0, 1

class Gen(PypowerClass):
    """Behavior of class `gen`"""

    NAME = "gen"
    PROPERTIES = (
        ("bus", "int32", prop("bus number")),
        ("Pg[MW]", "double", prop("real power output (MW)")),
        ("Qg[MVAr]", "double", prop("reactive power output (MVAr)")),
        ("Qmax[MVAr]", "double", prop("maximum reactive power output (MVAr)")),
        ("Qmin[MVAr]", "double", prop("minimum reactive power output (MVAr)")),
        ("Vg[pu.kV]", "double", prop("voltage magnitude setpoint (per unit)", "1 pu.kV")),
        ("mBase[MVA]", "double", prop("total MVA base of machine, defaults to baseMVA", "100 MVA")),
        ("status", "enumeration", prop("1 - in service, 0 - out of service", "IN_SERVICE",
            keywords=keywords(("IN_SERVICE", GS_INSERVICE), ("OUT_OF_SERVICE", GS_OUTOFSERVICE)))),
        ("Pmax[MW]", "double", prop("maximum real power output (MW)")),
        ("Pmin[MW]", "double", prop("minimum real power output (MW)")),
        ("Pc1[MW]", "double", prop("lower real power output of PQ capability curve (MW)")),
        ("Pc2[MW]", "double", prop("upper real power output of PQ capability curve (MW)")),
        ("Qc1min[MVAr]", "double", prop("minimum reactive power output at Pc1 (MVAr)")),
        ("Qc1max[MVAr]", "double", prop("maximum reactive power output at Pc1 (MVAr)")),
        ("Qc2min[MVAr]", "double", prop("minimum reactive power output at Pc2 (MVAr)")),
        ("Qc2max[MVAr]", "double", prop("maximum reactive power output at Pc2 (MVAr)")),
        ("ramp_agc[MW/min]", "double", prop("ramp rate for load following/AGC (MW/min)")),
        ("ramp_10[MW]", "double", prop("ramp rate for 10 minute reserves (MW)")),
        ("ramp_30[MW]", "double", prop("ramp rate for 30 minute reserves (MW)")),
        ("ramp_q[MVAr/min]", "double", prop("ramp rate for reactive power (2 sec timescale) (MVAr/min)")),
        ("apf", "double", prop("area participation factor")),
        ("mu_Pmax[pu./MW]", "double", prop("Kuhn-Tucker multiplier on upper Pg limit (per unit/MW)")),
        ("mu_Pmin[pu./MW]", "double", prop("Kuhn-Tucker multiplier on lower Pg limit (per unit/MW)")),
        ("mu_Qmax[pu./MVAr]", "double", prop("Kuhn-Tucker multiplier on upper Qg limit (per unit/MVAr)")),
        ("mu_Qmin[pu./MVAr]", "double", prop("Kuhn-Tucker multiplier on lower Qg limit (per unit/MVAr)")),
    )
    EVENTS = ("init", "precommit")

    @classmethod
    def state(cls, model:Any, name:str) -> dict[str,Any]:
        """State of a generator: `cost` (name of its gencost or `None`),
        `plant_count`, and the powerplant setpoints `Ps` and `Qs`"""
        return object_state(model, name, lambda: {"cost": None, "plant_count": 0, "Ps": 0.0, "Qs": 0.0})

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool|int: # pylint: disable=unused-argument
        """`gen::init()`"""
        if not ensure_init(model):
            return False
        out = msg(model, name)
        cls.state(model, name)
        parent = parent_of(model, name)
        if parent is None:
            out.error("parent bus not specified")
            return False
        if not isa(model, parent, "bus"):
            out.error(f"parent object '{parent}' is not a pypower bus")
            return False
        number = get_int(model, parent, "bus_i")
        if get_int(model, name, "bus") == 0:
            if number == 0:
                return 2
            set_int(model, name, "bus", number)
            out.verbose(f"setting bus index to {number}")
        elif get_int(model, name, "bus") != number:
            out.error(f"parent object '{parent}' bus index mismatch")
            return False
        return True

    @classmethod
    def precommit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`gen::precommit()`"""
        if cls.state(model, name)["plant_count"] > 0:
            for prop_ in ("Pmax", "Pg", "Qg"):
                set_double(model, name, prop_, 0.0)
        return TS_NEVER

def add_powerplant(model:Any, name:str, plant:str) -> None:
    """`gen::add_powerplant()`"""
    from ._common import gl_debug # pylint: disable=import-outside-toplevel
    gl_debug(f"powerplant '{plant}' connected")
    Gen.state(model, name)["plant_count"] += 1

def add_output(model:Any, name:str, real:float, reactive:float) -> None:
    """`gen::add_Pg()` and `gen::add_Qg()`"""
    set_double(model, name, "Pg", get_double(model, name, "Pg") + real)
    set_double(model, name, "Qg", get_double(model, name, "Qg") + reactive)

def add_pmax(model:Any, name:str, capacity:float) -> None:
    """`gen::add_Pmax()`"""
    pmax = get_double(model, name, "Pmax") + capacity
    qmax = pmax*float(global_value(model, f"{MODULE}::default_reactive_power_fraction"))
    set_double(model, name, "Pmax", pmax)
    set_double(model, name, "Qmax", qmax)
    set_double(model, name, "Qmin", -qmax)

def add_cost(model:Any, name:str, cost:str) -> None:
    """`gen::add_cost()`"""
    from .gencost import is_equal # pylint: disable=import-outside-toplevel
    state = Gen.state(model, name)
    if state["cost"] is None:
        state["cost"] = cost
    elif not is_equal(model, state["cost"], cost):
        msg(model, name).error("unable to add to different gencost models")
