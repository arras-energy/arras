"""Fixtures for the `assert` module tests"""

import pytest

from arras.oclass import Class
from arras.module import Module
from arras.model import Model
from arras.runner import Runner

CLOCK = """
clock {
    timezone "America/Los_Angeles";
    starttime "2001-01-01 00:00:00";
    stoptime "2001-01-01 00:00:00";
}
module assert;
"""
"""GLM header of the tests: one time step, and the module loaded"""

@pytest.fixture(autouse=True)
def reset():
    """Start each test with empty class and module registries"""
    Class.reset()
    Module.reset()
    yield
    Class.reset()
    Module.reset()

def run(glm:str, *args:str, header:bool=True) -> Runner:
    """Read GLM text (after `CLOCK` when `header` is true) and run it"""
    model = Model()
    model.read_glm((CLOCK if header else "") + glm)
    return Runner(*args, model=model)

@pytest.fixture(name="run")
def fixture_run():
    """The `run()` helper"""
    return run
