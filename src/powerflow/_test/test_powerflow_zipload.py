"""Classes `zipload`, `triplex_zipload`, and `pqload`: registration,
schedules, weather inputs, load data, and the loads they produce"""
# pylint: disable=missing-function-docstring,line-too-long

import cmath
import math

import numpy as np
import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model
from powerflow.zipload import ZipLoad, build_schedule
from powerflow._common import PowerflowError

VNOM = 2401.7771
STUB = "class weather_stub { double temperature[degF]; double solar_flux[W/sf]; double wind_speed[mph]; double rainfall[in/h]; double humidity[%]; }\n"

def feeder(cls:str, extra:str, tail:str="") -> str:
    return f"""{STUB}
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object test_line {{ name l01; phases ABCN; from n0; to n1; length 2000; }}
object {cls} {{ name n1; phases ABCN; nominal_voltage {VNOM}; {extra} }}
{tail}"""

def test_registration():
    Model().read_glm("module powerflow;\n")
    zip_ = Class.find("zipload", module="powerflow")
    assert zip_.parent.name == "load" and zip_.trl == 7
    assert zip_.find_property("Theat").default == "60 degF" and zip_.find_property("schedule").default == "* * * 1.0;"
    assert zip_.find_property("Qi_S").unit == "m^2" and zip_.find_property("scalar").unit == "pu.W"
    assert Class.find("triplex_zipload", module="powerflow").parent.name == "triplex_load"
    pq = Class.find("pqload", module="powerflow")
    assert pq.parent.name == "load" and pq.find_property("Zq_T").unit == "F/degF" and pq.find_property("T_nominal").default == "-459.67 degF"

def test_schedule():
    scale = build_schedule("* * * 1.0; 1-12 2-6 9-17 2.0; 7 1 22-2 3.0;")
    assert scale[0][0][0] == 1.0 and scale[5][1][8] == 2.0 and scale[5][1][17] == 1.0
    assert scale[6][0][21] == 3.0 and scale[6][0][0] == 3.0 and scale[6][0][1] == 3.0 and scale[6][0][2] == 1.0
    assert build_schedule("1,3 * 9-17 2.0;")[2][3][10] == 2.0
    with pytest.raises(PowerflowError, match="invalid hour"):
        build_schedule("* * 25 1.0;")
    with pytest.raises(PowerflowError, match="is not valid"):
        build_schedule("* * x 1.0;")

def test_zipload_constant(helpers):
    """Constant terms only: a third of each part on each phase, the same
    solution as the equivalent load"""
    r = helpers.run(feeder("zipload", "Pp 3000000; Qp 600000; Pz 300000; Qz 60000; Pi 300000; Qi 60000;"))
    assert r.returncode == 0, r.stderr
    m = r.model
    assert powerflow.get_complex(m, "n1", "P") == pytest.approx(1e6+2e5j)
    assert powerflow.get_complex(m, "n1", "constant_power_A") == pytest.approx(1e6+2e5j)
    zload = (VNOM**2/(1e5+2e4j)).conjugate()
    assert powerflow.get_complex(m, "n1", "constant_impedance_B") == pytest.approx(zload)
    same = helpers.run(feeder("load", " ".join(f"constant_power_{x} 1000000+200000j; constant_impedance_{x} {zload.real}{zload.imag:+}j; constant_current_{x} {cmath.rect(math.hypot(1e5, 2e4)/VNOM, -math.atan2(2e4, 1e5) + (0, -2*math.pi/3, 2*math.pi/3)[k])};".replace("(", "").replace(")", "") for k, x in enumerate("ABC"))))
    assert np.max(np.abs(helpers.voltages(m, "n1") - helpers.voltages(same.model, "n1"))) < 1e-3

def test_zipload_schedule_and_weather(helpers):
    """Heating degrees below Theat and the schedule value of the hour (an
    hourly meter interval makes the clock stop at each hour)"""
    glm = feeder("zipload", "weather w; Pp_H 30000; Pp 0; schedule \"* * * 0.5; * * 1 2.0;\";", "object weather_stub { name w; temperature 50; solar_flux 0; wind_speed 0; rainfall 0; humidity 50; }").replace("object node { name n0;", "object meter { measured_energy_delta_timestep 3600; name n0;")
    r = helpers.run(glm)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert powerflow.get_double(m, "n1", "H") == 10 and powerflow.get_double(m, "n1", "C") == 0
    assert powerflow.get_complex(m, "n1", "P") == pytest.approx(30000*10*2.0/3)
    later = helpers.run(glm, stop="2020-01-01 05:00:00")
    assert powerflow.get_complex(later.model, "n1", "P") == pytest.approx(30000*10*0.5/3)

def test_voltage_check(helpers):
    """No base power on a phase whose voltage is out of the deviation"""
    m = helpers.run(feeder("zipload", "Pp 3000;")).model
    m.set_property("n1", "voltage_B", "1000+0j")
    ZipLoad.before_solve(m, "n1", 1577836800)
    assert powerflow.get_double(m, "n1", "base_power_A") == pytest.approx(1000)
    assert powerflow.get_double(m, "n1", "base_power_B") == 0

def test_missing_weather_property(helpers):
    glm = feeder("zipload", "weather w; Pp 3000;", "object weather_stub { name w; }").replace("double rainfall[in/h]; ", "")
    r = helpers.run(glm)
    assert any("unable to find 'rainfall' property in weather object" in x for x in helpers.errors(r)), r.stderr

def test_load_data(helpers, tmp_path):
    (tmp_path / "loads.csv").write_text("geocode,load_class,load_type,Theat,Tcool,Pz_H,Pz_C,Pz_S,Pz_W,Pz_R,Pz,Qz_H,Qz_C,Qz_S,Qz_W,Qz_R,Qz,Pi_H,Pi_C,Pi_S,Pi_W,Pi_R,Pi,Qi_H,Qi_C,Qi_S,Qi_W,Qi_R,Qi,Pp_H,Pp_C,Pp_S,Pp_W,Pp_R,Pp,Qp_H,Qp_C,Qp_S,Qp_W,Qp_R,Qp,schedule\n"
        ",R,house,55,75,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,6000,0,0,0,0,0,0,* * * 1.0;\n")
    r = helpers.run(feeder("zipload", "load_class R; load_type house;"), module="zipload_data \"loads.csv\"; geocode_find -1;")
    assert r.returncode == 0, r.stderr
    m = r.model
    assert powerflow.get_double(m, "n1", "Theat") == 55 and powerflow.get_double(m, "n1", "Pp") == 6000
    assert powerflow.get_complex(m, "n1", "P") == pytest.approx(2000)
    missing = helpers.run(feeder("zipload", "load_class C; load_type house;"), module="zipload_data \"loads.csv\"; geocode_find -1;")
    assert any("no load data for geocode '', load_class 'C', load_type 'house'" in x for x in helpers.errors(missing)), missing.stderr

def test_triplex_zipload(helpers):
    """The whole load on 240 V, the schedule divided by sqrt(3)"""
    glm = f"""
object triplex_node {{ name t0; phases AS; nominal_voltage 120; bustype SWING; }}
object triplex_zipload {{ name t1; phases AS; parent t0; Pp 3000; Pz 1000; }}
"""
    r = helpers.run(glm, lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert powerflow.get_double(m, "t1", "base_power_12") == pytest.approx(4000/math.sqrt(3))
    assert powerflow.get_double(m, "t1", "base_power_1") == 0
    assert powerflow.get_complex(m, "t1", "constant_power_12") == pytest.approx(3000/math.sqrt(3))
    assert powerflow.get_complex(m, "t1", "constant_impedance_12") == pytest.approx((240**2)/(1000/math.sqrt(3)))

def test_pqload(helpers):
    """Power, impedance, and current (at its angle from the voltage) on
    every phase; the same solution as the equivalent load"""
    r = helpers.run(feeder("pqload", "Pp 500000; Pq 100000; Zp 400; Im 50; Ia -30;"))
    assert r.returncode == 0, r.stderr
    m = r.model
    assert any("pqload: no climate data found" in x for x in helpers.warnings(r))
    v = helpers.voltages(m, "n1")
    for k, x in enumerate("ABC"):
        assert powerflow.get_complex(m, "n1", f"constant_power_{x}") == 500000+100000j
        assert powerflow.get_complex(m, "n1", f"constant_impedance_{x}") == 400
        assert powerflow.get_complex(m, "n1", f"constant_current_{x}") == pytest.approx(cmath.rect(50, math.radians(-30) + cmath.phase(v[k])), rel=1e-4)
    same = helpers.run(feeder("load", " ".join(f"constant_power_{x} 500000+100000j; constant_impedance_{x} 400; constant_current_{x} {cmath.rect(50, math.radians(-30) + (0, -2*math.pi/3, 2*math.pi/3)[k])};".replace("(", "").replace(")", "") for k, x in enumerate("ABC"))))
    assert np.max(np.abs(v - helpers.voltages(same.model, "n1"))) < 1e-3
    assert powerflow.get_complex(m, "n1", "output_power") == 500000+100000j

def test_pqload_weather(helpers):
    glm = feeder("pqload", "weather w; Pp_T 1000; Pp_H 10;", "object weather_stub { name w; temperature 80; humidity 40; solar_flux 0; wind_speed 0; rainfall 0; }")
    r = helpers.run(glm)
    assert r.returncode == 0, r.stderr
    assert powerflow.get_double(r.model, "n1", "input_temp") == 80
    assert powerflow.get_complex(r.model, "n1", "constant_power_A") == pytest.approx(80*1000 + 40*10)
