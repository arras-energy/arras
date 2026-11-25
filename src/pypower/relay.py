# pylint: disable=line-too-long
"""Class `relay`: a controlled switch on a branch

Syntax
------

    object pypower.relay {
        parent <branch>;
        status {CLOSED,OPEN};
        controller "<function>";
    }

Description
-----------

A relay sets its parent branch `IN` when `CLOSED` and `OUT` when `OPEN`.
Given a model, a relay is expected to:

1. refuse a parent that is not a pypower branch; warn when it has no
   parent or no controller (it then does nothing, or only sets the
   branch's status);
2. refuse a controller when there is no controllers module, or when the
   function is not found or not callable;
3. at each sync, call its controller, if any, as
   `controller(NAME, tbus=, r=, x=, b=, rateA=, rateB=, rateC=, ratio=,
   angle=, status=, angmin=, angmax=, controller=, t=)`, where the branch
   values are those at initialization, `status` is the relay status that
   the branch's status gives (0 `CLOSED` when the branch is `IN`, 1 `OPEN`
   otherwise), and `t` is the clock; each property it returns is set and
   asks to run again at once, and its `t` is the time of the next event;
4. then set the branch's status from its own.

Caveats
-------

- A relay `status` of 0 is `CLOSED`, as in gridlabd.

References
----------

- `arras-energy/gridlabd`: `module/pypower/relay.cpp`, `relay.h`
"""

from typing import Any

from ._base import PypowerClass, prop, keywords, msg
from ._common import TS_NEVER, TS_INVALID, object_state, isa, parent_of, get_double, get_int, get_text, set_int
from ._module import ensure_init
from . import _controller
from .branch import BS_IN, BS_OUT
from .load import clock

RS_CLOSED, RS_OPEN = 0, 1

class Relay(PypowerClass):
    """Behavior of class `relay`"""

    NAME = "relay"
    PASSCONFIG = "BOTTOMUP|AUTOLOCK|OBSERVER"
    PROPERTIES = (
        ("status", "enumeration", prop("relay status (OPEN or CLOSED)", "CLOSED",
            keywords=keywords(("CLOSED", RS_CLOSED), ("OPEN", RS_OPEN)))),
        ("controller", "char256", prop("controller python function name")),
    )
    EVENTS = ("init", "sync")

    @classmethod
    def state(cls, model:Any, name:str) -> dict[str,Any]:
        """State of a relay: `controller` and its keyword arguments"""
        return object_state(model, name, lambda: {"controller": None, "kwargs": {}})

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`relay::init()`"""
        if not ensure_init(model):
            return False
        out = msg(model, name)
        state = cls.state(model, name)
        parent = parent_of(model, name)
        if parent is None:
            out.warning("relay without parent does nothing")
            return True
        if not isa(model, parent, "branch"):
            out.error("relay parent must by a pypower branch")
            return False
        if not get_text(model, name, "controller"):
            out.warning("relay has no controller")
            return True
        controller = _controller.find(model, name, required=True)
        if controller is False:
            return False
        state["controller"] = controller
        kwargs = {"tbus": get_int(model, parent, "tbus")}
        for key in ("r", "x", "b", "rateA", "rateB", "rateC", "ratio", "angle"):
            kwargs[key] = get_double(model, parent, key)
        kwargs["status"] = get_int(model, parent, "status")
        kwargs["angmin"] = get_double(model, parent, "angmin")
        kwargs["angmax"] = get_double(model, parent, "angmax")
        kwargs["controller"] = get_text(model, name, "controller")
        kwargs["t"] = float(clock(model))
        state["kwargs"] = kwargs
        return True

    @classmethod
    def sync(cls, model:Any, name:str, t:int) -> int:
        """`relay::sync()`"""
        parent = parent_of(model, name)
        if parent is None:
            return TS_NEVER
        state = cls.state(model, name)
        t1 = TS_NEVER
        if state["controller"] is not None:
            kwargs = state["kwargs"]
            kwargs["status"] = RS_CLOSED if get_int(model, parent, "status") == BS_IN else RS_OPEN
            kwargs["controller"] = get_text(model, name, "controller")
            kwargs["t"] = float(clock(model))
            result = _controller.call(model, name, state["controller"], kwargs, t, on_set="iterate")
            if result is None:
                return TS_INVALID
            t1 = result[0]
        set_int(model, parent, "status", BS_IN if get_int(model, name, "status") == RS_CLOSED else BS_OUT)
        return t1
