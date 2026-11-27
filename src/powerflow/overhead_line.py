# pylint: disable=line-too-long
"""Class `overhead_line`: a line of overhead conductors

Syntax
------

    object overhead_line {
        phases {A,B,C,N}[|...];
        from <node>;
        to <node>;
        length <real> ft;
        configuration <line_configuration>;
        ice_thickness <real> in;
        is_covered {TRUE,FALSE};
        // and the other properties of line and link
    }

Description
-----------

An `overhead_line` is a `line` whose configuration gives either the
impedance and capacitance matrices directly (`z11`, `z22`, or `z33` not
0: the `line` model) or the overhead conductors of each phase and the
neutral (`conductor_A` ... `conductor_N`, `overhead_line_conductor`) and
their `line_spacing`. When it initializes, it is expected to:

1. initialize as a `line`;
2. fail when it has no configuration, or the configuration is not a
   `line_configuration`;
3. unless the configuration gives the matrix for the phase, fail when a
   phase it has (or the neutral) has no conductor or a conductor that is
   not an `overhead_line_conductor`;
4. fail when the configuration has no `line_spacing` and no matrix;
5. compute its matrices (below), warning when an impedance term has a
   negative resistance.

From conductors and spacing, as gridlabd's `overhead_line::recalc()`
(Kersting, chapters 4 and 5), per mile then times the length:

- the primitive impedances by the modified Carson's equations at
  `powerflow::nominal_frequency` (or `current_frequency` with
  `enable_frequency_dependence`): self terms from each conductor's
  resistance and geometric mean radius (0 when either is 0), mutual terms
  from the spacing distances of the phases the line has (0 when 0);
- `Zabc` by Kron reduction of the neutral (when it has a positive radius
  and resistance);
- with `powerflow::line_capacitance`, the potential coefficients from the
  conductors' diameters and heights (`distance_XE`) and their images,
  Kron-reduced, inverted on the line's phases, times
  `j 2 pi f 1e-6 * miles` for `Yabc`; when a phase lacks a diameter or
  height, no capacitance at all, with a warning.

Caveats
-------

- `ice_thickness` and `is_covered` are published (gridlabd uses them for
  pole loading) but do not change the impedance.
- The ratings gridlabd derives from the conductors (`link_rating`) are not
  used: link limits are not implemented.
- Faults (`create_fault`, `fix_fault`) are not ported.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

None for the matrices; see `line` for the zero-length check.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/overhead_line.cpp`
- W. H. Kersting, *Distribution System Modeling and Analysis*, 4th ed.,
  CRC Press, 2017, chapters 4 and 5
"""

import math
from typing import Any

import numpy as np

from ._base import prop
from ._common import (PHASE_A, PHASE_B, PHASE_C, PHASE_N, PHASE_D, isa, ref, g, msg, get_int,
    get_double, object_state, PowerflowError)
from .line import Line, carson, frequency, snapshot, PERMITIVITTY_AIR
from .line_configuration import LineConfiguration

PHASES = (("A", PHASE_A), ("B", PHASE_B), ("C", PHASE_C), ("N", PHASE_N))
"""Conductors of a line: letter and phase bit"""

def matrix_based(model:Any, config:str) -> bool:
    """`True` when a configuration gives its impedance matrix (`z11`,
    `z22`, or `z33` not 0)"""
    z = LineConfiguration.impedance(model, config)
    return z[0, 0] != 0 or z[1, 1] != 0 or z[2, 2] != 0

class GeometricLine(Line):
    """Common behavior of the lines whose matrices come from conductors and
    spacing (`overhead_line`, `underground_line`)"""

    CONDUCTOR = ""
    """Class of the conductors"""

    KIND = ""
    """Word in the messages (`overhead`, `underground`)"""

    @classmethod
    def conductor_message(cls, name:str, problem:str, phase:str) -> str:
        """Message of a conductor check"""
        return f"{problem} conductor for phase {phase} of {cls.KIND} line {name}"

    @classmethod
    def init_link(cls, model:Any, name:str) -> None:
        """`init()`: `line::init()`, then the configuration, conductor, and
        spacing checks, then the matrices; raises `PowerflowError`"""
        super().init_link(model, name)
        config = ref(model, name, "configuration")
        if config is None:
            raise PowerflowError(f"no {cls.KIND} line configuration specified.")
        if not isa(model, config, "line_configuration"):
            raise PowerflowError(f"invalid line configuration for {cls.KIND} line")
        phases = get_int(model, name, "phases")
        z = LineConfiguration.impedance(model, config)
        for k, (x, bit) in enumerate(PHASES):
            given = z[k, k] != 0 if k < 3 else matrix_based(model, config)
            if given:
                continue
            conductor = ref(model, config, f"conductor_{x}") if model.objects[config].oclass.find_property(f"conductor_{x}") else None
            if conductor is not None and not isa(model, conductor, cls.CONDUCTOR):
                raise PowerflowError(cls.conductor_message(name, "invalid", x))
            if conductor is None and phases & bit:
                raise PowerflowError(cls.conductor_message(name, "missing", x))
        spacing = ref(model, config, "spacing") if model.objects[config].oclass.find_property("spacing") else None
        if not isa(model, spacing, "line_spacing") and not matrix_based(model, config):
            raise PowerflowError(f"invalid or missing line spacing on {cls.KIND} line")
        cls.recalc(model, name, warn=True)

    @classmethod
    def recalc(cls, model:Any, name:str, warn:bool=False) -> tuple[np.ndarray,np.ndarray]:
        """`Zabc`, `Yabc` (ohms, siemens), cached by the admittance key;
        `warn` writes the warnings gridlabd writes when it computes them"""
        state = object_state(model, name)
        key = cls.admittance_key(model, name)
        if not warn and state.get("matrices_key") == key:
            return state["matrices"]
        config = ref(model, name, "configuration")
        if matrix_based(model, config):
            zabc, yabc = super().line_matrices(model, name)
            if warn:
                c = LineConfiguration.capacitance(model, config)
                if (c[0, 0] != 0 or c[1, 1] != 0 or c[2, 2] != 0) and not g(model, "line_capacitance"):
                    msg(model, name).warning(f"Shunt capacitance of line:{name} specified without setting powerflow::line_capacitance = TRUE. Shunt capacitance will be ignored.")
        else:
            zabc, yabc = cls.geometric_matrices(model, name, warn)
        if warn and (zabc.real < 0).any():
            msg(model, name).warning(f"INIT: {cls.NAME}:{name} has a negative resistance in it's impedance matrix. This will result in unusual behavior. Please check the line's geometry and cable parameters.")
        state["matrices"] = (zabc, yabc)
        state["matrices_key"] = key
        return zabc, yabc

    @classmethod
    def setup(cls, model:Any, name:str) -> tuple:
        """Messages, phases, configuration, spacing, miles, and Carson
        coefficients of a line"""
        config = ref(model, name, "configuration")
        return (msg(model, name), get_int(model, name, "phases"), config, ref(model, config, "spacing"),
            get_double(model, name, "length")/5280.0, carson(model))

    @classmethod
    def geometric_matrices(cls, model:Any, name:str, warn:bool) -> tuple[np.ndarray,np.ndarray]:
        """Matrices from conductors and spacing (overridden)"""
        raise NotImplementedError

    @classmethod
    def line_matrices(cls, model:Any, name:str) -> tuple[np.ndarray,np.ndarray]:
        """`Zabc` and `Yabc`"""
        return cls.recalc(model, name)

    @classmethod
    def admittance_key(cls, model:Any, name:str) -> tuple:
        """The line's key and the properties of its configuration's
        conductors and spacing, and the frequency"""
        config = ref(model, name, "configuration")
        related = []
        if config is not None:
            for prop_ in ("conductor_A", "conductor_B", "conductor_C", "conductor_N", "conductor_1", "conductor_2", "spacing"):
                if model.objects[config].oclass.find_property(prop_):
                    related.append(ref(model, config, prop_))
        return super().admittance_key(model, name) + (snapshot(model, *related), frequency(model), get_int(model, name, "phases"))

def has(phases:int, bit:int) -> bool:
    """`True` when a phase set has a phase"""
    return phases & bit == bit

class OverheadLine(GeometricLine):
    """Behavior of class `overhead_line`"""

    NAME = "overhead_line"
    PARENT = "line"
    CONDUCTOR = "overhead_line_conductor"
    KIND = "overhead"
    PROPERTIES = (
        ("ice_thickness[in]", "double", prop("thickness of ice build-up on lines")),
        ("is_covered", "bool", prop("flag to indicate whether conductor is covered", "FALSE")),
    )

    @classmethod
    def geometric_matrices(cls, model:Any, name:str, warn:bool) -> tuple[np.ndarray,np.ndarray]:
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        out, phases, config, spacing, miles, (real, imag, additive) = cls.setup(model, name)
        conductor = {x: ref(model, config, f"conductor_{x}") for x, _ in PHASES}
        def cond(x:str, prop_:str) -> float:
            bit = dict(PHASES)[x]
            return get_double(model, conductor[x], prop_) if has(phases, bit) and conductor[x] else 0.0
        def dist(x:str, y:str) -> float:
            if not (has(phases, dict(PHASES)[x]) and has(phases, dict(PHASES)[y]) and spacing):
                return 0.0
            return space(x, y)
        def space(x:str, y:str) -> float:
            key = {"AB": "AB", "BC": "BC", "AC": "AC", "AN": "AN", "BN": "BN", "CN": "CN", "AE": "AE", "BE": "BE", "CE": "CE", "NE": "NE"}[x + y]
            return get_double(model, spacing, f"distance_{key}") if spacing else 0.0
        gmr = {x: cond(x, "geometric_mean_radius") for x, _ in PHASES}
        res = {x: cond(x, "resistance") for x, _ in PHASES}
        diam = {x: cond(x, "diameter") for x, _ in PHASES}
        def z_self(x:str) -> complex:
            return complex(res[x] + real, imag*(math.log(1.0/gmr[x]) + additive)) if gmr[x] > 0 and res[x] > 0 else 0j
        def z_mut(d:float) -> complex:
            return complex(real, imag*(math.log(1.0/d) + additive)) if d > 0 else 0j
        letters = "ABC"
        z = {}
        for i, x in enumerate(letters):
            present = has(phases, dict(PHASES)[x])
            z[x + x] = z_self(x) if present else 0j
            for y in letters[i+1:] + "N":
                z[x + y] = z_mut(dist(x, y)) if present and has(phases, dict(PHASES)[y]) else 0j
        line_cap = bool(g(model, "line_capacitance"))
        valid = line_cap
        p = {}
        if line_cap:
            if spacing is None:
                raise PowerflowError("Line spacing not found, capacitance calculations failed!")
            coeff = 1.0/(PERMITIVITTY_AIR*2.0*math.pi)
            for i, x in enumerate(letters):
                if not has(phases, dict(PHASES)[x]):
                    continue
                height = space(x, "E")
                if diam[x] > 0 and height > 0:
                    p[x + x] = coeff*math.log(2.0*height/diam[x]*24.0)
                    for y in letters[i+1:] + "N":
                        if has(phases, dict(PHASES)[y]):
                            d = space(x, y)
                            image = math.sqrt(d*d + 2.0*height*2.0*space(y, "E"))
                            p[x + y] = coeff*math.log(image/d) if d != 0 else 0.0
                else:
                    valid = False
                    if warn:
                        out.warning(f"Shunt capacitance of overhead line:{name} not calculated - invalid values")
        z_nn_inv = 0j
        if has(phases, PHASE_N) and gmr["N"] > 0 and res["N"] > 0:
            z_nn_inv = 1/z_self("N")
            if line_cap:
                height = space("N", "E")
                if diam["N"] > 0 and height > 0:
                    p["NN"] = coeff*math.log(2.0*height/diam["N"]*24.0)
                else:
                    valid = False
                    if warn:
                        out.warning(f"Shunt capacitance of overhead line:{name} not calculated - invalid values")
        def zv(x:str, y:str) -> complex:
            return z.get(x + y, z.get(y + x, 0j))
        zabc = np.zeros((3, 3), dtype=complex)
        for i, x in enumerate(letters):
            for j, y in enumerate(letters):
                zabc[i, j] = (zv(x, y) - zv(x, "N")*zv(y, "N")*z_nn_inv)*miles
        yabc = np.zeros((3, 3), dtype=complex)
        if valid and line_cap:
            def pv(x:str, y:str) -> float:
                return p.get(x + y, p.get(y + x, 0.0))
            pnn = pv("N", "N")
            pmat = np.zeros((3, 3))
            for i, x in enumerate(letters):
                for j, y in enumerate(letters):
                    pmat[i, j] = pv(x, y) - (pv(x, "N")*pv(y, "N")/pnn if pnn != 0 else 0.0)
            mask = [k for k, x in enumerate(letters) if has(phases, dict(PHASES)[x])]
            if has(phases, PHASE_D):
                mask = [0, 1, 2]
            if mask:
                multiplier = 1j*2.0*math.pi*frequency(model)*1e-6*miles
                yabc[np.ix_(mask, mask)] = np.linalg.inv(pmat[np.ix_(mask, mask)])*multiplier
        return zabc, yabc

__all__ = ["OverheadLine", "GeometricLine", "matrix_based"]
