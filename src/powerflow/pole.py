# pylint: disable=line-too-long
"""Class `pole`: wind and tilt loading, aging, failure, and repair of a
utility pole

Syntax
------

    object pole {
        configuration <pole_configuration>;
        install_year <integer>;
        tilt_angle <real> deg;
        tilt_direction <real> deg;
        weather <object>;              // wind_speed, wind_dir, wind_gust
        wind_speed <real> m/s;         // without weather
        wind_direction <real> deg;
        wind_gusts <real> m/s;
        repair_time <real> h;
        guy_height <real> ft;
    }

Outputs: `status` (`OK`, `FAILED`), `pole_stress` (pu), the moments
(ft*lb), `critical_wind_speed` (m/s), and `susceptibility`.

Description
-----------

A `pole` computes the loading of a utility pole of a `pole_configuration`,
as gridlabd's `pole` does (published, like it, without the properties of
its base class). Its height above the guy attachment is `pole_length -
pole_depth - guy_height`; its diameter there interpolates the top and
ground diameters; its resisting moment is `0.008186 *
strength_factor_250b_wood * fiber_strength * (D^3 - d^3)`, with `d` the
hollow diameter of an aged pole (`2 * age * degradation_rate * D /
ground_diameter`, the age in years from `install_year`).

At each time step (`precommit`) it reads the wind from `weather` (the
properties named by `powerflow::wind_speed_name`, `wind_dir_name`, and
`wind_gust_name`), updates the aging, repairs a failed pole once
`repair_time` has passed since it failed (tilt 0, installed in the
current year), and computes the pole's own moments: the wind pressure
`0.00256 (2.24 v)^2` psf times the pole's moment per unit wind pressure
(`h^2 (D + 2 D_top) / 72 * overload_factor_transverse_general`), and the
tilt moment of its weight (`material_density`). When the wind changed,
the pole was repaired, or no critical wind speed is known yet, it
recalculates after the solution (`postsync`): the total moment (pole,
wire, and equipment moments in x and y, the wire and equipment moments
being added by the objects mounted on the pole), `pole_stress` (total
over resisting moment), `susceptibility`, and `critical_wind_speed` (the
wind at which the resisting moment, with `wind_overdesign`, is reached);
a stress of 1 or more fails the pole, with a warning (or, when
`powerflow::stop_on_pole_failure` is true, a verbose message and a stop
of the run), and its repair time is an event.

When it initializes, a pole is expected to fail unless `configuration` is
a `pole_configuration`, to take `repair_time` from the configuration or
`powerflow::repair_time` when it is not positive (failing when neither
is positive), to bind the weather properties (warning for each missing
one, and when it overwrites a local value), to fail when `tilt_angle` is
not within 0 to 90 degrees or `tilt_direction` within 0 to 360 degrees,
and to warn when `install_year` is in the future.

Caveats
-------

- `pole_mount` is not ported, so the wire and equipment moments are 0
  unless set otherwise, and a failed pole does not change the network.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. `equipment_moment_x` and `equipment_moment_y` are the equipment
   moments; gridlabd publishes them at the addresses of `wire_moment_x`
   and `wire_moment_y`.
2. The pole's own moments (`pole_moment`, its wind moment) are computed
   at every time step; gridlabd computes them only when the wind changes
   and resets them to 0 otherwise, so a repair recalculates the stress
   without them.
3. A failed pole is repaired at its repair event (`repair_time` after the
   failure); gridlabd repairs it only after more than `repair_time`, so
   the event it asks for does not repair it.
4. An `install_year` after the current year is warned about; gridlabd
   compares the year with the clock timestamp, so it never warns.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/pole.cpp`, `pole.h`
"""

import math
from typing import Any

from ._base import PowerflowClass, prop, keywords
from ._common import TS_NEVER, TS_INVALID, isa, ref, g, msg, object_state, get_int, get_double, set_double, set_int

PS_OK, PS_FAILED = 0, 1
"""`status` values"""

COMMIT_OUTPUTS = ("equipment_moment_nowind", "pole_moment", "equipment_moment", "wire_weight", "wire_moment_x",
    "wire_moment_y", "wire_tension", "equipment_moment_x", "equipment_moment_y")
"""Accumulators reset at each time step (`reset_commit_accumulators()`)"""

def wind_gust_cdf(wind_ratio:float) -> float:
    """gridlabd `wind_gust_cdf()`: the chance a gust ratio is withstood"""
    x = math.log(wind_ratio)
    a1, a2, a3, a4, a5 = 0.31938153, -0.356563782, 1.781477937, -1.821255978, 1.330274429
    big_l = abs(x)
    k = 1.0/(1.0 + 0.2316419*big_l)
    w = 1.0/math.sqrt(2*3.1415)*math.exp(-big_l*big_l/2)*(a1*k + a2*k*k + a3*k**3 + a4*k**4 + a5*k**5)
    return 1 - w if x < 0 else w

class Pole(PowerflowClass):
    """Behavior of class `pole`"""

    NAME = "pole"
    TRL = 7 # TRL_PROTOTYPE
    PASSCONFIG = "PRETOPDOWN|POSTTOPDOWN|UNSAFE_OVERRIDE_OMIT|AUTOLOCK"
    EVENTS = ("init", "precommit", "presync", "postsync", "commit")
    PROPERTIES = (
        ("status", "enumeration", prop("pole status", "OK", keywords=keywords(("OK", PS_OK), ("FAILED", PS_FAILED)))),
        ("tilt_angle[deg]", "double", prop("tilt angle of pole from the centerline", "0.0 deg")),
        ("tilt_direction[deg]", "double", prop("tilt direction of pole", "0.0 deg")),
        ("weather", "object", prop("weather data")),
        ("configuration", "object", prop("configuration data", flags="REQUIRED")),
        ("install_year", "int32", prop("the year of pole was installed", flags="REQUIRED")),
        ("repair_time[h]", "double", prop("typical repair time after pole failure")),
        ("wind_speed[m/s]", "double", prop("local wind speed", "0 m/s")),
        ("wind_direction[deg]", "double", prop("local wind direction", "0 deg")),
        ("wind_gusts[m/s]", "double", prop("local wind gusts", "0 m/s")),
        ("pole_stress[pu]", "double", prop("ratio of actual stress to critical stress", flags="OUTPUT")),
        ("pole_stress_polynomial_a[ft*lb]", "double", prop("constant a of the pole stress polynomial function", flags="OUTPUT")),
        ("pole_stress_polynomial_b[ft*lb]", "double", prop("constant b of the pole stress polynomial function", flags="OUTPUT")),
        ("pole_stress_polynomial_c[ft*lb]", "double", prop("constant c of the pole stress polynomial function", flags="OUTPUT")),
        ("susceptibility[pu.s/m]", "double", prop("susceptibility of pole to wind stress (derivative of pole stress w.r.t wind speed)", flags="OUTPUT")),
        ("total_moment[ft*lb]", "double", prop("the total moment on the pole", flags="OUTPUT")),
        ("resisting_moment[ft*lb]", "double", prop("the resisting moment on the pole", flags="OUTPUT")),
        ("pole_moment[ft*lb]", "double", prop("the moment of the pole", flags="OUTPUT")),
        ("pole_moment_per_wind[ft*lb]", "double", prop("the moment of the pole without wind", flags="OUTPUT")),
        ("equipment_moment[ft*lb]", "double", prop("the moment of the equipment", flags="OUTPUT")),
        ("equipment_weight[ft*lb]", "double", prop("the moment of the equipment weight", flags="OUTPUT")),
        ("equipment_moment_nowind[ft*lb]", "double", prop("the moment of the equipment without wind", flags="OUTPUT")),
        ("critical_wind_speed[m/s]", "double", prop("wind speed at pole failure", flags="OUTPUT")),
        ("wire_weight[ft*lb]", "double", prop("wire moment due to conductor weight", flags="OUTPUT")),
        ("wire_moment_x[ft*lb]", "double", prop("wire moment in x-axis due to tension and wind load", flags="OUTPUT")),
        ("wire_moment_y[ft*lb]", "double", prop("wire moment in y-axis due to tension and wind load", flags="OUTPUT")),
        ("equipment_moment_x[ft*lb]", "double", prop("equipment moment in x-axis due to wind load", flags="OUTPUT")),
        ("equipment_moment_y[ft*lb]", "double", prop("equipment moment in y-axis due to wind load", flags="OUTPUT")),
        ("wire_tension[ft*lb]", "double", prop("wire moment due to conductor tension", flags="OUTPUT")),
        ("guy_height[ft]", "double", prop("guy wire attachment height", "0 ft")),
    )

    #
    # Geometry
    #
    @classmethod
    def height(cls, model:Any, name:str) -> float:
        """gridlabd `calc_height()`"""
        config = object_state(model, name)["config"]
        return get_double(model, config, "pole_length") - get_double(model, config, "pole_depth") - get_double(model, name, "guy_height")

    @classmethod
    def moment_per_wind(cls, model:Any, name:str) -> float:
        """gridlabd `calc_pole_moment_per_wind()`"""
        state = object_state(model, name)
        config, h = state["config"], state["height"]
        return h*h*(state["diameter"] + 2*get_double(model, config, "top_diameter"))/72.0*get_double(model, config, "overload_factor_transverse_general")

    @classmethod
    def resisting(cls, model:Any, name:str) -> float:
        """The resisting moment of the (aged) pole"""
        state = object_state(model, name)
        config = state["config"]
        return 0.008186*get_double(model, config, "strength_factor_250b_wood")*get_double(model, config, "fiber_strength")*(state["diameter"]**3 - state["hollow"]**3)

    #
    # Events
    #
    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool:
        """`pole::init()`"""
        # pylint: disable=too-many-branches,too-many-locals
        out = msg(model, name)
        config = ref(model, name, "configuration")
        if config is None or not isa(model, config, "pole_configuration"):
            out.error("configuration is not set to a pole_configuration object")
            return False
        state = object_state(model, name)
        state.update(config=config, refs={}, last_wind=0.0, down_time=TS_NEVER, hollow=0.0, recalc=False, wire_wind=0.0,
            wire_load_nowind=0.0, wire_moment_nowind=0.0, pole_moment_wind=0.0)
        if get_double(model, name, "repair_time") <= 0:
            if get_double(model, config, "repair_time") > 0:
                set_double(model, name, "repair_time", get_double(model, config, "repair_time"))
            elif float(g(model, "repair_time") or 0) > 0:
                set_double(model, name, "repair_time", float(g(model, "repair_time")))
            else:
                out.error("pole::default_repair_time must be positive")
                return False
        weather = ref(model, name, "weather")
        if weather is not None:
            for local, gname, what in (("wind_speed", "wind_speed_name", "speed"), ("wind_direction", "wind_dir_name", "direction"),
                    ("wind_gusts", "wind_gust_name", "gusts")):
                source = str(g(model, gname) or "")
                if model.objects[weather].oclass.find_property(source) is None:
                    out.warning(f"weather data does not include {source}, using local wind {what} data only")
                    continue
                if get_double(model, name, local) != 0:
                    out.warning(f"weather data will overwrite local wind {what} data")
                state["refs"][local] = (weather, source)
        tilt, direction = get_double(model, name, "tilt_angle"), get_double(model, name, "tilt_direction")
        if tilt < 0 or tilt > 90:
            out.error("pole tilt angle is not between and 0 and 90 degrees")
            return False
        if direction < 0 or direction >= 360:
            out.error("pole tilt direction is not between 0 and 360 degrees")
            return False
        state["height"] = cls.height(model, name)
        length = get_double(model, config, "pole_length") - get_double(model, config, "pole_depth")
        top, ground = get_double(model, config, "top_diameter"), get_double(model, config, "ground_diameter")
        state["diameter"] = top + state["height"]*(ground - top)/length
        set_double(model, name, "resisting_moment", cls.resisting(model, name))
        set_double(model, name, "pole_moment_per_wind", cls.moment_per_wind(model, name))
        if get_int(model, name, "install_year") > 1970 + int(t/86400/365.24):
            out.warning("pole install year in the future are assumed to be current time")
        return True

    @classmethod
    def precommit(cls, model:Any, name:str, t:int) -> int:
        """`pole::precommit()`: wind, aging, repair, and the pole's moments"""
        # pylint: disable=too-many-locals
        state = object_state(model, name)
        if "config" not in state:
            return TS_NEVER
        out = msg(model, name)
        config = state["config"]
        for prop_ in COMMIT_OUTPUTS:
            set_double(model, name, prop_, 0.0)
        state.update(wire_load_nowind=0.0, wire_moment_nowind=0.0, pole_moment_wind=0.0)
        for local, (weather, source) in state["refs"].items():
            set_double(model, name, local, get_double(model, weather, source))
        state["height"] = cls.height(model, name)
        age = 1970 + int(t/86400/365.24) - get_int(model, name, "install_year")
        rate = get_double(model, config, "degradation_rate")
        if age > 0 and rate > 0:
            state["hollow"] = 2.0*age*rate*state["diameter"]/get_double(model, config, "ground_diameter")
        resisting = cls.resisting(model, name)
        repaired = False
        if get_int(model, name, "status") == PS_FAILED and (t - state["down_time"])/3600.0 >= get_double(model, name, "repair_time"):
            out.verbose("pole repair time has arrived")
            set_double(model, name, "tilt_angle", 0.0)
            set_double(model, name, "tilt_direction", 0.0)
            model.objects[name]["status"] = "OK"
            set_int(model, name, "install_year", 1970 + int(t/86400/365.24))
            state["recalc"] = repaired = True
        wind = get_double(model, name, "wind_speed")
        if get_int(model, name, "status") == PS_OK:
            if resisting < 0:
                out.warning("pole has degraded past point of static failure")
                resisting = 0.0
            pressure = 0.00256*(2.24*wind)**2
            tilt = get_double(model, name, "tilt_angle")
            moment = 0.0
            if tilt > 0:
                d1 = get_double(model, config, "top_diameter")/12
                d0 = (state["diameter"] - state["hollow"])/12
                h = state["height"]
                moment = 0.125*get_double(model, config, "material_density")*math.pi*h*h*math.sin(tilt/180*math.pi)*((d0 + d1)**2/6 + d1*d1/3)
            set_double(model, name, "pole_moment", moment)
            per_wind = cls.moment_per_wind(model, name)
            set_double(model, name, "pole_moment_per_wind", per_wind)
            state["pole_moment_wind"] = pressure*per_wind if pressure > 0 else 0.0
            if repaired or state["last_wind"] != wind or get_double(model, name, "critical_wind_speed") == 0:
                state["last_wind"] = wind
                state["recalc"] = True
        set_double(model, name, "resisting_moment", resisting)
        return TS_NEVER

    @classmethod
    def presync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`pole::presync()`"""
        state = object_state(model, name)
        if state.get("recalc"):
            state["wire_wind"] = 0.0
        return TS_NEVER

    @classmethod
    def postsync(cls, model:Any, name:str, t:int) -> int:
        """`pole::postsync()`: stress, critical wind, and failure"""
        # pylint: disable=too-many-locals
        state = object_state(model, name)
        if "config" not in state:
            return TS_NEVER
        out = msg(model, name)
        get = lambda x: get_double(model, name, x) # pylint: disable=unnecessary-lambda-assignment
        repair = get("repair_time")
        if state["recalc"]:
            wind_dir, tilt_dir = get("wind_direction")*math.pi/180, get("tilt_direction")*math.pi/180
            pole_x = state["pole_moment_wind"]*math.cos(wind_dir) + get("pole_moment")*math.cos(tilt_dir)
            pole_y = state["pole_moment_wind"]*math.sin(wind_dir) + get("pole_moment")*math.sin(tilt_dir)
            x = get("wire_moment_x") + get("equipment_moment_x") + pole_x
            y = get("wire_moment_y") + get("equipment_moment_y") + pole_y
            total = math.sqrt(x*x + y*y)
            set_double(model, name, "total_moment", total)
            resisting = get("resisting_moment")
            stress = total/resisting if resisting > 0 else math.inf
            set_double(model, name, "pole_stress", stress)
            nowind = get("pole_moment_per_wind") + get("equipment_moment_nowind") + state["wire_moment_nowind"]
            wind = get("wind_speed")
            susceptibility = (math.cos(wind_dir) + math.sin(wind_dir))*nowind*(x + y)*(0.00256*2*2.24*wind*2.24)/total if wind > 0 and total > 0 else 0.0
            set_double(model, name, "susceptibility", susceptibility)
            effective = resisting*(1 + get_double(model, state["config"], "wind_overdesign"))
            weight = get("wire_weight") + get("equipment_weight") + get("pole_moment")
            try:
                failure_pressure = math.sqrt(effective*effective - weight*weight)/nowind
                critical = math.sqrt(failure_pressure/(0.00256*2.24*2.24))
            except (ValueError, ZeroDivisionError):
                critical = math.nan
            set_double(model, name, "critical_wind_speed", critical)
            gusts = get("wind_gusts")
            if gusts > 0 and critical > 0:
                out.verbose(f"chance_of_withstanding = {wind_gust_cdf(gusts/critical)*100:g} % (wind_gusts = {gusts:g} m/s)")
            failed = not stress < 1.0 # pylint: disable=unnecessary-negation # NaN fails, as gridlabd's `stress < 1 ? OK : FAILED`
            model.objects[name]["status"] = "FAILED" if failed else "OK"
            if failed:
                text = f"pole failed at {stress*100:.0f}% stress, time to repair is {repair:g} h"
                if g(model, "stop_on_pole_failure"):
                    out.verbose(text)
                else:
                    out.warning(text)
                state["down_time"] = t
            state["recalc"] = False
        if get_int(model, name, "status") == PS_FAILED:
            if g(model, "stop_on_pole_failure"):
                return TS_INVALID
            next_event = state["down_time"] + int(repair*3600)
            return TS_NEVER if t == next_event else next_event
        return TS_NEVER

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`pole::commit()`"""
        return TS_NEVER

__all__ = ["Pole", "wind_gust_cdf"]
