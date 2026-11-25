"""Fixtures for the `climate` module tests"""

import os
import csv
import sys
import types
import datetime

import pytest

from arras.oclass import Class
from arras.module import Module
from arras.model import Model
from arras.runner import Runner

DATA = os.path.join(os.path.dirname(__file__), "data")
"""Test data folder"""

REFERENCE = os.path.join(DATA, "reference")
"""gridlabd reference values"""

YAKIMA = "WA-Yakima_Air_Terminal.tmy3"
"""The Yakima TMY3 file (in `DATA`)"""

@pytest.fixture(autouse=True)
def reset():
    """Start each test with empty class and module registries"""
    Class.reset()
    Module.reset()
    yield
    Class.reset()
    Module.reset()

@pytest.fixture(name="data")
def fixture_data(monkeypatch):
    """Run the test in the data folder"""
    monkeypatch.chdir(DATA)
    return DATA

def model(glm:str, start:str="2006-01-01 00:00:00", stop:str|None=None,
        timezone:str="America/Los_Angeles") -> Model:
    """A model with a clock, the climate module, and GLM text"""
    m = Model()
    m.read_glm(f"""clock {{ timezone "{timezone}"; starttime "{start}"; stoptime "{stop or start}"; }}
module climate;
{glm}
""")
    return m

def run(glm:str, *args:str, **kwargs) -> Runner:
    """Run `model(glm, ...)`"""
    return Runner(*args, model=model(glm, **kwargs))

def add_ticker(m:Model, interval:int) -> None:
    """Add an object that asks for an event every `interval` seconds from
    the start of the run"""
    start = {}
    def tick(name, t): # pylint: disable=unused-argument
        start.setdefault("t", t)
        return t + interval - (t - start["t"]) % interval
    sys.modules["climate_test_ticker"] = types.SimpleNamespace(tick=tick)
    m.read_glm('class climate_test_ticker { double x; }\nobject climate_test_ticker { on_sync "python:climate_test_ticker.tick"; }\n')

def sample(m:Model, names:str|list[str], props:list[str], **kwargs) -> tuple[Runner,dict[int,list[str]]]:
    """Run a model and get the values of `props` of object `names` at each
    committed time, keyed on the time (with a list of names, the values of
    each object, in that order)"""
    rows = {}
    objects = [names] if isinstance(names, str) else names
    def progress(timestamp):
        if timestamp is not None:
            rows[timestamp] = [m.get_property(name, p) for name in objects for p in props]
    runner = Runner(model=m, progress=progress, **kwargs)
    return runner, rows

ZONES = {"UTC": 0, "GMT": 0, "PST": -8, "PDT": -7, "EST": -5, "EDT": -4, "HST": -10}
"""Offsets of the time zone abbreviations that gridlabd writes in the reference files"""

def timestamp(text:str) -> int:
    """Time of a timestamp as gridlabd's recorders write it, with the
    offset of its time zone abbreviation"""
    date, time, zone = text.split()
    local = datetime.datetime.fromisoformat(f"{date} {time}").replace(tzinfo=datetime.timezone.utc)
    return int(local.timestamp()) - ZONES[zone]*3600

def reference(name:str) -> tuple[list[str],dict[int,list[float]]]:
    """Columns and rows (keyed on the time) of a gridlabd reference file
    (`data/reference/`)"""
    with open(os.path.join(REFERENCE, f"{name}.csv"), encoding="utf-8") as fh:
        header = fh.readline().lstrip("# ").strip().split(",")
        rows = {timestamp(row[0]): [float(x) for x in row[1:]] for row in csv.reader(fh)}
    return header[1:], rows

def number(text) -> float:
    """Leading number of a property value"""
    return float(str(text).split()[0])

def mismatches(expected:dict[int,list[float]], actual:dict[int,list[str]], columns:list[str],
        rtol:float=1e-5, atol:float=1e-9) -> list[tuple[int,str,float,float]]:
    """Values that differ from the reference more than gridlabd's 6
    significant digits allow"""
    result = []
    for key, values in expected.items():
        assert key in actual, f"no value at {key}"
        for column, ref, value in zip(columns, values, actual[key]):
            got = number(value)
            if abs(got - ref) > atol + rtol*abs(ref):
                result.append((key, column, got, ref))
    return result

@pytest.fixture(name="helpers")
def fixture_helpers():
    """The helper functions"""
    return types.SimpleNamespace(model=model, run=run, add_ticker=add_ticker, sample=sample,
        reference=reference, mismatches=mismatches, number=number, DATA=DATA, YAKIMA=YAKIMA)
