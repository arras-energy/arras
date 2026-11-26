# pylint: disable=line-too-long
"""Class `line`: a link with a series impedance and a shunt capacitance

Syntax
------

    object line {
        phases {A,B,C,D,N}[|...];
        from <node>;
        to <node>;
        configuration <line_configuration>;
        length <real> ft;
        // and the other properties of link
    }

Description
-----------

`line` inherits the properties of `link` and adds `configuration` (the
line's `line_configuration`) and `length` (feet). gridlabd recommends its
subclasses (`overhead_line`, `underground_line`, `triplex_line`), which
compute their matrices from conductors and spacings; a `line` object
uses the matrix form of its configuration. When a line initializes, it is
expected to:

1. initialize as a `link` (and wait for its nodes when `link` does);
2. fail when the nominal voltages of its nodes differ by more than 0.1% of
   the from node's;
3. fail when its length is 0, whatever the solver method (every method
   inverts the line's impedance);
4. for an object of class `line` itself: warn that a subclass is
   recommended, fail when `configuration` is not a `line_configuration`,
   and warn when the configuration has a shunt capacitance (`c11`, `c22`,
   or `c33` not 0) while `powerflow::line_capacitance` is false (the
   capacitance is then left out).

In the network, a line is the pi model of Kersting's (6.9)–(6.18), as
gridlabd's NR solver uses it:

- `Zabc = zIJ * length / 5280` ohms on the phases the line has (an
  off-diagonal term only when both of its phases are present);
- `Yabc = j 2 pi f cIJ 1e-9 * length / 5280` siemens on the same terms,
  where `f` is `powerflow::nominal_frequency`, or 0 when
  `powerflow::line_capacitance` is false;
- series admittance `inv(Zabc)` on the line's phases, and `Yabc / 2` at
  each end.

The classes still to be ported that derive from `line` override
`Line.line_matrices()`.

Caveats
-------

- `overhead_line`, `underground_line`, and `triplex_line` are not ported
  yet; nor are the conductor and spacing classes.
- Line ratings and limits (`powerflow::line_limits`) are not implemented.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A zero-length line fails whatever the solver method: every method of
   the module inverts the line's impedance. gridlabd fails it only with
   NR (FBS uses the impedance without inverting it). The message is
   gridlabd's ("Newton-Raphson method does not support zero length lines
   at this time") for NR and FBS, and names the method (`FD_XB`, `FD_BX`,
   `DC`) for the others.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/line.cpp`, `line.h`,
  `link.cpp` (`NR_init`: the shunt admittance of lines)
- W. H. Kersting, *Distribution System Modeling and Analysis*, 4th ed.,
  CRC Press, 2017, chapter 6
"""

import math
from typing import Any

import numpy as np

from ._base import prop
from ._common import isa, ref, g, msg, get_double, PowerflowError, SM_FBS, SM_NR, SM_FD_XB, SM_FD_BX, SM_DC
from .link import Link
from .line_configuration import LineConfiguration

EARTH_RESISTIVITY = 100.0
"""Earth resistivity (ohm-m) of Carson's equations (gridlabd `EARTH_RESISTIVITY`)"""

PERMITIVITTY_AIR = 0.014240
"""Permittivity of air (uF/mile), gridlabd `PERMITIVITTY_AIR`"""

PERMITIVITTY_FREE = 0.01420
"""Permittivity of free space (uF/mile), gridlabd `PERMITIVITTY_FREE`"""

def frequency(model:Any) -> float:
    """Frequency of the line models: `powerflow::current_frequency` when
    `powerflow::enable_frequency_dependence`, else
    `powerflow::nominal_frequency`"""
    if g(model, "enable_frequency_dependence"):
        return float(g(model, "current_frequency") or 60.0)
    return float(g(model, "nominal_frequency") or 60.0)

def carson(model:Any) -> tuple[float,float,float]:
    """Constants of the modified Carson's equations, as gridlabd computes
    them: `(real, imag, additive)`, where a self impedance is
    `r + real + j imag (ln(1/GMR) + additive)` and a mutual impedance
    `real + j imag (ln(1/D) + additive)` (ohm/mile, feet)"""
    f = frequency(model)
    return 0.00158836*f, 0.00202237*f, math.log(EARTH_RESISTIVITY/f)/2.0 + 7.6786

def snapshot(model:Any, *names:str|None) -> tuple:
    """Property values of objects (for admittance keys)"""
    return tuple((name, tuple(sorted((k, str(v)) for k, v in model.objects[name].items()))) if name in model.objects else (name,) for name in names)

def label(model:Any, name:str) -> str:
    """Name gridlabd prints for `obj->name`: the name, or `Unnamed`"""
    obj = model.objects[name]
    return "Unnamed" if name == f"{obj.oclass.name}:{obj.id}" else name

ZERO_LENGTH_METHODS = {SM_FBS: "Newton-Raphson", SM_NR: "Newton-Raphson", SM_FD_XB: "FD_XB", SM_FD_BX: "FD_BX", SM_DC: "DC"}
"""Method named in the zero-length line error: gridlabd's message for NR
(and FBS, which is solved with NR), the method's keyword for the others"""

class Line(Link):
    """Behavior of class `line`"""

    NAME = "line"
    PARENT = "link"
    PROPERTIES = (
        ("configuration", "object", prop("reference to library object that describes this line's configuration", flags="REQUIRED")),
        ("length[ft]", "double", prop("length of this line", flags="REQUIRED")),
    )

    @classmethod
    def init_link(cls, model:Any, name:str) -> None:
        """`line::init()` after `link::init()`; raises `PowerflowError`"""
        super().init_link(model, name)
        obj = model.objects[name]
        label = name if name != f"{obj.oclass.name}:{obj.id}" else "Unnamed"
        fnominal = get_double(model, ref(model, name, "from"), "nominal_voltage")
        tnominal = get_double(model, ref(model, name, "to"), "nominal_voltage")
        if abs(fnominal - tnominal) > 0.001*fnominal:
            raise PowerflowError("from and to node nominal voltage mismatch of greater than 0.1%%")
        if get_double(model, name, "length") == 0:
            raise PowerflowError(f"{ZERO_LENGTH_METHODS.get(g(model, 'solver_method'), 'Newton-Raphson')} method does not support zero length lines at this time")
        if obj.oclass.name == "line":
            out = msg(model, name)
            out.warning(f"line:{obj.id} - {label} - use of an overhead_line, underground_line, or other line-based subclass is highly recommended!")
            config = ref(model, name, "configuration")
            if not isa(model, config, "line_configuration"):
                raise PowerflowError(f"line:{obj.id} - {label} - configuration object either doesn't exist, or is not a valid configuration object!")
            c = LineConfiguration.capacitance(model, config)
            if (c[0, 0] != 0 or c[1, 1] != 0 or c[2, 2] != 0) and not g(model, "line_capacitance"):
                out.warning(f"Shunt capacitance of line:{name} specified without setting powerflow::line_capacitance = TRUE. Shunt capacitance will be ignored.")

    @classmethod
    def line_matrices(cls, model:Any, name:str) -> tuple[np.ndarray,np.ndarray]:
        """`Zabc` (ohms) and `Yabc` (siemens), 3x3, from the matrix form of
        the line's configuration (gridlabd
        `line::load_matrix_based_configuration()`)"""
        config = ref(model, name, "configuration")
        if not isa(model, config, "line_configuration"):
            raise PowerflowError(f"line {name}: configuration is not a line_configuration")
        miles = get_double(model, name, "length")/5280.0
        mask = cls.phase_mask(model, name)
        terms = np.outer(mask, mask)
        zabc = LineConfiguration.impedance(model, config)*miles*terms
        c = LineConfiguration.capacitance(model, config)
        if g(model, "line_capacitance"):
            frequency = float(g(model, "nominal_frequency") or 60.0)
            yabc = 1j*2*math.pi*frequency*1e-9*miles*c*terms
        else:
            yabc = np.zeros((3, 3), dtype=complex)
        return zabc.astype(complex), yabc.astype(complex)

    @classmethod
    def series_impedance(cls, model:Any, name:str) -> np.ndarray:
        """`Zabc` (ohms)"""
        return cls.line_matrices(model, name)[0]

    @classmethod
    def shunt_admittance(cls, model:Any, name:str) -> tuple[np.ndarray,np.ndarray]:
        """Half of `Yabc` at each end"""
        half = cls.line_matrices(model, name)[1]/2
        return half, half.copy()

    @classmethod
    def admittance_key(cls, model:Any, name:str) -> tuple:
        """The link's key, the length, the configuration's matrices, and the
        capacitance globals"""
        config = ref(model, name, "configuration")
        values = LineConfiguration.key(model, config) if isa(model, config, "line_configuration") else (config,)
        return super().admittance_key(model, name) + (get_double(model, name, "length"), config, values,
            g(model, "line_capacitance"), g(model, "nominal_frequency"))
