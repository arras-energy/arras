# pylint: disable=line-too-long
"""Class `gencost`: a PYPOWER generator cost model

Syntax
------

    object pypower.gencost {
        parent <gen>;
        model {UNKNOWN,PIECEWISE,POLYNOMIAL};
        startup <real> $;
        shutdown <real> $;
        costs "<value>[,...]";
    }

Description
-----------

A cost model is a row of PYPOWER's gencost table, used when
`pypower::enable_opf` is true. Given a model, a cost model is expected to:

1. find the first `gen` among its parent and the parent's ancestors, and
   refuse a cost model that has none;
2. attach itself to that generator (a generator keeps its first cost
   model; another one that differs in any property is an error);
3. refuse a `model` of `UNKNOWN` and negative `startup` or `shutdown`
   costs.

The rows are passed to PYPOWER in creation order and matched to the
in-service generators by position, so cost models should be created in
the order of their generators, as PYPOWER cases list them. `costs` holds
the coefficients (polynomial, highest order first) or the `x,y` pairs
(piecewise linear) of PYPOWER's cost columns.

References
----------

- `arras-energy/gridlabd`: `module/pypower/gencost.cpp`, `gencost.h`
"""

from typing import Any

from ._base import PypowerClass, prop, keywords, msg
from ._common import isa, parent_of, get_double, get_int, get_text
from ._module import ensure_init

CM_UNKNOWN, CM_PIECEWISE, CM_POLYNOMIAL = 0, 1, 2

class Gencost(PypowerClass):
    """Behavior of class `gencost`"""

    NAME = "gencost"
    PROPERTIES = (
        ("model", "enumeration", prop("cost model (1=piecewise linear, 2=polynomial)",
            keywords=keywords(("UNKNOWN", CM_UNKNOWN), ("PIECEWISE", CM_PIECEWISE), ("POLYNOMIAL", CM_POLYNOMIAL)))),
        ("startup[$]", "double", prop("startup cost ($)")),
        ("shutdown[$]", "double", prop("shutdown cost($)")),
        ("costs", "char1024", prop("cost model (comma-separate values)")),
    )
    EVENTS = ("init",)

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`gencost::init()`"""
        from .gen import add_cost # pylint: disable=import-outside-toplevel
        if not ensure_init(model):
            return False
        out = msg(model, name)
        parent = parent_of(model, name)
        while parent is not None and not isa(model, parent, "gen"):
            parent = parent_of(model, parent)
        if parent is None:
            out.error("parent does not trace back to a pypower.gen object")
            return False
        add_cost(model, parent, name)
        if get_int(model, name, "model") == CM_UNKNOWN:
            out.error("cost model must be PIECEWISE or POLYNOMIAL")
            return False
        if get_double(model, name, "startup") < 0:
            out.error("startup cost must be non-negative")
            return False
        if get_double(model, name, "shutdown") < 0:
            out.error("shutdown cost must be non-negative")
            return False
        return True

def is_equal(model:Any, name:str, other:str) -> bool:
    """`gencost::is_equal()`"""
    return (get_int(model, other, "model") == get_int(model, name, "model")
        and get_double(model, other, "startup") == get_double(model, name, "startup")
        and get_double(model, other, "shutdown") == get_double(model, name, "shutdown")
        and get_text(model, other, "costs") == get_text(model, name, "costs"))
