# pylint: disable=line-too-long
"""Class `line_spacing`: the distances between the wires of a line

Syntax
------

    object line_spacing {
        distance_AB <real> ft;   // also distance_BC, distance_AC
        distance_AN <real> ft;   // also distance_BN, distance_CN
        distance_AE <real> ft;   // also distance_BE, distance_CE, distance_NE (to earth)
    }

Description
-----------

A `line_spacing` is a library object that a `line_configuration` refers to
with its `spacing` property. `overhead_line` and `underground_line`, which
are not ported yet, compute their impedance from it. It has no
initialization checks.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

None.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/line_spacing.cpp`
"""

from ._base import prop
from .powerflow_library import PowerflowLibrary

class LineSpacing(PowerflowLibrary): # pylint: disable=too-few-public-methods
    """Behavior of class `line_spacing`"""

    NAME = "line_spacing"
    PROPERTIES = (
        *((f"distance_{x}[ft]", "double", prop(default="0 ft")) for x in ("AB", "BC", "AC", "AN", "BN", "CN")),
        ("distance_AE[ft]", "double", prop("distance between phase A wire and earth", "0 ft")),
        ("distance_BE[ft]", "double", prop("distance between phase B wire and earth", "0 ft")),
        ("distance_CE[ft]", "double", prop("distance between phase C wire and earth", "0 ft")),
        ("distance_NE[ft]", "double", prop("distance between neutral wire and earth", "0 ft")),
    )
