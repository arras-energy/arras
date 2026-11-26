# pylint: disable=line-too-long
"""Class `overhead_line_conductor`: a conductor of overhead lines

Syntax
------

    object overhead_line_conductor {
        geometric_mean_radius <real> ft;
        resistance <real> Ohm/mile;
        diameter <real> in;
        rating.summer.continuous <real> A;   // also .summer.emergency, .winter.continuous, .winter.emergency
        weight <real> lb/ft;
        strength <real> lb;
    }

Description
-----------

A library object that a `line_configuration` refers to with its
`conductor_X` properties; `overhead_line`, not ported yet, computes its
impedance from it. When it initializes, it is expected to fail when
`resistance` is 0.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A zero `resistance` fails with every solver method, since every method
   inverts the impedance (gridlabd: an error with NR, a warning with FBS);
   the message names `NR` for NR and FBS and the method's keyword for the
   others.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/overhead_line_conductor.cpp`
"""

from typing import Any

from ._base import prop
from ._common import get_double, PowerflowError
from .powerflow_library import LibraryObject, method_label

RATINGS = (
    ("rating.summer.continuous[A]", "double", prop("Continuous summer amp rating", "1000 A")),
    ("rating.summer.emergency[A]", "double", prop("Emergency summer amp rating", "2000 A")),
    ("rating.winter.continuous[A]", "double", prop("Continuous winter amp rating", "1000 A")),
    ("rating.winter.emergency[A]", "double", prop("Emergency winter amp rating", "2000 A")),
)

class OverheadLineConductor(LibraryObject):
    """Behavior of class `overhead_line_conductor`"""

    NAME = "overhead_line_conductor"
    PROPERTIES = (
        ("geometric_mean_radius[ft]", "double", prop("radius of the conductor", flags="REQUIRED")),
        ("resistance[Ohm/mile]", "double", prop("resistance in Ohms/mile of the conductor", flags="REQUIRED")),
        ("diameter[in]", "double", prop("Diameter of line for capacitance calculations", flags="REQUIRED")),
        *RATINGS,
        ("weight[lb/ft]", "double", prop("Cable weight per lineal foot")),
        ("strength[lb]", "double", prop("Cable strength")),
    )

    @classmethod
    def check(cls, model:Any, name:str) -> None:
        if get_double(model, name, "resistance") == 0:
            raise PowerflowError(f"overhead_line_conductor:{model.objects[name].id} - {name} - {method_label(model)}: resistance is zero")
