"""Classes `transformer` and `regulator`: registration, initialization,
admittance, and solutions checked against independent computations"""
# pylint: disable=missing-function-docstring,line-too-long

import cmath
import math

import numpy as np
import pytest

import powerflow

from arras.oclass import Class
from arras.model import Model
from powerflow.transformer import Transformer
from powerflow.regulator import Regulator

VHIGH = 12470/math.sqrt(3)
VLOW = 4160/math.sqrt(3)
LOADS = (1.0e6+0.5e6j, 1.2e6+0.6e6j, 0.9e6+0.4e6j)

def transformer(connect:str, primary:float=12470, secondary:float=4160, extra:str="", phases:str="ABCN", node:str="") -> str:
    vf, vt = primary/math.sqrt(3), secondary/math.sqrt(3)
    loads = " ".join(f"power_{x} {s.real:.0f}{s.imag:+.0f}j;" for x, s in zip("ABC", LOADS))
    return f"""
object transformer_configuration {{ name tc; connect_type {connect}; install_type PADMOUNT; primary_voltage {primary}; secondary_voltage {secondary};
    power_rating 6000; impedance 0.01+0.06j; }}
object node {{ name n1; phases ABCN; nominal_voltage {vf}; bustype SWING; }}
object transformer {{ name t12; phases {phases}; from n1; to n2; configuration tc; {extra} }}
object node {{ name n2; phases ABCN; nominal_voltage {vt}; {loads} {node} }}
"""

def expected(c:np.ndarray, zt:complex, v1:np.ndarray) -> np.ndarray:
    """Secondary voltages of a transformer `V2 = C V1 - zt I` with the
    constant-power loads, by fixed-point iteration"""
    v2 = c @ v1
    for _ in range(200):
        v2 = c @ v1 - zt*np.conj(np.array(LOADS)/v2)
    return v2

def source(v:float) -> np.ndarray:
    return np.array([cmath.rect(v, math.radians(a)) for a in (0, -120, 120)])

ZT = (0.01+0.06j)*4160**2/6e6
NT = 12470/4160

def test_registration():
    Model().read_glm("module powerflow;\n")
    for name in ("transformer", "regulator"):
        oclass = Class.find(name, module="powerflow")
        assert oclass.parent.name == "link" and oclass.find_property("configuration").ptype == "object"
    assert Class.find("transformer", module="powerflow").find_property("degradation_factor").unit == "pu"
    reg = Class.find("regulator", module="powerflow")
    assert reg.find_property("tap_A").default == "-999" and reg.find_property("regulator_resistance").default == "-1 Ohm"
    assert reg.find_property("sense_node").ptype == "object"

@pytest.mark.parametrize("method", ["NR", "FD_XB", "FD_BX"])
def test_wye_wye(helpers, method):
    r = helpers.run(transformer("WYE_WYE"), module=f"solver_method {method};", lines=False)
    assert r.returncode == 0, r.stderr
    v2 = expected(np.eye(3)/NT, ZT, source(VHIGH))
    assert np.max(np.abs(helpers.voltages(r.model, "n2") - v2)) < 1e-3

@pytest.mark.parametrize("primary,secondary,lag", [(12470, 4160, 30), (4160, 12470, -30)])
@pytest.mark.parametrize("method", ["NR", "FD_BX"])
def test_delta_gwye(helpers, method, primary, secondary, lag):
    """The secondary lags a step-down primary by 30 degrees and leads a
    step-up primary by 30 degrees"""
    r = helpers.run(transformer("DELTA_GWYE", primary, secondary), module=f"solver_method {method};", lines=False)
    assert r.returncode == 0, r.stderr
    nt = primary/secondary
    zt = (0.01+0.06j)*secondary**2/6e6
    base = np.array([[1, 0, -1], [-1, 1, 0], [0, -1, 1]])/(nt*math.sqrt(3))
    v2 = expected(base if nt > 1 else base.T, zt, source(primary/math.sqrt(3)))
    assert np.max(np.abs(helpers.voltages(r.model, "n2") - v2)) < 1e-3
    assert np.angle(v2[0], deg=True) == pytest.approx(-lag, abs=3)

def test_delta_gwye_blocks(helpers):
    m = helpers.model(transformer("DELTA_GWYE"), lines=False)
    yff, yft, ytf, ytt = Transformer.admittance(m, "t12")
    alpha = NT*math.sqrt(3)
    assert np.allclose(yff, np.eye(3)/ZT/NT**2) and np.allclose(ytt, np.eye(3)/ZT)
    assert np.allclose(yft, ytf.T) and np.allclose(ytf, -np.array([[1, 0, -1], [-1, 1, 0], [0, -1, 1]])/alpha/ZT)

@pytest.mark.parametrize("connect,shift", [("WYE_WYE", 0), ("DELTA_GWYE", math.pi/6)])
def test_dc(helpers, connect, shift):
    """DC: each phase's angle drop is its power times the per-unit
    reactance of `zt`, less the shift"""
    r = helpers.run(transformer(connect), module="solver_method DC;", lines=False)
    assert r.returncode == 0, r.stderr
    v2 = helpers.voltages(r.model, "n2")
    xpu = ZT.imag*1e6/VLOW**2
    for k, angle in enumerate((0, -120, 120)):
        assert np.angle(v2[k]) == pytest.approx(math.radians(angle) - shift - LOADS[k].real/1e6*xpu, abs=1e-9)
    assert powerflow.get_complex(r.model, "t12", "power_in_A").real == pytest.approx(LOADS[0].real, rel=1e-6)

def test_single_phase_and_degradation(helpers):
    """A single-phase transformer on phase B; the degradation factor
    changes the ratio and the base of the impedance"""
    glm = transformer("SINGLE_PHASE", extra="degradation_factor 0.1;", phases="BN").replace("power_A 1000000+500000j;", "").replace("power_C 900000+400000j;", "").replace("name n2; phases ABCN", "name n2; phases BN")
    r = helpers.run(glm, lines=False)
    assert r.returncode == 0, r.stderr
    nt = NT*0.9
    zt = (0.01+0.06j)*(4160/0.9)**2/6e6
    v1 = source(VHIGH)[1]
    v2 = v1/nt
    for _ in range(200):
        v2 = v1/nt - zt*np.conj(LOADS[1]/v2)
    assert abs(helpers.voltages(r.model, "n2")[1] - v2) < 1e-3

def test_deferred_configuration(helpers):
    """A transformer before its configuration in the file waits for it"""
    glm = transformer("WYE_WYE")
    config, rest = glm.split("\n", 3)[1:3], glm.split("\n", 3)[3]
    r = helpers.run(rest + "\n".join(config), lines=False)
    assert r.returncode == 0, r.stderr

@pytest.mark.parametrize("glm,message", [
    (transformer("WYE_WYE").replace("configuration tc;", ""), "init_transformer(obj=2;t12): no transformer configuration specified."),
    (transformer("WYE_WYE").replace("configuration tc;", "configuration n1;"), "invalid transformer configuration"),
    (transformer("WYE_WYE", extra="degradation_factor 1;"), "degradation_factor must be between 0 and 1 pu"),
    (transformer("WYE_WYE", phases="AN").replace("name n2; phases ABCN", "name n2; phases AS"), "Transformer:t12 has a triplex phase or a triplex \"to\" node, but it is not an SPCT transformer"),
    (transformer("DELTA_GWYE", node="").replace("name n2; phases ABCN", "name n2; phases ABN"), "transformer:2 (delta-grounded wye) - t12 has a phase mismatch at one or both ends"),
    (transformer("WYE_WYE").replace("name n2; phases ABCN", "name n2; phases ABN"), "line:2 - t12 has a phase mismatch at one or both ends"),
])
def test_transformer_init_errors(helpers, glm, message):
    r = helpers.run(glm, lines=False)
    assert r.returncode != 0
    assert any(message in x for x in helpers.errors(r)), r.stderr

def test_thermal_warning(helpers):
    r = helpers.run(transformer("WYE_WYE", extra="use_thermal_model TRUE;"), lines=False)
    assert r.returncode == 0 and any("thermal model is not implemented" in x for x in helpers.warnings(r)), r.stderr

#
# Regulator
#
def regulator(control:str="MANUAL", config:str="", extra:str="", load:str="", center:float=2500, rtype:str="B", width:float=40) -> str:
    return f"""
object regulator_configuration {{ name rc; connect_type WYE_WYE; band_center {center}; band_width {width}; time_delay 30; dwell_time 15;
    raise_taps 16; lower_taps 16; regulation 0.10; Control {control}; Type {rtype}; {config} }}
object node {{ name n1; phases ABCN; nominal_voltage 2401.777; bustype SWING; }}
object regulator {{ name r12; phases ABCN; from n1; to n2; configuration rc; {extra} }}
object node {{ name n2; phases ABCN; nominal_voltage 2401.777; {load} }}
"""

def taps(m:Model) -> list[int]:
    return [int(m.get_property("r12", f"tap_{x}")) for x in "ABC"]

def counts(m:Model) -> list[float]:
    return [float(m.get_property("r12", f"tap_{x}_change_count")) for x in "ABC"]

@pytest.mark.parametrize("rtype", ["A", "B"])
def test_manual(helpers, rtype):
    """No-load output `V1/a`, `a = 1/(1 + tap*per)` (A) or `1 - tap*per`
    (B)"""
    r = helpers.run(regulator(extra="tap_A 5; tap_B 0; tap_C -3;", rtype=rtype), lines=False)
    assert r.returncode == 0, r.stderr
    per = 0.10/16
    a = [1/(1 + t*per) if rtype == "A" else 1 - t*per for t in (5, 0, -3)]
    v1 = source(2401.777)
    assert np.max(np.abs(helpers.voltages(r.model, "n2") - v1/np.array(a))) < 1e-3
    assert taps(r.model) == [5, 0, -3] and counts(r.model) == [0, 0, 0]

def test_admittance(helpers):
    m = helpers.model(regulator(extra="tap_A 2; tap_B 2; tap_C 2; regulator_resistance 0.01;"), lines=False)
    yff, yft, ytf, ytt = Regulator.admittance(m, "r12")
    a = 1 - 2*0.10/16
    assert np.allclose(np.diag(yff), 100/a**2) and np.allclose(np.diag(yft), -100/a) and np.allclose(ytf, yft) and np.allclose(np.diag(ytt), 100)

def test_first_run_jump(helpers):
    """Unset taps jump at once into the band: `ceil((2500 - 2401.8)/15.625)`
    = 7 taps, one change counted"""
    r = helpers.run(regulator("OUTPUT_VOLTAGE"), stop="2020-01-01 00:05:00", lines=False)
    assert r.returncode == 0, r.stderr
    assert taps(r.model) == [7]*3 and counts(r.model) == [1]*3
    assert np.all(np.abs(np.abs(helpers.voltages(r.model, "n2")) - 2500) < 20)

@pytest.mark.parametrize("stop,tap", [(44, 0), (45, 1), (89, 1), (90, 2), (135, 3)])
def test_dwell_and_delay(helpers, stop, tap):
    """With initial taps, a low voltage starts the dwell time (15 s); the
    first step comes after the time delay (30 s), then one step every dwell
    plus delay"""
    r = helpers.run(regulator("OUTPUT_VOLTAGE", "tap_pos_A 0; tap_pos_B 0; tap_pos_C 0;"), stop=f"2020-01-01 00:{stop//60:02d}:{stop%60:02d}", lines=False)
    assert r.returncode == 0, r.stderr
    assert taps(r.model) == [tap]*3 and counts(r.model) == [tap]*3

def test_remote_node_bank(helpers):
    """BANK control on the remote node's phase B moves all taps together"""
    glm = regulator("REMOTE_NODE", "control_level BANK; PT_phase B; CT_phase B;", "sense_node n2;", center=2450)
    r = helpers.run(glm, stop="2020-01-01 00:05:00", lines=False)
    assert r.returncode == 0, r.stderr
    t = taps(r.model)
    assert t[0] == t[1] == t[2] == math.ceil((2450 - 2401.777)/(2450*0.10/16))

def test_line_drop_compensation(helpers):
    """LDC: the monitored voltage is `V/PT - a I/CT (R + jX)`; a large R
    setting raises the taps further than output voltage control"""
    common = "current_transducer_ratio 100; power_transducer_ratio 20;"
    load = "power_A 300000; power_B 300000; power_C 300000;"
    plain = helpers.run(regulator("LINE_DROP_COMP", common, load=load, center=120, width=2), stop="2020-01-01 00:05:00", lines=False)
    comp = helpers.run(regulator("LINE_DROP_COMP", common + " compensator_r_setting_A 10; compensator_r_setting_B 10; compensator_r_setting_C 10;", load=load, center=120, width=2), stop="2020-01-01 00:05:00", lines=False)
    assert plain.returncode == 0 and comp.returncode == 0, plain.stderr + comp.stderr
    assert all(b > a for a, b in zip(taps(plain.model), taps(comp.model)))
    m = comp.model
    a = Regulator.ratios(m, "r12")
    v = helpers.voltages(m, "n2")
    i = np.array([powerflow.get_complex(m, "r12", f"current_in_{x}") for x in "ABC"])
    assert np.allclose(Regulator.monitored(m, "r12"), v/20 - a*i/100*10)

def test_reverse_flow_lock(helpers):
    """Reverse flow (generation at the to node) locks the taps at 0"""
    glm = regulator("OUTPUT_VOLTAGE", "reverse_flow_control LOCK_NEUTRAL;", load="power_A -500000; power_B -500000; power_C -500000;", center=2300)
    r = helpers.run(glm, stop="2020-01-01 00:05:00", lines=False)
    assert r.returncode == 0, r.stderr
    assert taps(r.model) == [0, 0, 0]

def test_shared_configuration(helpers):
    """Two regulators sharing a configuration with unset taps both jump on
    their first run, from the same solution (gridlabd writes 0 back to the
    configuration, so the second one would keep its taps at 0)"""
    glm = regulator("OUTPUT_VOLTAGE") + """
object regulator { name r23; phases ABCN; from n2; to n3; configuration rc; }
object node { name n3; phases ABCN; nominal_voltage 2401.777; }
"""
    r = helpers.run(glm, stop="2020-01-01 00:00:00", lines=False)
    assert r.returncode == 0, r.stderr
    assert r.model.get_property("rc", "tap_pos_A") == "999"
    assert taps(r.model) == [7]*3
    assert [int(r.model.get_property("r23", f"tap_{x}")) for x in "ABC"] == [7]*3

@pytest.mark.parametrize("method", ["FD_XB", "DC"])
def test_regulator_other_methods(helpers, method):
    r = helpers.run(regulator(extra="tap_A 5; tap_B 5; tap_C 5;", load="power_A 100000; power_B 100000; power_C 100000;"), module=f"solver_method {method};", lines=False)
    assert r.returncode == 0, r.stderr

@pytest.mark.parametrize("glm,message", [
    (regulator().replace("configuration rc;", ""), "no regulator configuration specified."),
    (regulator().replace("configuration rc;", "configuration n1;"), "invalid regulator configuration"),
    (regulator("REMOTE_NODE"), "Remote sensing node not found"),
])
def test_regulator_init_errors(helpers, glm, message):
    r = helpers.run(glm, lines=False)
    assert r.returncode != 0
    assert any(message in x for x in helpers.errors(r)), r.stderr

def test_zero_resistance(helpers):
    r = helpers.run(regulator(extra="regulator_resistance 0;"), lines=False)
    assert r.returncode == 0, r.stderr
    assert any("regulator_resistance has been set to zero" in x for x in helpers.warnings(r))
    assert powerflow.get_double(r.model, "r12", "regulator_resistance") > 0
