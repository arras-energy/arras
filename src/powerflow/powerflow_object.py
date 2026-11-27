# pylint: disable=line-too-long
"""Class `powerflow_object`: the abstract base of the powerflow classes

Syntax
------

    class powerflow_object {
        phases {A,B,C,D,N,S,G}[|...];
        nominal_voltage <real> V;
    }

The output `violation_detected` (`NONE`, `CURRENT`, `VOLTAGE`, `POWER`,
`THERMAL`, `CONTROL`) is also published.

Description
-----------

`powerflow_object` is abstract (`ABSTRACTONLY`): models create `node` and
`link` objects, which inherit its properties. When an object of a derived
class initializes, it is expected to:

1. take its parent's `phases` when it has none and its parent is a
   powerflow object;
2. fail when it has no phases;
3. fail when a split connection (`S`) has none or more than one of `A`,
   `B`, `C`, or is also a delta connection (`D`);
4. drop `N` from a split connection, with a warning.

The module globals `powerflow::violation_record`, `violation_count`,
`violation_active`, and `violation_watchset` are created with the class,
as gridlabd's constructor creates them.

Caveats
-------

- Violation recording (`violation_record` files, `violation_detected`) is
  not implemented yet: the globals and the property are published so that
  models that set them load.
- The `condition` and `solution` properties exist in gridlabd only when it
  is built with `SUPPORT_OUTAGES`, which it is not; they are not published.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

None for the published properties and the initialization checks.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/powerflow_object.cpp`,
  `powerflow_object.h`
"""

from typing import Any

from ._base import PowerflowClass, prop, keywords
from ._common import (NO_PHASE, PHASE_A, PHASE_B, PHASE_C, PHASE_N, PHASE_S, PHASE_D, GROUND,
    PHASE_S1, PHASE_S2, PHASE_SN, isa, ref, get_int, set_flags, msg, PowerflowError)

PHASE_KEYWORDS = keywords(("G", GROUND), ("S", PHASE_S), ("N", PHASE_N), ("D", PHASE_D),
    ("C", PHASE_C), ("B", PHASE_B), ("A", PHASE_A))
"""Keywords of `phases`, as gridlabd lists them"""

class PowerflowObject(PowerflowClass):
    """Behavior of class `powerflow_object`"""

    NAME = "powerflow_object"
    PASSCONFIG = "ABSTRACTONLY|AUTOLOCK"
    PROPERTIES = (
        ("phases", "set", prop("phases to which this object is connected", flags="REQUIRED", keywords=PHASE_KEYWORDS)),
        ("nominal_voltage[V]", "double", prop("nominal voltage for this object", flags="REQUIRED")),
        ("violation_detected", "set", prop("rating or limit violation flag", flags="OUTPUT",
            keywords=keywords(("CONTROL", 0x10), ("THERMAL", 0x08), ("POWER", 0x04), ("VOLTAGE", 0x02), ("CURRENT", 0x01), ("NONE", 0x00))))
    )

    @classmethod
    def init_object(cls, model:Any, name:str) -> None:
        """`powerflow_object::init()`: phase checks

        Exceptions
        ----------
        - `PowerflowError`: the phases are missing or not valid (gridlabd
          throws, and `INIT_CATCHALL()` fails the initialization)
        """
        phases = get_int(model, name, "phases")
        parent = ref(model, name, "parent")
        if phases == NO_PHASE and isa(model, parent, "powerflow_object"):
            phases = get_int(model, parent, "phases")
            set_flags(model, name, "phases", phases)
        if phases == 0:
            raise PowerflowError("phases not specified")
        abc = [phases & bit != 0 for bit in (PHASE_A, PHASE_B, PHASE_C)]
        if phases & PHASE_S == PHASE_S:
            if not any(abc):
                raise PowerflowError("split connection is missing A,B, or C phase connection")
            if sum(abc) > 1:
                raise PowerflowError("split connection is connected to two phases simultaneously")
            if phases & PHASE_D == PHASE_D:
                raise PowerflowError("split and delta connection cannot occur simultaneously")
            if phases & PHASE_N == PHASE_N:
                msg(model, name).warning("neutral phase ignored on split connection.")
                set_flags(model, name, "phases", phases ^ PHASE_N)

__all__ = ["PowerflowObject", "PHASE_KEYWORDS", "PHASE_S1", "PHASE_S2", "PHASE_SN"]
