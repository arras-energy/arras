# pylint: disable=line-too-long
"""Class `triplex_load`: a triplex node with constant-power, -current, and
-impedance loads

Syntax
------

    object triplex_load {
        phases {A,B,C}S;
        nominal_voltage <real> V;
        constant_power_1 <complex> VA;     // also _2, _12, and _real, _reac parts
        constant_current_1 <complex> A;
        constant_impedance_1 <complex> Ohm;
        base_power_1 <real> VA;            // ZIP form, also _2, _12
        power_fraction_1 <real> pu;        // also current_, impedance_
        power_pf_1 <real> pu;              // also current_pf_, impedance_pf_
        // and the other properties of triplex_node
    }

Description
-----------

A `triplex_load` is a `triplex_node` (gridlabd `PT_INHERIT "triplex_node"`)
whose loads are added to its accumulators before each solution, as
gridlabd's `triplex_load::load_update_fxn()` does: `constant_power_X` to
`power_X`, `constant_current_X` to `current_X`, `1/constant_impedance_X`
to `shunt_X` (X = 1, 2: line to neutral; 12: line 1 to line 2), after the
ZIP form and the frequency dependence as for `load`, with these triplex
differences:

- a ZIP current is the current of its power at the nominal voltage (twice
  the nominal voltage for 12) at the angle of the posted voltage
  (`voltage_1`, `voltage_2`, `voltage_12`), and a ZIP impedance of 12 is
  at twice the nominal voltage;
- a `constant_current_X` with a ZIP current part on the same line is
  overridden, with a warning at initialization.

After each solution `measured_voltage_1`, `measured_voltage_2`, and
`measured_voltage_12` are the node's voltages.

Caveats
-------

- GFA and deltamode are not ported.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

None.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/triplex_load.cpp`,
  `triplex_load.h`
"""

import cmath
import math
from typing import Any

from ._base import prop, keywords
from ._common import msg, object_state, get_double, get_complex, set_complex, set_double
from .load import Load, KINDS, ACCUMULATOR, sync_parts
from .triplex_node import TriplexNode

LINES = (("1", "1"), ("2", "2"), ("12", "1 to 2"))
"""Triplex load suffixes and the words in the descriptions"""

DESCRIPTIONS = {
    'load_class': 'Flag to track load type, not currently used for anything except sorting',
    'constant_power_1': 'constant power load on split phase 1, specified as VA',
    'constant_power_2': 'constant power load on split phase 2, specified as VA',
    'constant_power_12': 'constant power load on split phase 12, specified as VA',
    'constant_power_1_real': 'constant power load on spit phase 1, real only, specified as W',
    'constant_power_2_real': 'constant power load on phase 2, real only, specified as W',
    'constant_power_12_real': 'constant power load on phase 12, real only, specified as W',
    'constant_power_1_reac': 'constant power load on phase 1, imaginary only, specified as VAr',
    'constant_power_2_reac': 'constant power load on phase 2, imaginary only, specified as VAr',
    'constant_power_12_reac': 'constant power load on phase 12, imaginary only, specified as VAr',
    'constant_current_1': 'constant current load on phase 1, specified as Amps',
    'constant_current_2': 'constant current load on phase 2, specified as Amps',
    'constant_current_12': 'constant current load on phase 12, specified as Amps',
    'constant_current_1_real': 'constant current load on phase 1, real only, specified as Amps',
    'constant_current_2_real': 'constant current load on phase 2, real only, specified as Amps',
    'constant_current_12_real': 'constant current load on phase 12, real only, specified as Amps',
    'constant_current_1_reac': 'constant current load on phase 1, imaginary only, specified as Amps',
    'constant_current_2_reac': 'constant current load on phase 2, imaginary only, specified as Amps',
    'constant_current_12_reac': 'constant current load on phase 12, imaginary only, specified as Amps',
    'constant_impedance_1': 'constant impedance load on phase 1, specified as Ohms',
    'constant_impedance_2': 'constant impedance load on phase 2, specified as Ohms',
    'constant_impedance_12': 'constant impedance load on phase 12, specified as Ohms',
    'constant_impedance_1_real': 'constant impedance load on phase 1, real only, specified as Ohms',
    'constant_impedance_2_real': 'constant impedance load on phase 2, real only, specified as Ohms',
    'constant_impedance_12_real': 'constant impedance load on phase 12, real only, specified as Ohms',
    'constant_impedance_1_reac': 'constant impedance load on phase 1, imaginary only, specified as Ohms',
    'constant_impedance_2_reac': 'constant impedance load on phase 2, imaginary only, specified as Ohms',
    'constant_impedance_12_reac': 'constant impedance load on phase 12, imaginary only, specified as Ohms',
    'measured_voltage_1': 'measured voltage on phase 1',
    'measured_voltage_2': 'measured voltage on phase 2',
    'measured_voltage_12': 'measured voltage on phase 12',
    'base_power_1': 'in similar format as ZIPload, this represents the nominal power on phase 1 before applying ZIP fractions',
    'base_power_2': 'in similar format as ZIPload, this represents the nominal power on phase 2 before applying ZIP fractions',
    'base_power_12': 'in similar format as ZIPload, this represents the nominal power on phase 12 before applying ZIP fractions',
    'power_pf_1': 'in similar format as ZIPload, this is the power factor of the phase 1 constant power portion of load',
    'current_pf_1': 'in similar format as ZIPload, this is the power factor of the phase 1 constant current portion of load',
    'impedance_pf_1': 'in similar format as ZIPload, this is the power factor of the phase 1 constant impedance portion of load',
    'power_pf_2': 'in similar format as ZIPload, this is the power factor of the phase 2 constant power portion of load',
    'current_pf_2': 'in similar format as ZIPload, this is the power factor of the phase 2 constant current portion of load',
    'impedance_pf_2': 'in similar format as ZIPload, this is the power factor of the phase 2 constant impedance portion of load',
    'power_pf_12': 'in similar format as ZIPload, this is the power factor of the phase 12 constant power portion of load',
    'current_pf_12': 'in similar format as ZIPload, this is the power factor of the phase 12 constant current portion of load',
    'impedance_pf_12': 'in similar format as ZIPload, this is the power factor of the phase 12 constant impedance portion of load',
    'power_fraction_1': 'this is the constant power fraction of base power on phase 1',
    'current_fraction_1': 'this is the constant current fraction of base power on phase 1',
    'impedance_fraction_1': 'this is the constant impedance fraction of base power on phase 1',
    'power_fraction_2': 'this is the constant power fraction of base power on phase 2',
    'current_fraction_2': 'this is the constant current fraction of base power on phase 2',
    'impedance_fraction_2': 'this is the constant impedance fraction of base power on phase 2',
    'power_fraction_12': 'this is the constant power fraction of base power on phase 12',
    'current_fraction_12': 'this is the constant current fraction of base power on phase 12',
    'impedance_fraction_12': 'this is the constant impedance fraction of base power on phase 12',
}
"""gridlabd's descriptions of the properties (irregular, kept as published)"""

def _load_properties() -> tuple:
    result = []
    for kind, unit, real, reac, _ in KINDS:
        for suffix, _ in LINES:
            result.append((f"constant_{kind}_{suffix}[{unit}]", "complex", prop(DESCRIPTIONS[f"constant_{kind}_{suffix}"], f"0 {unit}")))
        for suffix, _ in LINES:
            result.append((f"constant_{kind}_{suffix}_real[{real}]", "double", prop(DESCRIPTIONS[f"constant_{kind}_{suffix}_real"], f"0 {real}")))
        for suffix, _ in LINES:
            result.append((f"constant_{kind}_{suffix}_reac[{reac}]", "double", prop(DESCRIPTIONS[f"constant_{kind}_{suffix}_reac"], f"0 {reac}")))
    return tuple(result)

def _zip_properties() -> tuple:
    result = [(f"base_power_{x}[VA]", "double", prop(DESCRIPTIONS[f"base_power_{x}"])) for x, _ in LINES]
    for x, _ in LINES:
        for kind in ("power", "current", "impedance"):
            result.append((f"{kind}_pf_{x}[pu]", "double", prop(DESCRIPTIONS[f"{kind}_pf_{x}"])))
    for x, _ in LINES:
        for kind in ("power", "current", "impedance"):
            result.append((f"{kind}_fraction_{x}[pu]", "double", prop(DESCRIPTIONS[f"{kind}_fraction_{x}"])))
    return tuple(result)

class TriplexLoad(TriplexNode):
    """Behavior of class `triplex_load`"""

    NAME = "triplex_load"
    PARENT = "triplex_node"
    PROPERTIES = (
        ("load_class", "enumeration", prop(DESCRIPTIONS["load_class"], "U", keywords=keywords(
            ("U", 0), ("R", 1), ("C", 2), ("I", 3), ("A", 4)))),
        *_load_properties(),
        *((f"measured_voltage_{x}[V]", "complex", prop(DESCRIPTIONS[f"measured_voltage_{x}"])) for x, _ in LINES),
        *_zip_properties(),
    )

    @classmethod
    def init_node(cls, model:Any, name:str) -> None:
        """`triplex_load::init()`"""
        super().init_node(model, name)
        values = cls.values(model, name, initial=True)
        if any(values[f"constant_current_{x}"] != 0 and get_double(model, name, f"base_power_{x}") != 0 for x, _ in LINES):
            msg(model, name).warning(f"triplex_load:{name} - ZIP fractions will override constant_current_X values")

    @classmethod
    def values(cls, model:Any, name:str, initial:bool=False) -> dict[str,complex]:
        """The load values by property name after the parts and the ZIP form"""
        values = {}
        for kind, unit, real, reac, _ in KINDS:
            for suffix, _ in LINES:
                whole = f"constant_{kind}_{suffix}"
                values[whole] = sync_parts(model, name, whole, unit, real, reac, initial)
        state = object_state(model, name)
        state["zip_current"] = {}
        for k in range(len(LINES)):
            for whole, value in cls.zip_values(model, name, k).items():
                set_complex(model, name, whole, value)
                set_double(model, name, f"{whole}_real", value.real)
                set_double(model, name, f"{whole}_reac", value.imag)
                state["parts"][whole] = value
                values[whole] = value
        return values

    @classmethod
    def zip_values(cls, model:Any, name:str, k:int) -> dict[str,complex]:
        """ZIP form of line `k` (1, 2, 12)"""
        # pylint: disable=too-many-locals
        x = LINES[k][0]
        state = object_state(model, name)
        nonzero = state.setdefault("zip_nonzero", [False]*3)
        base = get_double(model, name, f"base_power_{x}")
        if base == 0:
            if nonzero[k]:
                nonzero[k] = False
                return {f"constant_{kind}_{x}": 0j for kind in ("power", "current", "impedance")}
            return {}
        nonzero[k] = True
        fractions = {kind: get_double(model, name, f"{kind}_fraction_{x}") for kind in ("power", "current", "impedance")}
        diff = sum(fractions.values()) - 1.0
        if diff != 0:
            if abs(diff) > 1e-3:
                msg(model, name).warning(f"triplex_load:{name} - ZIP components on phase {x} did not sum to 1 (diff is {diff:g}). Setting power_fraction to {fractions['power']:.2f}")
            fractions["power"] -= diff
            set_double(model, name, f"power_fraction_{x}", fractions["power"])
        def apparent(kind:str) -> complex:
            pf = get_double(model, name, f"{kind}_pf_{x}")
            if pf == 0:
                real, imag = 0.0, base*fractions[kind]
            else:
                real = base*fractions[kind]*abs(pf)
                imag = real*math.sqrt(1/(pf*pf) - 1)
            return complex(real, -imag if pf < 0 else imag)
        scale = 2.0 if x == "12" else 1.0
        vnom = get_double(model, name, "nominal_voltage")*scale
        posted = get_complex(model, name, f"voltage_{x}")
        result = {f"constant_power_{x}": apparent("power") if fractions["power"] != 0 else 0j}
        if fractions["current"] != 0:
            current = apparent("current").conjugate()/vnom
            result[f"constant_current_{x}"] = cmath.rect(abs(current), cmath.phase(current) + cmath.phase(posted))
            state["zip_current"][x] = cmath.phase(posted)
        else:
            result[f"constant_current_{x}"] = 0j
        result[f"constant_impedance_{x}"] = (vnom*vnom/apparent("impedance")).conjugate() if fractions["impedance"] != 0 else 0j
        return result

    @classmethod
    def load_terms(cls, model:Any, name:str) -> dict[tuple[str,str],complex]:
        """The load values in the node's accumulators (a ZIP current
        referred to the nominal angle of its line, the network's
        convention)"""
        state = object_state(model, name)
        values = state.get("values") or cls.values(model, name)
        nominal = (0.0, -2*math.pi/3, 2*math.pi/3)[cls.base_phase(model, name)]
        terms = {}
        for kind, *_ in KINDS:
            for suffix, _ in LINES:
                value = values[f"constant_{kind}_{suffix}"]
                if kind == "impedance":
                    value = Load.frequency_impedance(model, value)
                    value = 1/value if value != 0 else 0j
                elif kind == "current" and suffix in state.get("zip_current", {}):
                    value *= cmath.exp(1j*(nominal - state["zip_current"][suffix]))
                if value != 0:
                    terms[(ACCUMULATOR[kind], suffix)] = value
        return terms

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        """Apply the parts and the ZIP form"""
        if "parts" in object_state(model, name):
            object_state(model, name)["values"] = cls.values(model, name)

    @classmethod
    def after_solve(cls, model:Any, name:str, t0:int) -> bool:
        """Write the measured voltages"""
        for x, _ in LINES:
            set_complex(model, name, f"measured_voltage_{x}", get_complex(model, name, f"voltage_{x}"))
        return False

__all__ = ["TriplexLoad"]
