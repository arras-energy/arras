# pylint: disable=line-too-long
"""Class `link`: a branch of the powerflow network

Syntax
------

    object link {
        phases {A,B,C,D,N,S,G}[|...];
        from <node>;
        to <node>;
        status {CLOSED,OPEN};
        nominal_voltage <real> V;
        continuous_rating <real> A;
        emergency_rating <real> A;
        violation_rating <real> A;
        mean_repair_time <real> s;
    }

Outputs: `power_in`, `power_out`, `power_losses` (VA), `power_out_real`
(W), `power_in_X`, `power_out_X`, `power_losses_X` (VA),
`current_in_X`, `current_out_X` (A) for each phase `X` of `A`, `B`, `C`,
and `flow_direction` (`AF`, `AR`, `AN`, ... for normal, reverse, and no
flow on each phase). The fault current and voltage properties are
published and stay 0.

Description
-----------

A link connects the phases it has of its `from` node to those of its `to`
node. When a link initializes, it is expected to:

1. fail when `from` or `to` is not set or is not a node, or when they are
   the same node;
2. wait (defer its initialization) until its nodes have initialized when
   either of them has a parent, as gridlabd's NR initialization does;
3. check its phases as `powerflow_object` does;
4. fail when the solver method is `GS`;
5. fail when its phases (without `N` and `D`) are not all phases of both
   nodes;
6. take the `from` node's nominal voltage when it has none, and fail when
   it is still 0;
7. warn and set `mean_repair_time` to 0 when it is negative; fail when
   `violation_rating` is negative, and set it to
   `powerflow::default_violation_rating` when it is 0.

During a run, a closed link adds its admittance to the network that the
module solves, and receives from each solution, phase by phase:

- `current_in_X = Yff V_from + Yft V_to` and
  `current_out_X = -(Ytf V_from + Ytt V_to)`;
- `power_in_X = V_from,X conj(current_in_X)` and
  `power_out_X = V_to,X conj(current_out_X)`;
- `power_losses_X = power_in_X - power_out_X`, with its real part made
  positive (gridlabd's correction for reverse flows);
- the totals of the phases, and `flow_direction` from the magnitudes of
  the powers in and out (`|S_in| - |S_out|` above `1e-6` is normal flow,
  below `-1e-6` reverse flow, otherwise no flow).

An open link carries nothing (its outputs are 0 and its flow is `AN|BN|CN`).
With the `DC` solver, each phase carries its real power from the DC
solution, with no losses, and its flow direction follows the sign of that
power (the magnitudes in and out are equal, so gridlabd's rule would
always give no flow).

Admittance of the link classes
------------------------------

The classes that derive from `link` in gridlabd (lines, transformers,
regulators, switches, fuses, ...) compute the link's 3x3 matrices. A
behavior class that derives from `Link` gives its admittance by
overriding `series_impedance()` (3x3, ohms) and `shunt_admittance()`
(3x3 at each end, siemens), or `admittance()` (the blocks `Yff`, `Yft`,
`Ytf`, `Ytt` in siemens) for links that are not series elements, such as
transformers; `admittance_key()` gives the values the admittance depends
on, so the module rebuilds the network only when one of them changes.

The base `link` class has no impedance of its own in gridlabd (its `b_mat`
is zero), so here it is a series resistance of
`powerflow::default_resistance` (1e-4 ohm) on each phase, the value
gridlabd gives safety devices (switches, fuses).

Caveats
-------

- Link ratings and limit checks (`powerflow::line_limits`) apply to line
  and transformer classes in gridlabd, which are not ported yet.
- Faults, reliability, deltamode in-rush, and frequency dependence are not
  implemented.
- `fault_voltage_A` ... `fault_voltage_C` are published in amperes, as
  gridlabd publishes them.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A `link` object (of the base class) is a `powerflow::default_resistance`
   resistance on each phase; gridlabd inverts the base class's zero
   matrix, which gives no usable solution.
2. Initialization does not set ranks or parents for the `FBS` method,
   because `FBS` is solved with NR (see the package documentation).

References
----------

- `arras-energy/gridlabd`: `module/powerflow/link.cpp`, `link.h`
"""

from typing import Any

import numpy as np

from ._base import prop, keywords
from ._common import (PHASE_N, PHASE_D, PHASE_BITS, LS_OPEN, LS_CLOSED, LS_INIT, SM_GS, ROUNDOFF,
    FD_A_NORMAL, FD_A_REVERSE, FD_A_NONE, FD_B_NORMAL, FD_B_REVERSE, FD_B_NONE, FD_C_NORMAL,
    FD_C_REVERSE, FD_C_NONE, FD_UNKNOWN, isa, ref, g, msg, object_state, get_int, get_double,
    set_double, set_complex, set_flags, PowerflowError)
from .powerflow_object import PowerflowObject
from .node import init_failed

DEFER = 2
"""`on_init` result that defers the initialization"""

def _out(name:str, unit:str, description:str, ptype:str="complex") -> tuple[str,str,dict[str,Any]]:
    return (f"{name}[{unit}]", ptype, prop(description, flags="OUTPUT"))

class Link(PowerflowObject):
    """Behavior of class `link`"""

    NAME = "link"
    PARENT = "powerflow_object"
    PASSCONFIG = "PRETOPDOWN|BOTTOMUP|POSTTOPDOWN|UNSAFE_OVERRIDE_OMIT|AUTOLOCK"
    PROPERTIES = (
        ("status", "enumeration", prop("", "CLOSED", keywords=keywords(("CLOSED", LS_CLOSED), ("OPEN", LS_OPEN), ("INITIALIZE", LS_INIT)))),
        ("from", "object", prop("from_node - source node", flags="REQUIRED")),
        ("to", "object", prop("to_node - load node", flags="REQUIRED")),
        _out("power_in", "VA", "power flow in (w.r.t from node)"),
        _out("power_out", "VA", "power flow out (w.r.t to node)"),
        _out("power_out_real", "W", "power flow out (w.r.t to node), real", "double"),
        _out("power_losses", "VA", "power losses"),
        *(_out(f"power_in_{x}", "VA", f"power flow in (w.r.t from node), phase {x}") for x in "ABC"),
        *(_out(f"power_out_{x}", "VA", f"power flow out (w.r.t to node), phase {x}") for x in "ABC"),
        *(_out(f"power_losses_{x}", "VA", f"power losses, phase {x}") for x in "ABC"),
        *(_out(f"current_out_{x}", "A", f"current flow out of link (w.r.t. to node), phase {x}") for x in "ABC"),
        *(_out(f"current_in_{x}", "A", f"current flow to link (w.r.t from node), phase {x}") for x in "ABC"),
        *(_out(f"fault_current_in_{x}", "A", f"fault current flowing in, phase {x}") for x in "ABC"),
        *(_out(f"fault_current_out_{x}", "A", f"fault current flowing out, phase {x}") for x in "ABC"),
        *((f"fault_voltage_{x}[A]", "complex", prop(f"fault voltage, phase {x}")) for x in "ABC"),
        ("flow_direction", "set", prop("flag used for describing direction of the flow of power", flags="OUTPUT",
            keywords=keywords(("UNKNOWN", FD_UNKNOWN), ("AF", FD_A_NORMAL), ("AR", FD_A_REVERSE), ("AN", FD_A_NONE),
                ("BF", FD_B_NORMAL), ("BR", FD_B_REVERSE), ("BN", FD_B_NONE), ("CF", FD_C_NORMAL), ("CR", FD_C_REVERSE), ("CN", FD_C_NONE)))),
        ("mean_repair_time[s]", "double", prop("Time after a fault clears for the object to be back in service")),
        ("continuous_rating[A]", "double", prop("Continuous rating for this link object (set individual line segments", "1000 A")),
        ("emergency_rating[A]", "double", prop("Emergency rating for this link object (set individual line segments", "2000 A")),
        ("inrush_convergence_value[V]", "double", prop("Tolerance, as change in line voltage drop between iterations, for deltamode in-rush completion", "0.0001 V")),
        ("violation_rating[A]", "double", prop("current violation rating for this link object")),
    )
    EVENTS = ("init",)

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool|int: # pylint: disable=unused-argument
        """`link::init()` (handler result: `True`, `False` after an error
        message, or 2 to defer)"""
        try:
            if cls.deferred(model, name):
                msg(model, name).verbose(f"link::init(): link:{model.objects[name].id} - {name} - deferring initialization on from/to node")
                return DEFER
            cls.init_object(model, name)
            cls.init_link(model, name)
        except PowerflowError as err:
            init_failed(model, name, err)
            return False
        object_state(model, name)["initialized"] = True
        return True

    @classmethod
    def deferred(cls, model:Any, name:str) -> bool:
        """`True` when the link must wait for its nodes (raises
        `PowerflowError` when a node is missing)"""
        fnode, tnode = ref(model, name, "from"), ref(model, name, "to")
        if fnode is None:
            raise PowerflowError("link from node is not specified")
        if tnode is None:
            raise PowerflowError("link to node is not specified")
        if ref(model, fnode, "parent") is None and ref(model, tnode, "parent") is None:
            return False
        return not (object_state(model, fnode).get("initialized") and object_state(model, tnode).get("initialized"))

    @classmethod
    def init_link(cls, model:Any, name:str) -> None:
        """Link checks (see the module description); raises
        `PowerflowError`"""
        out = msg(model, name)
        obj = model.objects[name]
        fnode, tnode = ref(model, name, "from"), ref(model, name, "to")
        if get_double(model, name, "mean_repair_time") < 0:
            out.warning(f"link:{name} has a negative mean_repair_time, set to 1 hour")
            set_double(model, name, "mean_repair_time", 0.0)
        if fnode == tnode:
            raise PowerflowError(f"link:{obj.id} - {name} - FROM and TO objects are the same object!")
        if g(model, "solver_method") == SM_GS:
            raise PowerflowError("Gauss_Seidel is a deprecated solver and has been removed")
        if not isa(model, fnode, "node"):
            raise PowerflowError("link from reference not a node")
        if not isa(model, tnode, "node"):
            raise PowerflowError("link to reference not a node")
        phases = get_int(model, name, "phases") & ~(PHASE_N | PHASE_D)
        if (get_int(model, fnode, "phases") & phases) != phases or (get_int(model, tnode, "phases") & phases) != phases:
            raise PowerflowError(f"line:{obj.id} - {name} has a phase mismatch at one or both ends")
        if get_double(model, name, "nominal_voltage") == 0:
            set_double(model, name, "nominal_voltage", get_double(model, fnode, "nominal_voltage"))
        if get_double(model, name, "nominal_voltage") == 0:
            raise PowerflowError("nominal voltage is not specified")
        rating = get_double(model, name, "violation_rating")
        if rating < 0:
            raise PowerflowError("negative violation_rating is not valid")
        if rating == 0:
            set_double(model, name, "violation_rating", float(g(model, "default_violation_rating") or 0.0))

    #
    # Admittance (overridden by the link classes)
    #
    @classmethod
    def closed(cls, model:Any, name:str) -> bool:
        """`True` when the link is in the network (`status` not `OPEN`)"""
        return get_int(model, name, "status") != LS_OPEN

    @classmethod
    def phase_mask(cls, model:Any, name:str) -> np.ndarray:
        """1 for each phase A, B, C that the link connects, else 0"""
        phases = get_int(model, name, "phases")
        return np.array([1.0 if phases & bit else 0.0 for bit in PHASE_BITS])

    @classmethod
    def series_impedance(cls, model:Any, name:str) -> np.ndarray:
        """Series impedance (3x3, ohms) on the phases the link connects;
        the base class: `powerflow::default_resistance` on each phase"""
        return np.diag(cls.phase_mask(model, name) * float(g(model, "default_resistance") or 1e-4)).astype(complex)

    @classmethod
    def shunt_admittance(cls, model:Any, name:str) -> tuple[np.ndarray,np.ndarray]: # pylint: disable=unused-argument
        """Shunt admittances (3x3, siemens) at the from and to ends; the
        base class has none"""
        return np.zeros((3, 3), dtype=complex), np.zeros((3, 3), dtype=complex)

    @classmethod
    def admittance(cls, model:Any, name:str) -> tuple[np.ndarray,np.ndarray,np.ndarray,np.ndarray]:
        """Admittance blocks `(Yff, Yft, Ytf, Ytt)` (3x3, siemens) of a
        series element: the inverse of the series impedance on the phases
        the link connects, plus the shunt admittances at each end"""
        z = cls.series_impedance(model, name)
        mask = cls.phase_mask(model, name) > 0
        y = np.zeros((3, 3), dtype=complex)
        if mask.any():
            sub = z[np.ix_(mask, mask)]
            y[np.ix_(mask, mask)] = np.linalg.inv(sub)
        yf, yt = cls.shunt_admittance(model, name)
        return y + yf, -y, -y, y + yt

    @classmethod
    def admittance_key(cls, model:Any, name:str) -> tuple:
        """Values the admittance depends on"""
        return (get_int(model, name, "phases"), cls.closed(model, name), g(model, "default_resistance"))

    #
    # Switching devices and solution hooks (overridden by fuse, switch, ...)
    #
    MAGNITUDE = False
    """`True` when the DC method uses the magnitude of the link's impedance
    (`powerflow.solver.Network.magnitude`)"""

    SWITCH = False
    """`True` for switching devices (gridlabd `SpecialLnk == SWITCH`): when
    one opens phases and its to node has no other link, those phases of
    the to node are taken out of the network (voltage 0), as gridlabd's NR
    does in strictly radial mode"""

    @classmethod
    def connected_phases(cls, model:Any, name:str) -> int:
        """Phase bits (A, B, C) the link connects now: its phases when
        closed, none when open"""
        return get_int(model, name, "phases") & 0x07 if cls.closed(model, name) else 0

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None: # pylint: disable=unused-argument
        """Called before each solution (fuses restore replaced phases)"""

    @classmethod
    def after_solve(cls, model:Any, name:str, t0:int) -> bool: # pylint: disable=unused-argument
        """Called after each solution with the flows written; `True` asks
        for another solution at the same time (fuses blow)"""
        return False

    @classmethod
    def next_event(cls, model:Any, name:str) -> int|None: # pylint: disable=unused-argument
        """Time of the link's next change (a soft event), or `None`"""
        return None

    #
    # Results
    #
    @classmethod
    def set_flows(cls, model:Any, name:str, vf:np.ndarray, vt:np.ndarray, i_in:np.ndarray, i_out:np.ndarray) -> None: # pylint: disable=too-many-arguments,too-many-positional-arguments
        """Write the currents, powers, losses, and flow direction from the
        end voltages and currents (by phase), as gridlabd's
        `calculate_power()` does"""
        s_in = vf*np.conj(i_in)
        s_out = vt*np.conj(i_out)
        write_flows(model, name, s_in, s_out, i_in, i_out)

def write_flows(model:Any, name:str, s_in:np.ndarray, s_out:np.ndarray, i_in:np.ndarray, i_out:np.ndarray, lossless:bool=False) -> None: # pylint: disable=too-many-arguments,too-many-positional-arguments
    """Write a link's outputs from its per-phase powers and currents; with
    `lossless` (the DC method), the flow direction follows the sign of the
    real power, since the powers in and out are equal"""
    loss = s_in - s_out
    loss = np.where(loss.real < 0, -loss.real + 1j*loss.imag, loss)
    direction = FD_UNKNOWN
    for k, shift in enumerate((0, 4, 8)):
        diff = s_in[k].real if lossless else abs(s_in[k]) - abs(s_out[k])
        if diff > ROUNDOFF:
            direction |= FD_A_NORMAL << shift
        elif diff < -ROUNDOFF:
            direction |= FD_A_REVERSE << shift
        else:
            direction |= FD_A_NONE << shift
    for k, x in enumerate("ABC"):
        set_complex(model, name, f"current_in_{x}", complex(i_in[k]))
        set_complex(model, name, f"current_out_{x}", complex(i_out[k]))
        set_complex(model, name, f"power_in_{x}", complex(s_in[k]))
        set_complex(model, name, f"power_out_{x}", complex(s_out[k]))
        set_complex(model, name, f"power_losses_{x}", complex(loss[k]))
    set_complex(model, name, "power_in", complex(s_in.sum()))
    set_complex(model, name, "power_out", complex(s_out.sum()))
    set_double(model, name, "power_out_real", float(s_out.sum().real))
    set_complex(model, name, "power_losses", complex(loss.sum()))
    set_flags(model, name, "flow_direction", direction)

__all__ = ["Link", "write_flows", "DEFER"]
