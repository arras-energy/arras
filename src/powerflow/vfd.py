# pylint: disable=line-too-long
"""Class `vfd`: a variable frequency drive between two nodes

Syntax
------

    object vfd {
        phases ABC[N];
        from <node>;
        to <node>;
        rated_motor_speed <real> 1/min;
        desired_motor_speed <real> 1/min;
        motor_poles <real>;
        rated_output_voltage <real> V;
        rated_horse_power <real> hp;
        nominal_output_frequency <real> Hz;
        stable_time <real> s;
        vfd_state {OFF,CHANGING,STEADY_STATE};
        // and the other properties of link
    }

Outputs: `desired_output_frequency` (Hz), `current_output_frequency`
(Hz), `efficiency` (%), `vfd_state`, and the flows of a link.

Description
-----------

A `vfd` is a `link` (gridlabd `PT_INHERIT "link"`) that decouples its
nodes, as gridlabd's VFD does: it adds no branch to the network; its `to`
node is a voltage source (a `REF` bus) at the drive's output voltage, and
its `from` node draws the drive's input power, balanced on the three
phases. Before each solution it is expected to update its state as
gridlabd's `VFD_current_injection()` does:

1. when `desired_motor_speed` changed: fail when it is negative; turn the
   drive off when it is 0, and on (`STEADY_STATE`) when it was 0 and is
   now positive; set `desired_output_frequency` to
   `desired_motor_speed * motor_poles / 120`, warning below 3 Hz, and
   warning when the speed is at most 75% of `rated_motor_speed`;
2. at each new time: a drive that turned on starts `CHANGING` at 3 Hz; a
   steady drive whose frequency differs from the desired one starts
   `CHANGING` from its frequency; a changing drive fills, one entry per
   second elapsed, a window of `stable_time` seconds (rounded, at least
   one) with the desired frequency, and its `current_output_frequency`
   is the mean of the window, until the window is full (`STEADY_STATE`);
   an `OFF` drive has frequency 0; the angle of each output phase
   advances by `(2 pi f - 2 pi f_nominal) dt`, with `f_nominal` the
   system's `nominal_frequency`;
3. set the `to` node's voltages to `rated_output_voltage / sqrt(3) *
   f / nominal_output_frequency` at the phase angles (0, -120, 120 degrees
   plus the advance).

After each solution, the drive's output power is the power the `to` node
supplies to its links and loads (`current_out_X` is its current); the
input power on each phase is the output power times
`100 / efficiency / 3`, with `efficiency` (%) gridlabd's 7th order fit of
the output frequency as a percentage of `nominal_output_frequency`;
`current_in_X` is the input power over the `from` node's voltage. When
the input power changed, the network is solved again with it. While the
drive is changing, the time the window fills is a soft event. An `OFF`
drive carries nothing and the nodes it feeds (through any links) are
taken out of the network (voltage 0).

When it initializes, a vfd is expected to initialize as a `link`, then to
fail when `stable_time`, `rated_motor_speed`, `motor_poles`, or
`rated_horse_power` is not positive, or when it does not have phases A,
B, and C; to warn and set `rated_output_voltage` to `sqrt(3)` times the
`to` node's nominal voltage when it is not positive (and warn when it
differs from it by more than 0.5 V); to warn when the `from` node's
nominal voltage is below the `to` node's; and to warn and set
`nominal_output_frequency` to `powerflow::nominal_frequency` when it is
not positive. A drive that starts in `STEADY_STATE` starts at its desired
frequency.

Caveats
-------

- The drive's frequency is not seen by the objects on its `to` side
  (the solution is a phasor solution at the system frequency), as in
  gridlabd.
- Deltamode is not ported.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The output voltage on each phase is the line-to-neutral voltage,
   `rated_output_voltage / sqrt(3)` at nominal frequency; gridlabd sets
   the line-to-line `rated_output_voltage` as each line-to-neutral
   voltage, `sqrt(3)` times the rated voltage.
2. The output current and power are those the `to` node supplies to all
   its links and loads; gridlabd copies the `to` node's constant-current
   accumulator, which leaves out its constant-power and impedance loads
   and the links it feeds.
3. The input power is a load on the `from` node's buses; gridlabd adds it
   to the `from` node's `power_X` accumulators, so it shows there.
4. The `to` node is a voltage source in the network; gridlabd's NR gives
   the drive a zero admittance and overwrites the `to` node's voltages
   during its iterations.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/vfd.cpp`, `vfd.h`
"""

import cmath
import math
from typing import Any

import numpy as np

from ._base import prop, keywords
from ._common import (PHASE_A, PHASE_B, PHASE_C, ref, g, msg, objects_of, object_state, get_int, get_double,
    get_complex, set_complex, set_double, PowerflowError)
from .link import Link, write_flows
from .node import top_node

VFD_OFF, VFD_CHANGING, VFD_STEADY = range(3)
"""`vfd_state` values"""

STATE_NAMES = ("OFF", "CHANGING", "STEADY_STATE")

EFFICIENCY = (96.014, 3.8759, -4.4504, -3.2079, 8.7113, 0.97848, -8.2828, 3.497)
"""Coefficients of gridlabd's efficiency fit (% of the percentage of the
nominal output frequency `p`, in powers of `z = (p - 50.138)/37.009`)"""

BASE = (0.0, -2*math.pi/3, 2*math.pi/3)

def efficiency(percent:float) -> float:
    """Drive efficiency (%) at an output of `percent` of the nominal
    frequency"""
    z = (percent - 50.138)/37.009
    return sum(c*z**k for k, c in enumerate(EFFICIENCY))

class VFD(Link):
    """Behavior of class `vfd`"""

    NAME = "vfd"
    PARENT = "link"
    TRL = 7 # TRL_PROTOTYPE
    SOURCE = True
    PROPERTIES = (
        ("rated_motor_speed[1/min]", "double", prop("Rated speed of the VFD in RPM. Default = 1800 RPM", "1800 1/min")),
        ("desired_motor_speed[1/min]", "double", prop("Desired speed of the VFD In ROM. Default = 1800 RPM (max)", "1800 1/min")),
        ("motor_poles", "double", prop("Number of Motor Poles. Default = 4", "4")),
        ("rated_output_voltage[V]", "double", prop("Line to Line Voltage - VFD Rated voltage. Default to TO node nominal_voltage", "-1 V")),
        ("rated_horse_power[hp]", "double", prop("Rated Horse Power of the VFD. Default = 75 HP", "75 hp")),
        ("nominal_output_frequency[Hz]", "double", prop("Nominal VFD output frequency. Default = 60 Hz", "-1 Hz")),
        ("desired_output_frequency[Hz]", "double", prop("VFD desired output frequency based on the desired RPM")),
        ("current_output_frequency[Hz]", "double", prop("VFD currently output frequency")),
        ("efficiency[%]", "double", prop("Current VFD efficiency based on the load/VFD output Horsepower")),
        ("stable_time[s]", "double", prop("Time taken by the VFD to reach desired frequency (based on RPM). Default = 1.45 seconds", "1.45 s")),
        ("vfd_state", "enumeration", prop("Current state of the VFD", "OFF",
            keywords=keywords(("OFF", VFD_OFF), ("CHANGING", VFD_CHANGING), ("STEADY_STATE", VFD_STEADY)))),
    )

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool|int:
        result = super().init(model, name, t)
        if result is True:
            object_state(model, name)["vfd_prev_time"] = float(t) - 1.0
        return result

    @classmethod
    def init_link(cls, model:Any, name:str) -> None:
        """`link::init()`, then `vfd::init()`; raises `PowerflowError`"""
        # pylint: disable=too-many-locals
        super().init_link(model, name)
        out = msg(model, name)
        obj = model.objects[name]
        label = f"VFD:{obj.id} - {name}"
        if get_double(model, name, "stable_time") <= 0:
            raise PowerflowError(f"{label} - the stableTime must be positive")
        fnode, tnode = ref(model, name, "from"), ref(model, name, "to")
        vto = get_double(model, tnode, "nominal_voltage")*math.sqrt(3)
        rated = get_double(model, name, "rated_output_voltage")
        if rated <= 0:
            set_double(model, name, "rated_output_voltage", vto)
            out.warning(f"{label} - rated_output_voltage was not set, defaulting to TO node nominal")
        elif abs(rated - vto) > 0.5:
            out.warning(f"{label} - rated_output_voltage does not match the TO node nominal voltage")
        if get_double(model, fnode, "nominal_voltage") < get_double(model, tnode, "nominal_voltage"):
            out.warning(f"{label} - FROM node nominal_voltage is not equal to or greater than TO node nominal_voltage - implies DC-DC converter!e")
        if get_double(model, name, "nominal_output_frequency") <= 0:
            out.warning(f"{label} - nominal_output_frequency is not set or is negative - defaulting to system nominal")
            set_double(model, name, "nominal_output_frequency", float(g(model, "nominal_frequency") or 60.0))
        for prop_ in ("rated_motor_speed", "motor_poles", "rated_horse_power"):
            if get_double(model, name, prop_) <= 0:
                raise PowerflowError(f"{label} - {prop_} must be positive and non-zero!")
        if (get_int(model, name, "phases") & (PHASE_A|PHASE_B|PHASE_C)) != (PHASE_A|PHASE_B|PHASE_C):
            raise PowerflowError(f"{label} - Must be three-phase!")
        length = int(get_double(model, name, "stable_time") + 0.5)
        if length <= 0:
            raise PowerflowError(f"{label} - Allocating the dynamic arrays for the frequency tracking failed")
        state = object_state(model, name)
        state.update(vfd_window=[0.0]*length, vfd_pos=0, vfd_phasor=list(BASE), vfd_prev_rpm=0.0,
            vfd_prev_state=VFD_OFF, vfd_pin=0j, vfd_time=None)
        if get_int(model, name, "vfd_state") == VFD_STEADY:
            state["vfd_prev_rpm"] = get_double(model, name, "desired_motor_speed")
            state["vfd_prev_state"] = VFD_STEADY
            cls.check_parameters(model, name)
            set_double(model, name, "current_output_frequency", get_double(model, name, "desired_output_frequency"))

    @classmethod
    def set_state(cls, model:Any, name:str, value:int) -> None:
        """Set `vfd_state`"""
        model.objects[name]["vfd_state"] = STATE_NAMES[value]

    @classmethod
    def check_parameters(cls, model:Any, name:str) -> None:
        """`vfd::CheckParameters()`"""
        out = msg(model, name)
        obj = model.objects[name]
        state = object_state(model, name)
        rpm = get_double(model, name, "desired_motor_speed")
        if rpm < 0:
            raise PowerflowError(f"VFD:{obj.id} - {name} - the desired_motor_speed must be positive")
        if rpm == 0:
            cls.set_state(model, name, VFD_OFF)
        if state["vfd_prev_rpm"] == 0 and rpm > 0:
            cls.set_state(model, name, VFD_STEADY)
        frequency = rpm*get_double(model, name, "motor_poles")/120.0
        set_double(model, name, "desired_output_frequency", frequency)
        if 0 < frequency < 3.0:
            out.warning(f"VFD:{obj.id} - {name} - the desired_motor_speed results in a frequency of less than 3.0 Hz")
        rated = get_double(model, name, "rated_motor_speed")
        if rpm/rated <= 0.75:
            out.warning(f"VFD:{obj.id} - {name} - VFD currently at {rpm*100/rated:f}% of rated speed -- VFDs perform best when running at >= 75 percent output")

    @classmethod
    def update(cls, model:Any, name:str, t0:int) -> None:
        """The state and frequency update of `VFD_current_injection()`"""
        # pylint: disable=too-many-branches,too-many-statements
        state = object_state(model, name)
        changed = False
        if state["vfd_prev_rpm"] != get_double(model, name, "desired_motor_speed"):
            cls.check_parameters(model, name)
            changed = True
            state["vfd_prev_rpm"] = get_double(model, name, "desired_motor_speed")
        now, prev = float(t0), state["vfd_prev_time"]
        if now == prev:
            return
        dt = now - prev
        steps = int(now - prev)
        window = state["vfd_window"]
        length = len(window)
        current = get_double(model, name, "current_output_frequency")
        desired = get_double(model, name, "desired_output_frequency")
        vstate = get_int(model, name, "vfd_state")
        if vstate == VFD_STEADY:
            if state["vfd_prev_state"] == VFD_OFF:
                vstate = VFD_CHANGING
                state["vfd_phasor"] = list(BASE)
                current = 3.0
                state["vfd_pos"] = 0
                window[:] = [3.0]*length
                steps = 1
            elif state["vfd_prev_state"] == VFD_CHANGING:
                state["vfd_prev_state"] = VFD_STEADY
            elif current != desired:
                vstate = VFD_CHANGING
                window[:] = [current]*length
                state["vfd_pos"] = 0
        if vstate == VFD_CHANGING:
            if state["vfd_prev_state"] == VFD_CHANGING and changed:
                window[:] = [current]*length
                state["vfd_pos"] = 0
                steps = 1
            if state["vfd_pos"] == length:
                vstate = VFD_STEADY
            else:
                limit = state["vfd_pos"] + steps
                if limit > length:
                    window[state["vfd_pos"]:] = [desired]*(length - state["vfd_pos"])
                    state["vfd_pos"] = length
                    vstate = VFD_STEADY
                else:
                    window[state["vfd_pos"]:limit] = [desired]*(limit - state["vfd_pos"])
                    state["vfd_pos"] = limit
                current = sum(window)/length
        if vstate == VFD_OFF:
            current = 0.0
        state["vfd_prev_state"] = vstate
        state["vfd_prev_time"] = now
        if vstate != VFD_OFF:
            nominal = 2*math.pi*float(g(model, "nominal_frequency") or 60.0)
            state["vfd_phasor"] = [p + (2*math.pi*current - nominal)*dt for p in state["vfd_phasor"]]
        cls.set_state(model, name, vstate)
        set_double(model, name, "current_output_frequency", current)

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        """Update the drive and set its output voltages"""
        cls.update(model, name, t0)
        tnode = ref(model, name, "to")
        if get_int(model, name, "vfd_state") == VFD_OFF:
            volts = [0j]*3
        else:
            magnitude = get_double(model, name, "rated_output_voltage")/math.sqrt(3)/get_double(model, name, "nominal_output_frequency")*get_double(model, name, "current_output_frequency")
            volts = [cmath.rect(magnitude, math.fmod(p, 2*math.pi)) for p in object_state(model, name)["vfd_phasor"]]
        old = [get_complex(model, tnode, f"voltage_{x}") for x in "ABC"]
        for x, v in zip("ABC", volts):
            set_complex(model, tnode, f"voltage_{x}", v)
        if all(v != 0 for v in old) and any(v != w for v, w in zip(volts, old)):
            cls.move_fed_voltages(model, name, [v/w for v, w in zip(volts, old)])

    @classmethod
    def move_fed_voltages(cls, model:Any, name:str, ratios:list[complex]) -> None:
        """Scale and turn the voltages of the nodes the drive feeds as its
        output voltages changed, so that each solution starts near the
        drive's new source voltages (an initial guess only)"""
        from ._module import behavior # pylint: disable=import-outside-toplevel
        tnode = top_node(model, ref(model, name, "to"))
        for node in cls.fed_nodes(model, name) - {tnode}:
            node_cls = behavior(model, node)
            if node_cls.split(model, node):
                factors = [ratios[node_cls.base_phase(model, node)]]*2
            else:
                factors = ratios
            for prop_, factor in zip(node_cls.VOLTAGES, factors):
                set_complex(model, node, prop_, get_complex(model, node, prop_)*factor)

    @classmethod
    def node_loads(cls, model:Any, name:str) -> list[tuple[str,str,str,complex]]:
        """The input power on the `from` node, by phase"""
        pin = object_state(model, name).get("vfd_pin", 0j)
        if pin == 0 or get_int(model, name, "vfd_state") == VFD_OFF:
            return []
        fnode = ref(model, name, "from")
        return [(fnode, "power", x, pin) for x in "ABC"]

    @classmethod
    def fed_nodes(cls, model:Any, name:str) -> set[str]:
        """Top nodes the drive feeds: its `to` node and the nodes linked to
        it, other than through the drive"""
        start = top_node(model, ref(model, name, "to"))
        seen, todo = {start}, [start]
        links = [x for x in objects_of(model, "link") if x != name]
        while todo:
            node = todo.pop()
            for link in links:
                ends = (top_node(model, ref(model, link, "from")), top_node(model, ref(model, link, "to")))
                if node in ends:
                    for other in ends:
                        if other not in seen:
                            seen.add(other)
                            todo.append(other)
        return seen

    @classmethod
    def isolates(cls, model:Any, name:str) -> set[tuple[str,int]]:
        """An `OFF` drive takes out the nodes it feeds"""
        if get_int(model, name, "vfd_state") != VFD_OFF or not cls.closed(model, name):
            return set()
        return {(node, k) for node in cls.fed_nodes(model, name) for k in range(3)}

    @classmethod
    def after_solve(cls, model:Any, name:str, t0:int) -> bool:
        """Output power, efficiency, input power, and flows; `True` when
        the input power changed"""
        # pylint: disable=too-many-locals
        from ._module import bus_currents # pylint: disable=import-outside-toplevel
        state = object_state(model, name)
        fnode, tnode = ref(model, name, "from"), ref(model, name, "to")
        zero = np.zeros(3, dtype=complex)
        if get_int(model, name, "vfd_state") == VFD_OFF:
            set_double(model, name, "efficiency", 0.0)
            write_flows(model, name, zero, zero, zero, zero)
            changed = state.get("vfd_pin", 0j) != 0
            state["vfd_pin"] = 0j
            return changed
        frequency = get_double(model, name, "current_output_frequency")
        eff = efficiency(100.0/get_double(model, name, "nominal_output_frequency")*frequency)
        set_double(model, name, "efficiency", eff)
        vt = np.array([get_complex(model, tnode, f"voltage_{x}") for x in "ABC"])
        vf = np.array([get_complex(model, fnode, f"voltage_{x}") for x in "ABC"])
        i_out = np.array(bus_currents(model, tnode) or [0j]*3)
        s_out = vt*np.conj(i_out)
        pin = complex(s_out.sum())*100.0/eff/3.0
        s_in = np.full(3, pin)
        with np.errstate(divide="ignore", invalid="ignore"):
            i_in = np.where(vf != 0, np.conj(s_in/np.where(vf != 0, vf, 1)), 0)
        write_flows(model, name, s_in, s_out, i_in, i_out)
        previous = state.get("vfd_pin", 0j)
        state["vfd_pin"] = pin
        return abs(pin - previous) > 1e-6*max(1.0, abs(pin))

    @classmethod
    def next_event(cls, model:Any, name:str) -> int|None:
        """`vfd::postsync()`: while changing, the time the window fills"""
        state = object_state(model, name)
        if get_int(model, name, "vfd_state") != VFD_CHANGING:
            return None
        left = len(state["vfd_window"]) - state["vfd_pos"]
        if left > 0:
            return int(state["vfd_prev_time"]) + left
        cls.set_state(model, name, VFD_STEADY)
        return None

__all__ = ["VFD", "efficiency"]
