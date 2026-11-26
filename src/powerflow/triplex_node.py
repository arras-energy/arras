# pylint: disable=line-too-long
"""Class `triplex_node`: a split-phase (triplex) node

Syntax
------

    object triplex_node {
        phases {A,B,C}S;
        nominal_voltage <real> V;        // 120 V, line to neutral
        bustype {PQ,PV,SWING,SWING_PQ};
        power_1 <complex> VA;            // also power_2, power_12
        current_1 <complex> A;           // also current_2, current_12
        shunt_1 <complex> S;             // also shunt_2, shunt_12
        // and the properties of powerflow_object
    }

Description
-----------

A `triplex_node` is the split-phase node of a center-tapped secondary:
lines 1 and 2 and a grounded neutral. gridlabd publishes it from
`powerflow_object` (not `node`, so that it does not publish the three-phase
properties), but it is a `node` in C++ (`isa("node")`), which
`powerflow._common.isa()` reproduces through behavior-class inheritance.

In the network, its lines 1 and 2 are the buses of slots 0 and 1, with
`voltage_1` and `voltage_2` the line-to-neutral voltages in gridlabd's
convention (line 2 measured from the neutral to the line, so both are near
`nominal_voltage` at the angle of the node's phase, and `voltage_12 =
voltage_1 + voltage_2`). Its loads, and those of its children, are
`power_1`, `current_1`, `shunt_1` (line 1 to neutral), `_2` (line 2 to
neutral), and `_12` (line 1 to line 2, at the 240 V voltage
`voltage_12`), positive when they draw power, constant currents at the
nominal voltage angle as for `node`. After each solution, `voltage_N` is 0
(the neutral is grounded), `voltage_1N` is `voltage_1`, and `voltage_2N`
is `voltage_2`.

When it initializes, a triplex node is expected to add phase `S` when it
lacks it, with gridlabd's warning, then initialize as a `node` (the
checks that apply to the properties it publishes).

Caveats
-------

- The neutral is solid at ground: a triplex line's neutral is
  Kron-reduced, and `voltage_N` is 0.
- Houses (`house_present`, residential currents), GFA, frequency
  measurement, deltamode, and service status are published but not used.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

None.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/triplex_node.cpp`,
  `triplex_node.h`, `node.cpp`
"""

import cmath
import math
from typing import Any

from ._base import prop, keywords
from ._common import PHASE_S, PQ, PV, SWING, SWING_PQ, NF_HASSOURCE, NF_ISSOURCE, msg, get_int, get_double, get_complex, set_complex, set_flags
from .node import Node

def _hidden(name:str, ptype:str, description:str) -> tuple[str,str,dict[str,Any]]:
    return (name, ptype, prop(description, access="HIDDEN"))

_ACC = "accumulator - used for debugging/interfacing only - "
_PRE = "deltamode-functionality - bus current injection (in = positive), but will not be rotated by powerflow for off-nominal frequency, this an accumulator only, not a output or input variable"

class TriplexNode(Node):
    """Behavior of class `triplex_node`"""

    NAME = "triplex_node"
    PARENT = "powerflow_object"
    VOLTAGES = ("voltage_1", "voltage_2", "voltage_N")
    SUFFIXES = ("1", "2", "12")
    PROPERTIES = (
        ("bustype", "enumeration", prop("defines whether the node is a PQ, PV, or SWING node", "PQ",
            keywords=keywords(("PQ", PQ), ("PV", PV), ("SWING", SWING), ("SWING_PQ", SWING_PQ)))),
        ("busflags", "set", prop("flag indicates node has a source for voltage, i.e. connects to the swing node", "HASSOURCE",
            keywords=keywords(("HASSOURCE", NF_HASSOURCE), ("ISSOURCE", NF_ISSOURCE)))),
        ("reference_bus", "object", prop("reference bus from which frequency is defined")),
        ("maximum_voltage_error[V]", "double", prop("convergence voltage limit or convergence criteria")),
        ("voltage_1[V]", "complex", prop("bus voltage, phase 1 to ground")),
        ("voltage_2[V]", "complex", prop("bus voltage, phase 2 to ground")),
        ("voltage_N[V]", "complex", prop("bus voltage, phase N to ground")),
        ("voltage_12[V]", "complex", prop("bus voltage, phase 1 to 2")),
        ("voltage_1N[V]", "complex", prop("bus voltage, phase 1 to N")),
        ("voltage_2N[V]", "complex", prop("bus voltage, phase 2 to N")),
        *(_hidden(f"prerotated_current_{x}[A]", "complex", _PRE) for x in ("1", "2", "12")),
        *(_hidden(f"residential_nominal_current_{x}[A]", "complex", f"posted current on phase {d} from a residential object, if attached")
            for x, d in (("1", "1"), ("2", "2"), ("12", "1 to 2"))),
        *(_hidden(f"residential_nominal_current_{x}_{part}[A]", "double", f"posted current on phase {d}, {part}, from a residential object, if attached")
            for x, d in (("1", "1"), ("2", "2"), ("12", "1 to 2")) for part in ("real", "imag")),
        *(_hidden(f"acc_temp_current_{x}[A]", "complex", f"{_ACC}current load on phase {d}") for x, d in (("1", "1"), ("2", "2"), ("N", "N"), ("12", "1 to 2"))),
        *(_hidden(f"acc_temp_power_{x}[VA]", "complex", f"{_ACC}power on phase {d}") for x, d in (("1", "1 (120V)"), ("2", "2 (120V)"), ("12", "1 to 2 (240V)"))),
        *(_hidden(f"acc_temp_shunt_{x}[S]", "complex", f"{_ACC}shunt impedance on phase {d}") for x, d in (("1", "1"), ("2", "2"), ("12", "1 to 2"))),
        *(_hidden(f"current_{x}[A]", "complex", f"{_ACC}current load on phase {d}") for x, d in (("1", "1"), ("2", "2"), ("N", "N"), ("12", "1 to 2"))),
        *(_hidden(f"power_{x}[VA]", "complex", f"{_ACC}power on phase {d}") for x, d in (("1", "1 (120V)"), ("2", "2 (120V)"), ("12", "1 to 2 (240V)"))),
        *(_hidden(f"shunt_{x}[S]", "complex", f"{_ACC}shunt impedance on phase {d}") for x, d in (("1", "1"), ("2", "2"), ("12", "1 to 2"))),
        ("house_present", "bool", prop("boolean for detecting whether a house is attached, not an input", "FALSE")),
        ("reset_disabled_island_state", "bool", prop("Deltamode/multi-island flag -- used to reset disabled status (and reform an island)", "FALSE")),
        ("GFA_enable", "bool", prop("Disable/Enable Grid Friendly Applicance(TM)-type functionality", "FALSE")),
        ("GFA_freq_low_trip[Hz]", "double", prop("Low frequency trip point for Grid Friendly Appliance(TM)-type functionality", "59.5 Hz")),
        ("GFA_freq_high_trip[Hz]", "double", prop("High frequency trip point for Grid Friendly Appliance(TM)-type functionality", "60.5 Hz")),
        ("GFA_volt_low_trip[pu]", "double", prop("Low voltage trip point for Grid Friendly Appliance(TM)-type functionality", "0.8 pu")),
        ("GFA_volt_high_trip[pu]", "double", prop("High voltage trip point for Grid Friendly Appliance(TM)-type functionality", "1.2 pu")),
        ("GFA_reconnect_time[s]", "double", prop("Reconnect time for Grid Friendly Appliance(TM)-type functionality", "300 s")),
        ("GFA_freq_disconnect_time[s]", "double", prop("Frequency violation disconnect time for Grid Friendly Appliance(TM)-type functionality", "0.2 s")),
        ("GFA_volt_disconnect_time[s]", "double", prop("Voltage violation disconnect time for Grid Friendly Appliance(TM)-type functionality", "0.2 s")),
        ("GFA_status", "bool", prop("Low frequency trip point for Grid Friendly Appliance(TM)-type functionality", "TRUE")),
        ("service_status", "enumeration", prop("In and out of service flag", "IN_SERVICE", keywords=keywords(("IN_SERVICE", 0), ("OUT_OF_SERVICE", 1)))),
        ("service_status_double", "double", prop("In and out of service flag - type double - will indiscriminately override service_status - useful for schedules")),
        ("previous_uptime[min]", "double", prop("Previous time between disconnects of node in minutes", "-1 min")),
        ("current_uptime[min]", "double", prop("Current time since last disconnect of node in minutes", "-1 min")),
        ("topological_parent", "object", prop("topological parent as per GLM configuration")),
        ("frequency_measure_type", "enumeration", prop("Frequency measurement dynamics-capable implementation", "NONE",
            keywords=keywords(("NONE", 0), ("SIMPLE", 1), ("PLL", 2)))),
        ("sfm_Tf[s]", "double", prop("Transducer time constant for simplified frequency measurement (seconds)", "0.01 s")),
        ("pll_Kp[pu]", "double", prop("Proportional gain of PLL frequency measurement", "10 pu")),
        ("pll_Ki[pu]", "double", prop("Integration gain of PLL frequency measurement", "100 pu")),
        ("measured_angle_1[rad]", "double", prop("bus angle measurement, phase 1N")),
        ("measured_frequency_1[Hz]", "double", prop("frequency measurement, phase 1N")),
        ("measured_angle_2[rad]", "double", prop("bus angle measurement, phase 2N")),
        ("measured_frequency_2[Hz]", "double", prop("frequency measurement, phase 2N")),
        ("measured_angle_12[rad]", "double", prop("bus angle measurement, across the phases")),
        ("measured_frequency_12[Hz]", "double", prop("frequency measurement, across the phases")),
        ("measured_frequency[Hz]", "double", prop("frequency measurement - average of present phases")),
    )

    @classmethod
    def init_node(cls, model:Any, name:str) -> None:
        """`triplex_node::init()`, then `node::init()`"""
        obj = model.objects[name]
        phases = get_int(model, name, "phases")
        if phases & PHASE_S != PHASE_S:
            msg(model, name).warning(f"Init() triplex_node (name:{name}, id:{obj.id}): Phases specified did not include phase S. Adding phase S. Check upstream devices.")
            set_flags(model, name, "phases", phases | PHASE_S)
        super().init_node(model, name)

    @classmethod
    def split(cls, model:Any, name:str) -> bool:
        return True

    @classmethod
    def init_voltages(cls, model:Any, name:str) -> None:
        """Lines 1 and 2 at the nominal voltage and the angle of the node's
        phase, the neutral at 0"""
        nominal = get_double(model, name, "nominal_voltage")
        angle = (0.0, -2*math.pi/3, 2*math.pi/3)[cls.base_phase(model, name)]
        for prop_ in ("voltage_1", "voltage_2"):
            if get_complex(model, name, prop_) == 0:
                set_complex(model, name, prop_, cmath.rect(nominal, angle), "d")
        set_complex(model, name, "voltage_N", 0j, "d")
        cls.line_voltages(model, name)

    @classmethod
    def line_voltages(cls, model:Any, name:str) -> None:
        """`voltage_12`, `voltage_1N`, `voltage_2N`, and the neutral"""
        v1, v2 = get_complex(model, name, "voltage_1"), get_complex(model, name, "voltage_2")
        set_complex(model, name, "voltage_N", 0j, "d")
        set_complex(model, name, "voltage_12", v1 + v2, "d")
        set_complex(model, name, "voltage_1N", v1, "d")
        set_complex(model, name, "voltage_2N", v2, "d")

__all__ = ["TriplexNode"]
