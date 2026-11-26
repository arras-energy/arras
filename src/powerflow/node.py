# pylint: disable=line-too-long
"""Class `node`: a bus of the powerflow network

Syntax
------

    object node {
        phases {A,B,C,D,N,S,G}[|...];
        nominal_voltage <real> V;
        bustype {PQ,PV,SWING,SWING_PQ};
        voltage_A <complex> V;
        voltage_B <complex> V;
        voltage_C <complex> V;
        maximum_voltage_error <real> V;
        power_A <complex> VA;    // also power_B, power_C, and the _AN, _BN, _CN, _AB, _BC, _CA forms
        current_A <complex> A;   // also current_B, current_C, ...
        shunt_A <complex> S;     // also shunt_B, shunt_C, ...
        parent <node>;
    }

The other properties that gridlabd publishes (`busflags`,
`reference_bus`, `mean_repair_time`, the frequency measurement, service
status, GFA, violation threshold, and `DER_value` properties) are
published with their defaults; the solver does not use them yet.

Description
-----------

Each phase `A`, `B`, `C` of a node is a bus of the three-phase network
that the module solves (`powerflow.solver`). When a node initializes, it
is expected to:

1. check its phases as `powerflow_object` does;
2. fail when the solver method is `GS` (removed from gridlabd);
3. when its parent is a node, become a child of it: it is folded into the
   parent's buses (its loads are the parent's, its voltages are copied
   from the parent's); a child of a child is moved to the top node of the
   chain, with a warning; the child's phases must be among the parent's;
   a different nominal voltage is replaced by the parent's, with a
   warning;
4. take its parent's nominal voltage when it has none and its parent is a
   powerflow object; fail when the nominal voltage is not positive;
5. fail when `maximum_voltage_error` is negative, and set it to
   `nominal_voltage` times `powerflow::default_maximum_voltage_error` when
   it is 0;
6. set the voltage of each phase it has that is 0 to the nominal voltage
   at the phase's nominal angle (0, -120, 120 degrees), and the voltages
   of the phases it does not have to 0, then set the line voltages
   `voltage_AB`, `voltage_BC`, `voltage_CA`.

During a run, the module solver is expected to read, at each sync:

- `bustype`: `SWING` and `SWING_PQ` nodes keep their voltages (reference
  buses); `PV` nodes keep their voltage magnitudes; `PQ` nodes are solved;
- the loads of the node and of its children, positive when they draw
  power: `power_X`, `current_X`, and `shunt_X` (`X` is `A`, `B`, `C`) are
  phase-to-ground constant power (VA), current (A, at the nominal voltage),
  and admittance (S) loads, or phase-to-phase loads `AB`, `BC`, `CA` when
  the node has phase `D`; `power_XN`, `current_XN`, `shunt_XN` are
  phase-to-ground and `power_XY`, `current_XY`, `shunt_XY` phase-to-phase
  loads whatever the connection. A constant-current load's current turns
  with the voltage angle and its power follows the voltage magnitude, as
  gridlabd computes it. A split-phase node (phase `S`) has lines 1 and 2
  (bus slots 0 and 1, `voltage_A` and `voltage_B`, both at the angle of its
  phase since gridlabd measures line 2 from the neutral to the line), and
  `power_A`, `power_B`, `power_C` are its line 1, line 2, and line 1 to 2
  loads, as gridlabd keeps them; `triplex_node` publishes them as `_1`,
  `_2`, `_12`;

and to write `voltage_A`, `voltage_B`, `voltage_C` and the line voltages
of each node from the solution.

Caveats
-------

- The load properties are accumulators in gridlabd: load objects add to
  them. Until the `load` class is ported, models set them directly.
- Split-phase (`S`) nodes initialize but the solver refuses them until
  the triplex classes are ported.
- `service_status`, frequency measurement, GFA, DER, and violation
  thresholds are published but not used.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. `shunt_AB`, `shunt_BC`, `shunt_CA`, `shunt_AN`, `shunt_BN`, and
   `shunt_CN` are their own values. gridlabd publishes them at the
   addresses of `power_AB` ... `power_CN`, so setting a delta or explicit
   wye shunt in gridlabd sets a constant-power load instead.
2. The node voltages are computed by the PYPOWER solvers on the full
   three-phase admittance matrix (see `powerflow.solver`) rather than by
   gridlabd's `solver_nr()`; within the solution tolerance the voltages
   are the same.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/node.cpp`, `node.h`
"""

import math
import cmath
from typing import Any

from ._base import prop, keywords
from ._common import (PHASE_A, PHASE_B, PHASE_C, PHASE_S, PQ, PV, SWING, SWING_PQ, NF_HASSOURCE,
    NF_ISSOURCE, SM_GS, isa, ref, g, msg, object_state, get_int, get_double, get_complex,
    set_double, set_complex, runner, PowerflowError)
from .powerflow_object import PowerflowObject

def _hidden(name:str, unit:str, description:str) -> tuple[str,str,dict[str,Any]]:
    return (f"{name}[{unit}]", "complex", prop(description, flags="OUTPUT", access="HIDDEN"))

_INJ = "bus current injection (in = positive), this an accumulator only, not a output or input variable"
_PWR = "bus power injection (in = positive), this an accumulator only, not a output or input variable"
_SHT = "bus shunt admittance, this an accumulator only, not a output or input variable"
_PRE = "deltamode-functionality - bus current injection (in = positive), but will not be rotated by powerflow for off-nominal frequency, this an accumulator only, not a output or input variable"

class Node(PowerflowObject):
    """Behavior of class `node`"""

    NAME = "node"
    PARENT = "powerflow_object"
    PASSCONFIG = "PRETOPDOWN|BOTTOMUP|POSTTOPDOWN|UNSAFE_OVERRIDE_OMIT|AUTOLOCK"
    PROPERTIES = (
        ("bustype", "enumeration", prop("defines whether the node is a PQ, PV, or SWING node", "PQ",
            keywords=keywords(("PQ", PQ), ("PV", PV), ("SWING", SWING), ("SWING_PQ", SWING_PQ)))),
        ("busflags", "set", prop("flag indicates node has a source for voltage, i.e. connects to the swing node", "HASSOURCE",
            keywords=keywords(("HASSOURCE", NF_HASSOURCE), ("ISSOURCE", NF_ISSOURCE)))),
        ("reference_bus", "object", prop("reference bus from which frequency is defined")),
        ("maximum_voltage_error[V]", "double", prop("convergence voltage limit or convergence criteria", "0 V")),
        ("voltage_A[V]", "complex", prop("bus voltage, Phase A to ground", flags="OUTPUT")),
        ("voltage_B[V]", "complex", prop("bus voltage, Phase B to ground", flags="OUTPUT")),
        ("voltage_C[V]", "complex", prop("bus voltage, Phase C to ground", flags="OUTPUT")),
        ("voltage_AB[V]", "complex", prop("line voltages, Phase AB", flags="OUTPUT")),
        ("voltage_BC[V]", "complex", prop("line voltages, Phase BC", flags="OUTPUT")),
        ("voltage_CA[V]", "complex", prop("line voltages, Phase CA", flags="OUTPUT")),
        _hidden("current_A", "A", _INJ), _hidden("current_B", "A", _INJ), _hidden("current_C", "A", _INJ),
        _hidden("power_A", "VA", _PWR), _hidden("power_B", "VA", _PWR), _hidden("power_C", "VA", _PWR),
        _hidden("shunt_A", "S", _SHT), _hidden("shunt_B", "S", _SHT), _hidden("shunt_C", "S", _SHT),
        _hidden("prerotated_current_A", "A", _PRE), _hidden("prerotated_current_B", "A", _PRE), _hidden("prerotated_current_C", "A", _PRE),
        *(_hidden(f"current_{x}", "A", f"bus current {kind}-connected injection (in = positive), this an accumulator only, not a output or input variable")
            for x, kind in (("AB", "delta"), ("BC", "delta"), ("CA", "delta"), ("AN", "wye"), ("BN", "wye"), ("CN", "wye"))),
        *(_hidden(f"power_{x}", "VA", f"bus power {kind}-connected injection (in = positive), this an accumulator only, not a output or input variable")
            for x, kind in (("AB", "delta"), ("BC", "delta"), ("CA", "delta"), ("AN", "wye"), ("BN", "wye"), ("CN", "wye"))),
        *(_hidden(f"shunt_{x}", "S", f"bus shunt {kind}-connected admittance, this an accumulator only, not a output or input variable")
            for x, kind in (("AB", "delta"), ("BC", "delta"), ("CA", "delta"), ("AN", "wye"), ("BN", "wye"), ("CN", "wye"))),
        ("mean_repair_time[s]", "double", prop("Time after a fault clears for the object to be back in service", "0 s")),
        ("frequency_measure_type", "enumeration", prop("Frequency measurement dynamics-capable implementation", "NONE",
            keywords=keywords(("NONE", 1), ("SIMPLE", 2), ("PLL", 3)))),
        ("sfm_Tf[s]", "double", prop("Transducer time constant for simplified frequency measurement (seconds)", "0.01 s")),
        ("pll_Kp[pu]", "double", prop("Proportional gain of PLL frequency measurement", "10 pu")),
        ("pll_Ki[pu]", "double", prop("Integration gain of PLL frequency measurement", "100 pu")),
        ("measured_angle_A[rad]", "double", prop("bus angle measurement, phase A")),
        ("measured_frequency_A[Hz]", "double", prop("frequency measurement, phase A", "60 Hz")),
        ("measured_angle_B[rad]", "double", prop("bus angle measurement, phase B")),
        ("measured_frequency_B[Hz]", "double", prop("frequency measurement, phase B", "60 Hz")),
        ("measured_angle_C[rad]", "double", prop("bus angle measurement, phase C")),
        ("measured_frequency_C[Hz]", "double", prop("frequency measurement, phase C", "60 Hz")),
        ("measured_frequency[Hz]", "double", prop("frequency measurement - average of present phases", "60 Hz")),
        ("service_status", "enumeration", prop("In and out of service flag", "IN_SERVICE",
            keywords=keywords(("IN_SERVICE", 1), ("OUT_OF_SERVICE", 0)))),
        ("service_status_double", "double", prop("In and out of service flag - type double - will indiscriminately override service_status - useful for schedules", "-1")),
        ("previous_uptime[min]", "double", prop("Previous time between disconnects of node in minutes", "-1 min")),
        ("current_uptime[min]", "double", prop("Current time since last disconnect of node in minutes", "-1 min")),
        ("Norton_dynamic", "bool", prop("Flag to indicate a Norton-equivalent connection -- used for generators and deltamode", "FALSE")),
        ("generator_dynamic", "bool", prop("Flag to indicate a voltage-sourcing or swing-type generator is present -- used for generators and deltamode", "FALSE")),
        ("reset_disabled_island_state", "bool", prop("Deltamode/multi-island flag -- used to reset disabled status (and reform an island)", "FALSE")),
        ("GFA_enable", "bool", prop("Disable/Enable Grid Friendly Appliance(TM)-type functionality", "FALSE")),
        ("GFA_freq_low_trip[Hz]", "double", prop("Low frequency trip point for Grid Friendly Appliance(TM)-type functionality", "59.5 Hz")),
        ("GFA_freq_high_trip[Hz]", "double", prop("High frequency trip point for Grid Friendly Appliance(TM)-type functionality", "60.5 Hz")),
        ("GFA_volt_low_trip[pu]", "double", prop("Low voltage trip point for Grid Friendly Appliance(TM)-type functionality", "0.8 pu")),
        ("GFA_volt_high_trip[pu]", "double", prop("High voltage trip point for Grid Friendly Appliance(TM)-type functionality", "1.2 pu")),
        ("GFA_reconnect_time[s]", "double", prop("Reconnect time for Grid Friendly Appliance(TM)-type functionality", "300 s")),
        ("GFA_freq_disconnect_time[s]", "double", prop("Frequency violation disconnect time for Grid Friendly Appliance(TM)-type functionality", "0.2 s")),
        ("GFA_volt_disconnect_time[s]", "double", prop("Voltage violation disconnect time for Grid Friendly Appliance(TM)-type functionality", "0.2 s")),
        ("GFA_status", "bool", prop("Low frequency trip point for Grid Friendly Appliance(TM)-type functionality", "TRUE")),
        ("GFA_trip_method", "enumeration", prop("Reason for GFA trip - what caused the GFA to activate", "NONE",
            keywords=keywords(("NONE", 0), ("UNDER_FREQUENCY", 1), ("OVER_FREQUENCY", 2), ("UNDER_VOLTAGE", 3), ("OVER_VOLTAGE", 4)))),
        ("topological_parent", "object", prop("topological parent as per GLM configuration")),
        ("voltage_violation_threshold[pu]", "double", prop("voltage violation threshold (per unit nominal voltage)", "+0.0 pu")),
        ("undervoltage_violation_threshold[pu]", "double", prop("under-voltage violation threshold (per unit nominal voltage)", "+0.0 pu")),
        ("overvoltage_violation_threshold[pu]", "double", prop("over-voltage violation threshold (per unit nominal voltage)", "+0.0 pu")),
        ("voltage_fluctuation_threshold[pu]", "double", prop("voltage fluctuation violation threshold (per unit nominal voltage)", "+0.0 pu")),
        ("DER_value[VA]", "complex", prop("DER power fluctuation value (per phase)")),
    )
    EVENTS = ("init",)

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`node::init()` (handler result: `True`, or `False` after an
        error message)"""
        try:
            cls.init_object(model, name)
            cls.init_node(model, name)
        except PowerflowError as err:
            init_failed(model, name, err)
            return False
        object_state(model, name)["initialized"] = True
        return True

    @classmethod
    def init_node(cls, model:Any, name:str) -> None:
        """Node checks and voltage initialization (see the module
        description); raises `PowerflowError`"""
        # pylint: disable=too-many-branches
        out = msg(model, name)
        if g(model, "solver_method") == SM_GS:
            raise PowerflowError("Gauss_Seidel is a deprecated solver and has been removed")
        if float(g(model, "default_resistance") or 0.0) <= 0:
            raise PowerflowError("INIT: The global default_resistance was less than or equal to zero. default_resistance must be greater than zero.")
        if model.objects[name].oclass.find_property("mean_repair_time") and get_double(model, name, "mean_repair_time") < 0:
            out.warning(f"node:{name} has a negative mean_repair_time, set to 1 hour")
            set_double(model, name, "mean_repair_time", 0.0)
        parent = ref(model, name, "parent")
        phases = get_int(model, name, "phases")
        if isa(model, parent, "node"):
            top = parent
            if ref(model, parent, "parent") is not None and isa(model, ref(model, parent, "parent"), "node"):
                while isa(model, ref(model, top, "parent"), "node"):
                    top = ref(model, top, "parent")
                oclass = model.objects[top].oclass.name
                out.warning(f"grandchildren objects are not supported, changing parent to {oclass}:{model.objects[top].id} ({top}) -- this might not be what you want")
                model.objects[name]["parent"] = top
            if get_int(model, top, "bustype") in (SWING, SWING_PQ):
                out.warning(f"Node:{name} is parented to a swing node and will get folded into it.")
            if (phases & 0x07) & ~(get_int(model, top, "phases") & 0x07):
                raise PowerflowError(f"NR: Parent and child node phases for nodes {top} and {name} do not match!")
            parent_v = get_double(model, top, "nominal_voltage")
            if get_double(model, name, "nominal_voltage") not in (0.0, parent_v):
                out.warning(f"Node:{name} does not have the same nominal voltage as its parent - copying voltage from parent.")
            set_double(model, name, "nominal_voltage", parent_v)
            object_state(model, name)["parent_bus"] = top
        nominal = get_double(model, name, "nominal_voltage")
        if nominal == 0 and isa(model, parent, "powerflow_object"):
            nominal = get_double(model, parent, "nominal_voltage")
            set_double(model, name, "nominal_voltage", nominal)
        maxerr = get_double(model, name, "maximum_voltage_error")
        if maxerr < 0:
            raise PowerflowError("negative maximum_voltage_error is invalid")
        if not nominal > 0:
            raise PowerflowError("nominal_voltage is not set")
        if maxerr == 0:
            set_double(model, name, "maximum_voltage_error", nominal*float(g(model, "default_maximum_voltage_error") or 0.0))
        cls.init_voltages(model, name)

    @classmethod
    def init_voltages(cls, model:Any, name:str) -> None:
        """Initial voltages (see the module description, step 6)"""
        init_voltages(model, name)

    #
    # Buses (overridden by the split-phase nodes)
    #
    VOLTAGES = ("voltage_A", "voltage_B", "voltage_C")
    """Voltage properties of the bus slots 0, 1, 2 (A, B, C; lines 1, 2,
    and the neutral of a split-phase node)"""

    SUFFIXES = ("A", "B", "C")
    """Load accumulator suffixes of a split-phase node's line 1, line 2,
    and line 1 to 2 loads (gridlabd keeps them in `power[0..2]`)"""

    @classmethod
    def split(cls, model:Any, name:str) -> bool:
        """`True` when the node is split-phase (phase `S`)"""
        return get_int(model, name, "phases") & PHASE_S == PHASE_S

    @classmethod
    def base_phase(cls, model:Any, name:str) -> int:
        """Index of the phase a split-phase node is on"""
        phases = get_int(model, name, "phases")
        return 0 if phases & PHASE_A else (1 if phases & PHASE_B else 2)

    @classmethod
    def bus_slots(cls, model:Any, name:str) -> list[tuple[int,str,float,complex]]:
        """The node's buses: `(slot, label, base voltage, initial voltage)`;
        a split-phase node has lines 1 and 2 in slots 0 and 1, both at the
        angle of its phase (gridlabd measures line 2 from the neutral to
        the line)"""
        vbase = get_double(model, name, "nominal_voltage")
        phases = get_int(model, name, "phases")
        result = []
        if cls.split(model, name):
            angle = (0.0, -2*math.pi/3, 2*math.pi/3)[cls.base_phase(model, name)]
            for slot, label in ((0, "1"), (1, "2")):
                v0 = get_complex(model, name, cls.VOLTAGES[slot])
                result.append((slot, label, vbase, v0 if v0 != 0 else cmath.rect(vbase, angle)))
            return result
        for k, bit in enumerate((PHASE_A, PHASE_B, PHASE_C)):
            if phases & bit:
                v0 = get_complex(model, name, cls.VOLTAGES[k])
                result.append((k, "ABC"[k], vbase, v0 if v0 != 0 else cmath.rect(vbase, (0.0, -2*math.pi/3, 2*math.pi/3)[k])))
        return result

    @classmethod
    def write_voltages(cls, model:Any, name:str, values:dict[int,complex]) -> bool:
        """Write the voltages of the bus slots (0 for a slot taken out of
        the network); `True` when one changed by more than
        `maximum_voltage_error`"""
        from pypower._common import notation # pylint: disable=import-outside-toplevel
        maxerr = get_double(model, name, "maximum_voltage_error")
        changed = False
        for slot, value in values.items():
            prop_ = cls.VOLTAGES[slot]
            if abs(value - get_complex(model, name, prop_)) > maxerr:
                changed = True
            set_complex(model, name, prop_, value, notation(model, name, prop_))
        cls.line_voltages(model, name)
        return changed

    @classmethod
    def line_voltages(cls, model:Any, name:str) -> None:
        """Set the line-to-line voltages"""
        set_line_voltages(model, name)

    #
    # Load terms and solution hooks (overridden by load, capacitor, ...)
    #
    @classmethod
    def load_terms(cls, model:Any, name:str) -> dict[tuple[str,str],complex]: # pylint: disable=unused-argument
        """Loads the node adds to its accumulators, as `{(kind, suffix):
        value}` with `kind` `power`, `current`, or `shunt` and `suffix` as in
        the accumulator names (`A`, `AN`, `AB`, ...); none by default"""
        return {}

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        """Called before each solution"""

    @classmethod
    def after_solve(cls, model:Any, name:str, t0:int) -> bool: # pylint: disable=unused-argument
        """Called after each solution with the voltages and flows written;
        `True` asks for another solution at the same time"""
        return False

    @classmethod
    def next_event(cls, model:Any, name:str) -> int|None: # pylint: disable=unused-argument
        """Time of the node's next change (a soft event), or `None`"""
        return None

def init_failed(model:Any, name:str, err:Exception) -> None:
    """`INIT_CATCHALL()`: the error message gridlabd writes when `init()`
    throws"""
    obj = model.objects[name]
    label = "unnamed" if name == f"{obj.oclass.name}:{obj.id}" else name
    runner().error(f"init_{obj.oclass.name}(obj={obj.id};{label}): {err}")

def init_voltages(model:Any, name:str) -> None:
    """Initial voltages of a node (see the module description, step 6)"""
    nominal = get_double(model, name, "nominal_voltage")
    phases = get_int(model, name, "phases")
    angles = (0.0, -2*math.pi/3, 2*math.pi/3)
    if phases & PHASE_S == PHASE_S:
        base = 0 if phases & PHASE_A else (1 if phases & PHASE_B else 2)
        for prop_ in ("voltage_A", "voltage_B"):
            if get_complex(model, name, prop_) == 0:
                set_complex(model, name, prop_, cmath.rect(nominal, angles[base]), "d")
        set_complex(model, name, "voltage_C", 0j, "d")
    else:
        for k, bit in enumerate((PHASE_A, PHASE_B, PHASE_C)):
            prop_ = "voltage_" + "ABC"[k]
            if not phases & bit:
                set_complex(model, name, prop_, 0j, "d")
            elif get_complex(model, name, prop_) == 0:
                set_complex(model, name, prop_, cmath.rect(nominal, angles[k]), "d")
    set_line_voltages(model, name)

def voltages(model:Any, name:str) -> list[complex]:
    """Phase-to-ground voltages A, B, C of a node (V)"""
    return [get_complex(model, name, f"voltage_{x}") for x in "ABC"]

def set_line_voltages(model:Any, name:str) -> None:
    """Set `voltage_AB`, `voltage_BC`, `voltage_CA` from the phase voltages
    (split-phase nodes: `voltage_AB` is 1 to 2, `voltage_BC` 2 to N,
    `voltage_CA` 1 to N, as gridlabd orders them)"""
    va, vb, vc = voltages(model, name)
    if get_int(model, name, "phases") & PHASE_S == PHASE_S:
        values = (va + vb, vb - vc, va - vc)
    else:
        values = (va - vb, vb - vc, vc - va)
    for prop_, value in zip(("voltage_AB", "voltage_BC", "voltage_CA"), values):
        set_complex(model, name, prop_, value, "d")

def is_child(model:Any, name:str) -> bool:
    """`True` when the node is folded into its parent node's buses"""
    return object_state(model, name).get("parent_bus") is not None

def top_node(model:Any, name:str) -> str:
    """The node whose buses a node uses (itself, or its parent for a
    child)"""
    return object_state(model, name).get("parent_bus") or name

__all__ = ["Node", "init_failed", "voltages", "set_line_voltages", "is_child", "top_node"]
