# pylint: disable=line-too-long
"""Class `underground_line_conductor`: a concentric-neutral or tape-shielded
cable of underground lines

Syntax
------

    object underground_line_conductor {
        outer_diameter <real> in;
        conductor_gmr <real> ft;
        conductor_diameter <real> in;
        conductor_resistance <real> Ohm/mile;
        neutral_gmr <real> ft;
        neutral_diameter <real> in;
        neutral_resistance <real> Ohm/mile;
        neutral_strands <integer>;
        shield_thickness <real> in;
        shield_diameter <real> in;
        insulation_relative_permitivitty <real> unit;
        shield_gmr <real> ft;
        shield_resistance <real> Ohm/mile;
        rating.summer.continuous <real> A;   // also .summer.emergency, .winter.continuous, .winter.emergency
        insulation_R <real> K/W;
    }

Description
-----------

A library object that a `line_configuration` refers to with its
`conductor_X` properties; `underground_line`, not ported yet, computes its
impedance from it (Kersting, figure 4.11). When it initializes, it is
expected to fail when:

1. `outer_diameter` is less than `conductor_diameter` or
   `neutral_diameter`;
2. `shield_diameter` is less than `shield_thickness`;
3. `conductor_resistance` is 0;
4. `insulation_R` is not positive.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A zero `conductor_resistance` fails with every solver method (gridlabd:
   an error with NR, a warning with FBS); the message names `NR` for NR
   and FBS and the method's keyword for the others.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/underground_line_conductor.cpp`
"""

from typing import Any

from ._base import prop
from ._common import get_double, PowerflowError
from .powerflow_library import LibraryObject, method_label

class UndergroundLineConductor(LibraryObject):
    """Behavior of class `underground_line_conductor`"""

    NAME = "underground_line_conductor"
    PROPERTIES = (
        ("outer_diameter[in]", "double", prop("Outer diameter of conductor and sheath", flags="REQUIRED")),
        ("conductor_gmr[ft]", "double", prop("Geometric mean radius of the conductor")),
        ("conductor_diameter[in]", "double", prop("Diameter of conductor", flags="REQUIRED")),
        ("conductor_resistance[Ohm/mile]", "double", prop("Resistance of conductor in ohm/mile")),
        ("neutral_gmr[ft]", "double", prop("Geometric mean radius of an individual neutral conductor/strand")),
        ("neutral_diameter[in]", "double", prop("Diameter of individual neutral conductor/strand of concentric neutral", flags="REQUIRED")),
        ("neutral_resistance[Ohm/mile]", "double", prop("Resistance of an individual neutral conductor/strand in ohm/mile")),
        ("neutral_strands", "int16", prop("Number of cable strands in neutral conductor")),
        ("shield_thickness[in]", "double", prop("The thickness of Tape shield in inches")),
        ("shield_diameter[in]", "double", prop("The outside diameter of Tape shield in inches")),
        ("insulation_relative_permitivitty[unit]", "double", prop("Permitivitty of insulation, relative to air", "1 unit")),
        ("shield_gmr[ft]", "double", prop("Geometric mean radius of shielding sheath")),
        ("shield_resistance[Ohm/mile]", "double", prop("Resistance of shielding sheath in ohms/mile")),
        ("rating.summer.continuous[A]", "double", prop("amp rating in summer, continuous", "1000 A")),
        ("rating.summer.emergency[A]", "double", prop("amp rating in summer, short term", "2000 A")),
        ("rating.winter.continuous[A]", "double", prop("amp rating in winter, continuous", "1000 A")),
        ("rating.winter.emergency[A]", "double", prop("amp rating in winter, short term", "2000 A")),
        ("insulation_R[K/W]", "double", prop("insulation thermal resistance", "+10 K/W")),
    )

    @classmethod
    def check(cls, model:Any, name:str) -> None:
        def value(prop_:str) -> float:
            return get_double(model, name, prop_)
        if value("outer_diameter") < value("conductor_diameter"):
            raise PowerflowError("outer_diameter was specified as less than the conductor_diameter")
        if value("outer_diameter") < value("neutral_diameter"):
            raise PowerflowError("outer_diameter was specified as less than the neutral_diameter")
        if value("shield_diameter") < value("shield_thickness"):
            raise PowerflowError("shield_diameter was specified as less than the tapeshield_thickness")
        if value("conductor_resistance") == 0:
            raise PowerflowError(f"underground_line_conductor:{model.objects[name].id} - {name} - {method_label(model)}: conductor_resistance is zero")
        if value("insulation_R") <= 0:
            raise PowerflowError("insulation_R must be positive")
