"""Fixtures for the `generators` module tests"""

import os
import shutil

import pytest

from arras.oclass import Class
from arras.module import Module
from arras.model import Model
from arras.runner import Runner

DATA = os.path.join(os.path.dirname(__file__), "data")
"""Test data folder"""

CLIMATE_DATA = os.path.join(os.path.dirname(__file__), "..", "..", "climate", "_test", "data")
"""The `climate` test data folder, which holds the Yakima TMY3 file"""

collect_ignore = ["data"]

@pytest.fixture(autouse=True)
def reset(tmp_path, monkeypatch):
    """Start each test in an empty folder with empty class and module
    registries, with the climate test data on `GLPATH`"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GLPATH", os.path.abspath(CLIMATE_DATA))
    Class.reset()
    Module.reset()
    yield
    Class.reset()
    Module.reset()

@pytest.fixture(name="data")
def fixture_data(tmp_path):
    """Copy the test data to the test's folder (the ported autotests write
    recorder files)"""
    for name in os.listdir(DATA):
        if name.endswith((".glm", ".player")):
            shutil.copy(os.path.join(DATA, name), tmp_path)
    return tmp_path

def model(glm:str, start:str="2020-06-01 12:00:00", stop:str|None=None, timezone:str="UTC", modules:str="module generators;") -> Model:
    """A model with a clock, the given modules, and GLM text"""
    m = Model()
    m.read_glm(f"""clock {{ timezone "{timezone}"; starttime "{start}"; stoptime "{stop or start}"; }}
{modules}
{glm}
""")
    return m

def run(glm:str, **kwargs) -> tuple[Model,Runner]:
    """Run `model(glm, ...)`"""
    m = model(glm, **kwargs)
    return m, Runner(model=m)

def errors(runner:Runner) -> list[str]:
    """Error lines of a run, without the time stamp"""
    return [x.split("]: ", 1)[1] for x in runner.stderr if x.startswith("ERROR")]

def warnings(runner:Runner) -> list[str]:
    """Warning lines of a run, without the time stamp"""
    return [x.split("]: ", 1)[1] for x in runner.stderr if x.startswith("WARNING")]
