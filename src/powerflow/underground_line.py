# pylint: disable=line-too-long
"""Class `underground_line`: a line of underground cables

Syntax
------

    object underground_line {
        phases {A,B,C,N}[|...];
        from <node>;
        to <node>;
        length <real> ft;
        configuration <line_configuration>;
        ductbank <object>;
        // and the other properties of line and link
    }

Description
-----------

An `underground_line` is a `line` whose configuration gives either the
impedance and capacitance matrices directly (`z11`, `z22`, or `z33` not
0: the `line` model) or the cables of each phase and the neutral
(`conductor_A` ... `conductor_N`, `underground_line_conductor`) and their
`line_spacing`. It initializes as `overhead_line` does, with
`underground_line_conductor` cables and "underground" in the messages.

From cables and spacing, as gridlabd's `underground_line::recalc()`
(Kersting, chapters 4 and 5), per mile then times the length:

- conductors 1 to 3 are the phase conductors, 4 to 6 their concentric
  neutrals or tape shields, 7 the separate neutral;
- concentric-neutral cables (a neutral GMR set, no shield GMR): each
  neutral is the equivalent conductor of its strands at the radius
  `(outer_diameter - neutral_diameter)/24`; `Zabc` is the Kron reduction
  of conductors 4 to 6 (the separate neutral is not used); with
  `powerflow::line_capacitance`, each phase's capacitance to its neutral
  is `2 pi e0 er / (ln(R/rc) - ln(k rs/R)/k)`;
- tape-shielded cables (a shield GMR set): the shields' self impedances
  include their resistance, the conductor-to-shield terms use the shield
  GMR, and `Zabc` is the Kron reduction of conductors 4 to 7; the
  capacitance is `2 pi e0 er / ln(R/rc)` with `R` half the shield's
  diameter less its thickness and `rc` half the conductor diameter (in
  inches, as gridlabd computes it);
- insulated cables (no neutral or shield GMR): the separate neutral's
  self term is taken from phase A's (or the first phase's) neutral data,
  as gridlabd takes it, so with those 0 there is no Kron reduction, and
  no capacitance.

A phase the line does not have gets 1 on the diagonal of the neutral
matrix before its inversion, as in gridlabd. Each phase whose capacitance
cannot be computed (a zero diameter, radius, or strand count, or a zero
denominator) gets none, with a warning.

A line whose `ductbank` names a `ductbank` adds its cables (the
conductors of its configuration) and its losses to the duct bank's
thermal model (`powerflow.ductbank`).

Caveats
-------

- The ratings gridlabd derives from the cables are not used.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A conductor check message names the line (`... of underground line
   NAME`); gridlabd's format has no `%s` for the name it passes.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/underground_line.cpp`
- W. H. Kersting, *Distribution System Modeling and Analysis*, 4th ed.,
  CRC Press, 2017, examples 4.3, 4.4, 5.2, 5.3
"""

import math
from typing import Any

import numpy as np

from ._base import prop
from ._common import PHASE_A, PHASE_B, PHASE_C, PHASE_N, g, ref, get_int, get_double, PowerflowError
from .line import frequency, PERMITIVITTY_FREE
from .overhead_line import GeometricLine, has

class UndergroundLine(GeometricLine):
    """Behavior of class `underground_line`"""

    NAME = "underground_line"
    PARENT = "line"
    CONDUCTOR = "underground_line_conductor"
    KIND = "underground"
    PROPERTIES = (
        ("ductbank", "object", prop("duct bank in which cable lies")),
    )

    @classmethod
    def geometric_matrices(cls, model:Any, name:str, warn:bool) -> tuple[np.ndarray,np.ndarray]:
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        out, phases, config, spacing, miles, (real, imag, additive) = cls.setup(model, name)
        bits = {"A": PHASE_A, "B": PHASE_B, "C": PHASE_C, "N": PHASE_N}
        conductor = {x: ref(model, config, f"conductor_{x}") for x in "ABCN"}
        def ug(x:str, prop_:str) -> float:
            if has(phases, bits[x]) and conductor[x]:
                return float(get_int(model, conductor[x], prop_)) if prop_ == "neutral_strands" else get_double(model, conductor[x], prop_)
            return 0.0
        od = [ug(x, "outer_diameter") for x in "ABC"]
        gmr = [ug("A", "conductor_gmr"), ug("B", "conductor_gmr"), ug("C", "conductor_gmr"),
            ug("A", "neutral_gmr"), ug("B", "neutral_gmr"), ug("C", "neutral_gmr"), ug("N", "conductor_gmr")]
        dia = [ug("A", "conductor_diameter"), ug("B", "conductor_diameter"), ug("C", "conductor_diameter"),
            ug("A", "neutral_diameter"), ug("B", "neutral_diameter"), ug("C", "neutral_diameter"), ug("N", "conductor_diameter")]
        res = [ug("A", "conductor_resistance"), ug("B", "conductor_resistance"), ug("C", "conductor_resistance"),
            ug("A", "neutral_resistance"), ug("B", "neutral_resistance"), ug("C", "neutral_resistance"), ug("N", "conductor_resistance")]
        gmrs = [ug(x, "shield_gmr") for x in "ABC"]
        ress = [ug(x, "shield_resistance") for x in "ABC"]
        thickness = [ug(x, "shield_thickness") for x in "ABC"]
        shield_dia = [ug(x, "shield_diameter") for x in "ABC"]
        strands = [int(ug(x, "neutral_strands")) for x in "ABC"]
        if not any(gmrs):
            rad = [(od[k] - dia[3+k])/24.0 for k in range(3)]
        else:
            rad = [0.0, 0.0, 0.0]
        present = [has(phases, bits[x]) for x in "ABC"]
        rcn = [res[3+k]/strands[k] if present[k] and strands[k] > 0 else 0.0 for k in range(3)]
        gmrcn = [(gmr[3+k]*strands[k]*rad[k]**(strands[k]-1))**(1.0/strands[k]) if present[k] and strands[k] > 0 else 0.0 for k in range(3)]
        insulated = not any(gmr[3:6]) and not any(gmrs)
        concentric = False
        if not insulated:
            if not any(gmrs):
                concentric = True
            else:
                rad = [(shield_dia[k] - thickness[k])/2 for k in range(3)]
        line_cap = bool(g(model, "line_capacitance"))
        perm = [ug(x, "insulation_relative_permitivitty") for x in "ABC"] if line_cap and not insulated else [0.0, 0.0, 0.0]
        def dist(x:str, y:str) -> float:
            if not (has(phases, bits[x]) and has(phases, bits[y]) and spacing):
                return 0.0
            return get_double(model, spacing, f"distance_{x}{y}")
        ab, ac, bc = dist("A", "B"), dist("A", "C"), dist("B", "C")
        an, bn, cn = dist("A", "N"), dist("B", "N"), dist("C", "N")
        r1, r2, r3 = (gmrs[k] if gmrs[k] > 0 else rad[k] for k in range(3))
        upper = {(1, 2): ab, (1, 3): ac, (1, 4): r1, (1, 5): ab, (1, 6): ac, (1, 7): an,
            (2, 3): bc, (2, 4): ab, (2, 5): r2, (2, 6): bc, (2, 7): bn,
            (3, 4): ac, (3, 5): bc, (3, 6): r3, (3, 7): cn,
            (4, 5): ab, (4, 6): ac, (4, 7): an, (5, 6): bc, (5, 7): bn, (6, 7): cn}
        d = np.zeros((8, 8))
        for (i, j), value in upper.items():
            d[i, j] = d[j, i] = value
        def z_gmr(i:int) -> complex:
            return 0j if gmr[i-1] == 0 else complex(real + res[i-1], imag*(math.log(1.0/gmr[i-1]) + additive))
        def z_gmrcn(i:int) -> complex:
            return 0j if gmrcn[i-4] == 0 else complex(real + rcn[i-4], imag*(math.log(1.0/gmrcn[i-4]) + additive))
        def z_dist(i:int, j:int) -> complex:
            return 0j if d[i, j] == 0 else complex(real, imag*(math.log(1.0/d[i, j]) + additive))
        def z_shield_self(i:int) -> complex:
            return 0j if gmrs[i-4] == 0 else complex(real + ress[i-4], imag*(math.log(1.0/gmrs[i-4]) + additive))
        def z_shield(i:int) -> complex:
            return 0j if gmrs[i-4] == 0 else complex(real, imag*(math.log(1.0/gmrs[i-4]) + additive))
        z = np.zeros((8, 8), dtype=complex)
        for i in range(1, 8):
            for j in range(1, 8):
                if concentric:
                    if i == j:
                        z[i, j] = z_gmrcn(i) if 3 < i < 7 else z_gmr(i)
                    else:
                        z[i, j] = z_dist(i, j)
                elif i == j:
                    if 3 < i < 7:
                        z[i, j] = z_shield_self(i)
                    elif i == 7:
                        first = next((k for k in range(3) if present[k]), None)
                        z[i, j] = z_gmr(4 + first) if first is not None else 0j
                    else:
                        z[i, j] = z_gmr(i)
                elif (i, j) in ((1, 4), (2, 5), (3, 6)):
                    z[i, j] = z_shield(j)
                else:
                    z[i, j] = z_dist(i, j)
        if not insulated:
            neutrals = [4, 5, 6] if concentric else [4, 5, 6, 7]
            zij = z[1:4, 1:4]
            zin = z[1:4, neutrals]
            znj = z[neutrals, 1:4]
            znn = z[np.ix_(neutrals, neutrals)].copy()
            if not all(present):
                for k in range(3):
                    if not present[k]:
                        znn[k, k] = 1.0
            try:
                zabc = (zij - zin @ np.linalg.inv(znn) @ znj)*miles
            except np.linalg.LinAlgError as err:
                raise PowerflowError(f"underground_line:{model.objects[name].id} - {name} - singular neutral impedance matrix") from err
        else:
            inv = 1/z[7, 7] if z[7, 7] != 0 else 0j
            zabc = np.array([[(z[i, j] - z[i, 7]*z[j, 7]*inv)*miles for j in range(1, 4)] for i in range(1, 4)])
        yabc = np.zeros((3, 3), dtype=complex)
        if line_cap and not insulated:
            multiplier = 1j*2.0*math.pi*frequency(model)*1e-6*miles
            for k in range(3):
                if not present[k]:
                    continue
                if dia[k] == 0 or rad[k] == 0 or (concentric and strands[k] == 0):
                    if warn:
                        out.warning(f"Unable to compute capacitance for {name}")
                    continue
                if concentric:
                    denom = math.log(rad[k]/(dia[k]/24.0)) - (1.0/strands[k])*math.log(strands[k]*dia[3+k]/24.0/rad[k])
                else:
                    denom = math.log(rad[k]/(dia[k]/2.0))
                if denom == 0:
                    if warn:
                        out.warning(f"Capacitance calculation failure for {name}")
                    continue
                yabc[k, k] = multiplier*(2.0*math.pi*PERMITIVITTY_FREE*perm[k])/denom
        return zabc, yabc
