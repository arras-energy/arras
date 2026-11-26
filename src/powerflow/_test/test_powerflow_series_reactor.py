"""Class `series_reactor`: registration, impedances and their parts, the
solution against an independent computation, a zero impedance, an open
reactor, and the DC method"""
# pylint: disable=missing-function-docstring,line-too-long

import cmath
import math

import numpy as np
import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model

VNOM = 2401.7771
LOADS = (300e3+100e3j, 200e3+50e3j, 100e3)

def feeder(reactor:str, method:str="NR") -> tuple[str,str]:
    glm = f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object series_reactor {{ name r01; phases ABCN; from n0; to n1; {reactor} }}
object node {{ name n1; phases ABCN; nominal_voltage {VNOM}; power_A {LOADS[0]}; power_B {LOADS[1]}; power_C {LOADS[2]}; }}
""".replace("(", "").replace(")", "")
    return glm, f"solver_method {method};"

def expected(z:list[complex]) -> list[complex]:
    """Each phase alone (no coupling): V = Vs - Z conj(S/V)"""
    result = []
    for k, (zk, s) in enumerate(zip(z, LOADS)):
        vs = cmath.rect(VNOM, (0, -2*math.pi/3, 2*math.pi/3)[k])
        v = vs
        for _ in range(200):
            v = vs - zk*(s/v).conjugate()
        result.append(v)
    return result

def test_registration():
    Model().read_glm("module powerflow;\n")
    reactor = Class.find("series_reactor", module="powerflow")
    assert reactor.parent.name == "link" and reactor.trl == 9
    assert reactor.find_property("phase_B_reactance").unit == "Ohm" and reactor.find_property("rated_current_limit").unit == "A"

@pytest.mark.parametrize("method", ["NR", "FD_XB", "FD_BX"])
def test_solution(helpers, method):
    """Each phase is its own series impedance"""
    z = [0.5+2j, 0.4+1.5j, 0.3+1j]
    glm, module = feeder(f"phase_A_impedance {z[0]}; phase_B_impedance {z[1]}; phase_C_impedance {z[2]};".replace("(", "").replace(")", ""), method)
    r = helpers.run(glm, module=module, lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert np.abs(helpers.voltages(m, "n1") - expected(z)).max() < 1e-3
    loss = powerflow.get_complex(m, "r01", "power_losses_A")
    assert loss == pytest.approx(abs(powerflow.get_complex(m, "r01", "current_in_A"))**2*z[0], rel=1e-6)

def test_parts(helpers):
    """The parts are taken in the order they are set, the last one winning"""
    glm, module = feeder("phase_A_impedance 1+2j; phase_A_reactance 3; phase_B_resistance 0.5; phase_B_reactance 1; phase_C_reactance 2; phase_C_impedance 0.1+0.2j;")
    m = helpers.run(glm, module=module, lines=False).model
    assert powerflow.get_complex(m, "r01", "phase_A_impedance") == 1+3j
    assert powerflow.get_double(m, "r01", "phase_A_resistance") == 1
    assert powerflow.get_complex(m, "r01", "phase_B_impedance") == 0.5+1j
    assert powerflow.get_complex(m, "r01", "phase_C_impedance") == 0.1+0.2j and powerflow.get_double(m, "r01", "phase_C_reactance") == 0.2
    assert np.abs(helpers.voltages(m, "n1") - expected([1+3j, 0.5+1j, 0.1+0.2j])).max() < 1e-3

def test_zero_impedance(helpers):
    """A zero impedance is gridlabd's NR admittance, 1e4+1e4j S"""
    glm, module = feeder("")
    m = helpers.run(glm, module=module, lines=False).model
    z = 1/complex(1e4, 1e4)
    assert np.abs(helpers.voltages(m, "n1") - expected([z]*3)).max() < 1e-6

def test_open(helpers):
    """An open reactor takes out the node it alone feeds"""
    glm, module = feeder("phase_A_impedance 0+1j; phase_B_impedance 0+1j; phase_C_impedance 0+1j; status OPEN;")
    r = helpers.run(glm, module=module, lines=False)
    assert r.returncode == 0, r.stderr
    assert np.abs(helpers.voltages(r.model, "n1")).max() == 0

@pytest.mark.parametrize("reactor", ["phase_A_impedance 0.1+2j; phase_B_impedance 0.1+2j; phase_C_impedance 0.1+2j;", "phase_A_impedance 2; phase_B_impedance 2; phase_C_impedance 2;"])
def test_dc(helpers, reactor):
    """DC angles: each phase's reactance, or the impedance's magnitude
    when it has no positive reactance"""
    glm, module = feeder(reactor, "DC")
    r = helpers.run(glm, module=module, lines=False)
    assert r.returncode == 0, r.stderr
    v = helpers.voltages(r.model, "n1")
    x = 2.0
    for k in range(3):
        drop = (0, -2*math.pi/3, 2*math.pi/3)[k] - cmath.phase(v[k])
        assert math.remainder(drop, 2*math.pi) == pytest.approx(LOADS[k].real*x/VNOM**2, rel=1e-6)
