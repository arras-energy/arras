"""Fixtures for the `tape` module tests"""

import os
import shutil

import pytest

from arras.oclass import Class
from arras.module import Module
from arras.model import Model
from arras.runner import Runner

DATA = os.path.join(os.path.dirname(__file__), "data")
"""Test data folder"""

collect_ignore = ["data"]
"""The data folder holds a handler module whose name starts with `test_`"""

@pytest.fixture(autouse=True)
def reset(tmp_path, monkeypatch):
    """Start each test in an empty folder with empty class and module
    registries"""
    monkeypatch.chdir(tmp_path)
    Class.reset()
    Module.reset()
    yield
    Class.reset()
    Module.reset()

def copy_data(folder:str) -> None:
    """Copy the test data into `folder`"""
    for name in os.listdir(DATA):
        if os.path.isfile(os.path.join(DATA, name)):
            shutil.copy(os.path.join(DATA, name), folder)

def model(glm:str, start:str="2020-01-01 00:00:00", stop:str|None=None, timezone:str="UTC", header:str="NAME") -> Model:
    """A model with a clock, the tape module (with `csv_header_type`
    `header`), and GLM text"""
    m = Model()
    m.read_glm(f"""clock {{ timezone "{timezone}"; starttime "{start}"; stoptime "{stop or start}"; }}
module tape {{ csv_header_type {header}; }}
{glm}
""")
    return m

def run(glm:str, *args:str, **kwargs) -> Runner:
    """Run `model(glm, ...)`"""
    return Runner(*args, model=model(glm, **kwargs))

def lines(file:str) -> list[str]:
    """Lines of a file"""
    with open(file, encoding="utf-8") as fh:
        return fh.read().splitlines()

def write(file:str, text:str) -> str:
    """Write a file; returns its name"""
    with open(file, "w", encoding="utf-8") as fh:
        fh.write(text)
    return file

class Helpers: # pylint: disable=too-few-public-methods
    """The helpers of this module, for tests (as the `helpers` fixture)"""
    DATA = DATA
    copy_data = staticmethod(copy_data)
    model = staticmethod(model)
    run = staticmethod(run)
    lines = staticmethod(lines)
    write = staticmethod(write)

@pytest.fixture(name="helpers")
def fixture_helpers():
    """The helpers of this module"""
    return Helpers
