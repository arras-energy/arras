"""Fixtures for the `powerflow` module tests"""
# pylint: disable=line-too-long

import os
import textwrap
from typing import Any

import numpy as np
import pytest

from arras.oclass import Class
from arras.module import Module
from arras.model import Model
from arras.runner import Runner

import powerflow
from powerflow._base import prop
from powerflow._common import BEHAVIORS, get_double
from powerflow.link import Link

DATA = os.path.join(os.path.dirname(__file__), "data")
"""Test data folder"""

collect_ignore = ["data"]

Z601 = np.array([[0.3465+1.0179j, 0.1560+0.5017j, 0.1580+0.4236j],
                 [0.1560+0.5017j, 0.3375+1.0478j, 0.1535+0.3849j],
                 [0.1580+0.4236j, 0.1535+0.3849j, 0.3414+1.0348j]])
"""Series impedance (ohm/mile) of IEEE 13-node feeder line configuration
601 (Kersting, Distribution System Modeling and Analysis, example 4.1)"""

B601 = 1j*np.array([[6.2998, -1.9958, -1.2595],
                    [-1.9958, 5.9597, -0.7417],
                    [-1.2595, -0.7417, 5.6386]])*1e-6
"""Shunt admittance (S/mile) of configuration 601 (example 5.1)"""

class StandInLine(Link):
    """A line of configuration 601 and a given length, standing in for the
    line classes that are not ported yet (it shows how they plug into
    `Link`); half its shunt admittance is at each end"""

    NAME = "test_line"
    PARENT = "link"
    PROPERTIES = (("length[ft]", "double", prop("line length")),)

    @classmethod
    def _miles(cls, model:Any, name:str) -> float:
        return get_double(model, name, "length")/5280

    @classmethod
    def series_impedance(cls, model:Any, name:str) -> np.ndarray:
        mask = cls.phase_mask(model, name)
        return Z601*cls._miles(model, name)*np.outer(mask, mask)

    @classmethod
    def shunt_admittance(cls, model:Any, name:str) -> tuple[np.ndarray,np.ndarray]:
        mask = cls.phase_mask(model, name)
        half = B601*cls._miles(model, name)/2*np.outer(mask, mask)
        return half, half

    @classmethod
    def admittance_key(cls, model:Any, name:str) -> tuple:
        return super().admittance_key(model, name) + (get_double(model, name, "length"),)

@pytest.fixture(autouse=True)
def reset(tmp_path, monkeypatch):
    """Start each test in an empty folder with empty class and module
    registries"""
    monkeypatch.chdir(tmp_path)
    Class.reset()
    Module.reset()
    yield
    BEHAVIORS.pop(StandInLine.NAME, None)
    Class.reset()
    Module.reset()

def register_test_line() -> None:
    """Register the module's classes and `test_line` before a model loads
    the module"""
    module = Module.load("powerflow")
    for cls in powerflow.CLASSES:
        if Class.find(cls.NAME, module="powerflow") is None:
            cls.register(module)
    if Class.find(StandInLine.NAME, module="powerflow") is None:
        StandInLine.register(module)
    BEHAVIORS[StandInLine.NAME] = StandInLine

def model(glm:str, start:str="2020-01-01 00:00:00", stop:str|None=None, module:str="", lines:bool=True) -> Model:
    """A model with a clock, the powerflow module (with `module` as its
    block's content), `test_line` (when `lines` is true), and GLM text"""
    if lines:
        register_test_line()
    m = Model()
    m.read_glm(f"""clock {{ timezone "UTC"; starttime "{start}"; stoptime "{stop or start}"; }}
module powerflow {{ {module} }}
{textwrap.dedent(glm)}
""")
    return m

def run(glm:str, *args:str, **kwargs) -> Runner:
    """Run `model(glm, ...)`"""
    return Runner(*args, model=model(glm, **kwargs))

def errors(runner:Runner) -> list[str]:
    """Error lines of a run"""
    return [x for x in runner.stderr if x.startswith("ERROR")]

def warnings(runner:Runner) -> list[str]:
    """Warning lines of a run"""
    return [x for x in runner.stderr if x.startswith("WARNING")]

def voltages(m:Model, name:str) -> np.ndarray:
    """Phase voltages of a node"""
    return np.array([powerflow.get_complex(m, name, f"voltage_{x}") for x in "ABC"])

VNOM = 2401.7771
"""Nominal line-to-neutral voltage of a 4.16 kV feeder (V)"""

def reference(nodes:dict[str,dict], lines:list[tuple[str,str,float]], swing:str, iterations:int=500) -> dict[str,np.ndarray]:
    """Independent solution of a three-phase network of configuration-601
    lines, by fixed-point iteration on the nodal equations (no PYPOWER, no
    `powerflow.solver`)

    Arguments
    ---------
    - `nodes`: node name to loads: `S`, `I`, `Y` (3 phase-to-ground values,
      VA, A at nominal angle, S) and `D` (3 phase-to-phase constant powers
      AB, BC, CA, VA)
    - `lines`: `(from, to, length in feet)`
    - `swing`: the swing node (voltages at nominal)
    """
    names = list(nodes)
    n = len(names)
    index = {name: k for k, name in enumerate(names)}
    Y = np.zeros((3*n, 3*n), dtype=complex)
    for fnode, tnode, length in lines:
        miles = length/5280
        ys = np.linalg.inv(Z601*miles)
        ysh = B601*miles/2
        f, t = 3*index[fnode], 3*index[tnode]
        Y[f:f+3, f:f+3] += ys + ysh
        Y[t:t+3, t:t+3] += ys + ysh
        Y[f:f+3, t:t+3] -= ys
        Y[t:t+3, f:f+3] -= ys
    vn = np.array([VNOM*np.exp(1j*a) for a in (0, -2*np.pi/3, 2*np.pi/3)])
    V = np.tile(vn, n)
    s = 3*index[swing]
    others = [k for k in range(3*n) if not s <= k < s+3]
    Yoo = Y[np.ix_(others, others)]
    Yos = Y[np.ix_(others, list(range(s, s+3)))]
    for _ in range(iterations):
        inj = np.zeros(3*n, dtype=complex)
        for name, load in nodes.items():
            b = 3*index[name]
            v = V[b:b+3]
            for k in range(3):
                drawn = 0j
                if load.get("S") is not None and v[k] != 0:
                    drawn += np.conj(load["S"][k]/v[k])
                if load.get("Y") is not None:
                    drawn += load["Y"][k]*v[k]
                if load.get("I") is not None and v[k] != 0:
                    drawn += np.conj(vn[k]*np.conj(load["I"][k])*abs(v[k])/(v[k]*VNOM))
                inj[b+k] -= drawn
            if load.get("D") is not None:
                for k, (a, c) in enumerate(((0, 1), (1, 2), (2, 0))):
                    current = np.conj(load["D"][k]/(v[a]-v[c]))
                    inj[b+a] -= current
                    inj[b+c] += current
        V[others] = np.linalg.solve(Yoo, inj[others] - Yos @ V[s:s+3])
    return {name: V[3*index[name]:3*index[name]+3] for name in names}

class Helpers: # pylint: disable=too-few-public-methods
    """The helpers of this module, for tests (as the `helpers` fixture)"""
    DATA = DATA
    VNOM = VNOM
    Z601 = Z601
    B601 = B601
    StandInLine = StandInLine
    model = staticmethod(model)
    run = staticmethod(run)
    errors = staticmethod(errors)
    warnings = staticmethod(warnings)
    voltages = staticmethod(voltages)
    reference = staticmethod(reference)
    register_test_line = staticmethod(register_test_line)

@pytest.fixture(name="helpers")
def fixture_helpers():
    """The helpers of this module"""
    return Helpers
