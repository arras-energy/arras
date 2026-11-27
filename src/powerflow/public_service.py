# pylint: disable=line-too-long
"""Class `public_service`: a scheduled public service load turned on by a threshold

Syntax
------

    object public_service {
        phases {A,B,C}[D|N];
        nominal_voltage <real> V;
        P0 <real> W;                    // nameplate power
        Pz <real> pu;                   // load composition: also Pi, Ma, Mb, Mc, Md, Pe
        Pf <real> pu;                   // power factor (default 1)
        schedule "<M-M>,<D-D>,<H-H>,<values>;...";
        threshold_source "<object>.<property>";     // or a global
        threshold_value <real>;
        threshold_invert {TRUE,FALSE};
        // and the meter and the other properties of load
    }

Description
-----------

A `public_service` object (gridlabd `PT_INHERIT "load"`) is a scheduled
load for street lighting, water pumping, and other public services, as
gridlabd's `public_service` does. Its schedule, composition, ZIP form,
and meter are those of `powerflow.agricultural`; in place of the
sensitivity, at the top of each hour the load is on only when the
`threshold_source` value exceeds `threshold_value` (or, with
`threshold_invert`, when it does not); without a source the load is
always on.

When it initializes, a public service load fails as an agricultural load
does, and when the threshold source is not an object property or a
global.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. Without a threshold source the load is on, as gridlabd's
   documentation says; gridlabd's code turns it on only with
   `threshold_invert` (its test starts from `invert` and changes only when
   there is a source).
2. An invalid threshold source fails the initialization; gridlabd writes
   the error and reads the invalid property in each hour.
3. The differences of `powerflow.agricultural` (weekdays from Monday, a
   working meter, the base power, loads with fewer than three phases, the
   meter's leading reactive power, and the schedule's default power
   factor).

References
----------

- `arras-energy/gridlabd`: `module/powerflow/public_service.cpp`,
  `public_service.h`, `docs/Module/Powerflow/Public_service.md`,
  `module/powerflow/autotest/test_public_service.glm`
"""

from typing import Any

from ._base import prop
from ._common import object_state, get_double, get_int, PowerflowError
from .agricultural import ScheduledLoad, COMPOSITION_PROPERTIES, schedule_property, nameplate_property
from .scheduled_load import METER_PROPERTIES, source_property, source_value

class PublicService(ScheduledLoad):
    """Behavior of class `public_service`"""

    NAME = "public_service"
    PROPERTIES = (
        schedule_property(),
        nameplate_property("public_service"),
        ("threshold_source", "char256", prop("source for threshold value")),
        ("threshold_value", "double", prop("threshold value for turning on load")),
        ("threshold_invert", "bool", prop("invert effect of threshold, i.e., 'on' if less than")),
        *COMPOSITION_PROPERTIES,
        ("Pf[pu]", "double", prop("power factor", "+1 pu")),
        *METER_PROPERTIES,
    )

    @classmethod
    def init_source(cls, model:Any, name:str) -> None:
        """The threshold source"""
        text = str(model.get_property(name, "threshold_source") or "").strip('"')
        source = None
        if text:
            source = source_property(model, text)
            if source is None:
                raise PowerflowError(f"{name}: threshold source '{text}' is not valid")
        object_state(model, name)["source"] = source

    @classmethod
    def on(cls, model:Any, name:str) -> bool:
        """Whether the threshold turns the load on"""
        source = object_state(model, name).get("source")
        if source is None:
            return True
        above = source_value(model, source) > get_double(model, name, "threshold_value")
        return above != bool(get_int(model, name, "threshold_invert"))

    @classmethod
    def adjust(cls, model:Any, name:str, parts:tuple[float,float,float]) -> tuple[float,float,float]:
        """No load when the threshold turns it off"""
        return parts if cls.on(model, name) else (0.0, 0.0, 0.0)

__all__ = ["PublicService"]
