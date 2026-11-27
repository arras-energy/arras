"""`solar` against values that gridlabd wrote

The `climate` package's reference files `solar_position.csv`,
`solar_solpos.csv`, and `solar_ideal.csv` (in
`src/climate/_test/data/reference/`, made by its `make_reference.py` with a
gridlabd build of master 076e78a) hold the `Insolation` that gridlabd
`solar` objects recorded every 15 minutes for two days with the Yakima
weather. The same model, run with this package, records the same values.
"""

import os
import csv
import shutil

import pytest

from arras.runner import Runner

from conftest import CLIMATE_DATA

REFERENCE = os.path.join(CLIMATE_DATA, "reference")

CASES = [
    ("solar_position", "orientation FIXED_AXIS; SOLAR_TILT_MODEL DEFAULT; orientation_azimuth 200;"),
    ("solar_solpos", "orientation FIXED_AXIS; SOLAR_TILT_MODEL SOLPOS; orientation_azimuth 200;"),
    ("solar_ideal", "orientation DEFAULT;"),
]
"""The solar objects of `make_reference.py`"""

SOLAR = """
object triplex_meter {{ name tm{i}; phases AS; voltage_1 120; voltage_2 120; voltage_N 0; nominal_voltage 120; bustype SWING; }}
object triplex_meter {{ name tpm{i}; phases AS; parent tm{i}; nominal_voltage 120; }}
object inverter {{ name inv{i}; phases CS; parent tpm{i}; rated_power 2500000; }}
object solar {{ name {name}; parent inv{i}; area 141.76 ft^2; tilt_angle 30.0; efficiency 0.05;
    SOLAR_POWER_MODEL FLATPLATE; {options} latitude 46.6; longitude -120.5;
    object recorder {{ file "{name}.csv"; interval 900; property Insolation; }}; }}
"""
"""`make_reference.py`'s solar object; the first triplex meter is a swing
bus here, since `arras` needs one (gridlabd's FBS run had none)"""

def read(path:str) -> dict[str,float]:
    """Recorded values by time"""
    with open(path, encoding="utf-8") as fh:
        rows = [x for x in csv.reader(fh) if x and not x[0].startswith("#")]
    return {row[0]: float(row[1]) for row in rows}

def test_insolation(tmp_path):
    """Every recorded insolation matches gridlabd's"""
    shutil.copy(os.path.join(CLIMATE_DATA, "WA-Yakima_Air_Terminal.tmy3"), tmp_path)
    glm = """clock { timezone "America/Los_Angeles"; starttime '2006-05-01 00:00:00'; stoptime '2006-05-03 00:00:00'; }
module tape;
module powerflow { solver_method NR; default_maximum_voltage_error 1e-9; line_limits FALSE; };
module generators;
module climate;
object climate { name Yakima; tmyfile "WA-Yakima_Air_Terminal.tmy3"; }
"""
    for i, (name, options) in enumerate(CASES):
        glm += SOLAR.format(i=i, name=name, options=options)
    (tmp_path / "model.glm").write_text(glm)
    runner = Runner("model.glm")
    assert runner.returncode == 0, runner.stderr
    for name, _ in CASES:
        expected = read(os.path.join(REFERENCE, f"{name}.csv"))
        actual = read(str(tmp_path / f"{name}.csv"))
        assert len(expected) == 192
        assert set(expected) <= set(actual), name  # arras's recorder also writes the stop time
        assert max(abs(expected[t]) for t in expected) > 50, name
        for t, value in expected.items():
            assert actual[t] == pytest.approx(value, rel=1e-5, abs=1e-6), (name, t)
