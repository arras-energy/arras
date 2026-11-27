"""Class `currdump`: dump of the link currents to a CSV file

Syntax
------

    object currdump {
        filename "<file>";
        group "<groupid>";          // all links when empty
        runtime <timestamp>;        // NEVER: the first time step
        interval <real> s;          // 0: at runtime only
        maxcount <integer>;
        mode {RECT,POLAR};
        filemode "<w|a>";
        version {1,2};
    }

Output: `runcount`, the number of dumps written.

Description
-----------

A `currdump` writes the currents into the powerflow links (of group
`group`, when it is set) at their from ends (`current_in_A`, `_B`, `_C`,
gridlabd's `read_I_in`) to `filename`, as gridlabd's `currdump` does,
when a time step is committed, with the timing, file modes, and formats
of `voltdump` (see `powerflow.voltdump`), the header `link_name,...,
currA_real,...` (`currA_mag,currA_angle,...` in `POLAR` mode), and the
comment `on <n> links` in version 1. Its defaults differ from
`voltdump`'s, as in gridlabd: `maxcount` 1 and `filemode` `w` (so an
interval dump rewrites the file each time unless `filemode` is `a`).

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. With an interval, the dumps stop after `maxcount` of them, and the
   sync asks for an event at the next multiple, as in `voltdump`.
2. Appending is reported as `currdump is appending data to <file>`;
   gridlabd's message names `voltdump`.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/currdump.cpp`, `currdump.h`
"""

from typing import Any

from ._common import get_complex
from .voltdump import Dump, dump_properties

class CurrDump(Dump):
    """Behavior of class `currdump`"""

    NAME = "currdump"
    TRL = 0 # TRL_UNKNOWN: gridlabd sets none
    KIND = "link"
    COLUMNS = ("curr", "link_name")
    WHAT = "current"
    PROPERTIES = dump_properties("current", "link", ("RECT", "POLAR"), "RECT", "1", "w")

    @classmethod
    def values(cls, model:Any, name:str) -> list[complex]:
        """The currents into the link at its from end"""
        return [get_complex(model, name, f"current_in_{x}") for x in "ABC"]

__all__ = ["CurrDump"]
