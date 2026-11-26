# pylint: disable=line-too-long
"""Class `triplex_line_configuration`: the configuration of a triplex
(split-phase secondary) line

Syntax
------

    object triplex_line_configuration {
        conductor_1 <triplex_line_conductor>;
        conductor_2 <triplex_line_conductor>;
        conductor_N <triplex_line_conductor>;
        insulation_thickness <real> in;
        diameter <real> in;
        spacing <line_spacing>;
        z11 <complex> Ohm/mile;   // also z12, z21, z22
        rating.summer.continuous <real> A;   // also .summer.emergency, .winter.continuous, .winter.emergency
    }

Description
-----------

A library object that `triplex_line`, not ported yet, refers to: either
its conductors, insulation thickness, and diameter, or the impedance
matrix of lines 1 and 2 (`z11`, `z12`, `z21`, `z22`). gridlabd's class
derives from `line_configuration` in C++ without inheriting its
publication: it publishes its own properties, has no parent class, and
answers `isa("line_configuration")`, so a `line` accepts it as its
configuration and uses its `z11` ... `z22` (the other terms and the
capacitances are 0). The ratings default to 1000 A continuous and 2000 A
emergency, as gridlabd's `create()` sets them. It has no initialization
checks.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

None.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/triplex_line_configuration.cpp`,
  `triplex_line_configuration.h`
"""

from ._base import prop
from .line_configuration import LineConfiguration

class TriplexLineConfiguration(LineConfiguration):
    """Behavior of class `triplex_line_configuration`"""

    NAME = "triplex_line_configuration"
    PROPERTIES = (
        ("conductor_1", "object", prop("conductor type for phase 1")),
        ("conductor_2", "object", prop("conductor type for phase 2")),
        ("conductor_N", "object", prop("conductor type for phase N")),
        ("insulation_thickness[in]", "double", prop("thickness of insulation around cabling", "0 in")),
        ("diameter[in]", "double", prop("total diameter of cable", "0 in")),
        ("spacing", "object", prop("defines the line spacing configuration")),
        ("z11[Ohm/mile]", "complex", prop("phase 1 self-impedance, used for direct entry of impedance values")),
        ("z12[Ohm/mile]", "complex", prop("phase 1-2 induced impedance, used for direct entry of impedance values")),
        ("z21[Ohm/mile]", "complex", prop("phase 2-1 induced impedance, used for direct entry of impedance values")),
        ("z22[Ohm/mile]", "complex", prop("phase 2 self-impedance, used for direct entry of impedance values")),
        ("rating.summer.continuous[A]", "double", prop("amp rating in summer, continuous", "1000 A")),
        ("rating.summer.emergency[A]", "double", prop("amp rating in summer, short term", "2000 A")),
        ("rating.winter.continuous[A]", "double", prop("amp rating in winter, continuous", "1000 A")),
        ("rating.winter.emergency[A]", "double", prop("amp rating in winter, short term", "2000 A")),
    )
