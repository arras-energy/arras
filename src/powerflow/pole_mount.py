# pylint: disable=line-too-long
"""Class `pole_mount`: a line or piece of equipment mounted on a pole

Syntax
------

    object pole_mount {
        parent <pole>;
        equipment <link>;
        pole_spacing <real> ft;     // overhead lines
        height <real> ft;           // other equipment
        offset <real> ft;
        direction <real> deg;
        area <real> sf;
        weight <real> lb;
    }

Outputs: `wind_speed` (m/s) and `wind_direction` (deg), copied from the
pole.

Description
-----------

A `pole_mount` adds the loading of its `equipment` to its parent `pole`,
and opens the equipment while the pole is failed, as gridlabd's
`pole_mount` does (published, like it, without the properties of its base
class).

When it initializes, it computes the moments of its equipment per unit
wind pressure and of its weight, with the pole's tilt `alpha`:

- for an `overhead_line`, from its configuration's conductors (`weight`,
  `diameter`, `strength`), spacing (heights `distance_XE`), and the line's
  `ice_thickness`, over half `pole_spacing` on each side: the weight
  moment of the conductors and ice (`overload_factor_vertical`, with each
  conductor at the pole radius at its height, and the conductor heights
  above the guy when tilted), the transverse wind load and moment
  (`overload_factor_transverse_wire`), and the tension moment of the
  conductor strengths;
- for other equipment, from its `height`, `offset`, `area`, and `weight`:
  the weight moment at the offset (`overload_factor_vertical`) and the
  wind moment (`overload_factor_transverse_general`).

At each time step (`precommit`), and before each solution (`presync`), it
closes the equipment (`status`) when the pole is `OK` and opens it when
the pole is `FAILED`. In the sync pass
it copies the pole's wind and adds, once per time step, its moments to
the pole: a line's wind moment (`wind_pressure * moment *
|sin(wind - direction)|`) and tension at its `direction`, a piece of
equipment's wind moment at the wind direction, and the weight moment at
the pole's tilt direction (or the mount's direction when the pole is
upright).

When it initializes, a pole mount is expected to fail unless its parent
is a `pole` and `equipment` is set, and to warn when the equipment is not
a powerflow link.

Caveats
-------

- Opening equipment that leaves nodes without a source fails the run (no
  swing bus), as gridlabd's NR fails without `fault_check`; a switching
  device whose `to` node has no other link takes that node out instead.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The weight moment of a line on a tilted pole uses each phase's
   conductor; gridlabd uses the phase A conductor for all four.
2. The moments are added to the pole at every time step, so the pole's
   wire and equipment outputs are those of the step; gridlabd adds them
   only when the pole recalculates (a wind change), so the outputs are 0
   at the other steps, and `equipment_weight`, which the pole does not
   reset, grows at each recalculation.
3. Only an `overhead_line` is loaded as a line (other links as
   equipment), and a line without a configuration, spacing, or conductor
   is an error; gridlabd loads any `line` as an overhead line and does not
   check them.
4. The equipment also follows the pole before each solution, so it opens
   in the pass the failed pole asks for (see `powerflow.pole`); gridlabd
   follows the pole only at the next time step.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/pole_mount.cpp`,
  `pole_mount.h`
"""

import math
from typing import Any

from ._base import PowerflowClass, prop
from ._common import TS_NEVER, LS_OPEN, isa, ref, msg, object_state, get_int, get_double, set_double, PowerflowError
from .pole import PS_OK, PS_FAILED

class PoleMount(PowerflowClass):
    """Behavior of class `pole_mount`"""

    NAME = "pole_mount"
    TRL = 7 # TRL_PROTOTYPE
    PASSCONFIG = "PRETOPDOWN|BOTTOMUP|UNSAFE_OVERRIDE_OMIT|AUTOLOCK"
    EVENTS = ("init", "precommit", "presync", "sync")
    PROPERTIES = (
        ("equipment", "object", prop("powerflow link object id")),
        ("height[ft]", "double", prop("height above ground at which equipment is mounted", "0.0 ft")),
        ("offset[ft]", "double", prop("distance from pole centerline at which equipment is mounted", "0.0 ft")),
        ("direction[deg]", "double", prop("direction from pole centerline at which equipment is mounted", "0.0 deg")),
        ("area[sf]", "double", prop("cross sectional area of equipment", "0.0 sf")),
        ("weight[lb]", "double", prop("weight of equipment mounted", "0.0 lb")),
        ("pole_spacing[ft]", "double", prop("Mean spacing between poles adjacent", "0.0 ft")),
        ("wind_speed[m/s]", "double", prop("local wind speed", "0 m/s")),
        ("wind_direction[deg]", "double", prop("local wind direction", "0 deg")),
    )

    #
    # Initialization
    #
    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`pole_mount::init()`"""
        out = msg(model, name)
        pole = ref(model, name, "parent")
        if pole is None or not isa(model, pole, "pole"):
            out.error("pole_mount must have a pole as parent object")
            return False
        if "config" not in object_state(model, pole):
            return 2 # defer until the pole has initialized
        equipment = ref(model, name, "equipment")
        if equipment is None:
            out.error("equipment not specified")
            return False
        is_line = False
        if not isa(model, equipment, "link"):
            out.warning("equipment is not a powerflow link object")
        else:
            is_line = isa(model, equipment, "overhead_line")
        state = object_state(model, name)
        state.update(pole=pole, equipment=equipment, is_line=is_line, added=None)
        try:
            if is_line:
                cls.init_line(model, name)
            else:
                cls.init_equipment(model, name)
        except PowerflowError as err:
            out.error(str(err))
            return False
        return True

    @classmethod
    def init_line(cls, model:Any, name:str) -> None:
        """The moments of an overhead line"""
        # pylint: disable=too-many-locals
        state = object_state(model, name)
        pole, line = state["pole"], state["equipment"]
        pconfig = object_state(model, pole)["config"]
        config = ref(model, line, "configuration")
        spacing = ref(model, config, "spacing") if config else None
        if config is None or spacing is None:
            raise PowerflowError(f"overhead_line {line} has no line configuration or spacing")
        conductors = [ref(model, config, f"conductor_{x}") for x in "ABCN"]
        heights = [get_double(model, spacing, f"distance_{x}E") for x in "ABCN"]
        ice = get_double(model, line, "ice_thickness")
        weights = [get_double(model, c, "weight") if c else 0.0 for c in conductors]
        diameters = [get_double(model, c, "diameter") if c else None for c in conductors]
        strengths = [get_double(model, c, "strength") if c else 0.0 for c in conductors]
        alpha = get_double(model, pole, "tilt_angle")*math.pi/180
        guy = get_double(model, pole, "guy_height")
        c = lambda x: get_double(model, pconfig, x) # pylint: disable=unnecessary-lambda-assignment
        d1, d0 = c("top_diameter")/12, c("ground_diameter")/12
        h = c("pole_length") - c("pole_depth")
        radius = [d0 - z*(d0 - d1)/h for z in heights]
        spacing_half = get_double(model, name, "pole_spacing")/2
        set_double(model, name, "weight", sum(weights)*spacing_half)
        loaded = [(w + 0.39744*math.pi*(d + ice)*ice) if d is not None else 0.0 for w, d in zip(weights, diameters)]
        if alpha == 0:
            moment_weight = c("overload_factor_vertical")*sum(r*w for r, w in zip(radius, loaded))*spacing_half
        else:
            moment_weight = c("overload_factor_vertical")*(sum(r*w for r, w in zip(radius, loaded))*math.cos(alpha)
                + sum((z - guy)*w for z, w in zip(heights, loaded))*math.sin(alpha))*spacing_half
        widths = [(d + 2*ice) if d is not None else 0.0 for d in diameters]
        spacing_full = get_double(model, name, "pole_spacing")
        state["load_nowind"] = sum(widths)/12*spacing_full
        state["moment_nowind"] = spacing_full*math.cos(alpha)*c("overload_factor_transverse_wire")*sum((z - guy)*w for z, w in zip(heights, widths))/12
        state["tension"] = c("overload_factor_transverse_wire")*math.cos(alpha)*sum((z - guy)*s for z, s in zip(heights, strengths))
        state["moment_weight"] = moment_weight

    @classmethod
    def init_equipment(cls, model:Any, name:str) -> None:
        """The moments of a piece of equipment"""
        state = object_state(model, name)
        pole = state["pole"]
        pconfig = object_state(model, pole)["config"]
        alpha = get_double(model, pole, "tilt_angle")*math.pi/180
        above = get_double(model, name, "height") - get_double(model, pole, "guy_height")
        offset = above*math.sin(alpha) + get_double(model, name, "offset")*math.cos(alpha)
        state["moment_weight"] = get_double(model, name, "weight")*offset*get_double(model, pconfig, "overload_factor_vertical")
        state["load_nowind"] = get_double(model, name, "area")*math.cos(alpha)
        state["moment_nowind"] = above*get_double(model, pconfig, "overload_factor_transverse_general")*state["load_nowind"]

    #
    # Events
    #
    @classmethod
    def precommit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`pole_mount::precommit()`: the equipment follows the pole"""
        state = object_state(model, name)
        if "pole" not in state:
            return TS_NEVER
        cls.follow(model, name)
        return TS_NEVER

    @classmethod
    def follow(cls, model:Any, name:str) -> None:
        """Close the equipment when the pole is `OK`, open it when the pole
        is `FAILED`"""
        state = object_state(model, name)
        status = get_int(model, state["pole"], "status")
        equipment = state["equipment"]
        closed = get_int(model, equipment, "status") != LS_OPEN
        if status == PS_OK and not closed:
            model.objects[equipment]["status"] = "CLOSED"
            msg(model, name).verbose("equipment status is now CLOSED")
        elif status == PS_FAILED and closed:
            model.objects[equipment]["status"] = "OPEN"
            msg(model, name).verbose("equipment status is now OPEN")

    @classmethod
    def presync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`pole_mount::presync()`: the pole's wind, and the equipment
        following the pole"""
        state = object_state(model, name)
        if "pole" in state:
            cls.follow(model, name)
            for prop_ in ("wind_speed", "wind_direction"):
                set_double(model, name, prop_, get_double(model, state["pole"], prop_))
        return TS_NEVER

    @classmethod
    def add(cls, model:Any, pole:str, prop_:str, value:float) -> None:
        """Add to one of the pole's accumulators (a property or its state)"""
        pstate = object_state(model, pole)
        if prop_ in pstate:
            pstate[prop_] += value
        else:
            set_double(model, pole, prop_, get_double(model, pole, prop_) + value)

    @classmethod
    def sync(cls, model:Any, name:str, t:int) -> int:
        """`pole_mount::sync()`: the moments added to the pole, once per
        time step"""
        # pylint: disable=too-many-locals
        state = object_state(model, name)
        if "pole" not in state or state["added"] == t:
            return TS_NEVER
        state["added"] = t
        pole = state["pole"]
        alpha = get_double(model, pole, "tilt_angle")*math.pi/180
        beta = get_double(model, pole, "tilt_direction")*math.pi/180
        theta = get_double(model, name, "direction")*math.pi/180
        wind, wind_dir = get_double(model, name, "wind_speed"), get_double(model, name, "wind_direction")
        pressure = 0.00256*(2.24*wind)**2
        weight_dir = beta if alpha > 0 else theta
        if state["is_line"]:
            wind_moment = state["moment_nowind"]*pressure*abs(math.sin((wind_dir - get_double(model, name, "direction"))*math.pi/180))
            for prop_, value in (("wire_wind", wind_moment), ("wire_load_nowind", state["load_nowind"]), ("wire_weight", state["moment_weight"]),
                    ("wire_moment_nowind", state["moment_nowind"]), ("wire_tension", state["tension"])):
                cls.add(model, pole, prop_, value)
            x = (state["tension"] + wind_moment)*math.cos(theta) + state["moment_weight"]*math.cos(weight_dir)
            y = (state["tension"] + wind_moment)*math.sin(theta) + state["moment_weight"]*math.sin(weight_dir)
            cls.add(model, pole, "wire_moment_x", x)
            cls.add(model, pole, "wire_moment_y", y)
        else:
            cls.add(model, pole, "equipment_moment_nowind", state["moment_nowind"])
            wind_moment = pressure*state["moment_nowind"]
            x = wind_moment*math.cos(wind_dir*math.pi/180) + state["moment_weight"]*math.cos(weight_dir)
            y = wind_moment*math.sin(wind_dir*math.pi/180) + state["moment_weight"]*math.sin(weight_dir)
            cls.add(model, pole, "equipment_weight", state["moment_weight"])
            cls.add(model, pole, "equipment_moment_x", x)
            cls.add(model, pole, "equipment_moment_y", y)
        return TS_NEVER

__all__ = ["PoleMount"]
