"""Fixtures for the `pypower` module tests"""

import os
import shutil
import textwrap

import pytest

from arras.oclass import Class
from arras.module import Module
from arras.model import Model
from arras.runner import Runner

DATA = os.path.join(os.path.dirname(__file__), "data")
"""Test data folder"""

collect_ignore = ["data"]
"""The data folder holds the autotests' Python files (`check_case.py`,
`verify.py`, `controllers.py`, the cases)"""

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

def model(glm:str, start:str="2020-01-01 00:00:00", stop:str|None=None, timezone:str="UTC") -> Model:
    """A model with a clock, the pypower module, and GLM text"""
    m = Model()
    m.read_glm(f"""clock {{ timezone "{timezone}"; starttime "{start}"; stoptime "{stop or start}"; }}
module pypower;
{textwrap.dedent(glm)}
""")
    return m

def run(glm:str, *args:str, **kwargs) -> Runner:
    """Run `model(glm, ...)`"""
    return Runner(*args, model=model(glm, **kwargs))

def write(file:str, text:str) -> str:
    """Write a file; returns its name"""
    with open(file, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text))
    return file

def lines(file:str) -> list[str]:
    """Lines of a file"""
    with open(file, encoding="utf-8") as fh:
        return fh.read().splitlines()

def errors(runner:Runner) -> list[str]:
    """Error lines of a run"""
    return [x for x in runner.stderr if x.startswith("ERROR")]

def warnings(runner:Runner) -> list[str]:
    """Warning lines of a run"""
    return [x for x in runner.stderr if x.startswith("WARNING")]

THREE_BUS = """
object bus { name b1; type REF; baseKV 230 kV; Vm 1.0 pu.kV;
    object gen { name g1; Pmax 200 MW; Qmax 100 MVAr; Qmin -100 MVAr; Vg 1.0 pu.kV; }; }
object bus { name b2; type PQ; baseKV 230 kV; Pd 50 MW; Qd 20 MVAr; }
object bus { name b3; type PQ; baseKV 230 kV; Pd 40 MW; Qd 10 MVAr; }
object branch { name l12; from b1; to b2; r 0.01; x 0.1; b 0.02; rateA 100 MVA; }
object branch { name l23; from b2; to b3; r 0.01; x 0.1; b 0.02; rateA 100 MVA; }
object branch { name l13; from b1; to b3; r 0.01; x 0.1; b 0.02; rateA 100 MVA; }
"""
"""A three-bus network: slack generator on `b1`, loads on `b2` and `b3`
(solution: `b2` 0.9792 pu at -2.643 deg, `b3` 0.983 pu at -2.462 deg,
`g1` 90.46+28.75j MVA)"""

class Helpers: # pylint: disable=too-few-public-methods
    """The helpers of this module, for tests (as the `helpers` fixture)"""
    DATA = DATA
    THREE_BUS = THREE_BUS
    copy_data = staticmethod(copy_data)
    model = staticmethod(model)
    run = staticmethod(run)
    write = staticmethod(write)
    lines = staticmethod(lines)
    errors = staticmethod(errors)
    warnings = staticmethod(warnings)

@pytest.fixture(name="helpers")
def fixture_helpers():
    """The helpers of this module"""
    return Helpers
