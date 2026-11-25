"""Event handlers that stand in for the solar classes of the ported
autotests (see `data/README.md`)

- `insolation()` is the `on_sync` handler of the `solar` class of
  `data/generators.glm`. It sets `Insolation` as the gridlabd `generators`
  module's `solar` object does (`module/generators/solar.cpp`): with the
  climate function `calc_solar_ideal_shading_position_radians` when
  `orientation` is `DEFAULT`, else with
  `calculate_solar_radiation_shading_position_radians` (`SOLAR_TILT_MODEL
  DEFAULT`, azimuth corrected to the south) or
  `calculate_solpos_radiation_shading_position_radians` (`SOLPOS`), at the
  object's latitude and longitude; negative values are 0.
- `opt_init()`, `opt_presync()`, and `opt_sync()` are the intrinsic C++
  functions of the `solar` class of gridlabd's `test_solar_opt.glm`,
  written in Python.
"""

import math
import weakref

import climate
from arras.runner import Runner

_STATE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()

def _number(model, name, prop, default=0.0):
    text = model.get_property(name, prop)
    if text in (None, ""):
        return default
    return float(str(text).split()[0])

def _weather(model, name):
    weather = model.get_property(name, "weather")
    if weather:
        return weather
    return next(x for x in model.objects if model.objects[x].oclass.name == "climate")

def insolation(name, t): # pylint: disable=unused-argument
    """Set `Insolation` from the climate object"""
    model = Runner.current().model
    weather = _weather(model, name)
    functions = model.objects[weather].oclass
    tilt = math.radians(_number(model, name, "tilt_angle"))
    azimuth = _number(model, name, "orientation_azimuth")
    latitude = float(model.get_property(name, "latitude"))
    longitude = float(model.get_property(name, "longitude"))
    shading = _number(model, name, "shading_factor", 1.0) if model.objects[name].get("shading_factor") else 1.0
    if model.get_property(name, "orientation") in ("DEFAULT", "0"):
        value = functions.get_function("calc_solar_ideal_shading_position_radians")(
            model, weather, tilt, latitude, longitude, shading)
    elif model.get_property(name, "SOLAR_TILT_MODEL") in ("SOLPOS", "1"):
        value = functions.get_function("calculate_solpos_radiation_shading_position_radians")(
            model, weather, tilt, math.radians(azimuth), latitude, longitude, shading)
    else:
        if latitude > 0:
            corrected = 180.0 - azimuth
        elif 0.0 <= azimuth <= 180.0:
            corrected = azimuth
        elif azimuth == 360.0:
            corrected = 0.0
        else:
            corrected = azimuth - 360.0
        value = functions.get_function("calculate_solar_radiation_shading_position_radians")(
            model, weather, tilt, math.radians(corrected), latitude, longitude, shading)
    model.set_property(name, "Insolation", max(value, 0.0))

def opt_init(name, t): # pylint: disable=unused-argument
    """`intrinsic init`: default efficiency, checks"""
    runner = Runner.current()
    model = runner.model
    efficiency = _number(model, name, "efficiency")
    if efficiency == 0:
        model.set_property(name, "efficiency", 0.85)
    elif efficiency < 0:
        runner.error("efficiency must be positive")
        return False
    if _number(model, name, "area") <= 0:
        runner.error("area must be positive")
        return False
    return True

def opt_presync(name, t):
    """`intrinsic presync`: energy += power*(t1-t0)/3600/1000"""
    model = Runner.current().model
    last = _STATE.setdefault(model, {}).get(name, t)
    energy = _number(model, name, "energy") + _number(model, name, "power")*(t-last)/3600.0/1000
    model.set_property(name, "energy", energy)
    _STATE[model][name] = t
    return None

def opt_sync(name, t): # pylint: disable=unused-argument
    """`intrinsic sync`: power from the solar flux (`FIXED`) or the direct
    irradiance (`TRACKING`)"""
    model = Runner.current().model
    weather = model.get_property(name, "weather")
    if model.get_property(name, "type") in ("FIXED", "0"):
        spec = model.objects[name].oclass.find_property("orientation")
        key = model.get_property(name, "orientation") or "0"
        orientation = spec.keywords.get(key, None)
        orientation = int(key) if orientation is None else orientation
        solar = climate.solar_flux(model, weather)[orientation]
    else:
        solar = _number(model, weather, "solar_direct")
    model.set_property(name, "power", solar*_number(model, name, "area")/1000*_number(model, name, "efficiency"))
    return None
