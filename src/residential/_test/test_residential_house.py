"""Class `house`: gridlabd's HVAC autotests, initialization defaults, the
ETP event solver, the thermostat, the panel and breakers, and the loads
posted to the parent meter"""
# pylint: disable=missing-function-docstring,line-too-long

import math

import pytest

import residential
from residential.house import e2solve

HVAC = {
    # test: (HVAC energy kWh, tolerance, meter energy Wh, tolerance), gridlabd's asserts (0.5% of the reference ETP results)
    "test_HVAC_common_cool": (10.541, 0.052705, 27543, 137.71),
    "test_HVAC_common_heat": (36.3181, 0.14889, 36318.1, 148.89),
    "test_HVAC_peak_cool": (21.5043, 0.10911, 38505, 194.11),
    "test_HVAC_peak_heat": (61.9347, 0.30967, 61934.7, 309.67),
}

@pytest.mark.parametrize("test", HVAC)
def test_hvac_autotests(helpers, test):
    """The HVAC energy of gridlabd's HVAC autotests (house with a heat pump
    and electric cooling in Yakima weather) at the stop time, within the
    autotests' tolerances (gridlabd checks 19 to 47 s later)"""
    hvac, hvac_tol, meter, meter_tol = HVAC[test]
    r = helpers.run_file(f"{test}.glm")
    assert r.returncode == 0, r.stderr
    m = r.model
    house = [x for x in m.objects if m.objects[x].oclass.name == "house"][0]
    target = "panel.energy" if "heat" in test else "energy"
    assert residential.get_complex(m, house, target).real == pytest.approx(hvac, abs=hvac_tol)
    assert residential.get_double(m, "meter", "measured_real_energy") == pytest.approx(meter, abs=meter_tol)
    assert residential.get_complex(m, "meter", "power_12") == 0

def test_hvac_balance(helpers):
    """gridlabd's test_HVAC_balance: its asserts are in service before the
    start time and check once, so they check that the panel and meter
    energies are 0 at the start; the heat pump then cycles"""
    r = helpers.run_file("test_HVAC_balance.glm")
    assert r.returncode == 0, r.stderr
    rows = helpers.read_csv("test_HVAC_balance_panel_energy.csv")
    assert rows[0][0].startswith("2001-05-05 05:00:00") and complex(rows[0][1]) == 0
    assert {"OFF", "HEAT"} <= {row[2] for row in rows}
    house = [x for x in r.model.objects if x.startswith("house")][0]
    assert residential.get_complex(r.model, house, "panel.energy").real == pytest.approx(
        residential.get_double(r.model, "meter", "measured_real_energy")/1000, rel=1e-5)

def test_init_defaults(helpers):
    """`house_e::init()` completes the defaults"""
    m = helpers.run("object house { name h; air_temperature 70; mass_temperature 70; }").model
    get = lambda p: residential.get_double(m, "h", p) # pylint: disable=unnecessary-lambda-assignment
    assert get("floor_area") == 2500 and get("ceiling_height") == 8 and get("number_of_stories") == 1
    assert get("Rroof") == 30 and get("Rwall") == 19 and get("Rfloor") == 22 and get("Rdoors") == 5
    assert get("Rwindows") == pytest.approx(1/0.47) # LOW_E_GLASS, TWO layers, THERMAL_BREAK
    assert get("window_shading") == 0.67 # TWO layers, CLEAR, THERMAL_BREAK
    gross = 2*1*(1.5+1)*8*math.sqrt(2500/1.5)
    assert get("gross_wall_area") == pytest.approx(gross)
    door, window = 4*3*78/12, gross*0.15
    ua = 2500/30 + 2500/22 + (gross - window - door)/19 + window*0.47 + door/5
    assert get("envelope_UA") == pytest.approx(ua)
    assert get("UA") == pytest.approx(ua + 0.5*8*2500*0.0735*0.2402)
    assert get("design_cooling_capacity") % 6000 == 0 and get("design_heating_capacity") == get("design_cooling_capacity")
    assert m.get_property("h", "heating_system_type") == "HEAT_PUMP"
    assert m.get_property("h", "auxiliary_system_type") == "ELECTRIC"
    assert m.get_property("h", "auxiliary_strategy") == "DEADBAND"
    assert get("heating_setpoint") == 70 and get("cooling_setpoint") == 75 and get("thermostat_deadband") == 2

def test_thermal_integrity(helpers):
    """`thermal_integrity_level` sets the R-values and air changes"""
    m = helpers.run("object house { name h; thermal_integrity_level VERY_GOOD; air_temperature 70; mass_temperature 70; }").model
    assert [residential.get_double(m, "h", p) for p in ("Rroof", "Rwall", "Rfloor", "Rdoors", "airchange_per_hour")] == [48, 22, 30, 11, 0.5]
    assert residential.get_double(m, "h", "Rwindows") == pytest.approx(1/0.31)

def test_legacy_system_type(helpers):
    """`system_type` maps to the system types"""
    m = helpers.run("object house { name h; system_type GAS|AIRCONDITIONING|FORCEDAIR; air_temperature 70; mass_temperature 70; }").model
    assert m.get_property("h", "heating_system_type") == "GAS"
    assert residential.get_int(m, "h", "cooling_system_type") == 2 # ELECTRIC, printed as HEAT_PUMP (same value), as gridlabd does
    assert m.get_property("h", "fan_type") == "ONE_SPEED"

@pytest.mark.parametrize("a,n,b,m,c", [(1, -1, 2, -3, -0.5), (-2, -0.5, 1, -2, 0.5), (3, -2, 0, -1, -1), (0, -1, 2, -0.5, -1)])
def test_e2solve(a, n, b, m, c):
    """`e2solve()` finds the first positive root of `a e^nt + b e^mt + c`"""
    t = e2solve(a, n, b, m, c, 1e-9)
    f = lambda x: a*math.exp(n*x) + b*math.exp(m*x) + c # pylint: disable=unnecessary-lambda-assignment
    assert t > 0 and abs(f(t)) < 1e-9
    steps = [k*t/1000 for k in range(1000)]
    assert all(f(x)*f(0) > 0 for x in steps[1:])

def test_e2solve_no_root():
    """No positive root: `nan`"""
    assert math.isnan(e2solve(1, -1, 1, -2, 1, 1e-9))

def test_thermostat_cooling(helpers):
    """A hot day without weather: the cooling cycles keep the air
    temperature within the deadband around the cooling setpoint"""
    r = helpers.run("""
        #set residential::default_outdoor_temperature=95
        object house { name h; air_temperature 76; mass_temperature 76; heating_system_type NONE; auxiliary_system_type NONE;
            object recorder { property air_temperature,system_mode,hvac_load; interval 60; file "h.csv"; };
        }
        """, stop="2020-01-01 06:00:00")
    assert r.returncode == 0, r.stderr
    rows = helpers.read_csv("h.csv")
    temps = [float(row[1]) for row in rows[60:]]
    assert 74 - 0.1 < min(temps) and max(temps) < 76 + 0.1
    assert {row[2] for row in rows} == {"COOL", "OFF"}
    assert residential.get_double(r.model, "h", "compressor_count") > 2
    assert residential.get_double(r.model, "h", "hvac_duty_cycle") > 0

def test_meter_loads(helpers):
    """The panel's loads are posted to the parent meter during the solution
    and removed after it; the meter measures them"""
    r = helpers.run("""
        object triplex_meter { name meter; phases AS; nominal_voltage 120;
            object house { name h; heating_system_type NONE; cooling_system_type NONE; auxiliary_system_type NONE; fan_type NONE;
                air_temperature 70; mass_temperature 70;
                object ZIPload { name z1; base_power 1; power_fraction 0.5; current_fraction 0.3; impedance_fraction 0.2; power_pf 0.9; };
                object ZIPload { name z2; base_power 2; is_240 TRUE; };
            };
        }
        """, stop="2020-01-01 01:00:00", feeder=True)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert m.get_property("meter", "house_present") == "TRUE"
    for x in ("power_1", "power_2", "power_12", "shunt_1", "residential_nominal_current_1"):
        assert abs(residential.get_complex(m, "meter", x)) < 1e-9
    expected = residential.get_complex(m, "z1", "power") + residential.get_complex(m, "z2", "power")
    assert residential.get_complex(m, "meter", "measured_power") == pytest.approx(expected*1000, abs=1e-3)
    assert residential.get_complex(m, "h", "panel.power") == pytest.approx(expected)

def test_out_of_service(helpers):
    """A meter out of service switches the house's loads off"""
    r = helpers.run("""
        object triplex_meter { name meter; phases AS; nominal_voltage 120; service_status OUT_OF_SERVICE;
            object house { name h; air_temperature 70; mass_temperature 70; object ZIPload { name z; base_power 1; }; };
        }
        """, stop="2020-01-01 01:00:00", feeder=True)
    assert r.returncode == 0, r.stderr
    assert residential.get_complex(r.model, "h", "panel.power") == 0
    assert residential.get_double(r.model, "meter", "measured_real_energy") == 0

def test_breaker_trip(helpers):
    """A circuit over its breaker rating opens (using one of its 100 trips)
    and recloses about five minutes later, until it fails"""
    r = helpers.run("""
        object house { name h; heating_system_type NONE; cooling_system_type NONE; auxiliary_system_type NONE; fan_type NONE;
            air_temperature 70; mass_temperature 70;
            object ZIPload { name z; base_power 3; breaker_val 20; };
        }
        """, stop="2020-01-01 02:00:00")
    assert r.returncode == 0, r.stderr
    circuit = residential.ZIPload.circuit(r.model, "z")
    assert 60 < circuit.tripsleft < 100 # about one trip per 5 minutes
    assert residential.get_complex(r.model, "z", "energy").real < 3*2

def test_ansi_warning(helpers):
    """A circuit voltage outside 88% to 106% of nominal warns"""
    r = helpers.run("""
        object triplex_meter { name meter; phases AS; nominal_voltage 120; bustype SWING; voltage_1 130; voltage_2 130; voltage_12 260;
            object house { name h; air_temperature 70; mass_temperature 70; };
        }
        """, stop="2020-01-01 00:10:00")
    assert any("is outside of ANSI standards" in x for x in helpers.warnings(r)), r.stderr
