# pylint: disable=line-too-long
"""Class `transformer`: a transformer that sets a branch's parameters

Syntax
------

    object pypower.transformer {
        parent <branch>;
        impedance <complex> Ohm;
        susceptance <real> S;
        rated_power <real> MVA;
        tap_ratio <real> pu;
        phase_shift <real> deg;
        status {IN,OUT};
    }

Description
-----------

A transformer gives its parent branch the parameters of a transformer.
Given a model, a transformer is expected to:

1. refuse an impedance whose real part is not positive and whose
   imaginary part is 0, and a negative susceptance; warn when the phase
   shift is beyond 360 degrees;
2. refuse a parent that is not a pypower branch or that already has a
   powerline or transformer, and warn when there is no parent;
3. at initialization, set the branch's `ratio` (tap ratio), `angle`
   (phase shift), `r` and `x` (impedance), `b` (susceptance), `rateA`
   (rated power), and `status`;
4. at each precommit, refuse a tap ratio that is not positive (the run
   stops), warn when it is outside 0.8 to 1.2, and set the branch's
   `ratio` and `status`.

Caveats
-------

- The impedance is copied in ohms to the branch's `r` and `x`, which are
  per unit, as in gridlabd.

References
----------

- `arras-energy/gridlabd`: `module/pypower/transformer.cpp`,
  `transformer.h`
"""

from typing import Any

from ._base import PypowerClass, prop, keywords, msg
from ._common import TS_NEVER, TS_INVALID, isa, parent_of, get_double, get_complex, get_int, set_double, set_int
from ._module import ensure_init
from .branch import Branch, BS_IN, BS_OUT

TS_OUT, TS_IN = 0, 1

class Transformer(PypowerClass):
    """Behavior of class `transformer`"""

    NAME = "transformer"
    PROPERTIES = (
        ("impedance[Ohm]", "complex", prop("transformer impedance (Ohm)", flags="REQUIRED")),
        ("susceptance[S]", "double", prop(default="0 S")),
        ("rated_power[MVA]", "double", prop("transformer power rating (MVA)", flags="REQUIRED")),
        ("tap_ratio[pu]", "double", prop("off-nominal turns ratio", "1 pu")),
        ("phase_shift[deg]", "double", prop("transformer phase shift (deg) - use 30 for DY or YD transformers")),
        ("status", "enumeration", prop("transformer status (IN or OUT)", "IN", keywords=keywords(("IN", TS_IN), ("OUT", TS_OUT)))),
    )
    EVENTS = ("init", "precommit")

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`transformer::init()`"""
        # pylint: disable=too-many-return-statements
        if not ensure_init(model):
            return False
        out = msg(model, name)
        impedance = get_complex(model, name, "impedance")
        if impedance.real <= 0 and impedance.imag == 0:
            out.error("transformer impedance must be positive")
            return False
        if get_double(model, name, "susceptance") < 0:
            out.error("transformer susceptance cannot be negative")
            return False
        shift = get_double(model, name, "phase_shift")
        if abs(shift) > 360:
            out.warning(f"phase shift value {shift:.4g} seems unlikely to be valid")
        parent = parent_of(model, name)
        if parent is None:
            out.warning("transformer without parent branch does nothing")
            return True
        if not isa(model, parent, "branch"):
            out.error(f"parent '{parent}' is not a pypower branch")
            return False
        branch = Branch.state(model, parent)
        if branch["child_count"] > 0:
            out.error(f"branch '{parent}' cannot accept more than one child component")
            return False
        branch["child_count"] += 1
        set_double(model, parent, "ratio", get_double(model, name, "tap_ratio"))
        set_double(model, parent, "angle", shift)
        set_double(model, parent, "r", impedance.real)
        set_double(model, parent, "x", impedance.imag)
        set_double(model, parent, "b", get_double(model, name, "susceptance"))
        set_double(model, parent, "rateA", get_double(model, name, "rated_power"))
        set_int(model, parent, "status", BS_IN if get_int(model, name, "status") == TS_IN else BS_OUT)
        return True

    @classmethod
    def precommit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`transformer::precommit()`"""
        parent = parent_of(model, name)
        if parent is not None:
            out = msg(model, name)
            ratio = get_double(model, name, "tap_ratio")
            if ratio <= 0:
                out.error("tap ratio must be positive")
                return TS_INVALID
            if ratio < 0.8 or ratio > 1.2:
                out.warning("tap ratio outside reasonable range of 0.8 to 1.2")
            set_double(model, parent, "ratio", ratio)
            set_int(model, parent, "status", BS_IN if get_int(model, name, "status") == TS_IN else BS_OUT)
        return TS_NEVER
