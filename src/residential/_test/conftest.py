"""Fixtures for the `residential` module tests"""
# pylint: disable=line-too-long

import csv
import os
import textwrap

import pytest

from arras.oclass import Class
from arras.module import Module
from arras.model import Model
from arras.runner import Runner

DATA = os.path.join(os.path.dirname(__file__), "data")
"""Test data folder"""

collect_ignore = ["data"]

FEEDER = """
object triplex_node { name source; phases AS; nominal_voltage 120; bustype SWING; }
object triplex_line_conductor { name tlc; resistance 1e-9; geometric_mean_radius 0.0111; }
object triplex_line_configuration { name tlcfg; conductor_1 tlc; conductor_2 tlc; conductor_N tlc; insulation_thickness 0.08; diameter 0.368; }
object triplex_line { name tl; phases AS; from source; to meter; length 0.1; configuration tlcfg; }
"""
"""A swing `triplex_node` feeding the triplex meter `meter` through a 0.1 ft
lossless triplex line, so the meter measures the loads at 120/240 V"""

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

def model(glm:str, start:str="2020-01-01 00:00:00", stop:str|None=None, module:str="implicit_enduses NONE;", feeder:bool=False) -> Model:
    """A model with a UTC clock, `powerflow`, `residential` (with `module` as
    its block's content), the `FEEDER` when `feeder` is true, and GLM text"""
    m = Model()
    m.read_glm(f"""clock {{ timezone "UTC"; starttime "{start}"; stoptime "{stop or start}"; }}
module powerflow;
module tape;
module residential {{ {module} }}
{FEEDER if feeder else ""}
{textwrap.dedent(glm)}
""")
    return m

def run(glm:str, *args:str, **kwargs) -> Runner:
    """Run `model(glm, ...)`"""
    return Runner(*args, model=model(glm, **kwargs))

def run_file(name:str) -> Runner:
    """Run a GLM file of the data folder, from the data folder (for the
    files it names)"""
    m = Model()
    cwd = os.getcwd()
    os.chdir(DATA)
    try:
        with open(name, encoding="utf-8") as fh:
            m.read_glm(fh.read())
    finally:
        os.chdir(cwd)
    tmy = os.path.join(DATA, "../../../climate/_test/data/WA-Yakima_Air_Terminal.tmy3")
    for name_, obj in m.objects.items():
        if obj.get("tmyfile"):
            obj["tmyfile"] = os.path.normpath(tmy)
        if obj.oclass.name == "player":
            obj["file"] = os.path.join(DATA, str(obj["file"]).strip('"'))
        _ = name_
    return Runner(model=m)

def errors(runner:Runner) -> list[str]:
    """Error lines of a run"""
    return [x for x in runner.stderr if x.startswith("ERROR")]

def warnings(runner:Runner) -> list[str]:
    """Warning lines of a run"""
    return [x for x in runner.stderr if x.startswith("WARNING")]

def read_csv(name:str) -> list[list[str]]:
    """Rows of a recorder file (without the `#` header lines)"""
    with open(name, encoding="utf-8") as fh:
        return [row for row in csv.reader(fh) if row and not row[0].startswith("#")]

class Helpers: # pylint: disable=too-few-public-methods
    """The helpers of this module, for tests (as the `helpers` fixture)"""
    DATA = DATA
    FEEDER = FEEDER
    model = staticmethod(model)
    run = staticmethod(run)
    run_file = staticmethod(run_file)
    errors = staticmethod(errors)
    warnings = staticmethod(warnings)
    read_csv = staticmethod(read_csv)

@pytest.fixture(name="helpers")
def fixture_helpers():
    """The helpers of this module"""
    return Helpers
