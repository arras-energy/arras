# pylint: disable=line-too-long
"""Class `triplex_line`: a split-phase secondary line

Syntax
------

    object triplex_line {
        phases {A,B,C}S[N];
        from <triplex node>;
        to <triplex node>;
        length <real> ft;
        configuration <triplex_line_configuration>;
        // and the other properties of line and link
    }

Description
-----------

A `triplex_line` is a `line` between split-phase (triplex) nodes: lines
1 and 2 and a neutral, the center-tapped secondary of a single-phase
transformer. Its configuration gives either the 2x2 impedance matrix
(`z11`, `z12`, `z21`, `z22`, with a warning that the system is
under-determined) or the three conductors (`conductor_1`, `conductor_2`,
`conductor_N`, `triplex_line_conductor`), the conductor `diameter`, and the
`insulation_thickness`. When it initializes, it is expected to:

1. initialize as a `line`;
2. warn when it does not have phase `S`;
3. unless the configuration gives the matrix, fail when a conductor is
   missing or is not a `triplex_line_conductor`;
4. compute its matrices as gridlabd's `triplex_line::recalc()` (Kersting,
   chapter 11) does, failing with methods other than NR (and FBS, which
   is solved with NR):

   - conductor spacings `D12 = (diameter + 2 insulation_thickness)/12` and
     `D13 = D23 = (diameter + insulation_thickness)/12` (feet), which must
     be positive;
   - primitive impedances by the modified Carson's equations, the neutral
     Kron-reduced, with gridlabd's sign convention for line 2 (its row
     negated: voltage 2 is measured in the opposite direction), times the
     length: `b_mat`;
   - the neutral current factors `tn = (-z13/z33, -z23/z33, 0)`;

   warning when `b_mat` has a negative resistance in its first row.

`TriplexLine.triplex_matrices()` gives `b_mat` and `tn`.

Caveats
-------

- Split-phase nodes (`triplex_node`, `triplex_meter`) and the center-tapped
  transformer are not ported, and the solver refuses split-phase nodes,
  so triplex lines initialize and compute their matrices but cannot be
  solved yet: a closed `triplex_line` in a network fails the solution.
- The ratings gridlabd derives from the conductors are not used.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A missing configuration, or one that is not a `line_configuration`,
   fails with `line`'s message; gridlabd dereferences it without a check.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/triplex_line.cpp`
- W. H. Kersting, *Distribution System Modeling and Analysis*, 4th ed.,
  CRC Press, 2017, chapter 11
"""

import math
from typing import Any

import numpy as np

from ._common import PHASE_S, SM_NR, SM_FBS, isa, g, msg, ref, get_int, get_double, object_state, PowerflowError
from .line import Line, carson, label
from .line_configuration import LineConfiguration
from .solver import SolverError

CONDUCTORS = {"triplex_line_configuration": ("conductor_1", "conductor_2", "conductor_N"),
    "line_configuration": ("conductor_A", "conductor_B", "conductor_C")}
"""Properties of lines 1, 2, and N by configuration class (gridlabd keeps
them in the same members)"""

class TriplexLine(Line):
    """Behavior of class `triplex_line`"""

    NAME = "triplex_line"
    PARENT = "line"

    @classmethod
    def _conductors(cls, model:Any, config:str) -> list[str|None]:
        names = CONDUCTORS.get(model.objects[config].oclass.name, CONDUCTORS["line_configuration"])
        return [ref(model, config, x) for x in names]

    @classmethod
    def init_link(cls, model:Any, name:str) -> None:
        """`triplex_line::init()`; raises `PowerflowError`"""
        super().init_link(model, name)
        obj = model.objects[name]
        if not get_int(model, name, "phases") & PHASE_S == PHASE_S:
            msg(model, name).warning(f"{name} ({obj.oclass.name}:{obj.id}) is triplex but doesn't have phases S set")
        config = ref(model, name, "configuration")
        if not isa(model, config, "line_configuration"):
            raise PowerflowError(f"line:{obj.id} - {label(model, name)} - configuration object either doesn't exist, or is not a valid configuration object!")
        z = LineConfiguration.impedance(model, config)
        if z[0, 0] == 0 and z[1, 1] == 0:
            for conductor in cls._conductors(model, config):
                if conductor is None:
                    raise PowerflowError(f"triplex_line:{obj.id} - {label(model, name)} - configuration doesn't have a valid phase conductor!")
                if not isa(model, conductor, "triplex_line_conductor"):
                    raise PowerflowError(f"triplex_line:{obj.id} - {label(model, name)} - configuration does not use a triplex_line_conductor for at least one phase!")
        cls.triplex_matrices(model, name, warn=True)

    @classmethod
    def triplex_matrices(cls, model:Any, name:str, warn:bool=False) -> tuple[np.ndarray,np.ndarray]:
        """`b_mat` (3x3, ohms, lines 1 and 2 in rows and columns 0 and 1)
        and `tn` (3) of gridlabd's `triplex_line::recalc()`; raises
        `PowerflowError`"""
        # pylint: disable=too-many-locals
        state = object_state(model, name)
        if not warn and "triplex" in state:
            return state["triplex"]
        out = msg(model, name)
        config = ref(model, name, "configuration")
        z = LineConfiguration.impedance(model, config)
        miles = get_double(model, name, "length")/5280.0
        nr = g(model, "solver_method") in (SM_NR, SM_FBS)
        b_mat = np.zeros((3, 3), dtype=complex)
        tn = np.zeros(3, dtype=complex)
        if z[0, 0] != 0 or z[1, 1] != 0:
            if warn:
                out.warning("Using a 2x2 z-matrix, instead of geometric values, is an under-determined system. Ground and/or neutral currents will be incorrect.")
            if not nr:
                raise PowerflowError("Only NR and FBS support z-matrix components.")
            b_mat[:2, :2] = z[:2, :2]*miles
        else:
            real, imag, additive = carson(model)
            oclass = model.objects[config].oclass
            diameter = get_double(model, config, "diameter") if oclass.find_property("diameter") else 0.0
            thickness = get_double(model, config, "insulation_thickness") if oclass.find_property("insulation_thickness") else 0.0
            conductors = cls._conductors(model, config)
            if any(c is None for c in conductors):
                raise PowerflowError(f"triplex_line_configuration:{model.objects[config].id} ({config}) is missing a conductor specification.")
            r = [get_double(model, c, "resistance") for c in conductors]
            gmr = [get_double(model, c, "geometric_mean_radius") for c in conductors]
            d12 = (diameter + 2*thickness)/12
            d13 = (diameter + thickness)/12
            if d12 <= 0 or d13 <= 0:
                raise PowerflowError("triplex_line_configuration diameter and/or insulation_thickness are incorrectly set. Please set both of these values to a positive value.")
            zp = [complex(r[k] + real, imag*(math.log(1/gmr[k]) + additive)) for k in range(3)]
            zp12, zp13 = (complex(real, imag*(math.log(1/d) + additive)) for d in (d12, d13))
            zp23 = zp13
            if not nr:
                raise PowerflowError("triplex_line:unsupported solver method")
            zs = np.zeros((3, 3), dtype=complex)
            zs[0, 0] = zp[0] - zp13*zp13/zp[2]
            zs[0, 1] = zp12 - zp13*zp23/zp[2]
            zs[1, 0] = -(zp12 - zp13*zp23/zp[2])
            zs[1, 1] = -(zp[1] - zp23*zp23/zp[2])
            tn[:2] = (-zp13/zp[2], -zp23/zp[2])
            b_mat = zs*miles
        if warn and (b_mat[0, :2].real < 0).any():
            out.warning(f"INIT: triplex_line:{name} has a negative resistance in it's impedance matrix. This will result in unusual behavior. Please check the line's geometry and cable parameters.")
        state["triplex"] = (b_mat, tn)
        return b_mat, tn

    @classmethod
    def admittance(cls, model:Any, name:str) -> tuple[np.ndarray,np.ndarray,np.ndarray,np.ndarray]:
        """Refused: split-phase networks are not supported by the solver
        yet (raises `powerflow.solver.SolverError`)"""
        raise SolverError(f"triplex_line {name}: triplex lines are not supported by the solver yet")
