# pylint: disable=line-too-long
"""Class `line_sensor`: noisy voltage, current, and power measurement on a line

Syntax
------

    object overhead_line {
        ...
        object line_sensor {
            measured_phase {A,B,C};
            location <real> ft;         // distance from the from node
            covariance "<s1> <s2> <s3> <s4>";  // or 2x6 or 4x4 form
        };
    }

Outputs: `measured_voltage` (V), `measured_current` (A), and
`measured_power` (VA).

Description
-----------

A `line_sensor` measures the voltage and current of one phase of its
parent powerflow line (`overhead_line`, `underground_line`, or
`triplex_line`) at `location` along it, as gridlabd's `line_sensor` does,
in each postsync pass (after the solution):

- the voltage is `(1-w) V_from + w V_to` and the current `(1-w)
  current_in + w current_out` on `measured_phase`, with `w = location /
  length` (clamped to 0 to 1, with a warning). On a triplex line, phase
  `A`, `B`, and `C` are the nodes' `voltage_1`, `voltage_2`, and
  `voltage_N`, as in gridlabd;
- with a `covariance`, the measurement gets noise: with `r` four
  independent standard normal numbers and `L` the lower Cholesky factor of
  the covariance of `[Vr Vi Ir Ii]`, `n = L r`, the real and imaginary
  parts of the voltage and current are multiplied by `sqrt(1 + n_k)`;
- `measured_power` is `measured_voltage conj(measured_current)`.

The covariance is written as a `double_array` (values separated by spaces
or commas, rows by `;`): `s1 s2 s3 s4` for independent noise (the
variances), `s1 s2 s3 s4 x x; a b c d e f` for the matrix `[s1 a b c; a s2
d e; b d s3 f; c e f s4]`, or a 4x4 matrix. Empty means no noise. The
random numbers come from a generator for each sensor, seeded by
`randomseed` and the object's id.

When it initializes, a line sensor fails without a parent, when its
parent is not a powerflow line, when the line's nodes are not powerflow
nodes, when the covariance has another form, and when it is not positive
semidefinite.

Caveats
-------

- A noise term below -1 makes a measured part NaN (the square root of a
  negative number), as in gridlabd.
- Each postsync pass draws new noise, so a time step solved in several
  passes keeps the last pass's measurement.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The measurement is at `location`: gridlabd's `init()` stores the
   weight in a local variable, so the sensor always measures at the from
   end (`w = 0`).
2. The noise uses the lower Cholesky factor of the covariance; gridlabd's
   decomposition writes the factor in the upper triangle and the noise
   reads the lower one, which still holds the covariance, so correlated
   noise (the 2x6 and 4x4 forms) is wrong.
3. A positive semidefinite covariance with zero variances (`0.03 0 0.02
   0.02`) is accepted; gridlabd divides by zero and rejects it as "not
   positive symmetric definite".
4. The warning for a negative location says `w<0` (gridlabd: `w>1`).

References
----------

- `arras-energy/gridlabd`: `module/powerflow/line_sensor.cpp`,
  `line_sensor.h`, `autotest/test_line_sensor.glm`
"""

import math
import random
import re
from typing import Any

import numpy as np

from ._base import PowerflowClass, prop, keywords
from ._common import (TS_NEVER, PHASE_A, PHASE_B, PHASE_C, ref, isa, object_state, get_int, get_double, get_complex,
    set_complex, gl_warning, PowerflowError)

PHASES = (PHASE_A, PHASE_B, PHASE_C)
"""`measured_phase` values, in voltage order"""

def parse_array(text:str) -> list[list[float]]:
    """Rows of a `double_array` text"""
    text = str(text or "").strip().strip('"')
    rows = [row for row in (x.strip() for x in text.split(";")) if row]
    return [[float(x) for x in re.split(r"[\s,]+", row) if x] for row in rows]

def covariance_matrix(rows:list[list[float]]) -> np.ndarray:
    """The 4x4 covariance of the `covariance` property's forms"""
    shape = (len(rows), len(rows[0]) if rows else 0)
    if any(len(row) != shape[1] for row in rows):
        shape = (-1, -1)
    c = np.zeros((4, 4))
    if shape == (0, 0):
        return c
    if shape == (1, 4):
        np.fill_diagonal(c, rows[0])
    elif shape == (2, 6):
        np.fill_diagonal(c, rows[0][:4])
        for value, (i, j) in zip(rows[1], ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))):
            c[i, j] = c[j, i] = value
    elif shape == (4, 4):
        c = np.array(rows, dtype=float)
    else:
        raise PowerflowError("covariance matrix is not in proper form; only 1x4, 2x6 or 4x4 forms allowed")
    return c

def cholesky(c:np.ndarray) -> np.ndarray:
    """The lower Cholesky factor of a symmetric positive semidefinite
    matrix (columns of zero pivots are zero)"""
    n = len(c)
    if not np.allclose(c, c.T):
        raise PowerflowError("covariance is not positive symmetric definite")
    tol = 1e-12*max(np.abs(c).max(), 1e-300)
    low = np.zeros((n, n))
    for j in range(n):
        pivot = c[j, j] - low[j, :j] @ low[j, :j]
        if pivot < -tol:
            raise PowerflowError("covariance is not positive symmetric definite")
        if pivot <= tol:
            rest = c[j+1:, j] - low[j+1:, :j] @ low[j, :j]
            if np.any(np.abs(rest) > tol):
                raise PowerflowError("covariance is not positive symmetric definite")
            continue
        low[j, j] = math.sqrt(pivot)
        low[j+1:, j] = (c[j+1:, j] - low[j+1:, :j] @ low[j, :j])/low[j, j]
    return low

class LineSensor(PowerflowClass):
    """Behavior of class `line_sensor`"""

    NAME = "line_sensor"
    TRL = 9 # TRL_PROVEN
    PASSCONFIG = "POSTTOPDOWN|AUTOLOCK|OBSERVER"
    EVENTS = ("init", "postsync")
    PROPERTIES = (
        ("measured_phase", "enumeration", prop("phase from which measurement is taken", flags="REQUIRED",
            keywords=keywords(("A", PHASE_A), ("B", PHASE_B), ("C", PHASE_C)))),
        ("measured_voltage[V]", "complex", prop("voltage measurement (with noise)", flags="OUTPUT")),
        ("measured_current[A]", "complex", prop("current measurement (with noise)", flags="OUTPUT")),
        ("measured_power[VA]", "complex", prop("power measurement (with noise)", flags="OUTPUT")),
        ("location[ft]", "double", prop("sensor placement downline", flags="REQUIRED")),
        ("covariance", "double_array", prop("sensor covariance matrix (components are [Vr Vi Ir Ii])")),
    )

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`line_sensor::init()`"""
        from .node import init_failed # pylint: disable=import-outside-toplevel
        try:
            line = ref(model, name, "parent")
            if line is None:
                raise PowerflowError(f"{name}: parent target must be specified")
            if not isa(model, line, "line"):
                raise PowerflowError(f"{name}: parent '{line}' must be a powerflow line object")
            nodes = []
            for end in ("from", "to"):
                node = ref(model, line, end)
                if node is None or not isa(model, node, "node"):
                    cname = model.objects[node].oclass.name if node is not None else "NULL"
                    raise PowerflowError(f"{name}: '{end}' object is not a powerflow node (it's a '{cname}')")
                nodes.append(node)
            w = get_double(model, name, "location")/get_double(model, line, "length")
            if w > 1.0:
                gl_warning(f"{name}: sensor location is beyond 'to' node (w>1); moving location to 'to' node")
                w = 1.0
            elif w < 0.0:
                gl_warning(f"{name}: sensor location is beyond 'from' node (w<0); moving location to 'from' node")
                w = 0.0
            try:
                rows = parse_array(model.get_property(name, "covariance"))
            except ValueError as err:
                raise PowerflowError(f"{name}: covariance matrix is not in proper form; only 1x4, 2x6 or 4x4 forms allowed") from err
            try:
                low = cholesky(covariance_matrix(rows))
            except PowerflowError as err:
                raise PowerflowError(f"{name}: {err}") from err
        except PowerflowError as err:
            init_failed(model, name, err)
            return False
        seed = int(model.globals.getvalue("randomseed") or 0)
        object_state(model, name).update(line=line, nodes=nodes, w=w, L=low,
            rng=random.Random(seed*1000003 + model.objects[name].id))
        return True

    @classmethod
    def postsync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument,too-many-locals
        """`line_sensor::postsync()`"""
        from ._module import behavior # pylint: disable=import-outside-toplevel
        state = object_state(model, name)
        if "line" not in state:
            return TS_NEVER
        line, (fnode, tnode), w = state["line"], state["nodes"], state["w"]
        phase = get_int(model, name, "measured_phase")
        voltage, current = 0j, 0j
        if phase in PHASES:
            k = PHASES.index(phase)
            x = "ABC"[k]
            vf = get_complex(model, fnode, behavior(model, fnode).VOLTAGES[k])
            vt = get_complex(model, tnode, behavior(model, tnode).VOLTAGES[k])
            voltage = vf*(1 - w) + vt*w
            current = get_complex(model, line, f"current_in_{x}")*(1 - w) + get_complex(model, line, f"current_out_{x}")*w
        rng = state["rng"]
        noise = state["L"] @ np.array([rng.gauss(0.0, 1.0) for _ in range(4)])
        scale = [math.sqrt(1 + n) if 1 + n >= 0 else math.nan for n in noise]
        voltage = complex(voltage.real*scale[0], voltage.imag*scale[1])
        current = complex(current.real*scale[2], current.imag*scale[3])
        set_complex(model, name, "measured_voltage", voltage)
        set_complex(model, name, "measured_current", current)
        set_complex(model, name, "measured_power", voltage*current.conjugate())
        return TS_NEVER

__all__ = ["LineSensor", "cholesky", "covariance_matrix", "parse_array"]
