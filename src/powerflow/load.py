# pylint: disable=line-too-long
"""Class `load`: a node with constant-power, -current, and -impedance loads

Syntax
------

    object load {
        phases {A,B,C}[D|N];
        nominal_voltage <real> V;
        constant_power_A <complex> VA;       // also _B, _C, _AN ... _CA,
        constant_current_A <complex> A;      //   _real and _reac parts
        constant_impedance_A <complex> Ohm;
        base_power_A <real> VA;              // ZIP form, also _B, _C
        power_fraction_A <real> pu;          // also current_, impedance_
        power_pf_A <real> pu;                // also current_pf_, impedance_pf_
        // and the other properties of node
    }

Description
-----------

A `load` is a `node` (gridlabd `PT_INHERIT "node"`) whose load properties
are added to the node's accumulators before each solution, as gridlabd's
`load::load_update_fxn()` does for NR:

- `constant_power_X` to `power_X`, `constant_current_X` to `current_X`,
  and `1/constant_impedance_X` to `shunt_X` (X = A, B, C: wye, or phase to
  phase AB, BC, CA when the load has phase `D`); the explicit wye
  (`AN`, `BN`, `CN`) and delta (`AB`, `BC`, `CA`) loads likewise, whatever
  the phases;
- with `base_power_X` not 0 (the ZIP form), `constant_power_X`,
  `constant_current_X`, and `constant_impedance_X` are replaced by the
  power, current, and impedance fractions of the base power at their
  power factors (a negative power factor is leading), the current at the
  phase's nominal angle and the impedance at `nominal_voltage`; when the
  fractions do not sum to 1, `power_fraction_X` takes the difference, with
  a warning when it exceeds 0.001; when `base_power_X` returns to 0, the
  three loads are cleared;
- with `powerflow::enable_frequency_dependence`, an impedance's reactance
  scales with `current_frequency` (inductive) or its inverse (capacitive).

Each complex load property and its `_real` and `_reac` parts are one
value, as in gridlabd's shared storage: a change to any of them (at
initialization, in the order they were set) is written to the others.
After each solution `measured_voltage_X` (and the line-to-line
`measured_voltage_AB` ...) are the node's voltages.

When it initializes, a load is expected to fail when it has phase `S`
("Load objects do not support triplex connections at this time!"), then
initialize as a `node`.

Caveats
-------

- `phase_loss_protection`, the low-voltage conversion to impedance (in-rush
  and reliability modes), GFA, deltamode, and master/slave runs are not
  ported.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. On a delta-connected load (phase `D`), the ZIP form refers
   `constant_current_X` to the nominal line-to-line angle of `AB`, `BC`,
   or `CA` (30, -90, 150 deg), the voltage the current flows under;
   gridlabd's `load_update_fxn()` uses the line-to-neutral angles (0,
   -120, 120 deg), so a delta current is 30 deg behind its power factor.
2. On a delta-connected load, the ZIP form computes the current and
   impedance parts at the nominal line-to-line voltage, `sqrt(3)` times
   `nominal_voltage`, so each part draws its share of `base_power_X` at
   nominal voltage; gridlabd uses `nominal_voltage`, so the current part
   draws `sqrt(3)` times its share and the impedance part 3 times.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/load.cpp`, `load.h`
"""

import cmath
import math
from typing import Any

from ._base import prop, keywords
from ._common import (PHASE_D, PHASE_S, g, msg, object_state, get_int, get_double, get_complex,
    set_complex, set_double, text_to_complex, text_to_double, PowerflowError)
from .node import Node

KINDS = (("power", "VA", "W", "VAr", "VA"), ("current", "A", "A", "A", "Amps"), ("impedance", "Ohm", "Ohm", "Ohm", "Ohms"))
"""Load kinds: name, units of the value and its parts, and the word in
the descriptions"""

GROUPS = ((("A", "A"), ("B", "B"), ("C", "C")), (("AN", "A"), ("BN", "B"), ("CN", "C")), (("AB", "A"), ("BC", "B"), ("CA", "C")))
"""Suffixes of the phase, wye, and delta loads, with the phase named in the
descriptions"""

CONNECTION = ("", "wye-connected ", "delta-connected ")

ACCUMULATOR = {"power": "power", "current": "current", "impedance": "shunt"}
"""Node accumulator of each kind"""

BASE_ANGLES = (0.0, -2*math.pi/3, 2*math.pi/3)
"""Nominal line-to-neutral angles of phases A, B, and C"""

def is_delta(model:Any, name:str) -> bool:
    """Whether a load object is delta-connected (has phase `D`)"""
    return get_int(model, name, "phases") & PHASE_D == PHASE_D

def nominal_angle(model:Any, name:str, k:int) -> float:
    """Nominal angle of the voltage across the load on phase `k` of a load
    object: line-to-neutral, or line-to-line (`AB`, `BC`, `CA`, 30 deg
    ahead) when the load is delta-connected"""
    return BASE_ANGLES[k] + (math.pi/6 if is_delta(model, name) else 0.0)

def nominal_magnitude(model:Any, name:str) -> float:
    """Nominal magnitude of the voltage across each load of a load object:
    `nominal_voltage` (line-to-neutral), or `sqrt(3)` times it
    (line-to-line) when the load is delta-connected"""
    vnom = get_double(model, name, "nominal_voltage")
    return vnom*math.sqrt(3) if is_delta(model, name) else vnom

def _load_properties() -> tuple:
    result = []
    for connection, group in zip(CONNECTION, GROUPS):
        for kind, unit, real, reac, word in KINDS:
            for suffix, phase in group:
                result.append((f"constant_{kind}_{suffix}[{unit}]", "complex", prop(f"constant {kind} {connection}load on phase {phase}, specified as {word}", f"0 {unit}")))
            for suffix, phase in group:
                result.append((f"constant_{kind}_{suffix}_real[{real}]", "double", prop(f"constant {kind} {connection}load on phase {phase}, real only, specified as {real if kind == 'power' else word}", f"0 {real}")))
            for suffix, phase in group:
                result.append((f"constant_{kind}_{suffix}_reac[{reac}]", "double", prop(f"constant {kind} {connection}load on phase {phase}, imaginary only, specified as {reac if kind == 'power' else word}", f"0 {reac}")))
    return tuple(result)

def _zip_properties() -> tuple:
    result = [(f"base_power_{x}[VA]", "double", prop(f"in similar format as ZIPload, this represents the nominal power on phase {x} before applying ZIP fractions")) for x in "ABC"]
    for x in "ABC":
        for kind in ("power", "current", "impedance"):
            result.append((f"{kind}_pf_{x}[pu]", "double", prop(f"in similar format as ZIPload, this is the power factor of the phase {x} constant {kind} portion of load")))
    for x in "ABC":
        for kind in ("power", "current", "impedance"):
            result.append((f"{kind}_fraction_{x}[pu]", "double", prop(f"this is the constant {kind} fraction of base power on phase {x}")))
    return tuple(result)

def sync_parts(model:Any, name:str, whole:str, unit:str, real_unit:str, imag_unit:str, initial:bool) -> complex:
    """Reconcile a complex property with its `_real` and `_reac` parts: at
    initialization in the order the object set them, afterwards the one
    that changed; writes all three and returns the value"""
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    state = object_state(model, name).setdefault("parts", {})
    real, imag = f"{whole}_real", f"{whole}_reac"
    if initial:
        value = 0j
        for key, text in model.objects[name].items():
            if key == whole:
                value = text_to_complex(text, unit)
            elif key == real:
                value = complex(text_to_double(text, real_unit), value.imag)
            elif key == imag:
                value = complex(value.real, text_to_double(text, imag_unit))
    else:
        value = get_complex(model, name, whole)
        last = state.get(whole)
        if last is not None and value == last:
            value = complex(get_double(model, name, real), get_double(model, name, imag))
    if state.get(whole) != value or initial:
        set_complex(model, name, whole, value)
        set_double(model, name, real, value.real)
        set_double(model, name, imag, value.imag)
    state[whole] = value
    return value

class Load(Node):
    """Behavior of class `load`"""

    NAME = "load"
    PARENT = "node"
    PROPERTIES = (
        ("load_class", "enumeration", prop("Flag to track load type--used by some subclasses of load", "U", keywords=keywords(
            ("U", 0), ("R", 1), ("C", 2), ("I", 3), ("A", 4), ("T", 5), ("P", 6)))),
        *_load_properties(),
        *((f"measured_voltage_{x}[V]", "complex", prop(f"current measured voltage on phase{'s' if len(x) > 1 else ''} {x}", flags="OUTPUT")) for x in ("A", "B", "C", "AB", "BC", "CA")),
        ("phase_loss_protection", "bool", prop("Trip all three phases of the load if a fault occurs", "FALSE")),
        *_zip_properties(),
    )

    @classmethod
    def init_node(cls, model:Any, name:str) -> None:
        """`load::init()`; raises `PowerflowError`"""
        if get_int(model, name, "phases") & PHASE_S == PHASE_S:
            raise PowerflowError("Load objects do not support triplex connections at this time!")
        super().init_node(model, name)
        cls.values(model, name, initial=True)

    @classmethod
    def values(cls, model:Any, name:str, initial:bool=False) -> dict[str,complex]:
        """The load values by property name (`constant_power_A` ...), after
        the parts and the ZIP form are applied"""
        values = {}
        for group in GROUPS:
            for kind, unit, real, reac, _ in KINDS:
                for suffix, _ in group:
                    whole = f"constant_{kind}_{suffix}"
                    values[whole] = sync_parts(model, name, whole, unit, real, reac, initial)
        for k in range(3):
            for whole, value in cls.zip_values(model, name, k).items():
                set_complex(model, name, whole, value)
                set_double(model, name, f"{whole}_real", value.real)
                set_double(model, name, f"{whole}_reac", value.imag)
                object_state(model, name)["parts"][whole] = value
                values[whole] = value
        return values

    @classmethod
    def zip_values(cls, model:Any, name:str, k:int) -> dict[str,complex]:
        """ZIP form of phase `k` (gridlabd `load_update_fxn()`): the three
        loads to write, or none"""
        x = "ABC"[k]
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
                msg(model, name).warning(f"load:{name} - ZIP components on phase {x} did not sum to 1 (diff is {diff:g}). Setting power_fraction to {fractions['power']:.2f}")
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
        vnom = nominal_magnitude(model, name)
        result = {}
        result[f"constant_power_{x}"] = apparent("power") if fractions["power"] != 0 else 0j
        if fractions["current"] != 0:
            current = apparent("current").conjugate()/vnom
            result[f"constant_current_{x}"] = cmath.rect(abs(current), cmath.phase(current) + nominal_angle(model, name, k))
        else:
            result[f"constant_current_{x}"] = 0j
        result[f"constant_impedance_{x}"] = (vnom*vnom/apparent("impedance")).conjugate() if fractions["impedance"] != 0 else 0j
        return result

    @classmethod
    def frequency_impedance(cls, model:Any, z:complex) -> complex:
        """An impedance at the current frequency, with
        `enable_frequency_dependence`"""
        if z == 0 or not g(model, "enable_frequency_dependence"):
            return z
        nominal = float(g(model, "nominal_frequency") or 60.0)
        current = float(g(model, "current_frequency") or nominal)
        return complex(z.real, z.imag/current*nominal if z.imag < 0 else z.imag/nominal*current)

    @classmethod
    def load_terms(cls, model:Any, name:str) -> dict[tuple[str,str],complex]:
        """The load values in the node's accumulators"""
        state = object_state(model, name)
        values = state.get("values")
        if values is None:
            values = cls.values(model, name)
        terms = {}
        for group in GROUPS:
            for kind, *_ in KINDS:
                for suffix, _ in group:
                    value = values[f"constant_{kind}_{suffix}"]
                    if kind == "impedance":
                        value = cls.frequency_impedance(model, value)
                        value = 1/value if value != 0 else 0j
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
        volts = [get_complex(model, name, f"voltage_{x}") for x in "ABC"]
        for x, v in zip("ABC", volts):
            set_complex(model, name, f"measured_voltage_{x}", v)
        for k, x in enumerate(("AB", "BC", "CA")):
            set_complex(model, name, f"measured_voltage_{x}", volts[k] - volts[(k + 1) % 3])
        return False

__all__ = ["Load", "sync_parts"]
