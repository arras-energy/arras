"""Class `climate`: initialization, presync, messages, and functions"""

import os
import math
import shutil

import pytest

import climate
from climate.climate import Climate, heat_index, find_weather_file, state, RT_TMY2, RT_CSV
from arras import exitcodes
from arras.runner import Runner

YAKIMA_OBJECT = 'object climate { name y; tmyfile "WA-Yakima_Air_Terminal.tmy3"; }'

def errors(runner):
    """Error and warning lines without their prefixes"""
    return [x.split("]: ", 1)[1] for x in runner.stderr]

def test_manual(helpers):
    """An empty `tmyfile` keeps the model's values and asks for no event"""
    r = helpers.run('object climate { name c; tmyfile ""; temperature 70; }', stop="2006-01-02 00:00:00")
    assert r.returncode == 0 and r.steps == 1
    assert r.model.get_property("c", "temperature") == "70"
    assert r.model.get_property("c", "heat_index") == "0.0"

def test_tmy_init(data, helpers): # pylint: disable=unused-argument
    """A TMY3 file gives the location, the records of extremes, and the
    values at the start"""
    r = helpers.run(YAKIMA_OBJECT)
    assert r.returncode == 0 and r.stderr == []
    m = r.model
    assert helpers.number(m.get_property("y", "latitude")) == pytest.approx(46 + 34/60)
    assert helpers.number(m.get_property("y", "longitude")) == pytest.approx(-120 - 33/60)
    assert helpers.number(m.get_property("y", "record.low")) == pytest.approx(-2.918, abs=1e-3)
    assert helpers.number(m.get_property("y", "record.high")) == pytest.approx(100.042, abs=1e-3)
    assert m.get_property("y", "record.low_day") == "360"
    assert m.get_property("y", "record.high_day") == "203"
    assert helpers.number(m.get_property("y", "temperature")) == pytest.approx(28.942, abs=1e-3)
    st = state(m, "y")
    assert st.reader_type == RT_TMY2 and not st.is_tmy2 and st.tz_meridian == -120

def test_file_not_found(helpers):
    """A weather file that is not found fails the initialization"""
    r = helpers.run('object climate { name c; tmyfile "missing.tmy3"; }')
    assert r.returncode == exitcodes.INIERR
    assert errors(r)[0] == "c: weather file 'missing.tmy3' access failed"

def test_library_path(tmp_path, helpers, monkeypatch):
    """Weather files are found in the folders of `climate::library_path`"""
    folder = tmp_path / "weather"
    folder.mkdir()
    shutil.copy(os.path.join(helpers.DATA, helpers.YAKIMA), folder)
    monkeypatch.chdir(tmp_path)
    m = helpers.model(YAKIMA_OBJECT)
    assert find_weather_file(m, helpers.YAKIMA) is None
    m.globals.set("climate::library_path", f"/nowhere:{folder}")
    assert find_weather_file(m, helpers.YAKIMA) == str(folder / helpers.YAKIMA)
    assert Runner(model=m).returncode == 0

def test_unknown_extension(tmp_path, helpers, monkeypatch):
    """A file that is not a TMY or CSV file is read as a TMY2 file, whose
    extension is refused"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data.txt").write_text("x\n")
    r = helpers.run('object climate { name c; tmyfile "data.txt"; }')
    assert r.returncode == exitcodes.INIERR
    assert errors(r)[:-1] == ["c: climate: unrecognized filetype, assuming TMY2",
        "tmy2_reader::open(file='data.txt'): unknown TMY file type (extension '.txt' is not recognized)",
        "c: climate::init() -- weather file header improperly formed"]

@pytest.mark.parametrize("latitude,longitude,message", [
    ("95.0", "-120.5", "Latitude is outside +/-90!"),
    ("45.0", "-190.5", "Longitude is outside +/-180!"),
])
def test_location_checks(tmp_path, helpers, monkeypatch, latitude, longitude, message):
    """A location out of range fails the initialization"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bad.tmy3").write_text(f'1,"X",XX,-8.0,{latitude},{longitude},10\n')
    r = helpers.run('object climate { tmyfile "bad.tmy3"; }')
    assert r.returncode == exitcodes.INIERR
    assert errors(r)[-2] == f"climate:0: climate:(null) - {message}"

def test_short_file(tmp_path, helpers, monkeypatch):
    """A TMY file with fewer than 8760 records gives an error line and
    still runs; a southern latitude gives a warning; records out of range
    give a warning"""
    monkeypatch.chdir(tmp_path)
    with open(os.path.join(helpers.DATA, helpers.YAKIMA), encoding="utf-8") as fh:
        lines = fh.readlines()[:26]
    lines[0] = lines[0].replace("46.567", "-46.567")
    lines.append("13/01/1990,01:00" + lines[3][16:])
    (tmp_path / "short.tmy3").write_text("".join(lines))
    r = helpers.run('object climate { name s; tmyfile "short.tmy3"; }')
    assert r.returncode == 0
    assert errors(r)[0] == "s: climate:s - Southern hemisphere solar position model may have issues"
    assert errors(r)[1].startswith("s: short.tmy3(24): hour ")
    assert errors(r)[-1] == "s: short.tmy3(25): unable to read a full year of data"
    assert helpers.number(r.model.get_property("s", "latitude")) == pytest.approx(-46 - 34/60)

def test_tmy2_warnings(tmp_path, helpers, monkeypatch):
    """A TMY2 file gives gridlabd's two warnings and no hour shift"""
    import climate_test_files # pylint: disable=import-outside-toplevel
    monkeypatch.chdir(tmp_path)
    climate_test_files.make_tmy2(str(tmp_path / "y.tmy2"))
    r = helpers.run('object climate { name y; tmyfile "y.tmy2"; }')
    assert r.returncode == 0
    assert errors(r) == ["daylight saving time (DST) is not handled correctly when using TMY2 datasets; please use TMY3 for DST-corrected weather data.",
        "y: TMY2 files exhibit unpredictable behavior, please use TMY3 file format."]
    assert state(r.model, "y").is_tmy2

def test_quadratic_clipping(data, helpers): # pylint: disable=unused-argument
    """Quadratic interpolation clips negative values with a verbose message
    for objects with the VERBOSE flag"""
    glm = 'object climate { name y; flags VERBOSE; tmyfile "WA-Yakima_Air_Terminal.tmy3"; interpolate QUADRATIC; }'
    m = helpers.model(glm, start="2006-06-09 05:45:00")
    m.globals.set("verbose", True)
    r = Runner(model=m)
    assert r.returncode == 0
    assert any("Quadratic interpolation caused the" in x for x in r.stderr)
    m = helpers.model(glm.replace(" flags VERBOSE;", ""), start="2006-06-09 05:45:00")
    m.globals.set("verbose", True)
    assert not any("Quadratic" in x for x in Runner(model=m).stderr)

def test_heat_index():
    """The heat index follows the NOAA equation and its adjustments"""
    assert heat_index(70, 0.5) == pytest.approx(0.75*70 + 0.25*(61+1.2*2+0.094*50))
    assert heat_index(90, 0.5) == pytest.approx(94.6, abs=0.1)
    assert heat_index(100, 0.10) < heat_index(100, 0.13)
    assert heat_index(85, 0.90) == pytest.approx(101.78, abs=0.01)

def test_cloud_init_checks(data, helpers, monkeypatch): # pylint: disable=unused-argument
    """The cloud model's properties are set to their limits with warnings"""
    monkeypatch.setattr(climate.cloud, "TILE_SIZE", 32)
    r = helpers.run('''object climate { name y; tmyfile "WA-Yakima_Air_Terminal.tmy3"; cloud_model CUMULUS;
        cloud_opacity 2; cloud_speed_factor -1; cloud_alpha 10; cloud_aerosol_transmissivity 2; }''')
    assert r.returncode == 0
    assert errors(r) == ["y: climate:y - Cloud opacity must be no greater than 1.0, setting to 1.0",
        "y: climate:y - Cloud speed adjustment cannot be negative, setting to 1.0",
        "y: climate:y - Cloud model alpha value must be less than or equal to cloud_num_layers, setting to cloud_num_layers",
        "y: climate:y - Cloud model aerosol transmissivity must be less than or equal to 1, setting to 1",
        "y: This cloud model places a large burden on computational resources. Patience and/or a more capable computer may be required."]
    m = r.model
    assert [helpers.number(m.get_property("y", x)) for x in ("cloud_opacity", "cloud_speed_factor", "cloud_alpha",
        "cloud_aerosol_transmissivity")] == [1.0, 1.0, 40.0, 1.0]
    r = helpers.run('''object climate { name y; tmyfile "WA-Yakima_Air_Terminal.tmy3"; cloud_model CUMULUS;
        cloud_opacity -1; cloud_aerosol_transmissivity -1; }''')
    assert errors(r)[:2] == ["y: climate:y - Cloud opacity must be no less than 0.0, setting to 0.0",
        "y: climate:y - Cloud model aerosol transmissivity must be greater than or equal to 0, setting to default value of 0.9"]

def test_cloud_events(data, helpers, monkeypatch): # pylint: disable=unused-argument
    """The cloud model asks for an event every minute"""
    monkeypatch.setattr(climate.cloud, "TILE_SIZE", 64)
    r = helpers.run('object climate { name y; tmyfile "WA-Yakima_Air_Terminal.tmy3"; cloud_model CUMULUS; }',
        start="2006-06-01 12:00:00", stop="2006-06-01 12:05:00")
    assert r.returncode == 0 and r.steps == 6
    # without a file the presync result is 0, which stops the run, as in gridlabd
    r = helpers.run('object climate { name c; tmyfile ""; cloud_model CUMULUS; }',
        start="2006-06-01 12:00:00", stop="2006-06-01 12:02:00")
    assert r.returncode == exitcodes.RUNERR
    assert errors(r)[-1] == "object c stopped its clock (its presync handler returned 0)"

def test_csv_with_cloud(data, helpers, monkeypatch): # pylint: disable=unused-argument
    """With a CSV file and the cloud model, the earlier event is used"""
    monkeypatch.setattr(climate.cloud, "TILE_SIZE", 32)
    r = helpers.run('''object csv_reader { name r; filename "weather.csv"; }
object climate { name c; tmyfile "weather.csv"; reader r; cloud_model CUMULUS; }''',
        start="2001-01-01 00:30:00", stop="2001-01-01 01:30:00")
    assert r.returncode == 0 and r.steps == 61

#
# Functions
#
def test_functions_not_climate(helpers):
    """The functions return `None` for objects that are not climate objects"""
    m = helpers.model("object weather { name w; }")
    for name, call in Climate.register.__globals__["FUNCTIONS"].items():
        args = {"calc_solar_ideal_shading_position_radians": 4}.get(name, 5 if "position" in name else
            (3 if "shading" in name else 2))
        assert call(m, "w", *([0.0]*args)) is None, name
        assert call(m, "missing", *([0.0]*args)) is None, name

def test_functions_outside_run(data, helpers): # pylint: disable=unused-argument
    """Outside a run the functions use the object's clock; the degree and
    radian forms agree"""
    m = helpers.model(YAKIMA_OBJECT, start="2006-06-01 12:00:00")
    Runner(model=m)
    f = m.classes["climate"].functions
    value = f["calculate_solar_radiation_degrees"](m, "y", 30, 20)
    assert value == pytest.approx(f["calculate_solar_radiation_radians"](m, "y", math.radians(30), math.radians(20)))
    assert value == pytest.approx(f["calculate_solar_radiation_shading_degrees"](m, "y", 30, 20, 1.0))
    assert value > 0
    solpos = climate.climate.calc_solar_solpos_shading_deg(m, "y", 30, 200, 1.0)
    assert solpos == pytest.approx(climate.climate.calc_solar_solpos_shading_rad(m, "y", math.radians(30), math.radians(200), 1.0))
    assert solpos > 0

def test_cloud_location(data, helpers, monkeypatch): # pylint: disable=unused-argument
    """With the cloud model, a location outside the pattern, or a climate
    object without a pattern, raises `ClimateError`; a location inside
    gives the cloud irradiance"""
    monkeypatch.setattr(climate.cloud, "TILE_SIZE", 32)
    m = helpers.model('''object climate { name y; tmyfile "WA-Yakima_Air_Terminal.tmy3"; cloud_model CUMULUS; }
class solar { double x; }
object solar { name s; latitude 46.6; longitude -120.5; }''', start="2006-06-01 12:00:00")
    assert Runner(model=m).returncode == 0
    ideal = m.classes["climate"].functions["calc_solar_ideal_shading_position_radians"]
    assert ideal(m, "y", 0.0, 46.6, -120.5, 1.0) > 0
    assert helpers.number(m.get_property("y", "solar_cloud_global")) > 0
    with pytest.raises(climate.ClimateError):
        ideal(m, "y", 0.0, 10.0, 10.0, 1.0)
    with pytest.raises(climate.ClimateError):
        ideal(m, "y", 0.0, math.nan, math.nan, 1.0)
    m = helpers.model('object climate { name c; tmyfile ""; cloud_model CUMULUS; }')
    with pytest.raises(climate.ClimateError):
        ideal(m, "c", 0.0, 0.0, 0.0, 1.0)

def test_solar_flux(data, helpers): # pylint: disable=unused-argument
    """`solar_flux()` gives the nine surfaces; the property is the first"""
    m = helpers.model(YAKIMA_OBJECT, start="2006-06-01 12:00:00")
    Runner(model=m)
    flux = climate.solar_flux(m, "y")
    assert len(flux) == 9
    assert flux[0] == helpers.number(m.get_property("y", "solar_flux"))
    assert flux[5] > flux[1]

def test_reader_type(data, helpers): # pylint: disable=unused-argument
    """A `.csv` file is read through the reader"""
    r = helpers.run('object csv_reader { name r; filename "weather.csv"; }\nobject climate { name c; tmyfile "weather.csv"; reader r; }',
        start="2001-01-01 00:00:00")
    assert state(r.model, "c").reader_type == RT_CSV

def test_records_cache(tmp_path, helpers, monkeypatch):
    """A TMY file read again gives the same records and messages; a file
    that changed is read again"""
    monkeypatch.chdir(tmp_path)
    with open(os.path.join(helpers.DATA, helpers.YAKIMA), encoding="utf-8") as fh:
        lines = fh.readlines()
    lines[5] = lines[5][:16] + ",1\n"
    (tmp_path / "y.tmy3").write_text("".join(lines))
    first = helpers.run('object climate { name y; tmyfile "y.tmy3"; }')
    second = helpers.run('object climate { name y; tmyfile "y.tmy3"; }')
    assert first.stderr == second.stderr
    assert "TMY reader did not get 17 values for line time 1/1 400" in errors(first)
    (tmp_path / "y.tmy3").write_text("".join(lines[:2] + lines[3:]))
    third = helpers.run('object climate { name y; tmyfile "y.tmy3"; }')
    assert errors(third)[-1] == "y: y.tmy3(8759): unable to read a full year of data"
