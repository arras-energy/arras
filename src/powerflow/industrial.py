# pylint: disable=line-too-long
"""Class `industrial`: a scheduled industrial load with a NAICS load composition

Syntax
------

    module powerflow {
        NAICS_datafile "<file>";        // default naics_data_file.csv
    }
    object industrial {
        phases {A,B,C}[D|N];
        nominal_voltage <real> V;
        industry_code "<code or index>";
        P0 <real> W;                    // nameplate power
        schedule "<M-M>,<D-D>,<H-H>,<values>;...";
        // and the meter and the other properties of load
    }

Description
-----------

An `industrial` object (gridlabd `PT_INHERIT "load"`) is a scheduled load
whose composition `Pz`, `Pi`, `Ma` ... `Pe` comes from the NERC composite
load model of its industry, as gridlabd's `industrial` does. Its
schedule, ZIP form, and meter are those of `powerflow.agricultural`,
with power factor 1 for records without one and no sensitivity.

The composition is read from `powerflow::NAICS_datafile`, found in the
search path (`arras.folders.findfile()`) or else among the package's data
files (gridlabd's `naics_data_file.csv`), with the header
`NAICS,Code,Industrial Load Type,IA,IB,IC,MD,PwrEl,Z,I` and a row per
industry: its NAICS index, code, and name, and the fractions of motors A,
B, C, D, power electronics, impedance, and current, normalized to sum to 1
(with a warning when they differ from 1 by more than 0.001). An
`industry_code` that is a positive number is an index, otherwise a code.

When it initializes, an industrial load fails when `P0` is not positive,
without an `industry_code`, when the data file is missing or invalid (its
header, a row with fewer than ten fields, or `IA` out of 0 to 1), when the
code is not found, and when a schedule record is invalid.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. An industry code that is not found fails the initialization; gridlabd
   writes the error and goes on with the composition given in the model.
2. The file's data are read once per file for all objects; gridlabd reads
   the first file named for all objects, even when `NAICS_datafile` is
   changed later, and keeps at most 256 rows.
3. The differences of `powerflow.agricultural` (weekdays from Monday, a
   working meter, the base power, loads with fewer than three phases, and
   the meter's leading reactive power).

References
----------

- `arras-energy/gridlabd`: `module/powerflow/industrial.cpp`,
  `industrial.h`, `docs/Module/Powerflow/Industrial.md`,
  `module/powerflow/autotest/test_industrial.glm`,
  `module/industrial/naics_data_file.csv`
"""

import os
from typing import Any

from ._base import prop
from ._common import g, msg, set_double, PowerflowError
from .agricultural import ScheduledLoad, COMPONENTS, COMPOSITION_PROPERTIES, schedule_property, nameplate_property
from .scheduled_load import METER_PROPERTIES, find_data_file

HEADER = "NAICS,Code,Industrial Load Type,IA,IB,IC,MD,PwrEl,Z,I"
"""The NAICS data file header"""

_FILES: dict[tuple[str,float],list[tuple[int,str,str,list[float]]]] = {}

def read_naics(path:str, warn:Any=None) -> list[tuple[int,str,str,list[float]]]:
    """The rows `(index, code, name, [IA, IB, IC, MD, PwrEl, Z, I])` of a
    NAICS data file, normalized; raises `PowerflowError`"""
    key = (path, os.path.getmtime(path))
    if key in _FILES:
        return _FILES[key]
    with open(path, encoding="utf-8") as file:
        lines = file.read().splitlines()
    if not lines:
        raise PowerflowError(f"{path}: missing header line")
    if lines[0] != HEADER:
        raise PowerflowError(f"{path}: invalid header line (expected '{HEADER}')")
    rows = []
    for number, line in enumerate(lines[1:]):
        if not line.strip():
            continue
        fields = line.split(",")
        try:
            values = [float(x) for x in fields[3:10]]
            index = int(fields[0])
        except ValueError:
            values, index = [], 0
        if len(fields) < 10 or len(values) < 7:
            raise PowerflowError(f"{path}({number}): missing required data field(s)")
        if values[0] < 0 or values[0] > 1:
            raise PowerflowError(f"{path}({number}): missing required data field(s)")
        total = sum(values)
        if abs(total - 1.0) > 1e-3 and warn is not None:
            warn(f"{path}({number}): index={index}, code='{fields[1]}', name='{fields[2]}' components do not sum to 1.0 (sum is {total:.4g})")
        rows.append((index, fields[1], fields[2], [x/total for x in values]))
    _FILES[key] = rows
    return rows

class Industrial(ScheduledLoad):
    """Behavior of class `industrial`"""

    NAME = "industrial"
    TOTALS = False
    PROPERTIES = (
        ("industry_code", "char32", prop("industrial facility code (see naics_data_file.csv)", flags="REQUIRED")),
        schedule_property(),
        nameplate_property("industrial"),
        *COMPOSITION_PROPERTIES,
        *METER_PROPERTIES,
    )

    @classmethod
    def default_pf(cls, model:Any, name:str) -> float:
        """Records without a power factor have power factor 1"""
        return 1.0

    @classmethod
    def init_composition(cls, model:Any, name:str) -> None: # pylint: disable=too-many-locals
        """The composition of the industry code"""
        code = str(model.get_property(name, "industry_code") or "").strip().strip('"')
        if not code:
            raise PowerflowError(f"{name}: NAICS industry code must be specified")
        filename = str(g(model, "NAICS_datafile") or "naics_data_file.csv").strip('"')
        path = find_data_file(filename)
        if path is None:
            raise PowerflowError(f"unable to stat file '{filename}'")
        rows = read_naics(path, msg(model, name).warning)
        try:
            index = int(code)
        except ValueError:
            index = 0
        for row_index, row_code, _, values in rows:
            if (row_index == index > 0) or (index <= 0 and row_code == code):
                break
        else:
            raise PowerflowError(f"{name}: unable to locate industry code '{code}' in NAICS data file '{filename}'")
        ia, ib, ic, md, pe, z, i = values
        for key, value in zip(COMPONENTS, (z, i, ia, ib, ic, md, pe)):
            set_double(model, name, key, value)

__all__ = ["Industrial", "read_naics"]
