# pylint: disable=line-too-long
"""Class `shunt`: a voltage-controlled shunt on a bus

Syntax
------

    object pypower.shunt {
        parent <bus>;
        control_mode {FIXED,DISCRETE_V,CONTINUOUS_V,DISCRETE_VAR,DISCRETE_VSC,DISCRETE_Y};
        status {OFFLINE,ONLINE};
        input {ANGLE,MAGNITUDE};
        output {REAL,REACTIVE};
        voltage_high <real>;
        voltage_low <real>;
        remote_bus <bus>;
        admittance <real> MVAr;
        steps_1 <integer>;
        admittance_1 <real> MVAr;
        [steps_2 ... steps_8, admittance_2 ... admittance_8]
        dwell_time <real> s;
        control_gain <real> MVAr/pu.V;
    }

The module globals `pypower::minimum_voltage_magnitude_deadband` (pu.kV,
0.002) and `pypower::minimum_voltage_angle_deadband` (deg, 0.01) are also
published.

Description
-----------

A shunt switches capacitor steps (`DISCRETE_V`) or adjusts a synchronous
condenser (`CONTINUOUS_V`) to hold the voltage of its `remote_bus`
(default: its parent bus) between `voltage_low` and `voltage_high`, and
adds its `admittance` to its parent bus. Given a model, a shunt is
expected to:

1. refuse control modes other than `FIXED`, `DISCRETE_V`, and
   `CONTINUOUS_V`; a `voltage_low` not below `voltage_high` by more than
   the minimum deadband of its `input` (for controlled modes); a deadband
   that is not positive; a parent or remote bus that is missing or not a
   pypower bus; a block 1 with steps and no admittance step; steps in
   blocks 2 to 8; a `dwell_time` that is not positive; a `CONTINUOUS_V`
   shunt without a positive `control_gain`, and a `DISCRETE_V` shunt
   without steps;
2. at each precommit and sync, when `ONLINE` and both buses have a
   voltage magnitude above 0.001: wait until `dwell_time` after its last
   step; then, with the input voltage `V` (`Vm` or `Va` of the remote bus)
   below `voltage_low` or above `voltage_high`, step the admittance up or
   down by `admittance_1` within `0..steps_1 admittance_1` (`DISCRETE_V`;
   warning at a limit or when the step reverses the previous one), or
   change it by `(1-V) control_gain` within
   `-admittance_1..admittance_1` (`CONTINUOUS_V`); then add the admittance to the bus (`REAL`: to `Pd`;
   `REACTIVE`: to `Pd`, and its negative to `Qd`), and ask to run again
   when the dwell time ends; when `OFFLINE`, set the admittance to 0.

Caveats
-------

- A `REACTIVE` shunt adds its admittance to the bus's `Pd` as well as
  subtracting it from `Qd`, as gridlabd does.
- `voltage_high` and `voltage_low` have no unit; give them in the unit of
  the input (per unit for `MAGNITUDE`, degrees for `ANGLE`).
- The bus resets its `Pd` and `Qd` in its presync, which comes after the
  shunt's precommit, so only the sync adds the admittance to the
  solution.
- The `CONTINUOUS_V` reference voltage is 1 whichever limit is crossed,
  because gridlabd assigns the `bool` test results (`Vlow`, `Vhigh`) to
  it. The intended reference is probably the limit crossed, but with it
  the `CONTINUOUS_V` shunt of gridlabd's `test_shunt_capacitor` autotest
  moves too slowly to settle within its 1000 iterations, so gridlabd's
  behavior is kept.

References
----------

- `arras-energy/gridlabd`: `module/pypower/shunt.cpp`, `shunt.h`
"""

from typing import Any

from ._base import PypowerClass, prop, keywords, msg
from ._common import (TS_NEVER, MODULE, TRL_PROTOTYPE, object_state, global_value, isa, parent_of, ref,
    get_double, get_int, set_double, set_text)
from ._module import ensure_init
from .bus import add_load

CM_FIXED, CM_DISCRETE_V, CM_CONTINUOUS_V, CM_DISCRETE_VAR, CM_DISCRETE_VSC, CM_DISCRETE_Y = range(6)
CS_OFFLINE, CS_ONLINE = 0, 1
CI_MAGNITUDE, CI_ANGLE = 0, 1
CO_REACTIVE, CO_REAL = 0, 1

def _blocks() -> tuple[tuple[str,str,dict[str,Any]],...]:
    items = []
    for n in range(1, 9):
        items.append((f"steps_{n}", "int32", prop("numbers of steps in control block 1" if n == 1 else f"number of steps in control block {n}")))
        items.append((f"admittance_{n}[MVAr]", "double", prop(f"control block {n} shunt admittance step at unity voltage")))
    return tuple(items)

class Shunt(PypowerClass):
    """Behavior of class `shunt`"""

    NAME = "shunt"
    PASSCONFIG = "BOTTOMUP|AUTOLOCK|OBSERVER"
    TRL = TRL_PROTOTYPE
    PROPERTIES = (
        ("control_mode", "enumeration", prop("shunt control mode", keywords=keywords(("FIXED", CM_FIXED),
            ("DISCRETE_V", CM_DISCRETE_V), ("CONTINUOUS_V", CM_CONTINUOUS_V), ("DISCRETE_VAR", CM_DISCRETE_VAR),
            ("DISCRETE_VSC", CM_DISCRETE_VSC), ("DISCRETE_Y", CM_DISCRETE_Y)))),
        ("status", "enumeration", prop("shunt status", keywords=keywords(("OFFLINE", CS_OFFLINE), ("ONLINE", CS_ONLINE)))),
        ("input", "enumeration", prop("voltage control input", keywords=keywords(("ANGLE", CI_ANGLE), ("MAGNITUDE", CI_MAGNITUDE)))),
        ("output", "enumeration", prop("voltage control output", "REACTIVE", keywords=keywords(("REAL", CO_REAL), ("REACTIVE", CO_REACTIVE)))),
        ("voltage_high", "double", prop("controlled voltage upper limit", flags="REQUIRED")),
        ("voltage_low", "double", prop("controlled voltage lower limit", flags="REQUIRED")),
        ("remote_bus", "object", prop("remote bus name")),
        ("admittance[MVAr]", "double", prop("shunt admittance at unity voltage")),
    ) + _blocks() + (
        ("dwell_time[s]", "double", prop("control lockout")),
        ("control_gain[MVAr/pu.V]", "double", prop("proportional feedback control gain")),
    )
    EVENTS = ("init", "precommit", "sync")

    @classmethod
    def state(cls, model:Any, name:str) -> dict[str,Any]:
        """State of a shunt: `last_update`, `last_delta`, `input_bus`,
        `output_bus`"""
        return object_state(model, name, lambda: {"last_update": 0, "last_delta": 0.0, "input_bus": None, "output_bus": None})

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`shunt::init()`"""
        # pylint: disable=too-many-return-statements,too-many-branches
        if not ensure_init(model):
            return False
        out = msg(model, name)
        state = cls.state(model, name)
        mode = get_int(model, name, "control_mode")
        low, high = get_double(model, name, "voltage_low"), get_double(model, name, "voltage_high")
        if mode > CM_CONTINUOUS_V:
            out.error("advanced control modes not supported yet (use FIXED, DISCRETE_V, or CONTINUOUS_V)")
            return False
        if mode != CM_FIXED and low >= high:
            out.error("voltage_low is greater than voltage_high")
            return False
        which = "magnitude" if get_int(model, name, "input") == CI_MAGNITUDE else "angle"
        deadband = float(global_value(model, f"{MODULE}::minimum_voltage_{which}_deadband"))
        if deadband <= 0:
            out.error("minimum_voltage_{magnitude,angle}_deadband is not positive")
            return False
        if mode != CM_FIXED and low > high - deadband:
            out.error("voltage_low is within minimum_voltage_{magnitude,angle}_deadband of voltage_high")
            return False
        parent = parent_of(model, name)
        if parent is None:
            out.error("parent bus must be specified")
            return False
        if not isa(model, parent, "bus"):
            out.error("parent is not a pypower bus")
            return False
        state["output_bus"] = parent
        remote = ref(model, name, "remote_bus")
        if remote is None:
            remote = parent
            set_text(model, name, "remote_bus", parent)
        if not isa(model, remote, "bus"):
            out.error("remote_bus is not a pypower bus")
            return False
        state["input_bus"] = remote
        if get_int(model, name, "steps_1") > 0 and get_double(model, name, "admittance_1") == 0:
            out.error("zero admittance step values are not valid for active control blocks")
            return False
        if any(get_int(model, name, f"steps_{n}") > 0 for n in range(2, 9)):
            out.error("multiple control blocks not supported yet (steps_[2-8] > 0)")
            return False
        if get_double(model, name, "dwell_time") <= 0:
            out.error("dwell_time must be positive")
            return False
        gain = get_double(model, name, "control_gain")
        if mode == CM_CONTINUOUS_V and gain <= 0:
            out.error(f"control_gain ({gain:g}) must be positive for control_mode == CONTINUOUS_V")
            return False
        if mode == CM_DISCRETE_V and get_int(model, name, "steps_1") <= 0:
            out.error("steps_1 must be positive for control_mode == DISCRETE_V")
            return False
        return True

    @classmethod
    def precommit(cls, model:Any, name:str, t:int) -> int:
        """`shunt::precommit()`"""
        return update_control(model, name, t)

    @classmethod
    def sync(cls, model:Any, name:str, t:int) -> int:
        """`shunt::sync()`"""
        return update_control(model, name, t)

def update_bus(model:Any, name:str) -> None:
    """`shunt::update_bus()`"""
    out = msg(model, name)
    out.verbose("update_bus()")
    bus = Shunt.state(model, name)["output_bus"]
    admittance = get_double(model, name, "admittance")
    if get_int(model, name, "output") == CO_REAL:
        out.verbose("control output is REAL")
        add_load(model, bus, admittance, 0)
    elif get_int(model, name, "output") == CO_REACTIVE:
        out.verbose("control output is REACTIVE")
        add_load(model, bus, admittance, -admittance)

def update_control(model:Any, name:str, t0:int, update_time:bool=False) -> int:
    """`shunt::update_control()`"""
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-nested-blocks
    out = msg(model, name)
    state = Shunt.state(model, name)
    stamp = model.globals.timestamp_to_string
    t1 = TS_NEVER
    ibus, obus = state["input_bus"], state["output_bus"]
    in_vm, in_va = get_double(model, ibus, "Vm"), get_double(model, ibus, "Va")
    out_vm, out_va = get_double(model, obus, "Vm"), get_double(model, obus, "Va")
    is_magnitude = get_int(model, name, "input") == CI_MAGNITUDE
    out.verbose(f"update_control(t0={stamp(t0)})")
    out.verbose(f"input/output voltage magnitudes/angles are {in_vm:g}{in_va:+g}j/{out_vm:g}{out_va:+g}j respectively")
    out.verbose(f"voltage input is {'MAGNITUDE' if is_magnitude else 'ANGLE'}")
    if get_int(model, name, "status") == CS_ONLINE and in_vm > 1e-3 and out_vm > 1e-3:
        dwell = get_double(model, name, "dwell_time")
        if t0 < state["last_update"] + dwell:
            t1 = int(state["last_update"] + dwell)
            state["last_delta"] = 0.0
            out.verbose(f"voltage control is LOCKED until {stamp(t1)}")
        else:
            v = in_vm if is_magnitude else in_va
            high, low = get_double(model, name, "voltage_high"), get_double(model, name, "voltage_low")
            vhigh, vlow = v > high, v < low
            out.verbose(f"voltage check: {low:g} < {v:g} < {high:g}")
            if vhigh:
                out.verbose("voltage is high")
            if vlow:
                out.verbose("voltage is low")
            mode = get_int(model, name, "control_mode")
            admittance = get_double(model, name, "admittance")
            step = get_double(model, name, "admittance_1")
            if mode == CM_DISCRETE_V:
                alo = admittance <= 0
                if vhigh and alo:
                    out.verbose("output is at minimum")
                ahi = admittance >= step*get_int(model, name, "steps_1")
                if vlow and ahi:
                    out.verbose("output is at maximum")
                if vlow and not update_time:
                    if ahi:
                        out.warning(f"shunt voltage discrete control upper limit reached at {admittance:g} MVAr (V={v:g})")
                        state["last_delta"] = 0.0
                    else:
                        state["last_update"] = t0
                        admittance += step
                        out.verbose(f"stepping up to {admittance:g} MVAr")
                        if state["last_delta"] < 0:
                            out.warning(f"shunt voltage discrete control hunting at {admittance:g} MVAr (V={v:g})")
                        state["last_delta"] = step
                elif vhigh and not update_time:
                    if alo:
                        out.warning(f"shunt voltage discrete control lower limit reached at {admittance:g} MVAr (V={v:g})")
                        state["last_delta"] = 0.0
                    else:
                        admittance -= step
                        state["last_update"] = t0
                        out.verbose(f"stepping down to {admittance:g} MVAr")
                        if state["last_delta"] > 0:
                            out.warning(f"shunt voltage discrete control hunting at {admittance:g} MVAr (V={v:g})")
                        state["last_delta"] = -step
                else:
                    state["last_delta"] = 0.0
                t1 = int(state["last_update"] + dwell)
            elif mode == CM_CONTINUOUS_V:
                if not update_time:
                    vref = 1.0 if vlow or vhigh else v # gridlabd assigns the bool vlow or vhigh
                    state["last_delta"] = (vref - v)*get_double(model, name, "control_gain")
                    admittance += state["last_delta"]
                    if admittance < -step:
                        admittance = -step
                        out.warning(f"shunt voltage continuous control lower limit reached at {admittance:g} MVAr (V={v:g})")
                    elif admittance > step:
                        admittance = step
                        out.warning(f"shunt voltage continuous control upper limit reached at {admittance:g} MVAr (V={v:g})")
                    else:
                        out.verbose(f"setting admittance to {admittance:g}")
                else:
                    state["last_delta"] = 0.0
                t1 = int(state["last_update"] + dwell)
            set_double(model, name, "admittance", admittance)
        update_bus(model, name)
    else:
        set_double(model, name, "admittance", 0.0)
    t1 = TS_NEVER if t1 <= t0 else t1
    out.verbose(f"update_control(t0={stamp(t0)}) -> {stamp(t1)}")
    return t1
