"""Class `line_sensor`: registration, location, noise, covariance forms,
triplex lines, and errors"""
# pylint: disable=missing-function-docstring,line-too-long

import numpy as np
import pytest

import powerflow
from powerflow.line_sensor import LineSensor, cholesky, covariance_matrix, parse_array
from powerflow._common import PowerflowError
from arras.oclass import Class
from arras.model import Model

VNOM = 2401.7771
FEEDER = f"""
object overhead_line_conductor {{ name olc336; geometric_mean_radius 0.0244 ft; resistance 0.306 Ohm/mile; diameter 0.721 in; }}
object overhead_line_conductor {{ name olc4/0; geometric_mean_radius 0.00814 ft; resistance 0.592 Ohm/mile; diameter 0.563 in; }}
object line_spacing {{ name ls; distance_AB 2.5 ft; distance_BC 4.5 ft; distance_AC 7.0 ft;
    distance_AN 5.656854 ft; distance_BN 4.272002 ft; distance_CN 5.0 ft;
    distance_AE 28 ft; distance_BE 28 ft; distance_CE 28 ft; distance_NE 24 ft; }}
object line_configuration {{ name oc; conductor_A olc336; conductor_B olc336; conductor_C olc336; conductor_N olc4/0; spacing ls; }}
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object overhead_line {{ name o01; phases ABCN; from n0; to n1; length 2000; configuration oc; }}
object node {{ name n1; phases ABCN; nominal_voltage {VNOM}; power_A 300000+150000j; power_B 200000+50000j; power_C 100000; }}
"""

def sensor(body:str) -> str:
    return f"object line_sensor {{ name ls1; parent o01; {body} }}\n"

def test_registration():
    Model().read_glm("module powerflow;\n")
    oclass = Class.find("line_sensor", module="powerflow")
    assert oclass.trl == 9 and oclass.parent is None
    assert oclass.find_property("measured_phase").ptype == "enumeration" and oclass.find_property("covariance").ptype == "double_array"
    names = [x.name for x in powerflow.classes()]
    assert names.index("line_sensor") == names.index("line") + 1

@pytest.mark.parametrize("phase,location", [("A", 500), ("B", 0), ("C", 2000)])
def test_measurement(helpers, phase, location):
    """Interpolated at location, no noise"""
    r = helpers.run(FEEDER + sensor(f"measured_phase {phase}; location {location} ft;"), lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    w = location/2000
    v = powerflow.get_complex(m, "n0", f"voltage_{phase}")*(1 - w) + powerflow.get_complex(m, "n1", f"voltage_{phase}")*w
    i = powerflow.get_complex(m, "o01", f"current_in_{phase}")*(1 - w) + powerflow.get_complex(m, "o01", f"current_out_{phase}")*w
    assert powerflow.get_complex(m, "ls1", "measured_voltage") == pytest.approx(v)
    assert powerflow.get_complex(m, "ls1", "measured_current") == pytest.approx(i)
    assert powerflow.get_complex(m, "ls1", "measured_power") == pytest.approx(v*i.conjugate())
    if location == 500:
        assert abs(v - powerflow.get_complex(m, "n0", "voltage_A")) > 1.0 # not at the from end (gridlabd's w = 0)

def test_location_clamped(helpers):
    r = helpers.run(FEEDER + sensor("measured_phase A; location 3000 ft;"), lines=False)
    assert r.returncode == 0, r.stderr
    assert any("ls1: sensor location is beyond 'to' node (w>1)" in x for x in helpers.warnings(r))
    assert powerflow.get_complex(r.model, "ls1", "measured_voltage") == pytest.approx(powerflow.get_complex(r.model, "n1", "voltage_A"))
    r = helpers.run(FEEDER + sensor("measured_phase A; location -10 ft;"), lines=False)
    assert any("ls1: sensor location is beyond 'from' node (w<0)" in x for x in helpers.warnings(r))
    assert powerflow.get_complex(r.model, "ls1", "measured_voltage") == pytest.approx(powerflow.get_complex(r.model, "n0", "voltage_A"))

def test_noise(helpers):
    """Each part scaled by sqrt(1+n) with n ~ N(0, s): repeatable for a seed,
    and statistically consistent over many postsync passes"""
    glm = FEEDER + sensor('measured_phase A; location 1000 ft; covariance "0.0004 0.0009 0 0.0001";')
    r = helpers.run(glm, lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    first = powerflow.get_complex(m, "ls1", "measured_voltage")
    v = (powerflow.get_complex(m, "n0", "voltage_A") + powerflow.get_complex(m, "n1", "voltage_A"))/2
    i = (powerflow.get_complex(m, "o01", "current_in_A") + powerflow.get_complex(m, "o01", "current_out_A"))/2
    vm, im = [], []
    for _ in range(2000):
        LineSensor.postsync(m, "ls1", 0)
        vm.append(powerflow.get_complex(m, "ls1", "measured_voltage"))
        im.append(powerflow.get_complex(m, "ls1", "measured_current"))
    vm, im = np.array(vm), np.array(im)
    assert np.allclose(im.real, i.real) # zero variance: no noise (gridlabd rejects it)
    n_vr, n_vi, n_ii = (vm.real/v.real)**2 - 1, (vm.imag/v.imag)**2 - 1, (im.imag/i.imag)**2 - 1
    assert np.std(n_vr) == pytest.approx(0.02, rel=0.1) and np.std(n_vi) == pytest.approx(0.03, rel=0.1)
    assert np.std(n_ii) == pytest.approx(0.01, rel=0.1) and abs(np.mean(n_vr)) < 0.002
    r2 = helpers.run(glm, lines=False)
    assert powerflow.get_complex(r2.model, "ls1", "measured_voltage") == first
    assert first != pytest.approx(v)

def test_correlated_noise(helpers):
    """Noise with the covariance's correlations (gridlabd uses the
    covariance in place of its Cholesky factor)"""
    r = helpers.run(FEEDER + sensor('measured_phase B; location 0; covariance "0.0004 0.0004 0.0001 0.0001 0 0; 0.0003 0 0 0 0 0";'), lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    v = powerflow.get_complex(m, "n0", "voltage_B")
    samples = []
    for _ in range(4000):
        LineSensor.postsync(m, "ls1", 0)
        x = powerflow.get_complex(m, "ls1", "measured_voltage")
        samples.append(((x.real/v.real)**2 - 1, (x.imag/v.imag)**2 - 1))
    cov = np.cov(np.array(samples).T)
    assert cov == pytest.approx(np.array([[0.0004, 0.0003], [0.0003, 0.0004]]), abs=4e-5)

def test_covariance_forms():
    assert parse_array('"1 2, 3 4"') == [[1, 2, 3, 4]] and parse_array("") == []
    assert np.array_equal(covariance_matrix([]), np.zeros((4, 4)))
    assert np.array_equal(covariance_matrix([[1, 2, 3, 4]]), np.diag([1, 2, 3, 4]))
    c = covariance_matrix([[4, 5, 6, 7, 0, 0], [1, 0.5, 0.25, 0.2, 0.1, 0.3]])
    assert np.array_equal(c, [[4, 1, 0.5, 0.25], [1, 5, 0.2, 0.1], [0.5, 0.2, 6, 0.3], [0.25, 0.1, 0.3, 7]])
    full = [[2, 0.5, 0, 0], [0.5, 2, 0, 0], [0, 0, 1, 0.1], [0, 0, 0.1, 1]]
    assert np.array_equal(covariance_matrix(full), full)
    with pytest.raises(PowerflowError, match="only 1x4, 2x6 or 4x4"):
        covariance_matrix([[1, 2, 3]])

def test_cholesky():
    c = covariance_matrix([[4, 5, 6, 7, 0, 0], [1, 0.5, 0.25, 0.2, 0.1, 0.3]])
    low = cholesky(c)
    assert np.allclose(low, np.linalg.cholesky(c)) and np.allclose(low @ low.T, c)
    low = cholesky(np.diag([0.03, 0, 0.02, 0.02]))
    assert np.allclose(low, np.diag(np.sqrt([0.03, 0, 0.02, 0.02])))
    with pytest.raises(PowerflowError, match="not positive symmetric definite"):
        cholesky(np.array([[1, 2, 0, 0], [2, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1.0]]))
    with pytest.raises(PowerflowError, match="not positive symmetric definite"):
        cholesky(np.diag([1, -1, 1, 1.0]))

def test_triplex(helpers):
    glm = """
object node { name n0; phases AS; nominal_voltage 120; bustype SWING; }
object triplex_line_conductor { name tlc; resistance 0.97; geometric_mean_radius 0.0111; }
object triplex_line_configuration { name tlcfg; conductor_1 tlc; conductor_2 tlc; conductor_N tlc; insulation_thickness 0.08; diameter 0.368; }
object triplex_line { name tl; phases AS; from n0; to l1; length 100; configuration tlcfg; object line_sensor { name ls1; measured_phase B; location 100; }; }
object triplex_load { name l1; phases AS; nominal_voltage 120; constant_power_1 1000+500j; constant_power_2 1500; }
"""
    r = helpers.run(glm, lines=False)
    assert r.returncode == 0, r.stderr
    assert powerflow.get_complex(r.model, "ls1", "measured_voltage") == pytest.approx(powerflow.get_complex(r.model, "l1", "voltage_2"))
    assert powerflow.get_complex(r.model, "ls1", "measured_current") == pytest.approx(powerflow.get_complex(r.model, "tl", "current_out_B"))

@pytest.mark.parametrize("glm,message", [
    ("object line_sensor { name ls1; measured_phase A; location 1; }", "init_line_sensor(obj=7;ls1): ls1: parent target must be specified"),
    ("object line_sensor { name ls1; parent n1; measured_phase A; location 1; }", "ls1: parent 'n1' must be a powerflow line object"),
    (sensor('measured_phase A; location 1; covariance "1 2 3";'), "ls1: covariance matrix is not in proper form; only 1x4, 2x6 or 4x4 forms allowed"),
    (sensor('measured_phase A; location 1; covariance "1 x 3 4";'), "ls1: covariance matrix is not in proper form"),
    (sensor('measured_phase A; location 1; covariance "1 1 1 1 0 0; 2 0 0 0 0 0";'), "ls1: covariance is not positive symmetric definite"),
])
def test_errors(helpers, glm, message):
    r = helpers.run(FEEDER + glm, lines=False)
    assert r.returncode != 0 and any(message in x for x in helpers.errors(r)), helpers.errors(r)
