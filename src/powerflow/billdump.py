# pylint: disable=line-too-long
"""Class `billdump`: dump of the meters' previous monthly bills to a CSV
file

Syntax
------

    object billdump {
        filename "<file>";
        group "<groupid>";          // all meters when empty
        runtime <timestamp>;        // NEVER: the first time step
        meter_type {TRIPLEX_METER,METER};
    }

Output: `runcount`, the number of dumps written.

Description
-----------

A `billdump` writes, once, the previous monthly bill and energy of the
`triplex_meter` objects (or, with `meter_type METER`, the `meter`
objects; of group `group`, when it is set) to `filename`, as gridlabd's
`billdump` does: at the first committed time at or after `runtime` (any
time when it is `NEVER`, the default; 0 means the first time). Its sync
asks for an event at `runtime`. The file starts with the comment
`# <file> run at <time> on <n> triplex meters` (or `meters`) and the
header `meter_name,previous_monthly_bill,previous_monthly_energy`, then a
row per meter with six decimals.

Caveats
-------

- `filename` is not required, as in gridlabd; without it the dump fails
  to open the file and reports an error.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/billdump.cpp`, `billdump.h`
"""

from typing import Any

from ._base import PowerflowClass, prop, keywords
from ._common import TS_NEVER, isa, msg, get_int, get_double, set_int, gl_error
from .voltdump import runtime_of

TRIPLEX_METER, METER = 0, 1
"""`meter_type` values"""

class BillDump(PowerflowClass):
    """Behavior of class `billdump`"""

    NAME = "billdump"
    TRL = 8 # TRL_QUALIFIED
    PASSCONFIG = "BOTTOMUP|AUTOLOCK"
    EVENTS = ("init", "sync", "commit")
    PROPERTIES = (
        ("group", "char32", prop("the group ID to output data for (all nodes if empty)")),
        ("runtime", "timestamp", prop("the time to check voltage data", "NEVER")),
        ("filename", "char256", prop("the file to dump the voltage data into")),
        ("runcount", "int32", prop("the number of times the file has been written to", access="REFERENCE")),
        ("meter_type", "enumeration", prop("describes whether to collect from 3-phase or S-phase meters", "TRIPLEX_METER",
            keywords=keywords(("TRIPLEX_METER", TRIPLEX_METER), ("METER", METER)))),
    )

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`billdump::init()`"""
        return True

    @classmethod
    def sync(cls, model:Any, name:str, t:int) -> int:
        """`sync_billdump()`: an event at `runtime`"""
        runtime = runtime_of(model, name)
        return runtime if runtime > t else TS_NEVER

    @classmethod
    def dump(cls, model:Any, name:str, t:int) -> None:
        """`billdump::dump()`"""
        cname = "triplex_meter" if get_int(model, name, "meter_type") == TRIPLEX_METER else "meter"
        group = str(model.get_property(name, "group") or "").strip('"')
        found = [x for x, obj in model.objects.items() if obj.oclass.name == cname
            and (not group or str(obj.get("groupid") or "").strip('"') == group)]
        if not found:
            msg(model, name).warning("no nodes were found to dump")
            return
        filename = str(model.get_property(name, "filename") or "").strip('"')
        try:
            outfile = open(filename, "w", encoding="utf-8") # pylint: disable=consider-using-with
        except OSError:
            gl_error(f"billdump unable to open {filename} for output")
            return
        what = "triplex meters" if cname == "triplex_meter" else "meters"
        with outfile:
            outfile.write(f"# {filename} run at {model.globals.timestamp_to_string(t)} on {len(found)} {what}\n")
            outfile.write("meter_name,previous_monthly_bill,previous_monthly_energy\n")
            for item in found:
                if isa(model, item, cname):
                    outfile.write(f"{item},{get_double(model, item, 'previous_monthly_bill'):f},{get_double(model, item, 'previous_monthly_energy'):f}\n")

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int:
        """`billdump::commit()`: one dump at or after `runtime`"""
        runtime = runtime_of(model, name)
        if runtime == 0:
            model.objects[name]["runtime"] = model.globals.timestamp_to_string(t)
            runtime = t
        count = get_int(model, name, "runcount")
        if (t >= runtime or runtime == TS_NEVER) and count < 1:
            cls.dump(model, name, t)
            set_int(model, name, "runcount", count + 1)
        return TS_NEVER

__all__ = ["BillDump"]
