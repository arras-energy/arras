# pylint: disable=line-too-long
"""Class `regulator`: a step voltage regulator

Syntax
------

    object regulator {
        phases {A,B,C}[N];
        from <node>;
        to <node>;
        configuration <regulator_configuration>;
        tap_A <integer>;           // also tap_B, tap_C
        sense_node <node>;         // REMOTE_NODE control
        regulator_resistance <real> Ohm;
        // and the other properties of link
    }

Description
-----------

A `regulator` is a `link` (gridlabd `PT_INHERIT "link"`): on each phase,
an autotransformer of ratio `a` (from voltage over to voltage at no load)
and a small series resistance `regulator_resistance` on the to side
(`powerflow::default_resistance` when it is not set or is 0). With
`tapChangePer = regulation/raise_taps`, `a = 1/(1 + tap*tapChangePer)` for
a type A regulator and `a = 1 - tap*tapChangePer` for type B, and
`Yr = 1/regulator_resistance`, the admittance is gridlabd's NR admittance:
`Yff = Yr/a^2`, `Yft = Ytf = -Yr/a`, `Ytt = Yr`, phase by phase.

The taps start at `tap_A`, `tap_B`, `tap_C` when they are set, else at the
configuration's `tap_pos_A` ... (0 when those are not set either). With
`MANUAL` control the taps follow `tap_A` ... at each solution. With the
automatic controls, after each solution the regulator applies gridlabd's
control (`regulator::presync()` and `postsync()`) to the voltage it
monitors:

- `OUTPUT_VOLTAGE`: the to node's voltages;
- `REMOTE_NODE`: the `sense_node`'s voltages;
- `LINE_DROP_COMP`: the to node's voltages divided by
  `power_transducer_ratio`, less the regulator's input currents (times
  `a`) divided by `current_transducer_ratio` times the compensator
  settings (`compensator_r_setting_X + j compensator_x_setting_X`, volts);

each phase (`INDIVIDUAL`) or the phase `PT_phase` (and `CT_phase`) for all
three (`BANK`). The band is `band_center -/+ band_width/2`. The first
time the regulator acts, it moves its taps at once by
`ceil(|band_center - V| / (band_center*tapChangePer))`; afterwards, a
voltage out of band starts the `dwell_time`, after which the taps move one
step every `time_delay`, within `-lower_taps` ... `raise_taps`. When it
moves a tap, the network is solved again at the same time; the next
dwell or tap-change time is a soft event. Reverse flow through the
regulator (its `flow_direction`) locks the taps at 0 (`LOCK_NEUTRAL`) or at
their position (`LOCK_CURRENT_POSITION`) while it lasts. The taps are
written to `tap_A` ..., and `tap_X_change_count` counts, for each time
step, a phase whose tap ended the step at a position other than the one
it started it at.

When it initializes, a regulator is expected to:

1. initialize as a `link`;
2. fail when it has no configuration ("no regulator configuration
   specified.") or the configuration is not a `regulator_configuration`
   ("invalid regulator configuration");
3. fail when its control is `REMOTE_NODE` and its `sense_node` is not a
   node ("Remote sensing node not found");
4. warn when `regulator_resistance` is 0 and use
   `powerflow::default_resistance`.

Caveats
-------

- gridlabd's control alternates with its NR solutions (it reads the
  voltages at its `presync` before the time step is solved, and every
  other pass); here it acts after each solution, on the voltages of the
  current time step, so a tap change can come one solution earlier than
  in gridlabd.
- Violations (taps at their limits) and the `minimum_timestep` adjustment
  of the next event are not ported.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A configuration's unset `tap_pos_X` (999) is not overwritten with 0, so
   every regulator that shares the configuration finds its taps unset;
   gridlabd writes 0 back to the configuration, so the second regulator
   takes 0 as a set initial tap and acts on its first solution.
2. A zero `regulator_resistance` becomes `default_resistance`, as
   gridlabd's warning says (gridlabd keeps 0, a singular matrix).
3. Regulators work with every solver method.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/regulator.cpp`,
  `regulator.h`
- W. H. Kersting, *Distribution System Modeling and Analysis*, 4th ed.,
  CRC Press, 2017, chapter 7
"""

import math
from typing import Any

import numpy as np

from ._base import prop
from ._common import (TS_NEVER, PHASE_A, PHASE_B, PHASE_C, isa, ref, g, msg, get_int, get_double,
    get_complex, set_int, set_double, object_state, PowerflowError)
from .link import Link
from .regulator_configuration import MANUAL, OUTPUT_VOLTAGE, REMOTE_NODE, LINE_DROP_COMP, BANK, WYE_WYE

TYPE_A, TYPE_B = 1, 2
"""`Type` values"""

LOCK_NEUTRAL, LOCK_CURRENT_POSITION = 1, 2
"""`reverse_flow_control` values"""

UNSET = -999
"""Tap value of a regulator whose tap is not set (gridlabd `create()`)"""

class Regulator(Link):
    """Behavior of class `regulator`"""

    NAME = "regulator"
    PARENT = "link"
    PROPERTIES = (
        ("configuration", "object", prop("reference to the regulator_configuration object used to determine regulator properties", flags="REQUIRED")),
        ("tap_A", "int16", prop("current tap position of tap A", str(UNSET))),
        ("tap_B", "int16", prop("current tap position of tap B", str(UNSET))),
        ("tap_C", "int16", prop("current tap position of tap C", str(UNSET))),
        ("tap_A_change_count", "double", prop("count of all physical tap changes on phase A since beginning of simulation (plus initial value)", "-1", flags="OUTPUT")),
        ("tap_B_change_count", "double", prop("count of all physical tap changes on phase B since beginning of simulation (plus initial value)", "-1", flags="OUTPUT")),
        ("tap_C_change_count", "double", prop("count of all physical tap changes on phase C since beginning of simulation (plus initial value)", "-1", flags="OUTPUT")),
        ("sense_node", "object", prop("Node to be monitored for voltage control in remote sense mode")),
        ("regulator_resistance[Ohm]", "double", prop("The resistance value of the regulator when it is not blown.", "-1 Ohm")),
    )

    @classmethod
    def config(cls, model:Any, name:str) -> str:
        """The configuration"""
        return ref(model, name, "configuration")

    @classmethod
    def init_link(cls, model:Any, name:str) -> None:
        """`regulator::init()` after `link::init()`; raises
        `PowerflowError`"""
        # pylint: disable=too-many-locals
        super().init_link(model, name)
        config = cls.config(model, name)
        if config is None:
            raise PowerflowError("no regulator configuration specified.")
        if not isa(model, config, "regulator_configuration"):
            raise PowerflowError("invalid regulator configuration")
        control = get_int(model, config, "Control")
        if control == REMOTE_NODE and not isa(model, ref(model, name, "sense_node"), "node"):
            raise PowerflowError("Remote sensing node not found")
        if get_int(model, config, "connect_type") != WYE_WYE:
            raise PowerflowError("Regulator connect type not supported yet")
        if get_int(model, config, "Type") not in (TYPE_A, TYPE_B):
            raise PowerflowError("invalid regulator type")
        resistance = get_double(model, name, "regulator_resistance")
        if resistance == 0:
            msg(model, name).warning(f"Regulator:{name} regulator_resistance has been set to zero. This will result singular matrix. Setting to the global default.")
        if resistance <= 0:
            set_double(model, name, "regulator_resistance", float(g(model, "default_resistance")))
        state = object_state(model, name)
        first = []
        for x in "ABC":
            given = get_int(model, config, f"tap_pos_{x}")
            if get_int(model, name, f"tap_{x}") == UNSET:
                set_int(model, name, f"tap_{x}", 0 if given == 999 else given)
            first.append(-2 if given == 999 else 0)
            if get_double(model, name, f"tap_{x}_change_count") < 0:
                set_double(model, name, f"tap_{x}_change_count", 0.0)
        state.update(first_run=first, mech_next=[TS_NEVER]*3, dwell_next=[TS_NEVER]*3, mech_flag=[0]*3, dwell_flag=[0]*3,
            reverse=[False]*3, reverse_banked=False, reverse_tap=[0]*3, step=None, step_taps=None, step_counts=None)

    #
    # Admittance
    #
    @classmethod
    def taps(cls, model:Any, name:str) -> list[int]:
        """Tap positions"""
        return [get_int(model, name, f"tap_{x}") for x in "ABC"]

    @classmethod
    def ratios(cls, model:Any, name:str) -> np.ndarray:
        """Ratio `a` of each phase (gridlabd `a_mat`)"""
        config = cls.config(model, name)
        per = cls.tap_change_per(model, name)
        taps = np.array(cls.taps(model, name), dtype=float)
        if get_int(model, config, "Type") == TYPE_A:
            return 1/(1 + taps*per)
        return 1 - taps*per

    @classmethod
    def tap_change_per(cls, model:Any, name:str) -> float:
        """Per-unit voltage change of one tap (gridlabd `tapChangePer`)"""
        config = cls.config(model, name)
        return get_double(model, config, "regulation")/get_int(model, config, "raise_taps")

    @classmethod
    def admittance(cls, model:Any, name:str) -> tuple[np.ndarray,np.ndarray,np.ndarray,np.ndarray]:
        """gridlabd's NR admittance (see the module description)"""
        a = cls.ratios(model, name)
        yr = cls.phase_mask(model, name)/get_double(model, name, "regulator_resistance")
        return np.diag(yr/a**2).astype(complex), np.diag(-yr/a).astype(complex), np.diag(-yr/a).astype(complex), np.diag(yr).astype(complex)

    @classmethod
    def admittance_key(cls, model:Any, name:str) -> tuple:
        """The link's key, the taps, the resistance, and the configuration's
        type and regulation"""
        config = cls.config(model, name)
        return super().admittance_key(model, name) + (tuple(cls.taps(model, name)), get_double(model, name, "regulator_resistance"),
            get_int(model, config, "Type"), get_double(model, config, "regulation"), get_int(model, config, "raise_taps"))

    #
    # Control
    #
    @classmethod
    def monitored(cls, model:Any, name:str) -> list[complex]:
        """Voltages the control compares with its band (gridlabd
        `get_monitored_voltage()`)"""
        # pylint: disable=too-many-locals
        config = cls.config(model, name)
        control = get_int(model, config, "Control")
        bank = get_int(model, config, "control_level") == BANK
        node = ref(model, name, "sense_node") if control == REMOTE_NODE else ref(model, name, "to")
        volts = [get_complex(model, node, f"voltage_{x}") for x in "ABC"]
        pt = {PHASE_A: 0, PHASE_B: 1, PHASE_C: 2}.get(get_int(model, config, "PT_phase"), 0)
        if control in (OUTPUT_VOLTAGE, REMOTE_NODE):
            return [volts[pt]]*3 if bank else volts
        if control != LINE_DROP_COMP:
            return [0j]*3
        ptr = get_double(model, config, "power_transducer_ratio")
        ctr = get_double(model, config, "current_transducer_ratio")
        a = cls.ratios(model, name)
        current = [a[k]*get_complex(model, name, f"current_in_{x}") for k, x in enumerate("ABC")]
        comp = [complex(get_double(model, config, f"compensator_r_setting_{x}"), get_double(model, config, f"compensator_x_setting_{x}")) for x in "ABC"]
        if bank:
            ct = {PHASE_A: 0, PHASE_B: 1, PHASE_C: 2}.get(get_int(model, config, "CT_phase"), 0)
            value = volts[pt]/ptr - (current[ct]/ctr*comp[ct] if ctr != 0 else 0)
            return [value]*3
        return [volts[k]/ptr - (current[k]/ctr*comp[k] if ctr != 0 else 0) for k in range(3)]

    @classmethod
    def _reverse_flow(cls, model:Any, name:str, taps:list[int]) -> list[bool]:
        """Reverse-flow detection of `regulator::postsync()`; the phases
        whose lock starts now"""
        config = cls.config(model, name)
        state = object_state(model, name)
        mode = get_int(model, config, "reverse_flow_control")
        new = [False]*3
        if mode not in (LOCK_NEUTRAL, LOCK_CURRENT_POSITION):
            return new
        direction = get_int(model, name, "flow_direction")
        reverse = [(direction >> (4*k)) & 0xF == 2 for k in range(3)]
        def lock(k:int) -> int:
            return 0 if mode == LOCK_NEUTRAL else taps[k]
        if get_int(model, config, "control_level") == BANK:
            if any(reverse) and not state["reverse_banked"]:
                state["reverse_banked"] = True
                state["reverse_tap"] = [lock(k) for k in range(3)]
                new = [True]*3
            elif not any(reverse) and state["reverse_banked"]:
                state["reverse_banked"] = False
        else:
            for k in range(3):
                if reverse[k] and not state["reverse"][k]:
                    state["reverse"][k] = True
                    state["reverse_tap"][k] = lock(k)
                    new[k] = True
                elif not reverse[k] and state["reverse"][k]:
                    state["reverse"][k] = False
        return new

    @classmethod
    def _step(cls, model:Any, name:str, t0:int, k:int, voltage:float, taps:list[int], banked:bool) -> None:
        """One phase (or the bank, `k` 0) of the control of
        `regulator::presync()`"""
        # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-branches,too-many-locals
        config = cls.config(model, name)
        state = object_state(model, name)
        center = get_double(model, config, "band_center")
        width = get_double(model, config, "band_width")
        raise_taps, lower_taps = get_int(model, config, "raise_taps"), get_int(model, config, "lower_taps")
        dwell, delay = int(get_double(model, config, "dwell_time")), int(get_double(model, config, "time_delay"))
        vtap = center*cls.tap_change_per(model, name)
        mech, dwl = state["mech_next"], state["dwell_next"]
        mflag, dflag = state["mech_flag"], state["dwell_flag"]
        locked = state["reverse_banked"] if banked else state["reverse"][k]
        def set_taps(value:int) -> None:
            if banked:
                taps[:] = list(state["reverse_tap"]) if locked else [value]*3
            else:
                taps[k] = state["reverse_tap"][k] if locked else value
        if voltage < center - width/2 or voltage > center + width/2:
            sign = 1 if voltage < center - width/2 else -1
            limit = raise_taps if sign > 0 else -lower_taps
            def clamp() -> bool:
                if (sign > 0 and taps[k] > limit) or (sign < 0 and taps[k] < limit):
                    if banked:
                        taps[:] = [limit]*3
                    else:
                        taps[k] = limit
                    return True
                return False
            if state["first_run"][k] == 0:
                set_taps(taps[k] + sign*int(math.ceil(abs(center - voltage)/vtap)))
                clamp()
                dwl[k], mech[k] = t0 + dwell, t0 + delay
            elif mflag[k] == 0 and dflag[k] == 1 and mech[k] - t0 >= delay:
                mech[k] = t0 + delay
            elif mflag[k] == 1 and dflag[k] == 1:
                set_taps(taps[k] + sign)
                if clamp():
                    dwl[k], mech[k] = t0 + dwell, t0 + delay
                    dflag[k] = mflag[k] = 0
                else:
                    mech[k], dwl[k] = t0 + delay, t0 + dwell
                    mflag[k] = 0
            elif dflag[k] == 0 and dwl[k] - t0 >= dwell:
                dwl[k] = t0 + dwell
                mech[k] = dwl[k] + delay
        else:
            dwl[k] = mech[k] = TS_NEVER
            dflag[k] = mflag[k] = 0

    @classmethod
    def control(cls, model:Any, name:str, t0:int) -> None:
        """The automatic control after a solution (see the module
        description)"""
        config = cls.config(model, name)
        state = object_state(model, name)
        banked = get_int(model, config, "control_level") == BANK
        taps = cls.taps(model, name)
        cls._reverse_flow(model, name, taps)
        units = [0] if banked else [0, 1, 2]
        for k in units:
            state["mech_flag"][k] = 1 if state["mech_next"][k] <= t0 else state["mech_flag"][k]
            state["dwell_flag"][k] = 1 if state["dwell_next"][k] <= t0 else 0
        voltages = cls.monitored(model, name)
        if banked:
            if state["first_run"][0] < 1:
                state["first_run"] = [x + 1 for x in state["first_run"]]
        else:
            state["first_run"] = [x + 1 if x < 1 else x for x in state["first_run"]]
        for k in units:
            cls._step(model, name, t0, k, abs(voltages[k]), taps, banked)
        for k, x in enumerate("ABC"):
            set_int(model, name, f"tap_{x}", taps[k])

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        """Start of a time step: remember the taps and counts the change
        counts are relative to"""
        state = object_state(model, name)
        if state.get("step") != t0:
            state["step"] = t0
            state["step_taps"] = cls.taps(model, name)
            state["step_counts"] = [get_double(model, name, f"tap_{x}_change_count") for x in "ABC"]

    @classmethod
    def after_solve(cls, model:Any, name:str, t0:int) -> bool:
        """Apply the control; `True` when a tap moved or the control is
        still starting (gridlabd iterates until its first run is done)"""
        config = cls.config(model, name)
        state = object_state(model, name)
        if get_int(model, config, "Control") == MANUAL or "first_run" not in state:
            return False
        before = cls.taps(model, name)
        cls.control(model, name, t0)
        after = cls.taps(model, name)
        if state.get("step_taps") is not None:
            for k, x in enumerate("ABC"):
                set_double(model, name, f"tap_{x}_change_count", state["step_counts"][k] + (after[k] != state["step_taps"][k]))
        units = [0] if get_int(model, config, "control_level") == BANK else [0, 1, 2]
        return after != before or any(state["first_run"][k] < 1 for k in units)

    @classmethod
    def next_event(cls, model:Any, name:str) -> int|None:
        """The next dwell or tap-change time (gridlabd's soft return from
        `presync`)"""
        state = object_state(model, name)
        if "mech_next" not in state:
            return None
        t0 = state.get("step") or 0
        times = []
        for k in range(3):
            t = None
            if t0 < state["mech_next"][k] != TS_NEVER:
                t = state["mech_next"][k]
            if t0 < state["dwell_next"][k] != TS_NEVER:
                t = state["dwell_next"][k]
            if t is not None:
                times.append(t)
        return min(times) if times else None

__all__ = ["Regulator"]
