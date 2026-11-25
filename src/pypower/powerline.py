# pylint: disable=line-too-long
"""Class `powerline`: a line that sets a branch's impedance

Syntax
------

    object pypower.powerline {
        parent <branch|powerline>;
        length <real> mile;
        impedance <complex> Ohm/mile;
        susceptance <real> S/mile;
        status {IN,OUT};
        composition {NONE,SERIES,PARALLEL};
    }

Description
-----------

A powerline gives its parent branch the impedance of a line, or of lines
composed in series or in parallel. Given a model, a powerline is expected
to:

1. on a branch, refuse a branch that already has a powerline or
   transformer; on a powerline, refuse a parent with a nonzero impedance
   or with `composition NONE`; refuse other parents, and warn when there
   is no parent;
2. with a nonzero `impedance`, refuse a `length` that is not positive, and
   compute its impedance `Z = impedance length`, admittance `Y = 1/Z`, and
   susceptance `b = susceptance length`;
3. at each presync, when it has a parent and no impedance of its own (a
   composition), reset its `Z`, `Y`, and `b` to 0;
4. at each sync (children before parents): on a branch, copy `Z` to the
   branch's `r` and `x` and `b` to `b`, and set the branch `IN`, or set
   the branch `OUT` when it is `OUT`; on a powerline parent, when `IN`,
   add its `Z` and `b` to a `SERIES` parent, or its `Y` and `b` to a
   `PARALLEL` parent. The branch keeps its `rateA`.

Caveats
-------

- `Z`, `Y`, and `b` are members that gridlabd does not publish.
- The impedance is copied in ohms to the branch's `r` and `x`, which are
  per unit, as in gridlabd.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The branch keeps its `rateA`. gridlabd copies a rating member that
   nothing sets (so 0) to the branch's `rateA`, and composes it as the
   smaller (series) or the sum (parallel) of the lines' ratings
   (arras-energy/gridlabd#411).

References
----------

- `arras-energy/gridlabd`: `module/pypower/powerline.cpp`, `powerline.h`
"""

from typing import Any

from ._base import PypowerClass, prop, keywords, msg
from ._common import TS_NEVER, object_state, isa, parent_of, get_double, get_complex, get_int, set_double, set_int
from ._module import ensure_init
from .branch import Branch, BS_IN, BS_OUT

PLS_OUT, PLS_IN = 0, 1
PLC_NONE, PLC_SERIES, PLC_PARALLEL = 0, 1, 2

def _inv(value:complex) -> complex:
    """gridlabd `complex::Inv()` (`nan` for 0)"""
    return 1/value if value != 0 else complex(float("nan"), float("nan"))

class Powerline(PypowerClass):
    """Behavior of class `powerline`"""

    NAME = "powerline"
    PASSCONFIG = "PRETOPDOWN|BOTTOMUP|AUTOLOCK|OBSERVER"
    PROPERTIES = (
        ("length[mile]", "double", prop("length (miles)", flags="REQUIRED")),
        ("impedance[Ohm/mile]", "complex", prop("line impedance (Ohm/mile)", flags="REQUIRED")),
        ("susceptance[S/mile]", "double", prop("line susceptance (S/mile)")),
        ("status", "enumeration", prop("line status (IN or OUT)", "IN", keywords=keywords(("IN", PLS_IN), ("OUT", PLS_OUT)))),
        ("composition", "enumeration", prop("parent line composition (SERIES or PARALLEL)",
            keywords=keywords(("NONE", PLC_NONE), ("SERIES", PLC_SERIES), ("PARALLEL", PLC_PARALLEL)))),
    )
    EVENTS = ("init", "presync", "sync")

    @classmethod
    def state(cls, model:Any, name:str) -> dict[str,Any]:
        """State of a powerline: `parent_is_branch`, `Z`, `Y`, `b` (members
        gridlabd does not publish)"""
        return object_state(model, name, lambda: {"parent_is_branch": False, "Z": 0j, "Y": 0j, "b": 0.0})

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`powerline::init()`"""
        # pylint: disable=too-many-return-statements
        if not ensure_init(model):
            return False
        out = msg(model, name)
        state = cls.state(model, name)
        parent = parent_of(model, name)
        if parent is not None:
            if isa(model, parent, "branch"):
                state["parent_is_branch"] = True
                branch = Branch.state(model, parent)
                if branch["child_count"] > 0:
                    out.error(f"parent '{parent}' cannot accept more than one child component")
                    return False
                branch["child_count"] += 1
            elif isa(model, parent, "powerline"):
                if get_complex(model, parent, "impedance") != 0:
                    out.error(f"parent '{parent}' non-zero impedance would be overwritten")
                    return False
                if get_int(model, parent, "composition") == PLC_NONE:
                    out.error(f"parent '{parent}' does not specify powerline composition")
                    return False
            else:
                out.error(f"parent '{parent}' is not a pypower branch or powerline")
                return False
        else:
            out.warning("powerline without parent does nothing")
        impedance = get_complex(model, name, "impedance")
        length = get_double(model, name, "length")
        if impedance != 0:
            if length <= 0:
                out.error("line length must be positive to calculate impedance and admittance")
                return False
            state["Z"] = impedance*length
            state["Y"] = _inv(state["Z"])
        state["b"] = get_double(model, name, "susceptance")*length
        return True

    @classmethod
    def presync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`powerline::presync()`"""
        if parent_of(model, name) is not None and get_complex(model, name, "impedance") == 0:
            state = cls.state(model, name)
            state["Z"] = state["Y"] = 0j
            state["b"] = 0.0
        return TS_NEVER

    @classmethod
    def sync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`powerline::sync()`"""
        parent = parent_of(model, name)
        if parent is None:
            return TS_NEVER
        state = cls.state(model, name)
        status = get_int(model, name, "status")
        if state["parent_is_branch"]:
            if status == PLS_IN:
                set_double(model, parent, "r", state["Z"].real)
                set_double(model, parent, "x", state["Z"].imag)
                set_double(model, parent, "b", state["b"])
                set_int(model, parent, "status", BS_IN)
            else:
                set_int(model, parent, "status", BS_OUT)
        elif status == PLS_IN:
            other = cls.state(model, parent)
            composition = get_int(model, parent, "composition")
            if composition == PLC_SERIES:
                other["Z"] = other["Z"] + state["Z"]
                other["Y"] = _inv(other["Z"])
                other["b"] += state["b"]
            elif composition == PLC_PARALLEL:
                other["Y"] = other["Y"] + state["Y"]
                other["Z"] = _inv(other["Y"])
                other["b"] += state["b"]
            else:
                msg(model, name).exception(f"invalid powerline composition value '{get_int(model, name, 'composition')}' encountered")
        return TS_NEVER
