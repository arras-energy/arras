# pylint: disable=line-too-long
"""Class `pole_configuration`: the design of a utility pole

Syntax
------

    object pole_configuration {
        pole_type {WOOD,CONCRETE,STEEL};
        design_ice_thickness <real> in;
        design_wind_loading <real> psi;
        design_temperature <real> degF;
        overload_factor_vertical <real>;    // and the other overload and strength factors
        pole_length <real> ft;
        pole_depth <real> ft;
        ground_diameter <real> in;
        top_diameter <real> in;
        fiber_strength <real> psi;
        repair_time <real> h;
        degradation_rate <real> in/yr;
        treatment_method {NONE,CREOSOTE,PENTA,CCA};
        material_density <real> lb/cf;
        wind_overdesign <real> pu;
    }

The class also creates the global `powerflow::climate_impact_zone`
(`NONE`, `LOW`, `MODERATE`, `INTERMEDIATE`, `HIGH`, `EXTREME`).

Description
-----------

A library object for pole loading models (gridlabd's `pole` class, in
another module). Its defaults are those gridlabd's `create()` sets: a
45/5 southern yellow pine pole in a medium loading district with grade C
factors. When it initializes, it is expected to:

1. warn and reset `powerflow::climate_impact_zone` to `NONE` when it is
   not valid, and `treatment_method` to `CCA` when it is not valid;
2. fail when `degradation_rate` is negative, and set it from the
   degradation table of the climate impact zone and the treatment method
   when it is 0 (only CCA-treated poles degrade: 0.035 to 0.05 in/yr from
   `LOW` to `EXTREME`);
3. fail when `repair_time` is negative.

`PoleConfiguration.pole_diameter()` gives the diameter at a height, as
gridlabd's `get_pole_diameter()`.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A treatment method that is not valid resets `treatment_method`;
   gridlabd resets `climate_impact_zone` instead (to the value of `CCA`).
   Neither can happen from GLM, since the keywords are checked when set.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/pole_configuration.cpp`,
  `pole_configuration.h`
"""

from typing import Any

from ._base import prop, keywords
from ._common import g, get_double, get_int, set_double, msg, PowerflowError, MODULE
from .powerflow_library import LibraryObject

CLIMATE_IMPACT_ZONES = {"NONE": 0, "LOW": 1, "MODERATE": 2, "INTERMEDIATE": 3, "HIGH": 4, "EXTREME": 5}
"""Keywords of `powerflow::climate_impact_zone`"""

TREATMENT_METHODS = {"NONE": 0, "CREOSOTE": 1, "PENTA": 2, "CCA": 3}
"""Keywords of `treatment_method`"""

DEGRADATION_RATE = (
    (0.00, 0.00, 0.00, 0.00),
    (0.00, 0.00, 0.00, 0.035),
    (0.00, 0.00, 0.00, 0.040),
    (0.00, 0.00, 0.00, 0.044),
    (0.00, 0.00, 0.00, 0.047),
    (0.00, 0.00, 0.00, 0.05),
)
"""Pole degradation rate (in/yr) by climate impact zone and treatment
method"""

def _f(description:str, default:str) -> dict[str,Any]:
    return prop(description, default)

class PoleConfiguration(LibraryObject):
    """Behavior of class `pole_configuration`"""

    NAME = "pole_configuration"
    PASSCONFIG = "NOSYNC"
    PROPERTIES = (
        ("pole_type", "enumeration", prop("material from which pole is made", "WOOD", keywords=keywords(("WOOD", 0), ("CONCRETE", 2), ("STEEL", 1)))),
        ("design_ice_thickness[in]", "double", _f("design ice thickness on conductors", "0.25 in")),
        ("design_wind_loading[psi]", "double", _f("design wind loading on pole", "4 psi")),
        ("design_temperature[degF]", "double", _f("design temperature for pole", "15 degF")),
        ("overload_factor_vertical", "double", _f("design overload factor (vertical)", "1.9")),
        ("overload_factor_transverse_general", "double", _f("design overload factor (transverse general)", "1.75")),
        ("overload_factor_transverse_crossing", "double", _f("design overload factor (transverse crossing)", "2.2")),
        ("overload_factor_transverse_wire", "double", _f("design overload factor (transverse wire)", "1.65")),
        ("overload_factor_longitudinal_general", "double", _f("design overload factor (longitudinal general)", "1")),
        ("overload_factor_longitudinal_deadend", "double", _f("design overload factor (longitudinal deadend)", "1.3")),
        ("strength_factor_250b_wood", "double", _f("design strength factor (Rule 250B wood structure)", "0.85")),
        ("strength_factor_250b_support", "double", _f("design strength factor (Rule 250B support hardware)", "1")),
        ("strength_factor_250c_wood", "double", _f("design strength factor (Rule 250C wood structure)", "0.75")),
        ("strength_factor_250c_support", "double", _f("design strength factor (Rule 250C support hardware)", "1")),
        ("pole_length[ft]", "double", _f("total length of pole (including underground portion)", "45 ft")),
        ("pole_depth[ft]", "double", _f("depth of pole underground", "4.5 ft")),
        ("ground_diameter[in]", "double", _f("diameter of pole at ground level", f"{32.5/3.14!r} in")),
        ("top_diameter[in]", "double", _f("diameter of pole at top", f"{0.58*32.5/3.14!r} in")),
        ("fiber_strength[psi]", "double", _f("pole structural strength", "8000 psi")),
        ("repair_time[h]", "double", _f("pole repair time", "0 h")),
        ("degradation_rate[in/yr]", "double", prop("rate of pole degradation.")),
        ("treatment_method", "enumeration", prop("pole degradation prevention treatment", "NONE", keywords=keywords(*TREATMENT_METHODS.items()))),
        ("material_density[lb/cf]", "double", _f("pole material density", "35 lb/cf")),
        ("wind_overdesign[pu]", "double", _f("design margin for critical wind", "1 pu")),
    )

    @classmethod
    def check(cls, model:Any, name:str) -> None:
        out = msg(model, name)
        zone = int(g(model, "climate_impact_zone") or 0)
        if not 0 <= zone < len(CLIMATE_IMPACT_ZONES):
            out.warning(f"climate impact zone {zone} is not valid, resetting to default NONE")
            model.globals.set(f"{MODULE}::climate_impact_zone", "NONE")
            zone = 0
        treatment = get_int(model, name, "treatment_method")
        if not 0 <= treatment < len(TREATMENT_METHODS):
            out.warning("pole treatment method is not valid, resetting to default CCA")
            model.objects[name]["treatment_method"] = "CCA"
            treatment = TREATMENT_METHODS["CCA"]
        rate = get_double(model, name, "degradation_rate")
        if rate < 0:
            raise PowerflowError(f"{name}: degradation_rate must be zero or positive")
        if rate == 0:
            set_double(model, name, "degradation_rate", DEGRADATION_RATE[zone][treatment])
        if get_double(model, name, "repair_time") < 0:
            raise PowerflowError(f"{name}: repair time must be positive (or negative to use global pole::repair_time")

    @classmethod
    def pole_diameter(cls, model:Any, name:str, height:float) -> float:
        """Diameter (in) at a height (ft), gridlabd `get_pole_diameter()`"""
        length = get_double(model, name, "pole_length")
        return (length - height)*(get_double(model, name, "ground_diameter") - get_double(model, name, "top_diameter"))/(length - get_double(model, name, "pole_depth"))
