"""Class `substation`: registration, initialization, sequence voltages,
distribution values, energy, and a `pypower` load parent"""
# pylint: disable=missing-function-docstring,line-too-long

import cmath
import math

import numpy as np
import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model
from powerflow.substation import sequence_to_phase

VNOM = 2401.7771

def feeder(sub:str, tail:str="", meter:bool=False) -> str:
    head = "object meter { measured_energy_delta_timestep 3600; " if meter else "object load { "
    return f"""
object substation {{ name n0; phases ABCN; nominal_voltage {VNOM}; base_power 1e6; {sub} }}
object test_line {{ name l01; phases ABCN; from n0; to n1; length 2000; }}
{head}name n1; phases ABCN; nominal_voltage {VNOM}; }}
object load {{ name n2; parent n1; phases ABCN; nominal_voltage {VNOM}; constant_power_A 100000+20000j; constant_power_B 80000; constant_power_C 50000+10000j; }}
{tail}"""

def test_registration():
    Model().read_glm("module powerflow;\n")
    sub = Class.find("substation", module="powerflow")
    assert sub.parent.name == "node" and sub.trl == 7
    assert sub.find_property("reference_phase").default == "PHASE_A"
    assert sub.find_property("distribution_load").unit == "VA" and sub.find_property("distribution_load").flags

def test_sequence_to_phase():
    a = cmath.rect(1, 2*math.pi/3)
    v = sequence_to_phase([10, 100, 5j], 0)
    assert v == pytest.approx([10 + 100 + 5j, 10 + a*a*100 + a*5j, 10 + a*100 + a*a*5j])
    assert sequence_to_phase([0, 100, 0], 1) == pytest.approx([100*a, 100, 100*a*a])
    assert sequence_to_phase([0, 100, 0], 2) == pytest.approx([100*a*a, 100*a, 100])

def test_sequence_voltages(helpers):
    """The swing voltages are the phase voltages of the sequence voltages;
    the distribution power is what the substation supplies"""
    r = helpers.run(feeder(f"bustype SWING; positive_sequence_voltage {VNOM*1.02}; negative_sequence_voltage 20; reference_phase PHASE_B;"))
    assert r.returncode == 0, r.stderr
    m = r.model
    expected = sequence_to_phase([0, VNOM*1.02, 20], 1)
    assert helpers.voltages(m, "n0") == pytest.approx(expected)
    assert powerflow.get_complex(m, "n0", "distribution_load") == pytest.approx(powerflow.get_complex(m, "l01", "power_in"), rel=1e-9)
    for x in "ABC":
        current = powerflow.get_complex(m, "n0", f"distribution_current_{x}")
        assert current == pytest.approx(powerflow.get_complex(m, "l01", f"current_in_{x}"), rel=1e-9)
        assert powerflow.get_complex(m, "n0", f"distribution_power_{x}") == pytest.approx(powerflow.get_complex(m, "n0", f"voltage_{x}")*current.conjugate())
        assert powerflow.get_complex(m, "n0", f"distribution_voltage_{x}") == powerflow.get_complex(m, "n0", f"voltage_{x}")
    assert powerflow.get_complex(m, "n0", "distribution_voltage_AB") == pytest.approx(expected[0] - expected[1])

def test_normal_node(helpers):
    r = helpers.run(feeder("bustype SWING;"))
    assert r.returncode == 0, r.stderr
    assert any("substation:n0 is set up as a normal node, no sequence values will be calculated" in x for x in helpers.warnings(r))
    assert helpers.voltages(r.model, "n0") == pytest.approx([cmath.rect(VNOM, a) for a in (0, -2*math.pi/3, 2*math.pi/3)])

def test_defaults_and_warnings(helpers):
    r = helpers.run(feeder(f"positive_sequence_voltage {VNOM};").replace("base_power 1e6;", ""))
    warnings = helpers.warnings(r)
    assert any("is using the default base power of 100 VA" in x for x in warnings)
    assert any("power_convergence_value not set - defaulting to 0.01 base_power" in x for x in warnings)
    assert any("substation is not a SWING bus, so answers may be unexpected" in x for x in warnings)
    assert powerflow.get_double(r.model, "n0", "power_convergence_value") == 1

def test_three_phases_required(helpers):
    glm = f"object substation {{ name n0; phases AN; nominal_voltage {VNOM}; bustype SWING; positive_sequence_voltage {VNOM}; }}\n"
    r = helpers.run(glm, lines=False)
    assert any("substation needs to have all three phases!" in x for x in helpers.errors(r)), r.stderr

def test_energy(helpers):
    """Energy of the real power of the previous solution, at each new time"""
    r = helpers.run(feeder(f"bustype SWING; positive_sequence_voltage {VNOM};", meter=True), stop="2020-01-01 02:00:00")
    assert r.returncode == 0, r.stderr
    m = r.model
    power = powerflow.get_complex(m, "n0", "distribution_load").real
    assert powerflow.get_double(m, "n0", "distribution_real_energy") == pytest.approx(2*power, rel=1e-6)

PYPOWER = """
module pypower;
object pypower.bus { name b1; type REF; baseKV 230 kV; Vm 1.0 pu.kV;
    object pypower.gen { name g1; Pmax 200 MW; Qmax 100 MVAr; Qmin -100 MVAr; Vg 1.0 pu.kV; }; }
object pypower.bus { name b2; type PQ; baseKV 230 kV; Pd 50 MW; Qd 20 MVAr; }
object pypower.branch { name l12; from b1; to b2; r 0.01; x 0.1; b 0.02; rateA 100 MVA; }
object pypower.load { name ld; parent b2; Vn %s kV; status ONLINE; }
"""

def test_pypower_parent(helpers):
    """The positive sequence voltage of the load's voltage (kV line to
    line), and the distribution load posted to the load (MVA)"""
    vn = 230000/math.sqrt(3)
    glm = PYPOWER % "230" + f"""
object substation {{ name n0; parent ld; phases ABCN; nominal_voltage {vn}; base_power 1e6; transmission_level_constant_power_load 1e6; transmission_level_constant_current_load 10+5j; transmission_level_constant_impedance_load 100000; }}
object test_line {{ name l01; phases ABCN; from n0; to n1; length 2000; }}
object load {{ name n1; phases ABCN; nominal_voltage {vn}; constant_power_A 1e6+2e5j; constant_power_B 1e6; constant_power_C 1e6; }}
"""
    r = helpers.run(glm)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert any("substation attached to pypower load and not a SWING bus - forcing bustype SWING" in x for x in helpers.warnings(r))
    assert m.get_property("n0", "bustype") == "SWING"
    v = powerflow.get_complex(m, "ld", "V")
    assert powerflow.get_complex(m, "n0", "positive_sequence_voltage") == pytest.approx(v*1000/math.sqrt(3))
    assert helpers.voltages(m, "n0")[0] == pytest.approx(v*1000/math.sqrt(3))
    total = powerflow.get_complex(m, "n0", "distribution_load")
    assert powerflow.get_complex(m, "ld", "P") == pytest.approx((1e6 + total)/1e6)
    assert powerflow.get_complex(m, "ld", "I") == pytest.approx((10-5j)*230000/1e6)
    assert powerflow.get_complex(m, "ld", "Z") == pytest.approx(230000**2/100000/1e6)

def test_pypower_nominal_mismatch(helpers):
    glm = PYPOWER % "115" + f"object substation {{ name n0; parent ld; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}\n"
    r = helpers.run(glm, lines=False)
    assert any("do not match to within 0.1%" in x for x in helpers.errors(r)), r.stderr

def test_other_parent(helpers):
    """A parent that is not a pypower load makes a normal node"""
    glm = f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object substation {{ name s0; parent n0; phases ABCN; nominal_voltage {VNOM}; positive_sequence_voltage {VNOM*1.1}; }}
"""
    r = helpers.run(glm, lines=False)
    assert r.returncode == 0, r.stderr
    assert np.abs(helpers.voltages(r.model, "s0")[0] - VNOM) < 1e-6
