"""The gridlabd `climate` module autotests, ported to `arras`

Each GLM file in `data/` named `test_*.glm` is a gridlabd autotest from
`module/climate/autotest/` with the changes listed in `data/README.md`.
Each must succeed with no error lines; the tests below also check what
each autotest leaves unchecked in gridlabd (its recorders write values
that nothing compares).
"""

import os
import glob

import pytest

import climate.cloud
from arras import exitcodes
from arras.model import Model
from arras.runner import Runner

DATA = os.path.join(os.path.dirname(__file__), "data")
TESTS = sorted(os.path.basename(x) for x in glob.glob(os.path.join(DATA, "test_*.glm")))

@pytest.fixture(autouse=True)
def small_clouds(monkeypatch):
    """Cloud patterns of 64-pixel tiles (the autotest's wind moves the
    pattern 25 pixels a minute), so the cloud model test takes seconds"""
    monkeypatch.setattr(climate.cloud, "TILE_SIZE", 64)

def test_files():
    """Every gridlabd autotest of the climate module is ported"""
    assert TESTS == ["test_WA-Yakima-tmy3.glm", "test_cloud_tmy3_opt.glm", "test_csvreader_dst.glm",
        "test_csvreader_exercise_5_1_2.glm", "test_singleHouseSolarInverter.glm", "test_solar_opt.glm"]

@pytest.mark.parametrize("file", TESTS)
def test_autotest(file, data): # pylint: disable=unused-argument
    """Each autotest succeeds with no error lines"""
    runner = Runner(file)
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert not [x for x in runner.stderr if x.startswith("ERROR")]

def test_yakima_asserts(data): # pylint: disable=unused-argument
    """Every assert of test_WA-Yakima-tmy3.glm whose window is in the run
    tests its value: it fails when the value is changed"""
    model = Model("test_WA-Yakima-tmy3.glm")
    asserts = [x for x in model.objects if model.objects[x].oclass.name == "double_assert"]
    assert len(asserts) == 11
    failed = []
    start, stop = model.globals.getvalue("starttime"), model.globals.getvalue("stoptime")
    for name in asserts:
        value = model.get_property(name, "value")
        model.set_property(name, "value", float(value) + 1)
        # run only the assert's window when it is in the run
        window = model.get_property(name, "in_svc")
        if window.startswith("2006"):
            model.globals.set("starttime", model.globals.timestamp_from_string(window))
            model.globals.set("stoptime", model.globals.timestamp_from_string(model.get_property(name, "out_svc")))
        runner = Runner(model=model)
        model.globals.set("starttime", start)
        model.globals.set("stoptime", stop)
        if runner.returncode == exitcodes.RUNERR:
            failed.append(model.get_property(name, "target"))
        model.set_property(name, "value", value)
    # the rainfall assert's window is in 2001, outside the run, in gridlabd too
    assert sorted(failed) == sorted(["temperature", "humidity", "solar_flux", "solar_diffuse",
        "solar_global", "extraterrestrial_direct_normal", "pressure", "wind_speed", "wind_dir", "solar_horiz"])

def _hourly(helpers, file):
    model = Model(file)
    helpers.add_ticker(model, 3600)
    runner, rows = helpers.sample(model, "MyClimate", ["temperature", "humidity"])
    assert runner.returncode == 0, runner.stderr
    return [tuple(helpers.number(x) for x in values) for _, values in sorted(rows.items())]

def test_csvreader_exercise(data, helpers): # pylint: disable=unused-argument
    """test_csvreader_exercise_5_1_2.glm gives the 24 hourly samples of
    weather.csv, then keeps the last until the sample of the next year"""
    with open("weather.csv", encoding="utf-8") as fh:
        samples = [tuple(float(x) for x in line.split(",")[1:3]) for line in fh if line[0].isdigit()]
    assert len(samples) == 24
    assert _hourly(helpers, "test_csvreader_exercise_5_1_2.glm") == samples + [samples[-1]]

def test_csvreader_dst(data, helpers): # pylint: disable=unused-argument
    """test_csvreader_dst.glm starts before the first sample of
    weather_dst.csv (July 1), so the last sample is used all day, as in
    gridlabd"""
    assert _hourly(helpers, "test_csvreader_dst.glm") == [(23.0, 0.1)] * 25

def test_single_house_insolation(data, helpers): # pylint: disable=unused-argument
    """The solar object of test_singleHouseSolarInverter.glm gets the
    insolation of gridlabd's (data/reference/solar_hawaii.csv)"""
    model = Model("test_singleHouseSolarInverter.glm")
    helpers.add_ticker(model, 900)
    runner, rows = helpers.sample(model, "DHHL_3_PV", ["Insolation"])
    assert runner.returncode == 0, runner.stderr
    columns, expected = helpers.reference("solar_hawaii")
    assert len(expected) == 60
    assert helpers.mismatches(expected, rows, columns, atol=1e-6) == []

def test_solar_opt_energy(data): # pylint: disable=unused-argument
    """The asserts of test_solar_opt.glm fail when the expected energy is
    0.2 MWh off"""
    model = Model("test_solar_opt.glm")
    asserts = [x for x in model.objects if model.objects[x].oclass.name == "double_assert"]
    assert len(asserts) == 2
    for name in asserts:
        value = model.get_property(name, "value")
        model.set_property(name, "value", float(value) + 0.2)
        assert Runner(model=model).returncode == exitcodes.RUNERR
        model.set_property(name, "value", value)

def test_cloud_insolation(data, helpers): # pylint: disable=unused-argument
    """The cloud model of test_cloud_tmy3_opt.glm dims the insolation
    between the clear-sky value and half of the direct irradiance
    (opacity 0.5), as the gridlabd autotest's player values do (77.5 to
    126.9 W/sf)"""
    model = Model("test_cloud_tmy3_opt.glm")
    runner, rows = helpers.sample(model, "DHHL_3_PV", ["Insolation"])
    assert runner.returncode == 0, runner.stderr
    assert runner.steps == 10
    values = [helpers.number(x[0]) for x in rows.values()]
    assert all(70 < x < 130 for x in values), values
    direct = helpers.number(model.get_property("Yakima", "solar_cloud_direct"))
    glob_ = helpers.number(model.get_property("Yakima", "solar_cloud_global"))
    assert 0 < direct < glob_
