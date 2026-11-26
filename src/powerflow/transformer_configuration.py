# pylint: disable=line-too-long
"""Class `transformer_configuration`: the ratings and impedances of a
transformer

Syntax
------

    object transformer_configuration {
        connect_type {WYE_WYE,DELTA_DELTA,DELTA_GWYE,SINGLE_PHASE,SINGLE_PHASE_CENTER_TAPPED};
        install_type {POLETOP,PADMOUNT,VAULT};
        primary_voltage <real> V;
        secondary_voltage <real> V;
        power_rating <real> kVA;        // or powerA_rating, powerB_rating, powerC_rating
        impedance <complex> pu.Ohm;     // or resistance and reactance
        impedance1 <complex> pu.Ohm;    // also impedance2, or resistance1/2 and reactance1/2
        shunt_impedance <complex> pu.Ohm;   // or shunt_resistance and shunt_reactance
        no_load_loss <real> pu;
        full_load_loss <real> pu;
        reactance_resistance_ratio <real>;
        // and the thermal aging and in-rush properties
    }

Description
-----------

A library object that `transformer`, not ported yet, refers to. gridlabd
publishes `resistance` and `reactance` at the real and imaginary parts of
`impedance` (and likewise for `impedance1`, `impedance2`, and
`shunt_impedance`), so the last of them that a model sets wins; at
initialization the three are reconciled in the order the object set them
and written back consistently. When it initializes, it is expected to:

1. set `power_rating` to the sum of the phase ratings when it is 0, and
   split it evenly among the phases when they are all 0;
2. fail when `connect_type` is `UNKNOWN`, `primary_voltage` or
   `secondary_voltage` is 0, `power_rating` is not positive, or the phase
   ratings differ from `power_rating` by more than 1%;
3. write a verbose message when `install_type` is `UNKNOWN`;
4. for connections other than `SINGLE_PHASE_CENTER_TAPPED`: warn that
   `impedance1`/`impedance2` are not supported when one has both parts
   non-zero, that `shunt_impedance` is not supported when it is not the
   default for connections other than `WYE_WYE`, and when `no_load_loss`
   or `full_load_loss` is set;
5. for `SINGLE_PHASE_CENTER_TAPPED`: compute `impedance` and
   `shunt_impedance` from `full_load_loss`, `no_load_loss`, and
   `reactance_resistance_ratio` when both losses are positive (warning
   when the ratio is the default 4.5 and the rating is above 500 kVA), and
   copy `impedance1` to `impedance2` (or back) when only one is set, with a
   warning;
6. fail when the resistance of `impedance` is not positive or that of
   `impedance1`/`impedance2` is negative, likewise for the reactances, or
   when a part of `shunt_impedance` is negative.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The `shunt_impedance` warning for connections other than `WYE_WYE`
   compares with the default (1e9+1e9j); gridlabd compares with
   999999999, so it warns for every such configuration.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/transformer_configuration.cpp`,
  `transformer_configuration.h`
"""

from typing import Any

from ._base import prop, keywords
from ._common import (get_double, get_int, set_double, set_complex, text_to_complex,
    text_to_double, msg, PowerflowError)
from .powerflow_library import LibraryObject

UNKNOWN, WYE_WYE, DELTA_DELTA, DELTA_GWYE, SINGLE_PHASE, SINGLE_PHASE_CENTER_TAPPED = range(6)
"""`connect_type` values"""

SHUNT_DEFAULT = complex(1e9, 1e9)
"""Default `shunt_impedance` (pu)"""

ALIASES = (("impedance", "resistance", "reactance", 0j), ("impedance1", "resistance1", "reactance1", 0j),
    ("impedance2", "resistance2", "reactance2", 0j), ("shunt_impedance", "shunt_resistance", "shunt_reactance", SHUNT_DEFAULT))
"""Complex properties and the two properties gridlabd publishes at their
real and imaginary parts, with the default"""

class TransformerConfiguration(LibraryObject):
    """Behavior of class `transformer_configuration`"""

    NAME = "transformer_configuration"
    PROPERTIES = (
        ("connect_type", "enumeration", prop("transformation connection type", "UNKNOWN", keywords=keywords(("UNKNOWN", UNKNOWN),
            ("WYE_WYE", WYE_WYE), ("DELTA_DELTA", DELTA_DELTA), ("DELTA_GWYE", DELTA_GWYE), ("SINGLE_PHASE", SINGLE_PHASE),
            ("SINGLE_PHASE_CENTER_TAPPED", SINGLE_PHASE_CENTER_TAPPED)))),
        ("install_type", "enumeration", prop("transformation installation type", "UNKNOWN", keywords=keywords(("UNKNOWN", 0),
            ("POLETOP", 1), ("PADMOUNT", 2), ("VAULT", 3)))),
        ("coolant_type", "enumeration", prop("transformation coolant type", "UNKNOWN", keywords=keywords(("UNKNOWN", 0),
            ("MINERAL_OIL", 1), ("DRY", 2)))),
        ("cooling_type", "enumeration", prop("transformation cooling type", "UNKNOWN", keywords=keywords(("UNKNOWN", 0),
            ("OA", 1), ("FA", 2), ("NDFOA", 3), ("NDFOW", 4), ("DFOA", 5), ("DFOW", 6)))),
        ("primary_voltage[V]", "double", prop("primary voltage level in L-L value kV", flags="REQUIRED")),
        ("secondary_voltage[V]", "double", prop("secondary voltage level kV", flags="REQUIRED")),
        ("power_rating[kVA]", "double", prop("kVA rating of transformer, total", flags="REQUIRED")),
        ("powerA_rating[kVA]", "double", prop("kVA rating of transformer, phase A")),
        ("powerB_rating[kVA]", "double", prop("kVA rating of transformer, phase B")),
        ("powerC_rating[kVA]", "double", prop("kVA rating of transformer, phase C")),
        ("powerN_rating[kVA]", "double", prop("kVA rating of transformer, neutral")),
        ("resistance[pu.Ohm]", "double", prop("Series impedance, pu, real")),
        ("reactance[pu.Ohm]", "double", prop("Series impedance, pu, imag")),
        ("impedance[pu.Ohm]", "complex", prop("Series impedance, pu")),
        ("resistance1[pu.Ohm]", "double", prop("Secondary series impedance (only used when you want to define each individual winding seperately, pu, real")),
        ("reactance1[pu.Ohm]", "double", prop("Secondary series impedance (only used when you want to define each individual winding seperately, pu, imag")),
        ("impedance1[pu.Ohm]", "complex", prop("Secondary series impedance (only used when you want to define each individual winding seperately, pu")),
        ("resistance2[pu.Ohm]", "double", prop("Secondary series impedance (only used when you want to define each individual winding seperately, pu, real")),
        ("reactance2[pu.Ohm]", "double", prop("Secondary series impedance (only used when you want to define each individual winding seperately, pu, imag")),
        ("impedance2[pu.Ohm]", "complex", prop("Secondary series impedance (only used when you want to define each individual winding seperately, pu")),
        ("shunt_resistance[pu.Ohm]", "double", prop("Shunt impedance on primary side, pu, real", "+1e+09 pu.Ohm")),
        ("shunt_reactance[pu.Ohm]", "double", prop("Shunt impedance on primary side, pu, imag", "+1e+09 pu.Ohm")),
        ("shunt_impedance[pu.Ohm]", "complex", prop("Shunt impedance on primary side, pu", "+1e+09+1e+09j pu.Ohm")),
        ("core_coil_weight[lb]", "double", prop("The weight of the core and coil assembly in pounds")),
        ("tank_fittings_weight[lb]", "double", prop("The weight of the tank and fittings in pounds")),
        ("oil_volume[gal]", "double", prop("The number of gallons of oil in the transformer")),
        ("rated_winding_time_constant[h]", "double", prop("The rated winding time constant in hours")),
        ("rated_winding_hot_spot_rise[degC]", "double", prop("winding hottest-spot rise over ambient temperature at rated load, degrees C")),
        ("rated_top_oil_rise[degC]", "double", prop("top-oil hottest-spot rise over ambient temperature at rated load, degrees C")),
        ("no_load_loss[pu]", "double", prop("Another method of specifying transformer impedances, defined as per unit power values (shunt)")),
        ("full_load_loss[pu]", "double", prop("Another method of specifying transformer impedances, defined as per unit power values (shunt and series)")),
        ("reactance_resistance_ratio", "double", prop("the reactance to resistance ratio (X/R)", "4.5")),
        ("installed_insulation_life[h]", "double", prop("the normal lifetime of the transformer insulation at rated load, hours")),
        ("magnetization_location", "enumeration", prop("winding to place magnetization influence for in-rush calculations", "NONE",
            keywords=keywords(("NONE", 0), ("PRIMARY", 1), ("SECONDARY", 2), ("BOTH", 3)))),
        ("inrush_saturation_enabled", "bool", prop("flag to include saturation effects during inrush calculations", "FALSE")),
        ("L_A[pu]", "double", prop("Air core inductance of transformer", "+0.2 pu")),
        ("phi_K[pu]", "double", prop("Knee flux value where the air core inductance interstes the flux axis of the saturation curve", "+1.17 pu")),
        ("phi_M[pu]", "double", prop("Peak magnetization flux at rated voltage of the saturation curve", "+1 pu")),
        ("I_M[pu]", "double", prop("Peak magnetization current at rated voltage of the saturation curve", "+0.01 pu")),
        ("T_D", "double", prop("Inrush decay time constant for inrush current", "+0.5")),
    )

    @classmethod
    def reconcile(cls, model:Any, name:str) -> dict[str,complex]:
        """The four complex impedances, from their complex and part
        properties in the order the object set them (the last wins, as with
        gridlabd's shared storage), written back to all three properties"""
        obj = model.objects[name]
        result = {}
        for whole, real, imag, default in ALIASES:
            value = default
            for key in list(obj):
                if key == whole:
                    value = text_to_complex(obj[key], "pu.Ohm")
                elif key == real:
                    value = complex(text_to_double(obj[key], "pu.Ohm"), value.imag)
                elif key == imag:
                    value = complex(value.real, text_to_double(obj[key], "pu.Ohm"))
            result[whole] = value
        return result

    @classmethod
    def write(cls, model:Any, name:str, values:dict[str,complex]) -> None:
        """Write the impedances to their complex and part properties"""
        for whole, real, imag, _ in ALIASES:
            value = values[whole]
            set_complex(model, name, whole, value)
            set_double(model, name, real, value.real)
            set_double(model, name, imag, value.imag)

    @classmethod
    def check(cls, model:Any, name:str) -> None:
        # pylint: disable=too-many-branches,too-many-locals,too-many-statements
        out = msg(model, name)
        obj = model.objects[name]
        values = cls.reconcile(model, name)
        rating = get_double(model, name, "power_rating")
        phases = [get_double(model, name, f"power{x}_rating") for x in "ABC"]
        if rating == 0:
            rating = sum(phases)
            set_double(model, name, "power_rating", rating)
        if sum(phases) == 0 and rating > 0:
            phases = [rating/3]*3
            for x in "ABC":
                set_double(model, name, f"power{x}_rating", rating/3)
        connect = get_int(model, name, "connect_type")
        if connect == UNKNOWN:
            raise PowerflowError("connection type not specified")
        if get_int(model, name, "install_type") == 0:
            out.verbose("installation type not specified")
        if get_double(model, name, "primary_voltage") == 0:
            raise PowerflowError("V_primary must be positive")
        if get_double(model, name, "secondary_voltage") == 0:
            raise PowerflowError("V_secondary must be positive")
        if rating <= 0:
            raise PowerflowError("kVA_rating(s) must be positive")
        if abs((rating - sum(phases))/rating) > 0.01:
            raise PowerflowError("kVA rating mismatch across phases exceeds 1%")
        z, z1, z2, zs = (values[x] for x in ("impedance", "impedance1", "impedance2", "shunt_impedance"))
        no_load, full_load = get_double(model, name, "no_load_loss"), get_double(model, name, "full_load_loss")
        if connect != SINGLE_PHASE_CENTER_TAPPED:
            if (z1.real != 0 and z1.imag != 0) or (z2.real != 0 and z2.imag != 0):
                out.warning(f"This connection type on transformer:{obj.id} ({name}) does not support impedance (impedance1 or impedance2) of secondaries at this time.")
            if connect != WYE_WYE and zs != SHUNT_DEFAULT:
                out.warning(f"This connection type on transformer:{obj.id} ({name}) does not support shunt_impedance at this time.")
            if no_load != 0 or full_load != 0:
                out.warning(f"This connection type on transformer:{obj.id} ({name}) does not support shunt_impedance at this time.")
        else:
            if no_load > 0 and full_load > 0:
                ratio = get_double(model, name, "reactance_resistance_ratio")
                if ratio == 4.5 and rating > 500:
                    out.warning(f"transormer_configuration:{obj.id} ({name}) reactance_resistance_ratio was not set and defaulted to 4.5. This may cause issues with larger transformers (>0.5 MVA)")
                z = complex(full_load, ratio*full_load)
                zs = complex(1/no_load, ratio/no_load)
            if z1 == 0 and (z2.real != 0 and z2.imag != 0):
                z1 = z2
                out.warning("impedance2 was defined, but impedance1 was not -- assuming they are equal")
            elif (z1.real != 0 and z1.imag != 0) and z2 == 0:
                z2 = z1
                out.warning("impedance1 was defined, but impedance2 was not -- assuming they are equal")
        cls.write(model, name, {"impedance": z, "impedance1": z1, "impedance2": z2, "shunt_impedance": zs})
        if z.real <= 0 or z1.real < 0 or z2.real < 0:
            raise PowerflowError("resistance must be non-negative")
        if z.imag <= 0 or z1.imag < 0 or z2.imag < 0:
            raise PowerflowError("reactance must be non-negative")
        if zs.real < 0:
            raise PowerflowError("shunt_resistance must be non-negative")
        if zs.imag < 0:
            raise PowerflowError("shunt_reactance must be non-negative")

__all__ = ["TransformerConfiguration"]
