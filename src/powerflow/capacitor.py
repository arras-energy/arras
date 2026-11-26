# pylint: disable=line-too-long
"""Class `capacitor`: a switched shunt capacitor bank

Syntax
------

    object capacitor {
        phases {A,B,C}[D|N];
        nominal_voltage <real> V;
        phases_connected {A,B,C}[D|N];
        capacitor_A <real> VAr;               // also capacitor_B, capacitor_C
        cap_nominal_voltage <real> V;
        switchA {OPEN,CLOSED};                // also switchB, switchC
        control {MANUAL,VOLT,VAR,VARVOLT,CURRENT};
        control_level {INDIVIDUAL,BANK};
        pt_phase {A,B,C}[D|N];
        voltage_set_low <real> V;             // VOLT, VARVOLT
        voltage_set_high <real> V;
        VAr_set_low <real> VAr;               // VAR, VARVOLT
        VAr_set_high <real> VAr;
        current_set_low <real> A;             // CURRENT
        current_set_high <real> A;
        time_delay <real> s;
        dwell_time <real> s;
        lockout_time <real> s;                // VARVOLT
        remote_sense <node or link>;
        remote_sense_B <node or link>;        // VARVOLT
        // and the other properties of node
    }

Description
-----------

A `capacitor` is a `node` (gridlabd `PT_INHERIT "node"`) with a capacitor
on each of its `phases_connected` (its `phases` when not set), switched by
`switchA`, `switchB`, `switchC`. A closed capacitor of `capacitor_X` VAr is
the shunt admittance `j capacitor_X / cap_nominal_voltage^2` (the node's
`nominal_voltage` when `cap_nominal_voltage` is not set), phase to ground,
or phase to phase (AB, BC, CA for A, B, C) when `phases_connected` has
`D`. The switches change as gridlabd's `capacitor::cap_sync_fxn()` changes
them before each solution:

- `MANUAL`: a change of a switch takes effect after `time_delay`;
- `VOLT`: a monitored voltage (the node's, or `remote_sense`'s; line to
  line when `pt_phase` has `D`) at or below `voltage_set_low` requests
  closing, at or above `voltage_set_high` opening;
- `VAR`: the reactive power into the monitored link (`remote_sense`) at or
  above `VAr_set_high` requests closing, at or below `VAr_set_low`
  opening;
- `VARVOLT`: as `VAR`, but a voltage at or above `voltage_set_high` (or
  the `lockout_time` after one) forces opening;
- `CURRENT`: the current magnitude into the monitored link at or above
  `current_set_high` requests closing, at or below `current_set_low`
  opening;

a request that holds for `dwell_time` becomes the next state, which takes
effect after `time_delay`; with `BANK` control, any monitored (`pt_phase`)
phase closed closes all of them. After each solution the monitored
reactive power or current is read and, the first time at each time step
when it would change a request, the network is solved again; the next
dwell or delay expiry is a soft event. `cap_X_switch_count` counts, for
each time step, a switch that ended the step in a state other than the one
it started it in.

When it initializes, a capacitor is expected to initialize as a `node`,
then to apply gridlabd's checks on its sensors, set points, monitored
phases, and connection (errors and warnings with gridlabd's messages).

Caveats
-------

- gridlabd alternates its control with its NR passes; here it acts before
  each solution on the values of the last one, so a switch can change one
  solution earlier or later than in gridlabd.
- Out-of-service nodes, deltamode, and the reliability functions are not
  ported.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A delta-connected capacitor on a wye node is a phase-to-phase shunt
   admittance in the network; gridlabd converts it to equivalent wye
   admittances from the voltages of the previous iteration (the same at
   convergence).
2. A wye-connected capacitor on a delta node fails the initialization;
   gridlabd fails at its first solution with the same message.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/capacitor.cpp`, `capacitor.h`
"""

from typing import Any

from ._base import prop, keywords
from ._common import (PHASE_A, PHASE_B, PHASE_C, PHASE_D, PHASE_N, isa, ref, msg,
    object_state, get_int, get_double, get_complex, set_double, PowerflowError)
from .node import Node

MANUAL, VAR, VOLT, VARVOLT, CURRENT = range(5)
"""`control` values"""

OPEN, CLOSED = 0, 1
"""Switch states"""

BANK, INDIVIDUAL = 0, 1
"""`control_level` values"""

_PHASES = keywords(("A", PHASE_A), ("B", PHASE_B), ("C", PHASE_C), ("D", PHASE_D), ("N", PHASE_N))
_SWITCH = keywords(("OPEN", OPEN), ("CLOSED", CLOSED))
BITS = (PHASE_A, PHASE_B, PHASE_C)
PAIRS = (PHASE_A | PHASE_B, PHASE_B | PHASE_C, PHASE_C | PHASE_A)

class Capacitor(Node):
    """Behavior of class `capacitor`"""

    NAME = "capacitor"
    PARENT = "node"
    PROPERTIES = (
        ("pt_phase", "set", prop("Phase(s) that the PT is on, used as measurement points for control", keywords=_PHASES)),
        ("phases_connected", "set", prop("phases capacitor is connected to", keywords=_PHASES)),
        *((f"switch{x}", "enumeration", prop(f"capacitor {x} switch open or close", "OPEN", keywords=_SWITCH)) for x in "ABC"),
        ("control", "enumeration", prop("control operation strategy", "MANUAL", keywords=keywords(
            ("MANUAL", MANUAL), ("VAR", VAR), ("VOLT", VOLT), ("VARVOLT", VARVOLT), ("CURRENT", CURRENT)))),
        *((f"cap_{x}_switch_count", "double", prop(f"number of switch operations on Phase {x}", "-1", flags="OUTPUT")) for x in "ABC"),
        ("voltage_set_high[V]", "double", prop("Turn off if voltage is above this set point")),
        ("voltage_set_low[V]", "double", prop("Turns on if voltage is below this set point")),
        ("VAr_set_high[VAr]", "double", prop("high VAR set point for VAR control (turn off)")),
        ("VAr_set_low[VAr]", "double", prop("low VAR set point for VAR control (turn on)")),
        ("current_set_low[A]", "double", prop("high current set point for current control mode (turn on)")),
        ("current_set_high[A]", "double", prop("low current set point for current control mode (turn off)")),
        ("capacitor_A[VAr]", "double", prop("Capacitance value for phase A or phase AB")),
        ("capacitor_B[VAr]", "double", prop("Capacitance value for phase B or phase BC")),
        ("capacitor_C[VAr]", "double", prop("Capacitance value for phase C or phase CA")),
        ("cap_nominal_voltage[V]", "double", prop("Nominal voltage for the capacitor. Used for calculation of capacitance value")),
        ("time_delay[s]", "double", prop("control time delay")),
        ("dwell_time[s]", "double", prop("Time for system to remain constant before a state change will be passed")),
        ("lockout_time[s]", "double", prop("Time for capacitor to remain locked out from further switching operations (VARVOLT control)")),
        ("remote_sense", "object", prop("Remote object for sensing values used for control schemes")),
        ("remote_sense_B", "object", prop("Secondary Remote object for sensing values used for control schemes (VARVOLT uses two)")),
        ("control_level", "enumeration", prop("define bank or individual control", "INDIVIDUAL", keywords=keywords(("BANK", BANK), ("INDIVIDUAL", INDIVIDUAL)))),
    )

    #
    # Initialization
    #
    @classmethod
    def init_node(cls, model:Any, name:str) -> None:
        """`capacitor::init()` after `node::init()`; raises
        `PowerflowError`"""
        # pylint: disable=too-many-branches,too-many-statements,too-many-locals
        super().init_node(model, name)
        out = msg(model, name)
        obj = model.objects[name]
        control = get_int(model, name, "control")
        first, second = ref(model, name, "remote_sense"), ref(model, name, "remote_sense_B")
        rnode = rlink = None
        if control == VARVOLT and second is not None:
            if first is None:
                raise PowerflowError(f"Please set the remote sensing location on capacitor:{obj.id} under \"remote_sense\"")
            if isa(model, first, "node") and isa(model, second, "link"):
                rnode, rlink = first, second
            elif isa(model, first, "link") and isa(model, second, "node"):
                rnode, rlink = second, first
            else:
                raise PowerflowError(f"For two remote sensors, Capacitor:{obj.id} requires one link and one node object specified.")
        elif control in (VARVOLT, CURRENT) and second is None and first is not None and isa(model, first, "link"):
            rlink = first
        elif second is not None:
            out.warning(f"Capacitor:{obj.id} has a secondary sensor specified, but is not in VARVOLT control.  This will be ignored.")
        if first is not None and control != VARVOLT:
            if isa(model, first, "node"):
                rnode = first
            elif isa(model, first, "link"):
                rlink = first
        caps = [get_double(model, name, f"capacitor_{x}") for x in "ABC"]
        if not any(caps):
            out.error(f"Capacitor:{obj.id} does not have any capacitance values defined!")
        if get_double(model, name, "cap_nominal_voltage") == 0:
            set_double(model, name, "cap_nominal_voltage", get_double(model, name, "nominal_voltage"))
        if get_double(model, name, "cap_nominal_voltage") == 0:
            raise PowerflowError(f"Capcitor:{obj.id} does not have a node nominal or capacitor nominal voltage specified.")
        vhigh, vlow = get_double(model, name, "voltage_set_high"), get_double(model, name, "voltage_set_low")
        qhigh, qlow = get_double(model, name, "VAr_set_high"), get_double(model, name, "VAr_set_low")
        ihigh, ilow = get_double(model, name, "current_set_high"), get_double(model, name, "current_set_low")
        pt = get_int(model, name, "pt_phase")
        if control == VOLT and (vhigh == 0 or vlow == 0):
            out.warning(f"Capacitor:{obj.id} does not have one or both of its voltage set points set.")
        if control == VARVOLT and vhigh == 0:
            out.warning(f"Capacitor:{obj.id} does not have its upper voltage limit set.")
        if control in (VAR, VARVOLT) and (qhigh == 0 or qlow == 0):
            out.warning(f"Capacitor:{obj.id} does not have one or both of its VAr set points set.")
        if control == CURRENT and (ihigh == 0 or ilow == 0):
            out.warning(f"Capacitor:{obj.id} does not have one or both of its current set points set.")
        if control in (VAR, VARVOLT, CURRENT) and rlink is None:
            raise PowerflowError(f"VAR, VARVOLT, or CURRENT control on capacitor:{obj.id} requires a remote link to monitor.")
        if control in (VAR, VARVOLT) and qlow > qhigh:
            raise PowerflowError(f"The lower VAr limit of capacitor:{obj.id} is larger than the high limit setpoint!")
        if control in (VOLT, VARVOLT) and vlow > vhigh:
            raise PowerflowError(f"The lower voltage limit of capacitor:{obj.id} is larger than the high limit setpoint!")
        if control == CURRENT and ilow > ihigh:
            raise PowerflowError(f"The lower current limit of capacitor:{obj.id} is larger than the high limit setpoint!")
        if control != MANUAL and get_double(model, name, "time_delay") == 0 and get_double(model, name, "dwell_time") == 0:
            out.warning("Automatic controls can oscillate to the iteration limit with no time delays.  To prevent this, ensure your switching limits are reasonable.")
        if control == VARVOLT and get_double(model, name, "lockout_time") == 0:
            out.warning(f"No lockout time specified for capacitor:{obj.id}'s VAR-VOLT control scheme.  May switch excessively.")
        if control != MANUAL and pt & 0x07 == 0:
            raise PowerflowError(f"Capacitor:{obj.id} is set to an automatic scheme, but is not monitoring any phases.")
        if control == MANUAL and get_int(model, name, "control_level") == BANK and pt & 0x07 == 0:
            out.warning(f"Capacitor:{obj.id} is set to manual bank mode, but does not know which phase to monitor.")
        phases = get_int(model, name, "phases")
        if get_int(model, name, "phases_connected") & 0x07 == 0:
            out.warning(f"No capacitor phase connection information is available for capacitor:{obj.id}.  Defaulting to the phases property.")
            model.objects[name]["phases_connected"] = model.objects[name]["phases"]
        connected = get_int(model, name, "phases_connected")
        if control not in (MANUAL, VOLT) and get_int(model, rlink, "phases") & pt != pt:
            raise PowerflowError(f"One of the monitored remote link phases for capacitor:{obj.id} does not exist")
        if control in (VOLT, VARVOLT) and rnode is not None and get_int(model, rnode, "phases") & pt != pt:
            raise PowerflowError(f"One of the monitored remote node phases for capacitor:{obj.id} does not exist")
        if control in (VOLT, VARVOLT) and rnode is None and phases & pt != pt:
            raise PowerflowError(f"One of the monitored node phases for capacitor:{obj.id} does not exist")
        if connected & PHASE_D != PHASE_D and phases & PHASE_D == PHASE_D:
            raise PowerflowError(f"Capacitor:{obj.id} is Wye-connected on a Delta-connected node.  This is not supported at this time.")
        for x in "ABC":
            if get_double(model, name, f"cap_{x}_switch_count") < 0:
                set_double(model, name, f"cap_{x}_switch_count", 0.0)
        switches = cls.switches(model, name)
        object_state(model, name).update(rnode=rnode, rlink=rlink, next=list(switches), prev=list(switches), request=list(switches),
            time_to_change=0.0, dwell_left=0.0, lockout_left=[0.0]*3, last_time=None, var=[0.0]*3, current=[0.0]*3,
            not_first=False, checked=None, step=None, step_switches=None, step_counts=None)

    #
    # Switches and admittance
    #
    @classmethod
    def switches(cls, model:Any, name:str) -> list[int]:
        """Switch states A, B, C"""
        return [get_int(model, name, f"switch{x}") for x in "ABC"]

    @classmethod
    def set_switches(cls, model:Any, name:str, states:list[int]) -> None:
        """Write the switch states"""
        for x, state in zip("ABC", states):
            model.objects[name][f"switch{x}"] = "CLOSED" if state == CLOSED else "OPEN"

    @classmethod
    def load_terms(cls, model:Any, name:str) -> dict[tuple[str,str],complex]:
        """The closed capacitors as shunt admittances (phase to phase for a
        delta connection on a wye node)"""
        connected = get_int(model, name, "phases_connected")
        vnom = get_double(model, name, "cap_nominal_voltage")
        if vnom == 0:
            return {}
        delta_cap = connected & PHASE_D == PHASE_D
        delta_node = get_int(model, name, "phases") & PHASE_D == PHASE_D
        terms = {}
        for k, x in enumerate("ABC"):
            if connected & BITS[k] and get_int(model, name, f"switch{x}") == CLOSED:
                y = 1j*get_double(model, name, f"capacitor_{x}")/(vnom*vnom)
                suffix = ("AB", "BC", "CA")[k] if delta_cap and not delta_node else x
                if y != 0:
                    terms[("shunt", suffix)] = y
        return terms

    #
    # Control
    #
    @classmethod
    def _voltages(cls, model:Any, name:str) -> list[float]:
        """Monitored voltage magnitudes (line to line when `pt_phase` has
        `D`)"""
        node = object_state(model, name)["rnode"] or name
        line = get_int(model, name, "pt_phase") & PHASE_D == PHASE_D
        props = ("voltage_AB", "voltage_BC", "voltage_CA") if line else ("voltage_A", "voltage_B", "voltage_C")
        return [abs(get_complex(model, node, p)) for p in props]

    @classmethod
    def _monitors(cls, model:Any, name:str, k:int) -> bool:
        """`True` when phase `k` (or pair, line to line) is monitored"""
        pt = get_int(model, name, "pt_phase")
        mask = PAIRS[k] if pt & PHASE_D == PHASE_D else BITS[k]
        return pt & mask == mask

    @classmethod
    def _requests(cls, model:Any, name:str, requests:list[int], var:list[float], current:list[float], volts:list[float]|None, lockout:list[float]) -> list[bool]:
        """The requests of the automatic controls (gridlabd's `switch
        (control)`), changed in place; the phases whose VARVOLT lockout
        starts"""
        # pylint: disable=too-many-arguments,too-many-positional-arguments
        control = get_int(model, name, "control")
        pt = get_int(model, name, "pt_phase")
        locks = [False]*3
        def band(values:list[float], low:float, high:float, below:int) -> None:
            for k in range(3):
                if pt & BITS[k]:
                    if low >= values[k]:
                        requests[k] = below
                    elif high <= values[k]:
                        requests[k] = CLOSED if below == OPEN else OPEN
        if control in (VAR, VARVOLT):
            band(var, get_double(model, name, "VAr_set_low"), get_double(model, name, "VAr_set_high"), OPEN)
            if control == VARVOLT and volts is not None:
                high = get_double(model, name, "voltage_set_high")
                for k in range(3):
                    if lockout[k] <= 0:
                        if cls._monitors(model, name, k) and volts[k] >= high:
                            requests[k] = OPEN
                            locks[k] = True
                    else:
                        requests[k] = OPEN
        elif control == VOLT and volts is not None:
            low, high = get_double(model, name, "voltage_set_low"), get_double(model, name, "voltage_set_high")
            for k in range(3):
                if cls._monitors(model, name, k):
                    if low >= volts[k]:
                        requests[k] = CLOSED
                    elif high <= volts[k]:
                        requests[k] = OPEN
        elif control == CURRENT:
            band(current, get_double(model, name, "current_set_low"), get_double(model, name, "current_set_high"), OPEN)
        return locks

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        """gridlabd's `cap_sync_fxn()`: timers, manual changes, the control,
        and the switches"""
        # pylint: disable=too-many-branches,too-many-locals,too-many-statements
        state = object_state(model, name)
        if "next" not in state:
            return
        if state["step"] != t0:
            state["step"] = t0
            state["step_switches"] = cls.switches(model, name)
            state["step_counts"] = [get_double(model, name, f"cap_{x}_switch_count") for x in "ABC"]
        elapsed = 0 if state["last_time"] is None else t0 - state["last_time"]
        state["last_time"] = t0
        state["time_to_change"] -= elapsed
        state["dwell_left"] -= elapsed
        state["lockout_left"] = [x - elapsed for x in state["lockout_left"]]
        control = get_int(model, name, "control")
        bank = get_int(model, name, "control_level") == BANK
        pt = get_int(model, name, "pt_phase")
        delay = get_double(model, name, "time_delay")
        switches = cls.switches(model, name)
        nxt, prev, req = state["next"], state["prev"], state["request"]
        if control == MANUAL:
            for k in range(3):
                if switches[k] != prev[k]:
                    if bank and not pt & BITS[k] and delay == 0:
                        switches[k] = nxt[k]
                    else:
                        nxt[k] = switches[k]
                        switches[k] = prev[k]
                    state["time_to_change"] = delay
        if state["time_to_change"] <= 0 and state["not_first"]:
            connected = get_int(model, name, "phases_connected")
            for k in range(3):
                if connected & BITS[k]:
                    switches[k] = nxt[k]
            volts = cls._voltages(model, name) if control in (VOLT, VARVOLT) else None
            if control == MANUAL:
                prev[:] = nxt
            else:
                locks = cls._requests(model, name, req, state["var"], state["current"], volts, state["lockout_left"])
                lockout = get_double(model, name, "lockout_time")
                if any(locks):
                    if bank:
                        state["lockout_left"] = [lockout]*3
                    else:
                        state["lockout_left"] = [lockout if locks[k] else state["lockout_left"][k] for k in range(3)]
                if prev != req:
                    state["dwell_left"] = get_double(model, name, "dwell_time")
                    prev[:] = req
                if state["dwell_left"] <= 0:
                    nxt[:] = req
            if bank:
                closed = any(cls._monitors(model, name, k) and nxt[k] == CLOSED for k in range(3))
                nxt[:] = [CLOSED if closed else OPEN]*3
                if control == MANUAL:
                    prev[:] = nxt
                    switches = list(nxt)
                else:
                    req[:] = nxt
            state["time_to_change"] = delay if switches != nxt else -1
        cls.set_switches(model, name, switches)

    @classmethod
    def after_solve(cls, model:Any, name:str, t0:int) -> bool:
        """gridlabd's `postsync()`: the switch counts, the first-solution
        reiteration, and the monitored reactive powers or currents (another
        solution when they change a request, once per time step)"""
        state = object_state(model, name)
        if "next" not in state:
            return False
        switches = cls.switches(model, name)
        for k, x in enumerate("ABC"):
            set_double(model, name, f"cap_{x}_switch_count", state["step_counts"][k] + (switches[k] != state["step_switches"][k]))
        if not state["not_first"]:
            state["not_first"] = True
            state["time_to_change"] = -1
            return True
        if switches != state["next"] and state["time_to_change"] <= 0:
            return True # a change without a time delay takes effect at the next solution
        control = get_int(model, name, "control")
        rlink = state["rlink"]
        if control in (VAR, VARVOLT):
            state["var"] = [get_complex(model, rlink, f"power_in_{x}").imag for x in "ABC"]
        elif control == CURRENT:
            state["current"] = [abs(get_complex(model, rlink, f"current_in_{x}")) for x in "ABC"]
        else:
            return False
        if state["checked"] == t0:
            return False
        state["checked"] = t0
        test = list(state["request"])
        volts = cls._voltages(model, name) if control == VARVOLT else None
        cls._requests(model, name, test, state["var"], state["current"], volts, state["lockout_left"])
        return test != state["request"]

    @classmethod
    def next_event(cls, model:Any, name:str) -> int|None:
        """The end of the dwell time, else of the time delay"""
        state = object_state(model, name)
        if state.get("step") is None:
            return None
        for left in (state["dwell_left"], state["time_to_change"]):
            if left > 0:
                return state["step"] + max(1, int(left))
        return None

__all__ = ["Capacitor"]
