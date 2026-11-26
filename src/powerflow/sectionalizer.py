# pylint: disable=line-too-long
"""Class `sectionalizer`: a switch that opens after an upstream recloser

Syntax
------

    object sectionalizer {
        phases {A,B,C}[N];
        from <node>;
        to <node>;
        // the properties of switch and link
    }

Description
-----------

A `sectionalizer` is a `switch` (gridlabd `PT_INHERIT "switch"`, no
properties of its own) that starts `BANKED` with every phase closed. In
gridlabd it opens only after `fault_check` finds a recloser upstream
(published function `change_sectionalizer_state`); without
`fault_check` it operates as a switch. `Sectionalizer.change_sectionalizer_state()`
closes as a switch does and, like gridlabd without `fault_check`, fails
when asked to open.

When it initializes, a sectionalizer is expected to initialize as a
`switch`.

Caveats
-------

- Faults and reliability (`fault_check`, `eventgen`) are not ported.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

None beyond those of `switch`.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/sectionalizer.cpp`,
  `sectionalizer.h`
"""

from typing import Any

from ._common import PowerflowError
from .switch import Switch

class Sectionalizer(Switch):
    """Behavior of class `sectionalizer`"""

    NAME = "sectionalizer"
    PARENT = "switch"
    TRL = 0
    PROPERTIES = ()

    @classmethod
    def change_sectionalizer_state(cls, model:Any, name:str, phase_change:int, state:bool) -> float:
        """gridlabd's published `change_sectionalizer_state`: closing is the
        switch change of `Switch.change_switch_state()` and returns 1;
        opening needs `fault_check` to find a recloser, which is not ported
        (raises `PowerflowError`, gridlabd's message without `fault_check`)"""
        if not state:
            raise PowerflowError("Reliability call made without fault_check object present!")
        cls.change_switch_state(model, name, phase_change, state)
        return 1.0

__all__ = ["Sectionalizer"]
