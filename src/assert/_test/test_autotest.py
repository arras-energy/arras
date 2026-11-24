"""The gridlabd `assert` module autotests, ported to `arras`

Each GLM file in `data/` is a gridlabd autotest from
`module/assert/autotest/` with the changes listed in `README.md`. Files
whose name ends in `_err` must fail with `RUNERR`; the others must succeed.
"""

import os
import glob
import importlib

import pytest

from arras import exitcodes
from arras.model import Model
from arras.runner import Runner

DATA = os.path.join(os.path.dirname(__file__), "data")
TESTS = sorted(os.path.basename(x) for x in glob.glob(os.path.join(DATA, "test_*.glm")))

ERRORS = {
    "test_assert_hold_err.glm": "ERROR [2001-01-01 00:02:00 PST]: assert:1: assert:1: assert failed on 'test:0.random_value..",
    "test_assert_start_err.glm": "ERROR [2001-01-01 00:31:00 PST]: assert:1: assert:1: assert failed on 'test:0.random_value..",
    "test_complex_assert_angle_err.glm": "ERROR [2000-01-01 00:00:00 UTC]: Assert failed on meter:0: Angle of voltage_A (0) not within 0.010000 of given value 0.174533",
    "test_complex_assert_imaginary_err.glm": "ERROR [2000-01-01 00:00:00 UTC]: Assert failed on meter:0: imaginary part of voltage_A +0i not within 1.000000 of given value +10i",
    "test_complex_assert_magnitude_err.glm": "ERROR [2000-01-01 00:00:00 UTC]: Assert failed on meter:0: Magnitude of voltage_A (110) not within 1.000000 of given value 121",
    # the gridlabd autotest named real_err tests the magnitude
    "test_complex_assert_real_err.glm": "ERROR [2000-01-01 00:00:00 UTC]: Assert failed on meter:0: Magnitude of voltage_A (110) not within 1.000000 of given value 121",
    "test_double_assert_err.glm": "ERROR [2000-01-01 00:00:00 UTC]: Assert failed on climate:0: temperature 50 not within 1.000000 of given value 55",
    "test_enum_assert_err.glm": "ERROR [2000-01-01 00:00:00 UTC]: Assert failed on climate:0: interpolate=0 did not match 1",
}

def test_files():
    """Every gridlabd autotest of the assert module is ported"""
    assert len(TESTS) == 15
    assert set(ERRORS) == {x for x in TESTS if x.endswith("_err.glm")}

@pytest.mark.parametrize("file", TESTS)
def test_autotest(file):
    """Each autotest succeeds, or fails with the expected first error"""
    runner = Runner(os.path.join(DATA, file))
    if file.endswith("_err.glm"):
        assert runner.returncode == exitcodes.RUNERR, runner.stderr
        assert runner.stderr[0].startswith(ERRORS[file])
    else:
        assert runner.returncode == exitcodes.SUCCESS, runner.stderr
        assert runner.stderr == []

def test_assert_objects_run():
    """Every assert in test_assert.glm runs: each fails alone when its
    status is FALSE"""
    model = Model(os.path.join(DATA, "test_assert.glm"))
    names = [x for x in model.objects if model.objects[x].oclass.name == "assert"]
    assert len(names) == 53
    for name in names:
        model.set_property(name, "status", "FALSE")
        runner = Runner(model=model)
        assert runner.returncode == exitcodes.RUNERR, name
        assert runner.stderr[0].split("]: ")[1].startswith(f"{name}: {name}: assert failed on NOT '")
        model.set_property(name, "status", "TRUE")
    assert Runner(model=model).returncode == exitcodes.SUCCESS

def test_hold_resets():
    """test_assert_hold.glm holds failures shorter than 30 s"""
    model = Model(os.path.join(DATA, "test_assert_hold.glm"))
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.SUCCESS
    assert runner.steps == 3601
    model.set_property("assert:1", "hold", "0 s")
    assert Runner(model=model).returncode == exitcodes.RUNERR

def test_group_size():
    """test_assert_group.glm checks the 10 objects of class test"""
    model = Model(os.path.join(DATA, "test_assert_group.glm"))
    Runner(model=model)
    state = importlib.import_module("assert._common").get_state(model, "assert:10")
    assert [x.name for x in state.targets] == [f"test:{n}" for n in range(10)]
