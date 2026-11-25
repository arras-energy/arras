"""`arras` against values written by gridlabd (`data/reference/`)

The reference files were written by gridlabd's `recorder` objects (see
`data/reference/make_reference.py`); each test runs the same model in
`arras` and compares every recorded value, within the 6 significant
digits that the recorders write.
"""

import os
import shutil

import pytest

import climate_test_files as files

TMY = [
    # reference, file, interpolate, start, stop, interval
    ("yakima_none", "WA-Yakima_Air_Terminal.tmy3", "NONE", "2006-03-26 00:00:00", "2006-04-09 00:00:00", 3600),
    ("yakima_linear", "WA-Yakima_Air_Terminal.tmy3", "LINEAR", "2006-04-01 00:00:00", "2006-04-03 00:00:00", 900),
    ("yakima_quadratic", "WA-Yakima_Air_Terminal.tmy3", "QUADRATIC", "2006-10-28 00:00:00", "2006-10-30 00:00:00", 900),
    ("yakima_tmy2_none", "yakima.tmy2", "NONE", "2006-07-01 00:00:00", "2006-07-03 00:00:00", 3600),
]

CSV = [
    # reference, file, reader options, start, stop, interval, time zone
    ("csv_weather", "weather.csv", "", "2001-01-01 00:00:00", "2001-01-02 00:00:00", 3600, "America/Los_Angeles"),
    ("csv_weather_dst", "weather_dst.csv", "", "2001-06-30 20:00:00", "2001-07-03 00:00:00", 1800, "America/Los_Angeles"),
    ("csv_year_wrap", "year.csv", "", "2001-12-30 00:00:00", "2002-01-03 00:00:00", 3600, "America/Los_Angeles"),
    ("csv_year_leap", "year.csv", "", "2004-02-27 00:00:00", "2004-03-02 00:00:00", 3600, "America/New_York"),
    ("csv_fmt", "fmt.csv", 'timefmt "%hd/%hd-%hd"; columns "temperature,humidity,solar_direct";',
        "2004-02-26 00:00:00", "2004-03-04 00:00:00", 3600, "America/Los_Angeles"),
]

@pytest.fixture(name="folder")
def fixture_folder(tmp_path, monkeypatch):
    """A folder with the weather files of the reference cases"""
    for name in ("WA-Yakima_Air_Terminal.tmy3", "weather.csv", "weather_dst.csv", "generators.glm"):
        shutil.copy(os.path.join(files.DATA, name), tmp_path)
    files.make_tmy2(str(tmp_path / "yakima.tmy2"))
    files.make_year_csv(str(tmp_path / "year.csv"))
    files.make_fmt_csv(str(tmp_path / "fmt.csv"))
    monkeypatch.chdir(tmp_path)
    return tmp_path

@pytest.mark.parametrize("case", TMY, ids=[x[0] for x in TMY])
def test_tmy(case, folder, helpers): # pylint: disable=unused-argument
    """TMY values, solar position, and flux match gridlabd"""
    name, file, mode, start, stop, interval = case
    columns, expected = helpers.reference(name)
    m = helpers.model(f'object climate {{ name site; tmyfile "{file}"; interpolate {mode}; }}', start=start, stop=stop)
    helpers.add_ticker(m, interval)
    runner, rows = helpers.sample(m, "site", columns)
    assert runner.returncode == 0, runner.stderr
    assert len(expected) > 40
    assert helpers.mismatches(expected, rows, columns) == []

@pytest.mark.parametrize("case", CSV, ids=[x[0] for x in CSV])
def test_csv(case, folder, helpers): # pylint: disable=unused-argument
    """CSV samples, solar position, and flux match gridlabd"""
    name, file, options, start, stop, interval, zone = case
    columns, expected = helpers.reference(name)
    m = helpers.model(f"""object csv_reader {{ name reader; filename "{file}"; {options} }}
object climate {{ name site; tmyfile "{file}"; reader reader; }}""", start=start, stop=stop, timezone=zone)
    helpers.add_ticker(m, interval)
    runner, rows = helpers.sample(m, "site", columns)
    assert runner.returncode == 0, runner.stderr
    assert len(expected) > 20
    assert helpers.mismatches(expected, rows, columns) == []

SOLAR = {
    "solar_position": ("calculate_solar_radiation_shading_position_radians", (30, 180-200)),
    "solar_solpos": ("calculate_solpos_radiation_shading_position_radians", (30, 200)),
    "solar_ideal": ("calc_solar_ideal_shading_position_radians", (30,)),
}

def test_solar_functions(folder, helpers): # pylint: disable=unused-argument
    """The class functions give the insolation of gridlabd's `solar` objects"""
    m = helpers.model('object climate { name Yakima; tmyfile "WA-Yakima_Air_Terminal.tmy3"; }\n#include "generators.glm"',
        start="2006-05-01 00:00:00", stop="2006-05-03 00:00:00")
    m.read_glm("""
object solar { name solar_position; tilt_angle 30; orientation_azimuth 200; orientation FIXED_AXIS; latitude 46.6; longitude -120.5; }
object solar { name solar_solpos; tilt_angle 30; orientation_azimuth 200; orientation FIXED_AXIS; SOLAR_TILT_MODEL SOLPOS; latitude 46.6; longitude -120.5; }
object solar { name solar_ideal; tilt_angle 30; orientation DEFAULT; latitude 46.6; longitude -120.5; }
""")
    helpers.add_ticker(m, 900)
    names = ["solar_position", "solar_solpos", "solar_ideal"]
    runner, rows = helpers.sample(m, names, ["Insolation"])
    assert runner.returncode == 0, runner.stderr
    for index, name in enumerate(names):
        columns, expected = helpers.reference(name)
        assert len(expected) == 192
        actual = {key: [values[index]] for key, values in rows.items()}
        assert helpers.mismatches(expected, actual, columns, atol=1e-6) == [], name
