"""Class `ZIPload`: gridlabd's autotest, the ZIP parts, duty cycles, heat
gain only loads, demand response, and loads without a house"""
# pylint: disable=missing-function-docstring,line-too-long

import math

import pytest

import residential

HOUSE = "heating_system_type NONE; cooling_system_type NONE; auxiliary_system_type NONE; fan_type NONE; air_temperature 70; mass_temperature 70;"

def test_autotest(helpers):
    """gridlabd's test_zipload_pow_en_hg: power, energy, and heat gain of a
    ZIP load, its house panel, and its meter"""
    r = helpers.run_file("test_zipload_pow_en_hg.glm")
    assert r.returncode == 0, r.stderr
    m = r.model
    zip_ = [x for x in m.objects if m.objects[x].oclass.name == "ZIPload"][0]
    assert residential.get_complex(m, zip_, "energy") == pytest.approx(24+0.812533j, abs=1e-6)

def test_parts(helpers):
    """The parts at their power factors, the total, its power factor, the
    actual power at the circuit voltage, and the heat gain"""
    r = helpers.run(f"""
        object house {{ name h; {HOUSE}
            object ZIPload {{ name z; base_power 2; multiplier 1.5; power_fraction 0.5; current_fraction 0.3; impedance_fraction 0.2;
                power_pf -0.9; current_pf 0.8; impedance_pf 1; heat_fraction 0.6; }};
        }}
        """, stop="2020-01-01 00:10:00")
    assert r.returncode == 0, r.stderr
    m = r.model
    get = lambda p: residential.get_complex(m, "z", p) # pylint: disable=unnecessary-lambda-assignment
    q = lambda pf: math.sqrt(1/pf**2 - 1) # pylint: disable=unnecessary-lambda-assignment
    assert get("constant_power") == pytest.approx(complex(1.5, -1.5*q(0.9)))
    assert get("constant_current") == pytest.approx(complex(0.9, 0.9*q(0.8)))
    assert get("constant_admittance") == pytest.approx(0.6)
    total = complex(3, -1.5*q(0.9) + 0.9*q(0.8))
    assert get("power") == pytest.approx(total)
    assert get("actual_power") == pytest.approx(total) # 120 V without a meter
    assert residential.get_double(m, "z", "power_factor") == pytest.approx(-math.cos(math.atan2(total.imag, total.real))) # leading: negative
    assert residential.get_double(m, "z", "heatgain") == pytest.approx(3*0.6*3412)

def test_duty_cycle(helpers):
    """A duty cycle of 0.25 over 1 h: on 15 minutes of each hour"""
    r = helpers.run(f"""
        object house {{ name h; {HOUSE}
            object ZIPload {{ name z; base_power 1; duty_cycle 0.25; period 1; phase 0;
                object recorder {{ property power; interval 60; file "z.csv"; }};
            }};
        }}
        """, stop="2020-01-01 04:00:00")
    assert r.returncode == 0, r.stderr
    powers = [complex(row[1].replace("i", "j")).real for row in helpers.read_csv("z.csv")]
    assert sum(powers)/len(powers) == pytest.approx(0.25, abs=0.02)
    assert residential.get_complex(r.model, "z", "energy").real == pytest.approx(1.0, abs=0.05)

def test_heatgain_only(helpers):
    """`heatgain_only`: heat gain without electric load"""
    m = helpers.run(f"object house {{ name h; {HOUSE} object ZIPload {{ name z; base_power 2; heatgain_only TRUE; }}; }}", stop="2020-01-01 00:10:00").model
    assert residential.get_complex(m, "z", "power") == 0
    assert residential.get_double(m, "z", "heatgain") == pytest.approx(2*3412)
    assert m.get_property("z", "configuration") != "IS110"

def test_no_house(helpers):
    """Without a house, the load is computed at a voltage factor of 1"""
    r = helpers.run("object ZIPload { name z; base_power 1; }", stop="2020-01-01 01:00:00")
    assert r.returncode == 0, r.stderr
    assert residential.get_complex(r.model, "z", "power") == pytest.approx(1)

def test_not_house_parent(helpers):
    """A parent that is not a house warns"""
    r = helpers.run("object triplex_meter { name meter; phases AS; nominal_voltage 120; bustype SWING; object ZIPload { name z; base_power 1; }; }",
        stop="2020-01-01 00:10:00")
    assert any("does not export attach_enduse function" in x for x in helpers.warnings(r)), r.stderr

def test_demand_response(helpers):
    """The demand response population keeps the number of devices"""
    r = helpers.run(f"""
        object house {{ name h; {HOUSE}
            object ZIPload {{ name z; base_power 10; demand_response_mode TRUE; number_of_devices 100; thermostatic_control_range 10;
                phi 0.3; demand_rate 0.1; rate_of_cooling 0.5; rate_of_heating 0.8; }};
        }}
        """, stop="2020-01-01 06:00:00")
    assert r.returncode == 0, r.stderr
    m = r.model
    on, off = residential.get_double(m, "z", "number_of_devices_on"), residential.get_double(m, "z", "number_of_devices_off")
    assert on + off == pytest.approx(100)
    assert residential.get_double(m, "z", "nominal_power") == pytest.approx(10*on/100)
    assert any("experimental model" in x for x in helpers.warnings(r))

@pytest.mark.parametrize("value,message", [("duty_cycle 2", "outside of 0-1"), ("duty_cycle 0.5; period 0", "Period is less than or equal to zero")])
def test_init_errors(helpers, value, message):
    """Invalid duty cycle settings fail the initialization"""
    r = helpers.run(f"object house {{ name h; {HOUSE} object ZIPload {{ name z; base_power 1; {value}; }}; }}")
    assert r.returncode != 0
    assert any(message in x for x in helpers.errors(r))
