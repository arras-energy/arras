"""The gridlabd `generators` module autotests, ported to `arras`

Each GLM file in `data/` named `test_*.glm` is a gridlabd autotest from
`module/generators/autotest/` with the changes listed in
`data/README.md`. Each must succeed with no error lines, except
`test_solar_parent_err.glm`, which must fail as it does in gridlabd. The
tests below also check that the asserts of each autotest detect a change
of the model.
"""

import os
import glob

import pytest

from arras import exitcodes
from arras.model import Model
from arras.runner import Runner

from conftest import DATA, errors

TESTS = sorted(os.path.basename(x) for x in glob.glob(os.path.join(DATA, "test_*.glm")))

def test_files():
    """The autotests that the ported classes and the Yakima weather file
    allow are ported"""
    assert TESTS == ["test_4quad_inv_modes_PF_PQ_default_efficiency.glm",
        "test_4quad_inv_modes_PF_PQ_multipoint_efficiency.glm", "test_Vout_PV.glm",
        "test_Vout_PV_solar_no_Parent.glm", "test_multipoint_inverter.glm", "test_solar_climate_default_playerval.glm",
        "test_solar_parent_err.glm"]

@pytest.mark.parametrize("file", [x for x in TESTS if not x.endswith("_err.glm")])
def test_autotest(file, data): # pylint: disable=unused-argument
    """Each autotest succeeds with no error lines"""
    runner = Runner(file)
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert not errors(runner)

def test_solar_parent_err(data): # pylint: disable=unused-argument
    """An array whose parent is not an inverter fails at init"""
    runner = Runner("test_solar_parent_err.glm")
    assert runner.returncode == exitcodes.INIERR
    assert errors(runner)[0] == "init_solar(obj=8;sol_inv_B_2_645): Solar panel can only have an inverter as its parent."

@pytest.mark.parametrize("file,name,prop,value", [
    ("test_Vout_PV.glm", "sol_inv_B_2_645", "V_Max", "80+0j"),
    ("test_Vout_PV_solar_no_Parent.glm", "sol_inv_B_2_645", "V_Max", "80+0j"),
    ("test_multipoint_inverter.glm", "trip_lat", "inverter_manufacturer", "SMA"),
    ("test_multipoint_inverter.glm", "trip_lat_solar", "area", "28 m^2"),
    ("test_4quad_inv_modes_PF_PQ_default_efficiency.glm", "const_pq_inv", "rated_power", "1200"),
    ("test_4quad_inv_modes_PF_PQ_default_efficiency.glm", "const_pf_inv", "I_In", "15.2+0j"),
    ("test_4quad_inv_modes_PF_PQ_multipoint_efficiency.glm", "const_pq_inv", "inverter_manufacturer", "FRONIUS"),
    ("test_4quad_inv_modes_PF_PQ_multipoint_efficiency.glm", "sol_inv_B_2_645", "area", "300"),
])
def test_asserts_detect_changes(file, name, prop, value, data): # pylint: disable=unused-argument,too-many-arguments,too-many-positional-arguments
    """Changing an input of the model makes an assert fail"""
    model = Model(file)
    model.set_property(name, prop, value)
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.RUNERR, runner.stderr
    assert any(x.startswith("Assert failed") for x in errors(runner))

@pytest.mark.parametrize("name,prop,value", [("trip_shad_solar1", "area", "28 m^2"), ("trip_shad_solar2", "tilt_angle", "40")])
def test_playerval_asserts_detect_changes(name, prop, value, data): # pylint: disable=unused-argument
    """The asserts of the year-long player autotest detect a change in its
    first week"""
    model = Model("test_solar_climate_default_playerval.glm")
    model.globals.set("stoptime", model.globals.timestamp_from_string("2009-01-08 00:00:00"))
    assert Runner(model=model).returncode == exitcodes.SUCCESS
    model = Model("test_solar_climate_default_playerval.glm")
    model.globals.set("stoptime", model.globals.timestamp_from_string("2009-01-08 00:00:00"))
    model.set_property(name, prop, value)
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.RUNERR, runner.stderr
    assert any(x.startswith("Assert failed") for x in errors(runner))
