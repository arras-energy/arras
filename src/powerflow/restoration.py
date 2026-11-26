# pylint: disable=line-too-long
"""Class `restoration`: reconfiguration of the network after a fault

Syntax
------

    object restoration {
        reconfig_attempts <integer>;
        reconfig_iteration_limit <integer>;
        source_vertex <object>;
        faulted_section <object>;
        feeder_power_limit "<VA>[,...]";
        feeder_power_links "<link>[,...]";
        feeder_vertex_list "<object>[,...]";
        microgrid_power_limit "<complex VA>[,...]";
        microgrid_power_links "<link>[,...]";
        microgrid_vertex_list "<object>[,...]";
        lower_voltage_limit <real> pu;
        upper_voltage_limit <real> pu;
        output_filename "<file>";
        generate_all_scenarios {TRUE,FALSE};
    }

Description
-----------

gridlabd's `fault_check` calls the `restoration` object, after a fault, to
find switch operations that restore service within feeder and microgrid
power limits and voltage limits. When it initializes, it is expected to:

1. fail when the solver method is `FD_XB`, `FD_BX`, or `DC` (NR and FBS,
   which is solved with NR, are accepted);
2. fail when it is not the model's first `restoration` object (one per
   model);
3. fail when `reconfig_attempts` is 0, and warn when
   `reconfig_iteration_limit` is 0;
4. parse the comma-separated lists, warning for each one that is empty,
   and fail when the feeder limits, feeder vertices, and feeder links (or
   the microgrid limits, vertices, and links) are not as many, or when a
   link of the lists is not a powerflow link;
5. fail when `upper_voltage_limit` is not above `lower_voltage_limit`;
6. create `output_filename` empty when it is set.

The defaults are those gridlabd's `create()` sets: 20 attempts, 50
iterations, voltage limits 0.95 and 1.05 pu.

Caveats
-------

- `fault_check` is not ported, so restoration never runs; only the
  initialization is implemented.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. FBS is accepted (it is solved with NR); gridlabd accepts only NR.
2. A name in the object lists that is not an object fails with "not
   found"; gridlabd stores a null object and fails when it looks up the
   link's power function.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/restoration.cpp`,
  `restoration.h`
"""

from typing import Any

from ._base import prop
from ._common import (SM_NR, SM_FBS, g, get_double, get_int, get_text, isa, objects_of, gl_warning,
    text_to_complex, object_state, PowerflowError)
from .powerflow_library import LibraryObject

TRL_PROTOTYPE = 7
"""Technology readiness level `TRL_PROTOTYPE`"""

def _items(text:str) -> list[str]:
    """Items of a comma-separated list (none for an empty text)"""
    text = (text or "").strip().strip('"')
    return [] if text == "" else [x.strip() for x in text.split(",")]

class Restoration(LibraryObject):
    """Behavior of class `restoration`"""

    NAME = "restoration"
    TRL = TRL_PROTOTYPE
    PROPERTIES = (
        ("reconfig_attempts", "int32", prop("Number of reconfigurations/timestep to try before giving up", "20")),
        ("reconfig_iteration_limit", "int32", prop("Number of iterations to let PF go before flagging this as a bad reconfiguration", "50")),
        ("source_vertex", "object", prop("Source vertex object for reconfiguration")),
        ("faulted_section", "object", prop("Faulted section for reconfiguration")),
        ("feeder_power_limit", "char1024", prop("Comma-separated power limit (VA) for feeders during reconfiguration")),
        ("feeder_power_links", "char1024", prop("Comma-separated list of link-based objects for monitoring power through")),
        ("feeder_vertex_list", "char1024", prop("Comma-separated object list that defines the feeder vertices")),
        ("microgrid_power_limit", "char1024", prop("Comma-separated power limit (complex VA) for microgrids during reconfiguration")),
        ("microgrid_power_links", "char1024", prop("Comma-separated list of link-based objects for monitoring power through")),
        ("microgrid_vertex_list", "char1024", prop("Comma-separated object list that defines the microgrid vertices")),
        ("lower_voltage_limit[pu]", "double", prop("Lower voltage limit for the reconfiguration validity checks - per unit", "0.95 pu")),
        ("upper_voltage_limit[pu]", "double", prop("Upper voltage limit for the reconfiguration validity checks - per unit", "1.05 pu")),
        ("output_filename", "char1024", prop("Output text file name to describe final or attempted switching operations")),
        ("generate_all_scenarios", "bool", prop("Flag to determine if restoration reconfiguration and continues, or explores the full space", "FALSE")),
    )

    @classmethod
    def check(cls, model:Any, name:str) -> None:
        # pylint: disable=too-many-branches
        if g(model, "solver_method") not in (SM_NR, SM_FBS):
            raise PowerflowError("Restoration control is only valid for the Newton-Raphson solver at this time.")
        if objects_of(model, "restoration")[0] != name:
            raise PowerflowError("Only one restoration object is permitted per model file")
        if get_int(model, name, "reconfig_attempts") == 0:
            raise PowerflowError("Infinite reconfigurations set.")
        if get_int(model, name, "reconfig_iteration_limit") == 0:
            gl_warning("Infinite reconfiguration iterations set.")
        for kind in ("feeder", "microgrid"):
            limits = _items(get_text(model, name, f"{kind}_power_limit"))
            vertices = _items(get_text(model, name, f"{kind}_vertex_list"))
            links = _items(get_text(model, name, f"{kind}_power_links"))
            label = "complex" if kind == "microgrid" else "double"
            if not limits:
                gl_warning(f"restoration: Attempt to parse {label} CSV array resulted in an empty array - check your inputs")
            for items in (vertices, links):
                if not items:
                    gl_warning("restoration: Attempt to parse object CSV array resulted in an empty array - check your inputs")
            if len(vertices) != len(limits):
                raise PowerflowError(f"restoration: The number of {kind} limits and {kind} vertices must be the same!")
            if len(links) != len(limits):
                raise PowerflowError(f"restoration: The number of {kind} links and {kind} vertices must be the same!")
            for item in vertices + links:
                if item not in model.objects:
                    raise PowerflowError(f"restoration: object {item} of the {kind} lists is not found")
            for link in links:
                if not isa(model, link, "link"):
                    raise PowerflowError(f"Restoration: failed to find power calculation function for link:{link}")
            object_state(model, name)[f"{kind}_limits"] = [text_to_complex(x) for x in limits]
        if get_double(model, name, "upper_voltage_limit") <= get_double(model, name, "lower_voltage_limit"):
            raise PowerflowError("restoration: the upper and lower voltage limits are either equal, or backwards")
        filename = get_text(model, name, "output_filename").strip().strip('"')
        if filename:
            with open(filename, "wt", encoding="utf-8"):
                pass
