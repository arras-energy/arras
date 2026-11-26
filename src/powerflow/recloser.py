# pylint: disable=line-too-long
"""Class `recloser`: a switch that recloses after a fault

Syntax
------

    object recloser {
        phases {A,B,C}[N];
        from <node>;
        to <node>;
        retry_time <real> s;
        max_number_of_tries <real>;
        // and the other properties of switch and link
    }

Description
-----------

A `recloser` is a `switch` (gridlabd `PT_INHERIT "switch"`) that starts
`BANKED` with every phase closed. In gridlabd its reclosing is driven by
`fault_check` and `eventgen` through the published functions
`change_recloser_state` (`Recloser.change_recloser_state()`: returns
`max_number_of_tries` when it opens, 1 when it closes) and
`recloser_reliability_operation`; without them it operates as a switch.
At each new time step `number_of_tries` returns to 0.

When it initializes, a recloser is expected to initialize as a `switch`,
then:

1. warn and use 0 when `max_number_of_tries` is negative, and use 3 when
   it is 0;
2. warn and use 0 when `retry_time` is negative, and use 1 s when it is 0.

Caveats
-------

- Faults and reliability (`fault_check`, `eventgen`) are not ported, so
  nothing calls `change_recloser_state` yet.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

None beyond those of `switch`.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/recloser.cpp`, `recloser.h`
"""

from typing import Any

from ._base import prop
from ._common import msg, object_state, get_double, set_double
from .switch import Switch

class Recloser(Switch):
    """Behavior of class `recloser`"""

    NAME = "recloser"
    PARENT = "switch"
    TRL = 0
    PROPERTIES = (
        ("retry_time[s]", "double", prop("the amount of time in seconds to wait before the recloser attempts to close")),
        ("max_number_of_tries", "double", prop("the number of times the recloser will try to close before permanently opening")),
        ("number_of_tries", "double", prop("Current number of tries recloser has attempted", flags="OUTPUT")),
    )

    @classmethod
    def init_link(cls, model:Any, name:str) -> None:
        """`recloser::init()` after `switch_object::init()`"""
        super().init_link(model, name)
        out = msg(model, name)
        if get_double(model, name, "max_number_of_tries") < 0:
            out.warning("The number of recloser tries is less than 0 resetting to zero")
            set_double(model, name, "max_number_of_tries", 0.0)
        if get_double(model, name, "retry_time") < 0:
            out.warning("retry time is < 0 resetting to zero")
            set_double(model, name, "retry_time", 0.0)
        if get_double(model, name, "max_number_of_tries") == 0:
            set_double(model, name, "max_number_of_tries", 3.0)
        if get_double(model, name, "retry_time") == 0:
            set_double(model, name, "retry_time", 1.0)

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        """`recloser::sync()`: reset `number_of_tries` at a new time step,
        then the switch logic"""
        state = object_state(model, name)
        if state.get("time") != t0:
            state["time"] = t0
            set_double(model, name, "number_of_tries", 0.0)
        super().before_solve(model, name, t0)

    @classmethod
    def change_recloser_state(cls, model:Any, name:str, phase_change:int, state:bool) -> float:
        """gridlabd's published `change_recloser_state`: the switch change
        of `Switch.change_switch_state()`; returns `max_number_of_tries`
        when opening (all tries made), 1 when closing"""
        cls.change_switch_state(model, name, phase_change, state)
        return 1.0 if state else get_double(model, name, "max_number_of_tries")

__all__ = ["Recloser"]
