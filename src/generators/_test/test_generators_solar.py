"""Class `solar`: init checks and defaults, the power models, and the weather"""

import math

import pytest

from arras import exitcodes
from pypower._common import get_double, get_complex

from conftest import run, errors, warnings

PLAYER = """object solar {{
    name pv;
    SOLAR_TILT_MODEL PLAYERVALUE;
    generator_mode SUPPLY_DRIVEN;
    generator_status ONLINE;
    panel_type {panel};
    {extra}
}}
"""

def player_solar(panel="SINGLE_CRYSTAL_SILICON", extra="", **kwargs):
    """Run one solar object in player mode"""
    return run(PLAYER.format(panel=panel, extra=extra), **kwargs)

def test_base_efficiency_model():
    """The default power model, temperature correction, and output voltage"""
    m, r = player_solar(extra="rated_power 1000 W; Insolation 80 W/sf; ambient_temperature 70 degF; V_Max 30; Voc_Max 36;")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    coeff = -0.00437/33.8
    tmodule = 70 + (118.4-68)/74.32*80
    power = 1000*80/92.902*(1 + coeff*(tmodule-77))*0.95*0.95
    assert get_double(m, "pv", "Tmodule") == pytest.approx(tmodule, rel=1e-12)
    assert get_complex(m, "pv", "VA_Out") == pytest.approx(complex(power, 0), rel=1e-12)
    voc = 36*(1 + (-0.00393/33.8)*(tmodule-77))
    assert get_complex(m, "pv", "V_Out") == pytest.approx(complex(30*voc/36, 0), rel=1e-12)
    assert get_complex(m, "pv", "I_Out") == pytest.approx(complex(power/(30*voc/36), 0), rel=1e-12)

def test_flat_plate_model():
    """The flat plate model (cell temperature from insolation and wind)"""
    m, r = player_solar(extra="rated_power 2000 W; SOLAR_POWER_MODEL FLATPLATE; Insolation 90 W/sf; ambient_temperature 77 degF; wind_speed 2 mph;")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    tambient = 15 + (25-15)/2  # first step: the previous temperature is the create() value, 15 degC
    insol = 90*10.7639104*0.95
    tcell = insol*math.exp(-2.81 - 0.0455*2*0.44704) + tambient
    power = 90*0.95*0.95*(2000/92.902)*(1 - 0.5*(tcell-25)/100)
    assert get_double(m, "pv", "Tcell") == pytest.approx(tcell, rel=1e-12)
    assert get_complex(m, "pv", "P_Out") == pytest.approx(complex(power, 0), rel=1e-12)
    assert get_complex(m, "pv", "VA_Out") == pytest.approx(complex(power, 0), rel=1e-12)

def test_flat_plate_temperature_history(tmp_path):
    """The ambient temperature is the average of the last two shifted
    values; the object's clock moves at each bottom-up pass, so the second
    step does not shift (gridlabd's sync_solar())"""
    (tmp_path / "amb.player").write_text("2020-06-01 00:00:00,59\n2020-06-01 01:00:00,77\n2020-06-01 02:00:00,95\n")
    m, r = player_solar(extra='rated_power 2000 W; SOLAR_POWER_MODEL FLATPLATE; Insolation 0 W/sf;\n object player { property ambient_temperature; file "amb.player"; };',
        start="2020-06-01 00:00:00", stop="2020-06-01 02:00:00", modules="module tape;\nmodule generators;")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    # step 1: 15 and 15 degC; step 2: no shift; step 3: 15 and 35 degC
    assert get_double(m, "pv", "Tambient") == pytest.approx((15 + 35)/2)

def test_init_defaults_and_warnings():
    """Unset mode, status, and panel type are set with gridlabd's warnings"""
    m, r = run("object solar { name pv; SOLAR_TILT_MODEL PLAYERVALUE; area 100 sf; }")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    assert warnings(r) == [
        "pv: Generator control mode is not specified! Using default: SUPPLY_DRIVEN",
        "pv: Solar panel status is unknown! Using default: ONLINE",
        "pv: Solar panel type is unknown! Using default: SINGLE_CRYSTAL_SILICON",
        "pv: solar panel:0 has no parent defined. Using static voltages.",
        "pv: Solar object:pv is in player mode - be sure to specify relevant values"]
    assert m.get_property("pv", "generator_mode") == "SUPPLY_DRIVEN"
    assert get_double(m, "pv", "efficiency") == 0.2
    assert get_double(m, "pv", "rated_power") == pytest.approx(92.902*0.2*100)

@pytest.mark.parametrize("panel,efficiency", [("MULTI_CRYSTAL_SILICON", 0.15), ("AMORPHOUS_SILICON", 0.07),
    ("THIN_FILM_GA_AS", 0.3), ("CONCENTRATOR", 0.15)])
def test_panel_efficiency(panel, efficiency):
    """Each panel type has its default efficiency"""
    m, r = player_solar(panel=panel, extra="area 10 sf;")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    assert get_double(m, "pv", "efficiency") == efficiency

def test_rated_power_overspecified():
    """A rated power that disagrees with area and efficiency is replaced"""
    m, r = player_solar(extra="rated_power 5000 W; area 100 sf; efficiency 0.2;")
    assert r.returncode == exitcodes.SUCCESS
    assert get_double(m, "pv", "rated_power") == pytest.approx(92.902*0.2*100)
    assert "pv: init(): Rated_kVA, efficiency, Rate_Insolation, and area did not calculated to the same value.  Ignoring Rated_kVA." in warnings(r)

@pytest.mark.parametrize("mode", ["CONSTANT_V", "CONSTANT_PQ", "CONSTANT_PF"])
def test_mode_refused(mode):
    """The array operates only in SUPPLY_DRIVEN mode"""
    _, r = run(f"object solar {{ name pv; generator_mode {mode}; SOLAR_TILT_MODEL PLAYERVALUE; }}")
    assert r.returncode == exitcodes.INIERR
    assert errors(r)[0] == f"pv: Generator control mode is {mode}. The Solar object only operates in SUPPLY_DRIVEN generator control mode."

def test_static_weather():
    """Without a climate object the static values are used; the tilt
    angle's cosine is taken in degrees as radians, as gridlabd does"""
    m, r = player_solar(extra="SOLAR_TILT_MODEL DEFAULT; rated_power 1000 W; tilt_angle 30 deg;")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    assert "pv: solarpanel: no climate data found, using static data" in warnings(r)
    assert get_double(m, "pv", "Insolation") == pytest.approx(92.902 + 92.902 + 92.902*(1 - math.cos(30))*0.2/2)

def test_fixed_axis_needs_climate():
    """FIXED_AXIS without a climate object fails"""
    _, r = player_solar(extra="SOLAR_TILT_MODEL DEFAULT; orientation FIXED_AXIS;")
    assert r.returncode == exitcodes.INIERR
    assert errors(r)[0] == "init_solar(obj=0;pv): FIXED_AXIS requires a climate file!"

def test_weather_not_climate():
    """The weather object must be a climate object"""
    _, r = run("object solar { name x; SOLAR_TILT_MODEL PLAYERVALUE; }\nobject solar { name pv; weather x; panel_type SINGLE_CRYSTAL_SILICON; generator_mode SUPPLY_DRIVEN; generator_status ONLINE; }")
    assert r.returncode == exitcodes.INIERR
    assert 'pv: weather property refers to a(n) "solar" object and not a climate object' in errors(r)

@pytest.mark.parametrize("tilt,message", [(-1, "Invalid tilt_angle - tilt must be between 0 and 90 degrees"),
    (91, "Invalid tilt angle - values above 90 degrees are unsupported!")])
def test_tilt_checked(tilt, message):
    """The tilt angle is between 0 and 90 degrees"""
    _, r = run(f'object climate {{ name w; tmyfile "WA-Yakima_Air_Terminal.tmy3"; }}\nobject solar {{ name pv; tilt_angle {tilt}; panel_type SINGLE_CRYSTAL_SILICON; generator_mode SUPPLY_DRIVEN; generator_status ONLINE; }}',
        modules="module climate;\nmodule generators;", timezone="America/Los_Angeles")
    assert r.returncode == exitcodes.INIERR
    assert errors(r)[0] == f"init_solar(obj=1;pv): {message}"

def test_climate_found_and_latitude_fix():
    """The first climate object is used and written to weather; the tilt
    can be fixed to the site latitude; FIXED_AXIS uses the climate function"""
    m, r = run('object climate { name w; tmyfile "WA-Yakima_Air_Terminal.tmy3"; }\n'
        'object solar { name pv; latitude_angle_fix TRUE; orientation FIXED_AXIS; SOLAR_TILT_MODEL SOLPOS; area 10 m^2; panel_type SINGLE_CRYSTAL_SILICON; generator_mode SUPPLY_DRIVEN; generator_status ONLINE; }',
        modules="module climate;\nmodule generators;", timezone="America/Los_Angeles", start="2010-06-01 12:00:00")
    assert r.returncode == exitcodes.SUCCESS, r.stderr
    assert m.get_property("pv", "weather") == "w"
    assert get_double(m, "pv", "tilt_angle") == pytest.approx(get_double(m, "w", "latitude"))
    assert get_double(m, "pv", "Insolation") > 50
    assert get_double(m, "pv", "ambient_temperature") == get_double(m, "w", "temperature")

def test_shading_checked():
    """A shading factor outside [0, 1] fails the run"""
    _, r = player_solar(extra="shading_factor 2;")
    assert r.returncode == exitcodes.RUNERR
    assert errors(r)[0] == "sync_solar(obj=0;pv): Shading factor outside [0 1] limits in pv"

def test_parent_must_be_inverter():
    """The parent of an array is an inverter"""
    _, r = run("object solar { name pv; SOLAR_TILT_MODEL PLAYERVALUE; }\nobject solar { name pv2; parent pv; SOLAR_TILT_MODEL PLAYERVALUE; }")
    assert r.returncode == exitcodes.INIERR
    assert "init_solar(obj=1;pv2): Solar panel can only have an inverter as its parent." in errors(r)
