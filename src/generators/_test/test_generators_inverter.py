"""Class `inverter`: init checks, legacy and four-quadrant outputs, and
posting to the parent meter"""

import math

import pytest

from arras import exitcodes
from pypower._common import get_double, get_complex

from conftest import run, errors, warnings

MODULES = "module powerflow;\nmodule generators;"

FEEDER = """object node {{ name n1; phases {phases}; nominal_voltage {vnom}; bustype SWING; }}
object link {{ name l1; from n1; to m1; phases {phases}; }}
object meter {{ name m1; phases {phases}; nominal_voltage {vnom}; {meter} }}
object inverter {{
    name inv;
    parent m1;
    generator_status ONLINE;
    V_In 400 V;
    I_In 25 A;
    {inverter}
}}
"""

TRIPLEX = """object triplex_meter {{ name n1; phases AS; nominal_voltage 120; bustype SWING; }}
object triplex_line_conductor {{ name c1; resistance 0.97; geometric_mean_radius 0.01111; }}
object triplex_line_configuration {{ name tc1; conductor_1 c1; conductor_2 c1; conductor_N c1; insulation_thickness 0.08; diameter 0.368; }}
object triplex_line {{ name l1; from n1; to m1; phases AS; length 100 ft; configuration tc1; }}
object triplex_meter {{ name m1; phases AS; nominal_voltage 120; }}
object inverter {{
    name inv;
    parent m1;
    generator_status ONLINE;
    V_In 400 V;
    I_In 25 A;
    {inverter}
}}
"""

def feeder(inverter, phases="ABCN", meter="", vnom=2401.7771):
    """Run an inverter on a meter fed from a swing node"""
    return run(FEEDER.format(phases=phases, vnom=vnom, meter=meter, inverter=inverter), modules=MODULES)

def measured(m):
    """Power the meter measures"""
    return get_complex(m, "m1", "measured_power")

def test_legacy_three_phase():
    """A PWM inverter converts the DC power with its efficiency, splits it
    among the phases, and posts currents that are removed after the
    solution"""
    m, r = feeder("inverter_type PWM; generator_mode CONSTANT_PF; inverter_efficiency 0.95;")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    assert get_complex(m, "inv", "VA_In") == pytest.approx(10000)
    assert get_complex(m, "inv", "VA_Out") == pytest.approx(9500)
    for x in "ABC":
        assert get_complex(m, "inv", f"power_{x}") == pytest.approx(complex(9500/3, 0))
        assert abs(get_complex(m, "m1", f"current_{x}")) < 1e-9
    assert measured(m) == pytest.approx(complex(-9500, 0), abs=1)

def test_legacy_power_factor_single_phase():
    """The output power factor and a single-phase connection"""
    m, r = feeder("inverter_type PWM; generator_mode CONSTANT_PF; power_factor 0.8;", phases="AN")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    s = 10000*0.9
    assert get_complex(m, "inv", "power_A") == pytest.approx(complex(0.8*s, 0.6*s))
    assert measured(m) == pytest.approx(complex(-0.8*s, -0.6*s), abs=1)
    assert m.get_property("inv", "phases") == "AN"

def test_legacy_two_phase():
    """Two phases share the output"""
    m, r = feeder("inverter_type SIX_PULSE; generator_mode CONSTANT_PF;", phases="ABN")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    assert get_complex(m, "inv", "power_A") == pytest.approx(complex(4000, 0))
    assert get_complex(m, "inv", "power_B") == pytest.approx(complex(4000, 0))
    assert "inv: inverter_efficiency unspecified--defaulted to 0.80 for this inverter type" in warnings(r)

def test_legacy_triplex():
    """A triplex inverter posts its current across the 240 V connection;
    powerflow turns a current load with the voltage angle, so the power
    delivered turns by the voltage angle drop across the line, as in
    gridlabd"""
    m, r = run(TRIPLEX.format(inverter="inverter_type PWM; generator_mode CONSTANT_PF;"), modules=MODULES)
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    assert get_complex(m, "inv", "power_A") == pytest.approx(complex(9000, 0))
    assert abs(measured(m)) == pytest.approx(9000, rel=1e-6)
    assert measured(m).real == pytest.approx(-9000, rel=1e-5)
    assert abs(get_complex(m, "m1", "current_12")) < 1e-9

def test_two_pulse_becomes_pwm():
    """TWO_PULSE has the value of an unset type, so it becomes PWM"""
    m, r = feeder("inverter_type TWO_PULSE; generator_mode CONSTANT_PF;")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    assert m.get_property("inv", "inverter_type") == "PWM"
    assert "inv: Inverter type is unknown! Using default: PWM" in warnings(r)

@pytest.mark.parametrize("mode,message", [("CONSTANT_PQ", "Constant PQ mode not supported at this time"),
    ("CONSTANT_V", "Constant V mode not supported at this time"),
    ("SUPPLY_DRIVEN", "SUPPLY_DRIVEN mode for inverters not supported at this time")])
def test_legacy_modes_refused(mode, message):
    """The legacy modes gridlabd does not support fail the run"""
    _, r = feeder(f"inverter_type PWM; generator_mode {mode};")
    assert r.returncode == exitcodes.RUNERR
    assert errors(r)[0] == f"sync_inverter(obj=3;inv): {message}"

def test_four_quadrant_power_factor():
    """Four-quadrant CONSTANT_PF: a negative power factor is leading"""
    m, r = feeder("inverter_type FOUR_QUADRANT; four_quadrant_control_mode CONSTANT_PF; power_factor -0.9; inverter_efficiency 0.95;")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    p = 10000*0.95
    q = p/0.9*math.sqrt(1 - 0.81)
    assert get_complex(m, "inv", "VA_Out") == pytest.approx(complex(p, q))
    assert get_double(m, "inv", "P_Out") == pytest.approx(p)
    assert get_double(m, "inv", "Q_Out") == pytest.approx(q)
    assert measured(m) == pytest.approx(complex(-p, -q), abs=1)
    for x in "ABC":
        assert abs(get_complex(m, "m1", f"power_{x}")) < 1e-9

def test_four_quadrant_limit():
    """An output above the maximum keeps its power factor at the maximum"""
    m, r = feeder("inverter_type FOUR_QUADRANT; four_quadrant_control_mode CONSTANT_PF; power_factor 0.8; inverter_efficiency 0.95; rated_power 1 kVA;")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    va = get_complex(m, "inv", "VA_Out")
    assert va == pytest.approx(complex(3000*0.8, -3000*0.6))
    assert get_double(m, "inv", "excess_input_power") == pytest.approx(9500/0.8 - 3000)

def test_constant_pq_limits():
    """CONSTANT_PQ reduces the reactive power first, then the real power"""
    m, r = feeder("inverter_type FOUR_QUADRANT; four_quadrant_control_mode CONSTANT_PQ; rated_power 2 kVA; P_Out 5 kW; Q_Out -5 kVAr;")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    assert get_complex(m, "inv", "VA_Out") == pytest.approx(complex(5000, -math.sqrt(6000**2 - 5000**2)))
    m, r = feeder("inverter_type FOUR_QUADRANT; four_quadrant_control_mode CONSTANT_PQ; rated_power 2 kVA; P_Out -7 kW; Q_Out 1 kVAr;")
    assert get_complex(m, "inv", "VA_Out") == pytest.approx(complex(-6000, 0))
    assert get_double(m, "inv", "power_in") == pytest.approx(-6000*0.9)

def test_constant_pq_battery_full():
    """A full battery is not charged"""
    m, r = feeder("inverter_type FOUR_QUADRANT; four_quadrant_control_mode CONSTANT_PQ; P_Out -1 kW; Q_Out 1 kVAr; battery_soc 1;")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    assert get_complex(m, "inv", "VA_Out") == pytest.approx(complex(0, 1000))
    assert "inv: inverter:inv - battery full - no charging allowed" in warnings(r)

def test_offline():
    """An offline inverter outputs nothing"""
    m, r = feeder("inverter_type FOUR_QUADRANT; generator_status OFFLINE; P_Out 1 kW;")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    assert get_complex(m, "inv", "VA_Out") == 0
    assert abs(measured(m)) < 1

def test_parent_out_of_service():
    """A parent out of service gets nothing"""
    m, r = feeder("inverter_type PWM; generator_mode CONSTANT_PF;", meter="service_status OUT_OF_SERVICE;")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    assert abs(measured(m)) < 1

def test_parent_required():
    """An inverter needs a meter or triplex meter parent"""
    _, r = run("object inverter { name inv; }", modules=MODULES)
    assert r.returncode == exitcodes.INIERR
    assert errors(r)[0] == "init_inverter(obj=0;inv): cannot initialize an inverter without a parent"
    _, r = run("object node { name n1; phases ABCN; nominal_voltage 120; bustype SWING; }\nobject inverter { name inv; parent n1; }", modules=MODULES)
    assert errors(r)[0] == "init_inverter(obj=1;inv): Inverter must have a meter or triplex meter as it's parent"

@pytest.mark.parametrize("setting,message", [
    ("four_quadrant_control_mode VOLT_VAR;", "four_quadrant_control_mode VOLT_VAR is not supported yet"),
    ("four_quadrant_control_mode LOAD_FOLLOWING;", "four_quadrant_control_mode LOAD_FOLLOWING is not supported yet"),
    ("pf_reg INCLUDED;", "pf_reg (power-factor regulation) is not supported yet"),
    ("enable_1547_checks TRUE;", "enable_1547_checks (IEEE 1547 checks) is not supported yet"),
])
def test_not_ported(setting, message):
    """Modes that are not ported fail at init"""
    _, r = feeder(f"inverter_type FOUR_QUADRANT; {setting}")
    assert r.returncode == exitcodes.INIERR
    assert errors(r)[0] == f"init_inverter(obj=3;inv): {message}"

def test_multipoint_needs_parameters():
    """The multipoint model without a manufacturer needs its parameters"""
    _, r = feeder("inverter_type PWM; generator_mode CONSTANT_PF; use_multipoint_efficiency TRUE;")
    assert r.returncode == exitcodes.INIERR
    assert errors(r)[0] == "inv: no maximum dc power was given for the inverter."

def test_multipoint_preset():
    """A manufacturer preset sets the curve and the maximum output"""
    m, r = feeder("inverter_type PWM; generator_mode CONSTANT_PF; use_multipoint_efficiency TRUE; inverter_manufacturer SMA;", phases="AN")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    assert get_double(m, "inv", "maximum_dc_power") == 2694
    assert get_double(m, "inv", "rated_power") == 2500
    c1 = 2694*(1 + 6.525e-5*(400 - 302))
    c2 = 20.7*(1 + 2.836e-3*(400 - 302))
    c3 = -1.545e-5*(1 - 3.058e-4*(400 - 302))
    p = ((2500/(c1 - c2)) - c3*(c1 - c2))*(10000 - c2) + c3*(10000 - c2)**2
    assert get_complex(m, "inv", "VA_Out").real == pytest.approx(p)
    assert "inv: The dc voltage is greater than the specified maximum for the inverter. Efficiency model may be inaccurate." in warnings(r)

def test_solar_before_inverter():
    """An array declared before its inverter waits for it"""
    m, r = run("""object node { name n1; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
object link { name l1; from n1; to m1; phases ABCN; }
object solar { name pv; parent inv; SOLAR_TILT_MODEL PLAYERVALUE; Insolation 92.902 W/sf; area 100 sf;
    panel_type SINGLE_CRYSTAL_SILICON; generator_mode SUPPLY_DRIVEN; generator_status ONLINE; }
object meter { name m1; phases ABCN; nominal_voltage 2401.7771; }
object inverter { name inv; parent m1; generator_status ONLINE; inverter_type PWM; generator_mode CONSTANT_PF; }
""", modules=MODULES)
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    assert get_complex(m, "inv", "VA_In") == pytest.approx(get_complex(m, "pv", "VA_Out"))
    assert get_complex(m, "inv", "VA_Out") == pytest.approx(0.9*get_complex(m, "pv", "VA_Out"))
