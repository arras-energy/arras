# pylint: disable=line-too-long
"""Class `line_configuration`: the impedance and capacitance of a line

Syntax
------

    object line_configuration {
        z11 <complex> Ohm/mile;    // also z12, z13, z21, z22, z23, z31, z32, z33
        c11 <real> nF/mile;        // also c12, c13, c21, c22, c23, c31, c32, c33
        conductor_A <conductor>;   // also conductor_B, conductor_C, conductor_N
        spacing <line_spacing>;
        rating.summer.continuous <real> A;
        rating.summer.emergency <real> A;
        rating.winter.continuous <real> A;
        rating.winter.emergency <real> A;
    }

Description
-----------

A `line_configuration` is a library object (`NOSYNC`) that lines refer to
with their `configuration` property. A `line` object (of the base class)
uses its matrix form: the series impedance `zIJ` (ohm per mile) and the
shunt capacitance `cIJ` (nF per mile) between phases `I` and `J` (1, 2, 3
for A, B, C). The conductor and spacing references are used by
`overhead_line` and `underground_line`, which are not ported yet.

Caveats
-------

- The conductor and spacing classes are not ported yet, so `conductor_X`
  and `spacing` can only refer to objects of other classes; they are not
  used.
- The ratings are published but not used (link limits are not
  implemented).

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

None.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/line_configuration.cpp`,
  `line_configuration.h`
"""

from typing import Any

import numpy as np

from ._base import PowerflowClass, prop
from ._common import get_complex, get_double

INDEXES = ("11", "12", "13", "21", "22", "23", "31", "32", "33")
"""Matrix terms, in gridlabd's publication order"""

class LineConfiguration(PowerflowClass):
    """Behavior of class `line_configuration`"""

    NAME = "line_configuration"
    PASSCONFIG = "NOSYNC"
    PROPERTIES = (
        ("conductor_A", "object", prop()),
        ("conductor_B", "object", prop()),
        ("conductor_C", "object", prop()),
        ("conductor_N", "object", prop()),
        ("spacing", "object", prop()),
        *((f"z{ij}[Ohm/mile]", "complex", prop(default="0+0j")) for ij in INDEXES),
        *((f"c{ij}[nF/mile]", "double", prop(default="0 nF/mile")) for ij in INDEXES),
        ("rating.summer.continuous[A]", "double", prop("amp rating in summer, continuous", "1000 A")),
        ("rating.summer.emergency[A]", "double", prop("amp rating in summer, short term", "2000 A")),
        ("rating.winter.continuous[A]", "double", prop("amp rating in winter, continuous", "1000 A")),
        ("rating.winter.emergency[A]", "double", prop("amp rating in winter, short term", "2000 A")),
    )

    @classmethod
    def impedance(cls, model:Any, name:str) -> np.ndarray:
        """Series impedance matrix (3x3, ohm per mile)"""
        return np.array([get_complex(model, name, f"z{ij}") for ij in INDEXES]).reshape(3, 3)

    @classmethod
    def capacitance(cls, model:Any, name:str) -> np.ndarray:
        """Shunt capacitance matrix (3x3, nF per mile)"""
        return np.array([get_double(model, name, f"c{ij}") for ij in INDEXES]).reshape(3, 3)

    @classmethod
    def key(cls, model:Any, name:str) -> tuple:
        """Values the matrices depend on"""
        return tuple(cls.impedance(model, name).ravel()) + tuple(cls.capacitance(model, name).ravel())
