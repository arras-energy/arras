# pylint: disable=line-too-long
"""Class `branch`: a PYPOWER branch (line or transformer)

Syntax
------

    object pypower.branch {
        from <bus>;
        to <bus>;
        fbus <integer>;
        tbus <integer>;
        r <real> pu.Ohm;
        x <real> pu.Ohm;
        b <real> pu.S;
        rateA <real> MVA;
        rateB <real> MVA;
        rateC <real> MVA;
        ratio <real> pu;
        angle <real> deg;
        status {IN,OUT};
        angmin <real> deg;
        angmax <real> deg;
    }

The outputs `current` (A), `loss` (MW), and the OPF multipliers
`mu_sfrom`, `mu_sto`, `mu_angmin`, `mu_angmax` are also published, and the
module global `pypower::autosize_angle` (rad).

Description
-----------

A branch is a row of PYPOWER's branch table. Given a model, a branch is
expected to:

1. refuse a `from` or `to` object that is missing or is not a pypower bus;
2. take `fbus` and `tbus` from the buses' `bus_i` when they are 0
   (deferring its initialization until the buses have numbers);
3. refuse a negative `pypower::autosize_angle`, `rateA`, or `ratio`, and
   warn when `autosize_angle` is above pi/2-0.1;
4. when `autosize_angle` is positive: refuse a `rateA` of 0, raise `rateB`
   to `rateA` and `rateC` to `rateB` (with a warning when they were set
   lower), and set the `r`, `x`, and `b` that are 0 from the buses' base
   voltages, `rateC`, and the distance between the buses' `latitude` and
   `longitude`: a device (same voltage, less than 0.01 mile) gets 1 mOhm
   and `x = 10 r`, a transformer (different voltages) gets
   `r = (0.0348 ln(fromKV) - 0.04209)/Zbase` and
   `x = r max(26.8608 ln(rateC/1e6) - 11.7491, 5)`, and a line gets
   `r = rateC/(rateC/cos(angle))/Zbase`,
   `x = (0.699 - 0.0008 fromKV) length/Zbase`, and
   `b = (0.1122 - 0.0002 fromKV) 1e-6 length Zbase`, with
   `Zbase = fromKV^2/baseMVA`;
5. set `angmin` and `angmax` of 0 to -360 and +360 degrees;
6. receive `current` (`(Vfrom-Vto)/(r+jx)` times `baseMVA`) and `loss`
   from each solution.

Caveats
-------

- The autosizing formulas are gridlabd's, including the transformer `x`
  that takes the logarithm of `rateC/1e6` (`rateC` is in MVA).

References
----------

- `arras-energy/gridlabd`: `module/pypower/branch.cpp`, `branch.h`
"""

import math
from typing import Any

from ._base import PypowerClass, prop, keywords, msg
from ._common import (MODULE, object_state, global_value, isa, ref, get_double, get_int,
    set_double, set_int)
from ._module import ensure_init

BS_OUT, BS_IN = 0, 1
"""Branch status values"""

def distance(model:Any, a:str, b:str) -> float:
    """Distance in miles between two objects' `latitude` and `longitude`
    (gridlabd `gld_object::get_distance()`), `nan` when one is missing"""
    def coord(name:str, prop_:str) -> float:
        value = model.objects[name].get(prop_)
        try:
            return float(value) if value not in (None, "") else math.nan
        except ValueError:
            return math.nan
    flat, flon = coord(a, "latitude")*math.pi/180, coord(a, "longitude")*math.pi/180
    tlat, tlon = coord(b, "latitude")*math.pi/180, coord(b, "longitude")*math.pi/180
    if any(math.isnan(x) for x in (flat, flon, tlat, tlon)):
        return math.nan
    value = (1-math.cos(flat-tlat)+math.cos(flat)*math.cos(tlat)*(1-math.cos(flon-tlon)))/2
    return 2*3958.8*math.asin(math.sqrt(value))

class Branch(PypowerClass):
    """Behavior of class `branch`"""

    NAME = "branch"
    PROPERTIES = (
        ("from", "object", prop("from bus name", flags="REQUIRED")),
        ("to", "object", prop("to bus name", flags="REQUIRED")),
        ("fbus", "int32", prop("from bus number", flags="OUTPUT")),
        ("tbus", "int32", prop("to bus number", flags="OUTPUT")),
        ("r[pu.Ohm]", "double", prop("resistance (per unit)")),
        ("x[pu.Ohm]", "double", prop("reactance (per unit)")),
        ("b[pu.S]", "double", prop("total line charging susceptance (per unit)")),
        ("rateA[MVA]", "double", prop("MVA rating A (long term rating)", flags="REQUIRED")),
        ("rateB[MVA]", "double", prop("MVA rating B (short term rating)", "0 MVA")),
        ("rateC[MVA]", "double", prop("MVA rating C (emergency term rating)", "0 MVA")),
        ("ratio[pu]", "double", prop("transformer off nominal turns ratio", "0 pu")),
        ("angle[deg]", "double", prop("transformer phase shift angle (degrees)", "0 deg")),
        ("status", "enumeration", prop("initial branch status, IN=1 - in service, OUT=0 - out of service", "IN",
            keywords=keywords(("OUT", BS_OUT), ("IN", BS_IN)))),
        ("angmin[deg]", "double", prop("minimum angle difference, angle(Vf) - angle(Vt) (degrees)", "-360 deg")),
        ("angmax[deg]", "double", prop("maximum angle difference, angle(Vf) - angle(Vt) (degrees)", "360 deg")),
        ("current[A]", "complex", prop("line current (A)", flags="OUTPUT")),
        ("loss[MW]", "double", prop("line loss (MW)", flags="OUTPUT")),
        ("mu_sfrom", "double", prop("Kuhn-Tucker multiplier on MVA limit at 'from' bus")),
        ("mu_sto", "double", prop("Kuhn-Tucker multiplier on MVA limit at 'to' bus ")),
        ("mu_angmin", "double", prop("Kuhn-Tucker multiplier lower angle difference limit")),
        ("mu_angmax", "double", prop("Kuhn-Tucker multiplier upper angle difference limit")),
    )
    EVENTS = ("init",)

    @classmethod
    def state(cls, model:Any, name:str) -> dict[str,Any]:
        """State of a branch: `child_count` (powerlines and transformers
        attached)"""
        return object_state(model, name, lambda: {"child_count": 0})

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool|int: # pylint: disable=unused-argument
        """`branch::init()`"""
        # pylint: disable=too-many-return-statements,too-many-branches,too-many-locals,too-many-statements
        if not ensure_init(model):
            return False
        out = msg(model, name)
        cls.state(model, name)
        buses = {}
        for end, label in (("from", "from"), ("to", "to")):
            other = ref(model, name, end)
            if other is None:
                out.error(f"{label} bus not specified")
                return False
            if not isa(model, other, "bus"):
                out.error(f"{label} object '{other}' is not a pypower bus")
                return False
            buses[end] = other
        fobj, tobj = buses["from"], buses["to"]
        for field, other in (("fbus", fobj), ("tbus", tobj)):
            if get_int(model, name, field) == 0:
                number = get_int(model, other, "bus_i")
                if number == 0:
                    return 2
                set_int(model, name, field, number)
        autosize_angle = float(global_value(model, f"{MODULE}::autosize_angle") or 0.0)
        if autosize_angle < 0:
            out.error("autosize_angle must be non-negative")
            return False
        if autosize_angle > math.pi/2-0.1:
            out.warning("autosize_angle should not be 90 deg or greater")
        rate_a = get_double(model, name, "rateA")
        if rate_a < 0:
            out.error("rateA must be non-negative")
            return False
        if get_double(model, name, "ratio") < 0:
            out.error("turns ratio must be non-negative")
            return False
        if autosize_angle > 0:
            if rate_a == 0:
                out.error(f"rateA {rate_a:.1f} MW is not specified but is needed for autosizing")
                return False
            rate_b, rate_c = get_double(model, name, "rateB"), get_double(model, name, "rateC")
            if 0 < rate_b < rate_a:
                out.warning("rateB is less than rateA, setting rateB equal to rateA")
            rate_b = max(rate_a, rate_b)
            set_double(model, name, "rateB", rate_b)
            if 0 < rate_c < rate_b:
                out.warning("rateC is less than rateB, setting rateC equal to rateB")
            rate_c = max(rate_b, rate_c)
            set_double(model, name, "rateC", rate_c)
            from_kv, to_kv = get_double(model, fobj, "baseKV"), get_double(model, tobj, "baseKV")
            is_transformer = from_kv != to_kv
            length = distance(model, fobj, tobj)
            r, x, b = get_double(model, name, "r"), get_double(model, name, "x"), get_double(model, name, "b")
            if not is_transformer and (r == 0 or x == 0):
                if math.isnan(length):
                    out.warning("unable to compute default line r/x/b without lat/lon for from/to bus")
                else:
                    def coord(obj:str, p:str) -> float:
                        return float(model.objects[obj].get(p) or "nan")
                    out.verbose(f"distance from {coord(fobj,'latitude'):.6f},{coord(fobj,'longitude'):.6f} to {coord(tobj,'latitude'):.6f},{coord(tobj,'longitude'):.6f} is {length:.1f} miles\n")
            elif is_transformer and length > 0.01:
                out.warning(f"transformer from and to busses are {length:.2f} miles apart")
            is_device = not is_transformer and length < 0.01
            base_mva = float(global_value(model, f"{MODULE}::baseMVA"))
            from_puz = from_kv*from_kv/base_mva
            if r == 0 and from_puz > 0:
                if is_device:
                    r = 0.001/from_puz
                    out.verbose(f"device r is zero, autosize to default {r*1e3:.3g} pu.mOhm")
                elif is_transformer:
                    r = (0.0348*math.log(from_kv)-0.04209)/from_puz
                    out.verbose(f"transformer r is zero, autosize to default {r:.4g} pu.Ohm for {from_kv:.1f} kV")
                elif length > 0:
                    imax = rate_c/math.cos(autosize_angle)
                    r = rate_c/imax/from_puz
                    out.verbose(f"line r is zero, autosize for {imax:.1f} A to {r:.4g} pu.Ohms for {from_kv:.3g} kV {length:.1f} mile line")
            if x == 0 and from_puz > 0:
                if is_device:
                    x = 10*r
                    out.verbose(f"device x is zero, autosize to default {x*1e3:.3g} pu.mOhm")
                elif is_transformer:
                    x = r*max(26.8608*_log(rate_c/1e6)-11.7491, 5.0)
                    out.verbose(f"transformer x is zero, autosize to default {x:.4g} pu.Ohm for {rate_c:.1f} MVA")
                elif length > 0:
                    x = (-0.0008*from_kv+0.699)*length/from_puz
                    out.verbose(f"line x is zero, autosize to {x:.4g} pu.Ohms for {from_kv:.3g} kV {length:.1f} mile line")
            if b == 0 and from_puz > 0:
                if is_device:
                    out.verbose("device b is zero, no autosize available")
                elif is_transformer:
                    out.verbose("transformer b is zero, no autosize available")
                elif length > 0:
                    b = (-0.0002*from_kv+0.1122)*1e-6*length*from_puz
                    out.verbose(f"b is zero, autosize to {b:.4g} pu.S for {from_kv:.3g} kV {length:.1f} mile line")
            set_double(model, name, "r", r)
            set_double(model, name, "x", x)
            set_double(model, name, "b", b)
        if get_double(model, name, "angmin") == 0:
            set_double(model, name, "angmin", -360.0)
        if get_double(model, name, "angmax") == 0:
            set_double(model, name, "angmax", 360.0)
        return True

def _log(value:float) -> float:
    """C `log()`: `-inf` for 0 and `nan` for negative values"""
    if value == 0:
        return -math.inf
    if value < 0:
        return math.nan
    return math.log(value)
