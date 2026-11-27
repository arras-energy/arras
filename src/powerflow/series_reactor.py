# pylint: disable=line-too-long
"""Class `series_reactor`: a link with a series impedance on each phase

Syntax
------

    object series_reactor {
        phases {A,B,C}[N];
        from <node>;
        to <node>;
        phase_A_impedance <complex> Ohm;   // or phase_A_resistance, phase_A_reactance
        phase_B_impedance <complex> Ohm;
        phase_C_impedance <complex> Ohm;
        rated_current_limit <real> A;
        // and the other properties of link
    }

Description
-----------

A `series_reactor` is a `link` (gridlabd `PT_INHERIT "link"`) whose phases
are each a series impedance, with no coupling between the phases and no
shunt admittance: the admittance of phase `X` is `1/phase_X_impedance`,
or `1e4+1e4j` S when the impedance is 0, as gridlabd's NR solver sets it.
Like a switch (gridlabd sets `SpecialLnk = SWITCH`), an open reactor
whose to node has no other link takes the to node's phases out of the
network (`Link.SWITCH`).

`phase_X_resistance` and `phase_X_reactance` are the parts of
`phase_X_impedance` (gridlabd publishes them at the addresses of its real
and imaginary parts): when it initializes, the reactor takes them in the
order the object set them (the last one set wins) and writes all three.
The impedances are read once, at initialization, as gridlabd's static
reactor does. `rated_current_limit` is published and not used, as in
gridlabd.

In the DC method each phase's reactance is the imaginary part of its
impedance, or its magnitude when that is not positive (a resistive
reactor, or the zero-impedance admittance whose reactance is negative).

When it initializes, a series reactor is expected to initialize as a
`link`, then to resolve its impedances.

Caveats
-------

- Deltamode and the link limit checks are not ported.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The admittance is the NR one with every solver method (FBS is solved
   with NR); gridlabd's FBS uses the impedance itself, so a zero impedance
   is a short circuit there.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/series_reactor.cpp`,
  `series_reactor.h`
"""

from typing import Any

import numpy as np

from ._base import prop
from ._common import PHASE_BITS, object_state, get_int, set_complex, set_double, text_to_complex, text_to_double
from .link import Link

ZERO_ADMITTANCE = complex(1e4, 1e4)
"""Admittance (S) of a phase whose impedance is 0 (gridlabd's NR value)"""

def _parts(x:str) -> tuple:
    return (
        (f"phase_{x}_impedance[Ohm]", "complex", prop(f"Series impedance of reactor on phase {x}")),
        (f"phase_{x}_resistance[Ohm]", "double", prop(f"Resistive portion of phase {x}'s impedance")),
        (f"phase_{x}_reactance[Ohm]", "double", prop(f"Reactive portion of phase {x}'s impedance")),
    )

class SeriesReactor(Link):
    """Behavior of class `series_reactor`"""

    NAME = "series_reactor"
    PARENT = "link"
    SWITCH = True
    PROPERTIES = (
        *_parts("A"), *_parts("B"), *_parts("C"),
        ("rated_current_limit[A]", "double", prop("Rated current limit for the reactor")),
    )

    @classmethod
    def init_link(cls, model:Any, name:str) -> None:
        """`link::init()`, then the impedances of `series_reactor::init()`"""
        super().init_link(model, name)
        impedances = []
        for x in "ABC":
            value = 0j
            for key, text in model.objects[name].items():
                if key == f"phase_{x}_impedance":
                    value = text_to_complex(text, "Ohm")
                elif key == f"phase_{x}_resistance":
                    value = complex(text_to_double(text, "Ohm"), value.imag)
                elif key == f"phase_{x}_reactance":
                    value = complex(value.real, text_to_double(text, "Ohm"))
            set_complex(model, name, f"phase_{x}_impedance", value)
            set_double(model, name, f"phase_{x}_resistance", value.real)
            set_double(model, name, f"phase_{x}_reactance", value.imag)
            impedances.append(value)
        object_state(model, name)["impedances"] = impedances

    @classmethod
    def phase_admittances(cls, model:Any, name:str) -> list[complex]:
        """Admittance (S) of each phase A, B, C (0 for a phase the reactor
        does not have)"""
        phases = get_int(model, name, "phases")
        impedances = object_state(model, name).get("impedances", [0j]*3)
        return [(1/z if z != 0 else ZERO_ADMITTANCE) if phases & bit else 0j for z, bit in zip(impedances, PHASE_BITS)]

    @classmethod
    def admittance(cls, model:Any, name:str) -> tuple[np.ndarray,np.ndarray,np.ndarray,np.ndarray]:
        """`1/phase_X_impedance` on each phase, no shunt"""
        y = np.diag(cls.phase_admittances(model, name))
        return y, -y, -y, y.copy()

    @classmethod
    def dc_model(cls, model:Any, name:str) -> tuple[np.ndarray|None,float]:
        """Each phase's impedance, with a reactance of its magnitude when
        its reactance is not positive"""
        result = []
        for y in cls.phase_admittances(model, name):
            z = 1/y if y != 0 else 0j
            result.append(z if z.imag > 0 else complex(z.real, abs(z)))
        return np.array(result), 0.0

    @classmethod
    def admittance_key(cls, model:Any, name:str) -> tuple:
        return super().admittance_key(model, name) + tuple(object_state(model, name).get("impedances", ()))

__all__ = ["SeriesReactor"]
