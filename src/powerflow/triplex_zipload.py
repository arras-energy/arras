# pylint: disable=line-too-long
"""Class `triplex_zipload`: a triplex load whose ZIP components follow the
weather and a schedule

Syntax
------

    object triplex_zipload {
        phases {A,B,C}S;
        nominal_voltage <real> V;
        // the properties of zipload, and those of triplex_load
    }

Description
-----------

A `triplex_zipload` is a `triplex_load` (gridlabd `PT_INHERIT
"triplex_load"`) with the weather, schedule, and load data of `zipload`
(`powerflow.zipload.ZipModel`), as gridlabd's `triplex_zipload::sync()`
computes them, with these differences from `zipload`:

- the whole load is the 240 V load (`base_power_12` and its fractions and
  power factors; those of lines 1 and 2 are 0);
- the schedule value is divided by `sqrt(3)` (as gridlabd divides it);
- `base_power_12` is the sum of the magnitudes of the three parts, and
  there is no voltage check.

When it initializes, a triplex zipload is expected to link its weather
object, build its schedule, read its load data, then initialize as a
`triplex_load`.

Caveats
-------

- The `sqrt(3)` divisor is gridlabd's (a 240 V load has no three phases to
  share the schedule value); it is kept so that results compare with
  gridlabd's.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

As `zipload` (2 to 5).

References
----------

- `arras-energy/gridlabd`: `module/powerflow/triplex_zipload.cpp`,
  `triplex_zipload.h`
"""

import math
from typing import Any

from ._common import object_state, set_double
from .triplex_load import TriplexLoad
from .zipload import ZipModel, zip_properties, TRL_PROTOTYPE

class TriplexZipLoad(ZipModel, TriplexLoad):
    """Behavior of class `triplex_zipload`"""

    NAME = "triplex_zipload"
    PARENT = "triplex_load"
    TRL = TRL_PROTOTYPE
    DIVISOR = math.sqrt(3)
    PROPERTIES = zip_properties()

    @classmethod
    def init_node(cls, model:Any, name:str) -> None:
        """`triplex_zipload::init()`"""
        cls.zip_init(model, name)
        super().init_node(model, name)

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        """The inputs and the ZIP form of the 240 V load, then the load's
        values"""
        if "scale" in object_state(model, name):
            cls.zip_inputs(model, name)
            z, i, p = cls.zip_parts(model, name, t0)
            total = abs(z) + abs(i) + abs(p)
            for x in ("1", "2"):
                set_double(model, name, f"base_power_{x}", 0.0)
                for kind in ("impedance", "current", "power"):
                    set_double(model, name, f"{kind}_fraction_{x}", 0.0)
                    set_double(model, name, f"{kind}_pf_{x}", 0.0)
            set_double(model, name, "base_power_12", total)
            for kind, part in (("impedance", z), ("current", i), ("power", p)):
                set_double(model, name, f"{kind}_fraction_12", abs(part)/total if total > 0 else 0.0)
                set_double(model, name, f"{kind}_pf_12", cls.pf(part))
        super().before_solve(model, name, t0)

__all__ = ["TriplexZipLoad"]
