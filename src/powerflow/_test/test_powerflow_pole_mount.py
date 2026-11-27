"""Class `pole_mount`: registration, initialization, line and equipment
moments against an independent computation, the pole's totals, tilted
poles, failure opening the equipment, and moments at every time step"""
# pylint: disable=missing-function-docstring,line-too-long

import math

import numpy as np
import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model

VNOM = 7200
HEIGHTS = (28, 28, 28, 24)

def model(wind:float=10, pole:str="", line_mount:str="pole_spacing 300; direction 90;", equipment:str="height 25; offset 1; area 10; weight 500; direction 0;", meter:str="") -> str: # pylint: disable=too-many-arguments,too-many-positional-arguments
    head = f"object meter {{ measured_energy_delta_timestep {meter}; " if meter else "object node { "
    return f"""
object line_spacing {{ name ls; distance_AB 2.5; distance_BC 4.5; distance_AC 7; distance_AN 5.66; distance_BN 4.27; distance_CN 5; distance_AE {HEIGHTS[0]}; distance_BE {HEIGHTS[1]}; distance_CE {HEIGHTS[2]}; distance_NE {HEIGHTS[3]}; }}
object overhead_line_conductor {{ name oc; geometric_mean_radius 0.0244; resistance 0.306; diameter 0.721; weight 0.5; strength 100; }}
object overhead_line_conductor {{ name on; geometric_mean_radius 0.0244; resistance 0.306; diameter 0.5; weight 0.3; strength 80; }}
object line_configuration {{ name lc; conductor_A oc; conductor_B oc; conductor_C oc; conductor_N on; spacing ls; }}
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object overhead_line {{ name ol; phases ABCN; from n0; to n1; length 300; configuration lc; ice_thickness 0.25; }}
object overhead_line {{ name ol2; phases ABCN; from n0; to n1; length 300; configuration lc; }}
{head}name n1; phases ABCN; nominal_voltage {VNOM}; }}
object load {{ name ld; parent n1; phases ABCN; nominal_voltage {VNOM}; constant_power_A 100000; constant_power_B 100000; constant_power_C 100000; }}
object switch {{ name sw; phases ABCN; from n1; to n2; status CLOSED; }}
object node {{ name n2; phases ABCN; nominal_voltage {VNOM}; }}
object pole_configuration {{ name pc; }}
object pole {{ name p1; configuration pc; install_year 2000; wind_speed {wind}; {pole} }}
object pole_mount {{ name m1; parent p1; equipment ol; {line_mount} }}
object pole_mount {{ name m2; parent p1; equipment sw; {equipment} }}
"""

def config(m:Model) -> dict[str,float]:
    return {x: powerflow.get_double(m, "pc", x) for x in ("top_diameter", "ground_diameter", "pole_length", "pole_depth",
        "overload_factor_vertical", "overload_factor_transverse_wire", "overload_factor_transverse_general")}

def line_moments(m:Model, tilt:float=0.0) -> dict[str,float]: # pylint: disable=too-many-locals
    """Independent moments of the line mount (spacing 300 ft, ice 0.25 in)"""
    c = config(m)
    weights, diameters, strengths, ice, spacing = (0.5, 0.5, 0.5, 0.3), (0.721, 0.721, 0.721, 0.5), (100, 100, 100, 80), 0.25, 300
    d1, d0, h = c["top_diameter"]/12, c["ground_diameter"]/12, c["pole_length"] - c["pole_depth"]
    radius = [d0 - z*(d0 - d1)/h for z in HEIGHTS]
    loaded = [w + 0.39744*math.pi*(d + ice)*ice for w, d in zip(weights, diameters)]
    alpha = math.radians(tilt)
    weight = c["overload_factor_vertical"]*(sum(r*w for r, w in zip(radius, loaded))*math.cos(alpha) + sum(z*w for z, w in zip(HEIGHTS, loaded))*math.sin(alpha))*spacing/2
    widths = [d + 2*ice for d in diameters]
    nowind = spacing*math.cos(alpha)*c["overload_factor_transverse_wire"]*sum(z*w for z, w in zip(HEIGHTS, widths))/12
    tension = c["overload_factor_transverse_wire"]*math.cos(alpha)*sum(z*s for z, s in zip(HEIGHTS, strengths))
    return {"weight": weight, "nowind": nowind, "tension": tension, "mass": sum(weights)*spacing/2}

def test_registration():
    Model().read_glm("module powerflow;\n")
    pm = Class.find("pole_mount", module="powerflow")
    assert pm.trl == 7 and pm.parent is None
    assert pm.find_property("area").unit == "sf" and pm.find_property("pole_spacing").default == "0.0 ft"

@pytest.mark.parametrize("wind, wind_dir", [(10, 0), (30, 135)])
def test_moments(helpers, wind, wind_dir): # pylint: disable=too-many-locals
    """The line's and the equipment's moments added to the pole, and the
    pole's totals"""
    r = helpers.run(model(wind, pole=f"wind_direction {wind_dir};"))
    assert r.returncode == 0, r.stderr
    m = r.model
    c = config(m)
    get = lambda x: powerflow.get_double(m, "p1", x) # pylint: disable=unnecessary-lambda-assignment
    line = line_moments(m)
    pressure = 0.00256*(2.24*wind)**2
    line_wind = line["nowind"]*pressure*abs(math.sin(math.radians(wind_dir - 90)))
    assert powerflow.get_double(m, "m1", "weight") == pytest.approx(line["mass"])
    assert get("wire_weight") == pytest.approx(line["weight"]) and get("wire_tension") == pytest.approx(line["tension"])
    assert get("wire_moment_x") == pytest.approx(0, abs=1e-6) # upright: the weight acts in the mount's direction, 90 deg
    assert get("wire_moment_y") == pytest.approx(line["tension"] + line_wind + line["weight"])
    equip_weight = 500*1*c["overload_factor_vertical"]
    equip_nowind = 25*c["overload_factor_transverse_general"]*10
    assert get("equipment_weight") == pytest.approx(equip_weight) and get("equipment_moment_nowind") == pytest.approx(equip_nowind)
    ex = pressure*equip_nowind*math.cos(math.radians(wind_dir)) + equip_weight
    ey = pressure*equip_nowind*math.sin(math.radians(wind_dir))
    assert get("equipment_moment_x") == pytest.approx(ex) and get("equipment_moment_y") == pytest.approx(ey)
    pole_wind = pressure*get("pole_moment_per_wind")
    x = get("wire_moment_x") + ex + pole_wind*math.cos(math.radians(wind_dir))
    y = get("wire_moment_y") + ey + pole_wind*math.sin(math.radians(wind_dir))
    assert get("total_moment") == pytest.approx(math.hypot(x, y))
    assert get("pole_stress") == pytest.approx(get("total_moment")/get("resisting_moment"))
    assert powerflow.get_double(m, "m1", "wind_speed") == wind and powerflow.get_double(m, "m2", "wind_direction") == wind_dir

def test_tilted(helpers):
    """A tilted pole's line weight moment uses each phase's conductor"""
    m = helpers.run(model(pole="tilt_angle 10; tilt_direction 45;")).model
    line = line_moments(m, 10)
    assert powerflow.get_double(m, "p1", "wire_weight") == pytest.approx(line["weight"])
    assert powerflow.get_double(m, "p1", "wire_tension") == pytest.approx(line["tension"])

def test_every_step(helpers):
    """The moments are the pole's outputs at every time step, not only when
    it recalculates"""
    m = helpers.run(model(meter="3600"), stop="2020-01-01 03:00:00").model
    assert powerflow.get_double(m, "p1", "wire_tension") == pytest.approx(line_moments(m)["tension"])
    assert powerflow.get_double(m, "p1", "equipment_weight") == pytest.approx(500*config(m)["overload_factor_vertical"])

def test_failure(helpers):
    """A failed pole opens its equipment at once; the parallel line carries
    the load and the switch's node is taken out"""
    r = helpers.run(model(55))
    assert r.returncode == 0, r.stderr
    m = r.model
    assert m.get_property("p1", "status") == "FAILED"
    assert m.get_property("ol", "status") == "OPEN" and m.get_property("sw", "status") == "OPEN"
    assert abs(powerflow.get_complex(m, "ol", "current_in_A")) == 0 and abs(powerflow.get_complex(m, "ol2", "current_in_A")) > 0
    assert np.abs(helpers.voltages(m, "n1")).min() > 0 and np.abs(helpers.voltages(m, "n2")).max() == 0
    ok = helpers.run(model(10)).model
    assert ok.get_property("ol", "status") == "CLOSED" and ok.get_property("sw", "status") == "CLOSED"

def test_init(helpers):
    r = helpers.run(model().replace("object pole_mount { name m1; parent p1;", "object pole_mount { name m1; parent n1;"))
    assert any("pole_mount must have a pole as parent object" in x for x in helpers.errors(r)), r.stderr
    r = helpers.run(model().replace("equipment ol;", ""))
    assert any("equipment not specified" in x for x in helpers.errors(r)), r.stderr
    r = helpers.run(model().replace("equipment sw;", "equipment ld;"))
    assert any("equipment is not a powerflow link object" in x for x in helpers.warnings(r)), r.stderr
