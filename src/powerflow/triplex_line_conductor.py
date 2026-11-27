# pylint: disable=line-too-long
"""Class `triplex_line_conductor`: a conductor of triplex lines

Syntax
------

    object triplex_line_conductor {
        resistance <real> Ohm/mile;
        geometric_mean_radius <real> ft;
        rating.summer.continuous <real> A;   // also .summer.emergency, .winter.continuous, .winter.emergency
    }

Description
-----------

A library object that `triplex_line_configuration`, not ported yet, refers
to. Its ratings default to 202 A continuous and 212.1 A emergency (1/0
class A AA wire), as gridlabd's `create()` sets them. When it initializes,
it is expected to fail when `resistance` is 0.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A zero `resistance` fails with every solver method (gridlabd: an error
   with NR, a warning with FBS); the message names `NR` for NR and FBS and
   the method's keyword for the others.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/triplex_line_conductor.cpp`
"""

from typing import Any

from ._base import prop
from ._common import get_double, PowerflowError
from .powerflow_library import LibraryObject, method_label

class TriplexLineConductor(LibraryObject):
    """Behavior of class `triplex_line_conductor`"""

    NAME = "triplex_line_conductor"
    PROPERTIES = (
        ("resistance[Ohm/mile]", "double", prop("resistance of cable in ohm/mile", "0 Ohm/mile")),
        ("geometric_mean_radius[ft]", "double", prop("geometric mean radius of the cable", "0 ft")),
        ("rating.summer.continuous[A]", "double", prop("amp ratings for the cable during continuous operation in summer", "202 A")),
        ("rating.summer.emergency[A]", "double", prop("amp ratings for the cable during short term operation in summer", "212.1 A")),
        ("rating.winter.continuous[A]", "double", prop("amp ratings for the cable during continuous operation in winter", "202 A")),
        ("rating.winter.emergency[A]", "double", prop("amp ratings for the cable during short term operation in winter", "212.1 A")),
    )

    @classmethod
    def check(cls, model:Any, name:str) -> None:
        if get_double(model, name, "resistance") == 0:
            raise PowerflowError(f"triplex_line_conductor:{model.objects[name].id} - {name} - {method_label(model)}: resistance is zero")
