# pylint: disable=line-too-long
"""Class `transformer`: a distribution transformer

Syntax
------

    object transformer {
        phases {A,B,C,N,S}[|...];
        from <node>;
        to <node>;
        configuration <transformer_configuration>;
        degradation_factor <real> pu;
        // thermal model properties (published, not used)
        // and the other properties of link
    }

Description
-----------

A `transformer` is a `link` (gridlabd `PT_INHERIT "link"`) whose
admittance is that of gridlabd's NR solver for the connection type of its
`transformer_configuration`. With `nt = primary_voltage/secondary_voltage
* (1 - degradation_factor)` and the series impedance on the secondary side
`zt = impedance * Vb^2 / (power_rating * 1000)` (`Vb = secondary_voltage /
(1 - degradation_factor)`), and `Yt = 1/zt` on each phase the transformer
has (every phase for `DELTA_DELTA` and `DELTA_GWYE`), the blocks are (as
gridlabd's `link::init()` builds `YSfrom`, `From_Y`, `To_Y`, `YSto`):

- `WYE_WYE`, `SINGLE_PHASE`, `DELTA_DELTA`: `Yff = Yt/nt^2`, `Yft = Ytf =
  -Yt/nt`, `Ytt = Yt`, phase by phase;
- `DELTA_GWYE`: `Yff = Yt/nt^2`, `Yft = -B Yt`, `Ytf = -Yt C`, `Ytt = Yt`,
  where for a step-down transformer (`nt > 1`) `C = [[1,0,-1],[-1,1,0],
  [0,-1,1]]/(nt sqrt 3)` and `B` is its transpose (the secondary lags the
  primary by 30 degrees), and for a step-up transformer `C` and `B` are
  exchanged (the secondary leads by 30 degrees);
- `SINGLE_PHASE_CENTER_TAPPED`: from its primary phase to lines 1 and 2
  of its split-phase to node, gridlabd's NR model (`Transformer.center_tapped()`:
  primary and half-winding impedances from `impedance` split 0.5R+0.8jX on
  the primary and R+0.4jX on each half, or `impedance`, `impedance1`,
  `impedance2` when `impedance1` is set, on the bases of the phase's kVA
  rating, and the magnetizing impedance), in the nodes' convention for
  line 2.

The shunt (magnetizing) impedance is not in gridlabd's NR admittance of
the three-phase connections, so it is not used there. The fast-decoupled and DC methods use the self impedance
`zt*nt` of each phase (the series impedance seen across the nominal
voltages of the two nodes), and the DC method the 30-degree shift of a
delta-wye transformer.

When it initializes, a transformer is expected to:

1. fail when it has no configuration ("no transformer configuration
   specified.") or the configuration is not a `transformer_configuration`
   ("invalid transformer configuration"), and wait for its configuration
   to initialize;
2. initialize as a `link`, with gridlabd's phase checks for delta-wye and
   split-phase transformers;
3. fail when `degradation_factor` is not in [0, 1);
4. fail when it has phase `S` or its to node is split-phase but it is not
   center-tapped, and, when it is center-tapped, when its configuration has
   no rating for its phase;
5. warn that the thermal model is not ported when `use_thermal_model` is
   set.

Caveats
-------

- The thermal and aging model, in-rush, saturation, and deltamode are not
  ported; their properties are published.
- Delta-delta and delta-wye primaries have gridlabd's phase-by-phase
  `Yff`, which gives the primary a zero-sequence path that a physical
  delta winding does not have; this matters only when the primary
  voltages are unbalanced in zero sequence.
- The fast-decoupled methods leave the 30-degree shift of a delta-wye
  transformer out of their iteration matrices (the mismatches include it),
  so they may need more iterations.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. Transformers work with every solver method; gridlabd refuses methods
   other than NR and FBS (FBS is solved with NR here).
2. A `degradation_factor` outside [0, 1) and a triplex phase or to node
   on a transformer that is not center-tapped fail the initialization;
   gridlabd writes the error and goes on (dividing by zero when
   `degradation_factor` is 1).

References
----------

- `arras-energy/gridlabd`: `module/powerflow/transformer.cpp`,
  `link.cpp` (`link::init()`, `NR_branch_init`)
- W. H. Kersting, *Distribution System Modeling and Analysis*, 4th ed.,
  CRC Press, 2017, chapter 8
"""

import math
from typing import Any

import numpy as np

from ._base import prop
from ._common import (PHASE_A, PHASE_B, PHASE_C, PHASE_N, PHASE_D, PHASE_S, isa, ref, msg, get_int,
    get_double, get_complex, object_state, PowerflowError)
from .link import Link
from .transformer_configuration import WYE_WYE, DELTA_DELTA, DELTA_GWYE, SINGLE_PHASE, SINGLE_PHASE_CENTER_TAPPED

STEP_DOWN = np.array([[1, 0, -1], [-1, 1, 0], [0, -1, 1]], dtype=float)
"""Delta-wye voltage matrix of a step-down transformer, times `nt sqrt 3`
(gridlabd `c_mat`)"""

class Transformer(Link):
    """Behavior of class `transformer`"""

    NAME = "transformer"
    PARENT = "link"
    PROPERTIES = (
        ("configuration", "object", prop("Configuration library used for transformer setup", flags="REQUIRED")),
        ("climate", "object", prop("climate object used to describe thermal model ambient temperature")),
        ("ambient_temperature[degC]", "double", prop("ambient temperature in degrees C")),
        ("top_oil_hot_spot_temperature[degC]", "double", prop("top-oil hottest-spot temperature, degrees C")),
        ("winding_hot_spot_temperature[degC]", "double", prop("winding hottest-spot temperature, degrees C")),
        ("percent_loss_of_life", "double", prop("the percent loss of life")),
        ("aging_constant", "double", prop("the aging rate slope for the transformer insulation")),
        ("use_thermal_model", "bool", prop("boolean to enable use of thermal model", "FALSE")),
        ("transformer_replacement_count", "double", prop("counter of the number times the transformer has been replaced due to lifetime failure")),
        ("aging_granularity[s]", "double", prop("maximum timestep before updating thermal and aging model in seconds")),
        *((f"phase_{x}_{side}_flux_value[Wb]", "double", prop(f"instantaneous magnetic flux in phase {x} on the {side} side of the transformer during saturation calculations"))
            for side in ("primary", "secondary") for x in "ABC"),
        ("degradation_factor[pu]", "double", prop("turns ratio degradataion factor (0 means no degradation)")),
    )

    @classmethod
    def deferred(cls, model:Any, name:str) -> bool:
        """The configuration checks of `transformer::init()`, then wait for
        the configuration and the nodes"""
        config = ref(model, name, "configuration")
        if config is None:
            raise PowerflowError("no transformer configuration specified.")
        if not isa(model, config, "transformer_configuration"):
            raise PowerflowError("invalid transformer configuration")
        if not object_state(model, config).get("initialized"):
            return True
        return super().deferred(model, name)

    @classmethod
    def connect_type(cls, model:Any, name:str) -> int:
        """`connect_type` of the configuration"""
        return get_int(model, ref(model, name, "configuration"), "connect_type")

    @classmethod
    def check_phases(cls, model:Any, name:str) -> None:
        """`link::init()` phase checks of delta-wye and split-phase
        transformers (gridlabd `SpecialLnk` `DELTAGWYE`, `SPLITPHASE`)"""
        connect = cls.connect_type(model, name)
        obj = model.objects[name]
        fnode, tnode = ref(model, name, "from"), ref(model, name, "to")
        phases = get_int(model, name, "phases") & ~(PHASE_N | PHASE_D)
        fphases, tphases = get_int(model, fnode, "phases") & phases, get_int(model, tnode, "phases") & phases
        label = name if name != f"{obj.oclass.name}:{obj.id}" else "Unnamed"
        if connect == SINGLE_PHASE_CENTER_TAPPED:
            if tphases & PHASE_S != PHASE_S:
                raise PowerflowError(f"transformer:{obj.id} (split phase) - {label} has a phase mismatch the \"to\" end")
            if fphases & ~PHASE_S != phases & ~PHASE_S:
                raise PowerflowError(f"transformer:{obj.id} (split phase) - {label} has a phase mismatch the \"from\" end")
            if tphases != phases:
                msg(model, name).warning(f"transformer:{obj.id} (split phase) - {label} has a phase mismatch against the triplex end")
        elif connect == DELTA_GWYE:
            if fphases != phases or tphases != phases:
                raise PowerflowError(f"transformer:{obj.id} (delta-grounded wye) - {name} has a phase mismatch at one or both ends")
        else:
            super().check_phases(model, name)

    @classmethod
    def init_link(cls, model:Any, name:str) -> None:
        """`transformer::init()` after `link::init()`; raises
        `PowerflowError`"""
        super().init_link(model, name)
        obj = model.objects[name]
        out = msg(model, name)
        label = name if name != f"{obj.oclass.name}:{obj.id}" else "unnamed"
        config = ref(model, name, "configuration")
        degradation = get_double(model, name, "degradation_factor")
        if degradation < 0 or degradation >= 1:
            raise PowerflowError("degradation_factor must be between 0 and 1 pu")
        connect = cls.connect_type(model, name)
        phases = get_int(model, name, "phases")
        tphases = get_int(model, ref(model, name, "to"), "phases")
        if connect in (WYE_WYE, SINGLE_PHASE, DELTA_DELTA, DELTA_GWYE):
            if PHASE_S in (phases & PHASE_S, tphases & PHASE_S):
                raise PowerflowError(f"Transformer:{label} has a triplex phase or a triplex \"to\" node, but it is not an SPCT transformer")
        elif connect == SINGLE_PHASE_CENTER_TAPPED:
            for x, bit in (("A", PHASE_A), ("B", PHASE_B), ("C", PHASE_C)):
                if phases & bit:
                    if get_double(model, config, f"power{x}_rating") == 0:
                        raise PowerflowError(f"Split-phase tranformer:{obj.id} trying to attach to phase {x} not defined in the configuration")
                    break
        if get_int(model, name, "use_thermal_model"):
            out.warning(f"transformer:{obj.id} ({name}): the thermal model is not implemented, use_thermal_model ignored")

    @classmethod
    def ratio_impedance(cls, model:Any, name:str) -> tuple[float,complex]:
        """`nt` (primary/secondary voltage) and `zt` (ohms, secondary
        side)"""
        config = ref(model, name, "configuration")
        degradation = get_double(model, name, "degradation_factor")
        vsec = get_double(model, config, "secondary_voltage")
        vbase = vsec/(1 - degradation)
        nt = get_double(model, config, "primary_voltage")/vsec*(1 - degradation)
        zt = get_complex(model, config, "impedance")*vbase*vbase/(get_double(model, config, "power_rating")*1000.0)
        return nt, zt

    @classmethod
    def admittance(cls, model:Any, name:str) -> tuple[np.ndarray,np.ndarray,np.ndarray,np.ndarray]:
        """gridlabd's NR admittance (see the module description)"""
        connect = cls.connect_type(model, name)
        if connect == SINGLE_PHASE_CENTER_TAPPED:
            y = cls.center_tapped(model, name)
            yff, yft, ytf, ytt = (np.zeros((3, 3), dtype=complex) for _ in range(4))
            yff[0, 0] = y[0, 0]
            yft[0, :2] = y[0, 1:]
            ytf[:2, 0] = y[1:, 0]
            ytt[:2, :2] = y[1:, 1:]
            return yff, yft, ytf, ytt
        nt, zt = cls.ratio_impedance(model, name)
        mask = np.ones(3) if connect in (DELTA_DELTA, DELTA_GWYE) else cls.phase_mask(model, name)
        yt = np.diag(mask/zt).astype(complex)
        if connect == DELTA_GWYE:
            alpha = nt*math.sqrt(3)
            c = (STEP_DOWN if nt > 1 else STEP_DOWN.T)/alpha
            return yt/nt**2, -c.T @ yt, -yt @ c, yt.copy()
        return yt/nt**2, -yt/nt, -yt/nt, yt.copy()

    @classmethod
    def center_tapped(cls, model:Any, name:str) -> np.ndarray:
        """Admittance (3x3, siemens) of a center-tapped transformer between
        its primary and lines 1 and 2, in the nodes' convention (line 2
        measured from the neutral to the line), from gridlabd's NR model:
        primary impedance `z0`, magnetizing impedance `zc` after it, an ideal
        transformer of ratio `nt` to each half winding, and half-winding
        impedances `z1`, `z2`"""
        # pylint: disable=too-many-locals
        config = ref(model, name, "configuration")
        degradation = get_double(model, name, "degradation_factor")
        vprimary = get_double(model, config, "primary_voltage")
        vsecondary = get_double(model, config, "secondary_voltage")
        nt = vprimary/vsecondary*(1 - degradation)
        vbase = vsecondary/(1 - degradation)
        phases = get_int(model, name, "phases")
        x = "A" if phases & PHASE_A else ("B" if phases & PHASE_B else "C")
        rating = get_double(model, config, f"power{x}_rating")*1000
        high, low = vprimary*vprimary/rating, vbase*vbase/rating
        z, z1, z2, zs = (get_complex(model, config, key) for key in ("impedance", "impedance1", "impedance2", "shunt_impedance"))
        if z1 == 0:
            z0 = complex(0.5*z.real, 0.8*z.imag)*high
            z1 = z2 = complex(z.real, 0.4*z.imag)*low
        else:
            z0, z1, z2 = z*high, z1*low, z2*low
        zc = high*zs.real*1j*zs.imag/zs
        y = np.zeros((3, 3), dtype=complex)
        for col in range(3):
            v = np.zeros(3, dtype=complex)
            v[col] = 1
            vs, v1, v2 = v[0], v[1], -v[2] # line 2 in the physical direction
            a = np.array([[z0, 0, 0, nt], [1, 1/nt, -1/nt, -nt/zc], [0, z1, 0, 1], [0, 0, z2, -1]], dtype=complex)
            ip, j1, j2, _ = np.linalg.solve(a, np.array([vs, 0, v1, v2], dtype=complex))
            y[:, col] = (ip, j1, -j2)
        return y

    @classmethod
    def bus_slots(cls, model:Any, name:str) -> tuple[list[int],list[int]]:
        """A center-tapped transformer's primary phase at the from end and
        lines 1 and 2 at the to end; the phases otherwise"""
        if cls.connect_type(model, name) != SINGLE_PHASE_CENTER_TAPPED:
            return super().bus_slots(model, name)
        phases = get_int(model, name, "phases")
        primary = 0 if phases & PHASE_A else (1 if phases & PHASE_B else 2)
        return [primary, -1, -1], [0, 1, -1]

    @classmethod
    def paths(cls, model:Any, name:str) -> list[tuple[int,...]]|None:
        """A center-tapped transformer conducts from its primary to both
        lines, which are coupled through the primary impedance"""
        return [(0, 0, 1, 0), (0, 0, 1, 1), (1, 0, 1, 1)] if cls.connect_type(model, name) == SINGLE_PHASE_CENTER_TAPPED else None

    @classmethod
    def dc_model(cls, model:Any, name:str) -> tuple[np.ndarray|None,float]:
        """Self impedance `zt*nt` of each phase and, for delta-wye, the
        30-degree shift"""
        connect = cls.connect_type(model, name)
        if connect == SINGLE_PHASE_CENTER_TAPPED:
            return None, 0.0
        nt, zt = cls.ratio_impedance(model, name)
        shift = (math.pi/6 if nt > 1 else -math.pi/6) if connect == DELTA_GWYE else 0.0
        return np.full(3, zt*nt), shift

    @classmethod
    def admittance_key(cls, model:Any, name:str) -> tuple:
        """The link's key, the ratio and impedance, and the connection"""
        config = ref(model, name, "configuration")
        values = tuple(get_complex(model, config, x) if x.endswith("impedance") or x[-1] in "12" else get_double(model, config, x)
            for x in ("primary_voltage", "secondary_voltage", "power_rating", "powerA_rating", "powerB_rating", "powerC_rating",
                "impedance", "impedance1", "impedance2", "shunt_impedance"))
        return super().admittance_key(model, name) + (config, cls.connect_type(model, name), values, get_double(model, name, "degradation_factor"))

__all__ = ["Transformer"]
