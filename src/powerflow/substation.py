# pylint: disable=line-too-long
"""Class `substation`: a node that joins the distribution network to a
transmission model or to sequence voltages

Syntax
------

    object substation {
        phases ABC[N|D];
        nominal_voltage <real> V;
        bustype SWING;
        parent <pypower.load>;               // optional
        zero_sequence_voltage <complex> V;   // when no parent
        positive_sequence_voltage <complex> V;
        negative_sequence_voltage <complex> V;
        reference_phase {PHASE_A,PHASE_B,PHASE_C};
        base_power <real> VA;
        power_convergence_value <real> VA;
        transmission_level_constant_power_load <complex> VA;
        transmission_level_constant_current_load <complex> A;
        transmission_level_constant_impedance_load <complex> Ohm;
        // and the other properties of node
    }

Description
-----------

A `substation` is a `node` (gridlabd `PT_INHERIT "node"`) that works in
one of three modes, as gridlabd's `substation` does:

- with a `pypower` `load` parent (gridlabd's `pw_load` parent of module
  `network` is not ported), the substation is the swing bus of the
  distribution network: before each solution its positive sequence
  voltage is the load's voltage `V` (in kV, line to line, as the
  `pypower` module keeps it) converted to volts line to neutral, the zero
  and negative sequence voltages are 0; after each solution, when the
  total change of the phase power magnitudes since the previous solution
  is at most `power_convergence_value`, it posts the distribution load to
  the parent, in MVA: `P` is the transmission-level constant power plus
  the distribution power, `I = conj(I_t) Vn / 1e6`, and
  `Z = Vn^2 / conj(Z_t) / 1e6` (0 when `Z_t` is 0), with `I_t` and `Z_t`
  the transmission-level constant current and impedance loads and `Vn`
  the load's nominal voltage in volts;
- with nonzero sequence voltages and no parent, the substation converts
  them to its phase voltages before each solution;
- otherwise (no parent and zero sequence voltages, or a parent that is
  not a `pypower` load) it is a normal node, with a warning.

When it converts sequence voltages, the phase voltages are
`V_A = (V0 + V1 + V2) r`, `V_B = (V0 + a^2 V1 + a V2) r`,
`V_C = (V0 + a V1 + a^2 V2) r` with `a = 1 at 120 deg` and `r` the
reference phase rotation (1, `1 at 120 deg`, `1 at -120 deg` for
`PHASE_A`, `PHASE_B`, `PHASE_C`).

After each solution, in every mode, it writes `distribution_power_X`
(`V_X conj(I_X)`, with `I_X` the current the node draws for its loads
and the links it feeds, as gridlabd's `current_inj`: at a swing node the
current it supplies), their sum `distribution_load`,
`distribution_current_X` (`I_X`), and `distribution_voltage_X`,
`distribution_voltage_XY` (the node voltages). At each new time,
`distribution_real_energy` is increased by the real distribution power
of the previous solution times the time elapsed, when the real powers of
all three phases are nonzero.

When it initializes, a substation is expected to warn and set
`base_power` to 100 VA when it is not positive, and
`power_convergence_value` to 1% of `base_power` when it is not positive;
with a `pypower` load parent, to fail when the load's nominal voltage
`Vn` (kV, line to line) differs from `sqrt(3)` times `nominal_voltage` by
more than 0.1%, and to warn and become a swing bus when it is not one;
with sequence voltages, to warn when it is not a swing bus; and, unless
it is a normal node, to fail without phases A, B, and C; then to
initialize as a `node`.

Caveats
-------

- The posted loads reach the `pypower` load at the next time the
  `pypower` module solves, as the parent's values do in gridlabd.
- Deltamode is not ported.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. With a `pypower` load parent, the load's voltage and nominal voltage
   are converted from kV line to line to volts line to neutral before
   they are used; gridlabd compares `Vn` (kV) with `nominal_voltage`
   (volts) and uses `V` (kV, line to line) as the positive sequence
   voltage in volts, so it works only in a model whose distribution
   voltages are in kV line to line.
2. The sequence voltages are converted with every solver method;
   gridlabd converts them only with NR and FBS.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/substation.cpp`, `substation.h`
"""

import cmath
import math
from typing import Any

from ._base import prop, keywords
from ._common import (PHASE_A, PHASE_B, PHASE_C, SWING, SWING_PQ, ref, msg, object_state, get_int, get_double,
    get_complex, set_complex, set_double, PowerflowError)
from .node import Node

PHASE_KEYWORDS = keywords(("PHASE_A", 0), ("PHASE_B", 1), ("PHASE_C", 2))

ALPHA = cmath.rect(1.0, 2*math.pi/3)
"""Sequence operator `a`"""

MODE_PARENT, MODE_SEQUENCE, MODE_NODE = 1, 0, 2
"""gridlabd's `has_parent` values: a transmission load parent, sequence
voltages, a normal node"""

def _out(description:str|None=None) -> dict[str,Any]:
    return prop(description, flags="OUTPUT") if description else prop(flags="OUTPUT")

def pypower_load(model:Any, name:str|None) -> bool:
    """`True` when an object is a `pypower` `load`"""
    if name is None or name not in model.objects:
        return False
    oclass = model.objects[name].oclass
    return oclass.name == "load" and oclass.module == "pypower"

def sequence_to_phase(seq:list[complex], reference:int) -> list[complex]:
    """Phase voltages of the zero, positive, and negative sequence voltages
    with reference phase `reference` (0, 1, 2 for A, B, C)"""
    rot = (1.0, ALPHA, ALPHA.conjugate())[reference]
    v0, v1, v2 = seq
    return [(v0 + v1 + v2)*rot, (v0 + ALPHA**2*v1 + ALPHA*v2)*rot, (v0 + ALPHA*v1 + ALPHA**2*v2)*rot]

class Substation(Node):
    """Behavior of class `substation`"""

    NAME = "substation"
    PARENT = "node"
    TRL = 7 # TRL_PROTOTYPE
    PROPERTIES = (
        ("zero_sequence_voltage[V]", "complex", prop("The zero sequence representation of the voltage for the substation object.")),
        ("positive_sequence_voltage[V]", "complex", prop("The positive sequence representation of the voltage for the substation object.")),
        ("negative_sequence_voltage[V]", "complex", prop("The negative sequence representation of the voltage for the substation object.")),
        ("base_power[VA]", "double", prop("The 3 phase VA power rating of the substation.")),
        ("power_convergence_value[VA]", "double", prop("Default convergence criterion before power is posted to pw_load objects if connected, otherwise ignored")),
        ("reference_phase", "enumeration", prop("The reference phase for the positive sequence voltage.", "PHASE_A", keywords=PHASE_KEYWORDS)),
        ("transmission_level_constant_power_load[VA]", "complex", _out("the average constant power load to be posted directly to the pw_load object.")),
        ("transmission_level_constant_current_load[A]", "complex", _out("the average constant current load at nominal voltage to be posted directly to the pw_load object.")),
        ("transmission_level_constant_impedance_load[Ohm]", "complex", _out("the average constant impedance load at nominal voltage to be posted directly to the pw_load object.")),
        ("distribution_load[VA]", "complex", _out("The total load of all three phases at the substation object.")),
        *((f"distribution_power_{x}[VA]", "complex", _out()) for x in "ABC"),
        *((f"distribution_voltage_{x}[V]", "complex", _out()) for x in ("A", "B", "C", "AB", "BC", "CA")),
        *((f"distribution_current_{x}[A]", "complex", _out()) for x in "ABC"),
        ("distribution_real_energy[Wh]", "double", _out()),
    )

    @classmethod
    def init_node(cls, model:Any, name:str) -> None:
        """`substation::init()`, then `node::init()`; raises
        `PowerflowError`"""
        out = msg(model, name)
        obj = model.objects[name]
        if get_double(model, name, "base_power") <= 0:
            out.warning(f"substation:{obj.id} is using the default base power of 100 VA. This could cause instability on your system.")
            set_double(model, name, "base_power", 100.0)
        if get_double(model, name, "power_convergence_value") <= 0:
            out.warning("power_convergence_value not set - defaulting to 0.01 base_power")
            set_double(model, name, "power_convergence_value", 0.01*get_double(model, name, "base_power"))
        parent = ref(model, name, "parent")
        if parent is not None:
            if pypower_load(model, parent):
                vn = get_double(model, parent, "Vn")*1000.0
                vll = get_double(model, name, "nominal_voltage")*math.sqrt(3)
                if abs(vn - vll) > 1e-3*max(vn, vll):
                    raise PowerflowError(f"pypower load bus nominal voltage (Vn {vn/1000:.4g} kV) and substation (nominal_voltage {vll/1000:.4g} kV line to line) do not match to within 0.1%")
                if get_int(model, name, "bustype") not in (SWING, SWING_PQ):
                    out.warning("substation attached to pypower load and not a SWING bus - forcing bustype SWING")
                    model.objects[name]["bustype"] = "SWING"
                mode = MODE_PARENT
            else:
                mode = MODE_NODE
        elif any(get_complex(model, name, f"{x}_sequence_voltage") != 0 for x in ("zero", "positive", "negative")):
            if get_int(model, name, "bustype") not in (SWING, SWING_PQ):
                out.warning("substation is not a SWING bus, so answers may be unexpected")
            mode = MODE_SEQUENCE
        else:
            out.warning(f"substation:{name} is set up as a normal node, no sequence values will be calculated")
            mode = MODE_NODE
        if mode != MODE_NODE and (get_int(model, name, "phases") & (PHASE_A|PHASE_B|PHASE_C)) != (PHASE_A|PHASE_B|PHASE_C):
            raise PowerflowError("substation needs to have all three phases!")
        object_state(model, name).update(sub_mode=mode, sub_last=[0j]*3, sub_time=None)
        super().init_node(model, name)

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        """`substation::presync()` (energy) and `substation::sync()`
        (sequence voltages)"""
        state = object_state(model, name)
        last = state.get("sub_last", [0j]*3)
        previous = state.get("sub_time")
        if previous is not None and t0 > previous and previous != 0 and all(p.real != 0 for p in last):
            energy = get_double(model, name, "distribution_real_energy")
            set_double(model, name, "distribution_real_energy", energy + sum(p.real for p in last)*(t0 - previous)/3600.0)
        if previous is None or t0 > previous:
            state["sub_time"] = t0
        mode = state.get("sub_mode", MODE_NODE)
        if mode == MODE_PARENT:
            parent = ref(model, name, "parent")
            set_complex(model, name, "positive_sequence_voltage", get_complex(model, parent, "V")*1000.0/math.sqrt(3))
            set_complex(model, name, "zero_sequence_voltage", 0j)
            set_complex(model, name, "negative_sequence_voltage", 0j)
        seq = [get_complex(model, name, f"{x}_sequence_voltage") for x in ("zero", "positive", "negative")]
        if mode != MODE_NODE and any(v != 0 for v in seq):
            for x, v in zip("ABC", sequence_to_phase(seq, get_int(model, name, "reference_phase"))):
                set_complex(model, name, f"voltage_{x}", v)
            cls.line_voltages(model, name)

    @classmethod
    def after_solve(cls, model:Any, name:str, t0:int) -> bool:
        """The distribution values of `substation::sync()`, and the loads
        posted to a transmission load parent"""
        # pylint: disable=too-many-locals
        from ._module import bus_currents # pylint: disable=import-outside-toplevel
        state = object_state(model, name)
        currents = bus_currents(model, name) or [0j]*3
        volts = [get_complex(model, name, f"voltage_{x}") for x in "ABC"]
        powers = [v*i.conjugate() for v, i in zip(volts, currents)]
        for x, v in zip(("A", "B", "C", "AB", "BC", "CA"), volts + [volts[0] - volts[1], volts[1] - volts[2], volts[2] - volts[0]]):
            set_complex(model, name, f"distribution_voltage_{x}", v)
        for x, i, s in zip("ABC", currents, powers):
            set_complex(model, name, f"distribution_current_{x}", i)
            set_complex(model, name, f"distribution_power_{x}", s)
        set_complex(model, name, "distribution_load", sum(powers))
        last = state.get("sub_last", [0j]*3)
        change = sum(abs(abs(s) - abs(p)) for s, p in zip(powers, last))
        state["sub_last"] = powers
        if state.get("sub_mode") == MODE_PARENT and change <= get_double(model, name, "power_convergence_value"):
            parent = ref(model, name, "parent")
            vn = get_double(model, parent, "Vn")*1000.0
            current = get_complex(model, name, "transmission_level_constant_current_load")
            impedance = get_complex(model, name, "transmission_level_constant_impedance_load")
            set_complex(model, parent, "I", current.conjugate()*vn/1e6)
            set_complex(model, parent, "Z", vn*vn/impedance.conjugate()/1e6 if impedance != 0 else 0j)
            set_complex(model, parent, "P", (get_complex(model, name, "transmission_level_constant_power_load") + sum(powers))/1e6)
        return False

__all__ = ["Substation", "sequence_to_phase"]
