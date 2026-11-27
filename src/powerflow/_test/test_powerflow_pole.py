"""Class `pole`: registration, globals, initialization, the moments and
stress against an independent computation, aging, weather, failure and
repair"""
# pylint: disable=missing-function-docstring,line-too-long

import math

import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model
from powerflow.pole import wind_gust_cdf

def glm(pole:str, config:str="", extra:str="") -> str:
    return f"""
object pole_configuration {{ name pc; {config} }}
object pole {{ name p1; configuration pc; install_year 2000; {pole} }}
{extra}"""

def expected(m:Model, wind:float, tilt:float, tilt_dir:float, wind_dir:float=0.0, hollow:float=0.0) -> dict[str,float]: # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    """Independent loading of the pole"""
    c = lambda x: powerflow.get_double(m, "pc", x) # pylint: disable=unnecessary-lambda-assignment
    h = c("pole_length") - c("pole_depth")
    d = c("ground_diameter")
    resisting = 0.008186*c("strength_factor_250b_wood")*c("fiber_strength")*(d**3 - hollow**3)
    per_wind = h*h*(d + 2*c("top_diameter"))/72*c("overload_factor_transverse_general")
    d0, d1 = (d - hollow)/12, c("top_diameter")/12
    tilt_moment = 0.125*c("material_density")*math.pi*h*h*math.sin(math.radians(tilt))*((d0 + d1)**2/6 + d1*d1/3)
    wind_moment = 0.00256*(2.24*wind)**2*per_wind
    x = wind_moment*math.cos(math.radians(wind_dir)) + tilt_moment*math.cos(math.radians(tilt_dir))
    y = wind_moment*math.sin(math.radians(wind_dir)) + tilt_moment*math.sin(math.radians(tilt_dir))
    total = math.hypot(x, y)
    effective = resisting*(1 + c("wind_overdesign"))
    critical = math.sqrt(math.sqrt(effective**2 - tilt_moment**2)/per_wind/(0.00256*2.24*2.24))
    return {"resisting_moment": resisting, "pole_moment_per_wind": per_wind, "pole_moment": tilt_moment,
        "total_moment": total, "pole_stress": total/resisting, "critical_wind_speed": critical}

def test_registration():
    m = Model()
    m.read_glm("module powerflow;\n")
    pole = Class.find("pole", module="powerflow")
    assert pole.trl == 7 and pole.parent is None and pole.find_property("phases") is None
    assert pole.find_property("status").default == "OK" and pole.find_property("install_year").has_flag("REQUIRED")
    assert m.globals.getvalue("powerflow::wind_speed_name") == "wind_speed" and m.globals.getvalue("powerflow::wind_dir_name") == "wind_dir"
    assert float(str(m.globals.getvalue("powerflow::repair_time")).split()[0]) == 24

@pytest.mark.parametrize("wind, tilt, tilt_dir, wind_dir", [(0, 5, 90, 0), (20, 0, 0, 0), (40, 10, 45, 120)])
def test_loading(helpers, wind, tilt, tilt_dir, wind_dir):
    r = helpers.run(glm(f"wind_speed {wind}; tilt_angle {tilt}; tilt_direction {tilt_dir}; wind_direction {wind_dir};"), lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    for prop, value in expected(m, wind, tilt, tilt_dir, wind_dir).items():
        assert powerflow.get_double(m, "p1", prop) == pytest.approx(value, rel=1e-9), prop
    assert m.get_property("p1", "status") == "OK" and powerflow.get_double(m, "p1", "repair_time") == 24
    assert (powerflow.get_double(m, "p1", "susceptibility") != 0) == (wind > 0)

def test_aging(helpers):
    """The hollow diameter of a pole 20 years old reduces its resisting
    moment"""
    m = helpers.run(glm("", "degradation_rate 0.01;"), lines=False).model
    hollow = 2*20*0.01
    assert powerflow.get_double(m, "p1", "resisting_moment") == pytest.approx(expected(m, 0, 0, 0, hollow=hollow)["resisting_moment"])

def test_failure_and_repair(helpers):
    """A pole beyond its strength fails, and is repaired (tilt 0, installed
    the current year) at its repair event"""
    model = glm("wind_speed 120; tilt_angle 5;")
    r = helpers.run(model, lines=False, stop="2020-01-01 12:00:00")
    m = r.model
    assert m.get_property("p1", "status") == "FAILED" and powerflow.get_double(m, "p1", "pole_stress") >= 1
    assert any("pole failed at" in x and "time to repair is 24 h" in x for x in helpers.warnings(r))
    m = helpers.run(model, lines=False, stop="2020-01-02 00:00:00").model
    assert m.get_property("p1", "install_year") == "2020" and powerflow.get_double(m, "p1", "tilt_angle") == 0

def test_stop_on_failure(helpers):
    r = helpers.run(glm("wind_speed 120;", extra="#set powerflow::stop_on_pole_failure=TRUE\n"), lines=False)
    assert r.returncode != 0 and any("object p1 stopped its clock" in x for x in helpers.errors(r)), r.stderr
    assert not helpers.warnings(r)

def test_weather(helpers):
    """Wind from a weather object, with warnings for missing and
    overwritten data"""
    r = helpers.run(glm("weather p0; wind_speed 5;", extra="object pole { name p0; configuration pc; install_year 2000; wind_speed 30; }\n"), lines=False)
    m = r.model
    assert powerflow.get_double(m, "p1", "wind_speed") == 30
    warnings = helpers.warnings(r)
    assert any("weather data does not include wind_dir, using local wind direction data only" in x for x in warnings)
    assert any("weather data will overwrite local wind speed data" in x for x in warnings)

def test_wind_gust_cdf():
    assert wind_gust_cdf(1.0) == pytest.approx(0.5, abs=1e-3)
    assert wind_gust_cdf(0.5) > 0.5 > wind_gust_cdf(2.0)

@pytest.mark.parametrize("pole, message", [
    ("tilt_angle 95;", "pole tilt angle is not between and 0 and 90 degrees"),
    ("tilt_direction 360;", "pole tilt direction is not between 0 and 360 degrees"),
    ("install_year 2050;", None),
])
def test_init(helpers, pole, message):
    r = helpers.run(glm(pole), lines=False)
    if message:
        assert any(message in x for x in helpers.errors(r)), r.stderr
    else:
        assert any("pole install year in the future are assumed to be current time" in x for x in helpers.warnings(r))

def test_configuration(helpers):
    r = helpers.run(glm("").replace("configuration pc;", "configuration p0;") + "object pole { name p0; configuration pc; install_year 2000; }\n", lines=False)
    assert any("configuration is not set to a pole_configuration object" in x for x in helpers.errors(r)), r.stderr
