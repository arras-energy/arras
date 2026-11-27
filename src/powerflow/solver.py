# pylint: disable=line-too-long
"""Three-phase power flow with the vendored PYPOWER solvers

Syntax
------

    from powerflow.solver import Network, solve
    net = Network()
    a = net.add_bus("n1.A", vbase, v0, "REF")
    ...
    net.add_branch((a, b, c), (d, e, f), Yff, Yft, Ytf, Ytt)
    net.add_wye_load(d, S=..., I=..., Y=..., vnom=...)
    net.add_delta_load(d, e, S=..., I=..., Y=..., vnom=...)
    result = solve(net, "NR")

Description
-----------

The powerflow module replaces gridlabd's Newton-Raphson solver
(`solver_nr.cpp`) with PYPOWER 5.1.16 (`pypower._pypower`). PYPOWER solves
single-phase (positive-sequence) networks from a bus admittance matrix and
bus power injections; this module gives it a three-phase network in phase
coordinates instead, so that unbalanced flows are solved without a
sequence reduction:

1. every phase of every node is one solver bus, with the node's nominal
   (line-to-neutral) voltage as its base voltage;
2. every link contributes its four 3x3 admittance blocks (`Yff`, `Yft`,
   `Ytf`, `Ytt`, in siemens, including the mutual coupling between phases)
   to the bus admittance matrix, on the buses of the phases it connects;
3. constant-impedance loads (wye: phase to ground; delta: phase to phase)
   are added to the admittance matrix;
4. the matrix and the injections are put in per unit (`Sbase` 1 MVA by
   default, the bus base voltages) and passed to PYPOWER;
5. constant-power, constant-current, and fixed-current loads depend on
   the voltages (delta loads on phase-to-phase voltages, constant-current
   loads on voltage magnitudes and angles as gridlabd defines them, a
   fixed current, gridlabd's pre-rotated current, draws `V conj(I)`), so the
   injections are computed at the voltages of the last solution and
   PYPOWER is called again until the injections change by less than the
   solution tolerance (`max_outer` calls at most).

Given a network, `solve()` is expected to return the voltages at which:

- with `NR` (`newtonpf()`), `FD_XB`, or `FD_BX` (`fdpf()`), the power
  mismatch of every bus that is not a reference bus is below the
  tolerance in per unit, for the full three-phase network (the
  fast-decoupled methods only simplify their iteration matrices: B' and
  B'' are built phase by phase from the same-phase terms of the links'
  admittance matrices, without the terms between phases, because
  PYPOWER's decoupling assumes angles near zero while the phases of a
  three-phase network are 120 degrees apart; the XB and BX conventions
  leave the resistance out of B' and B'' respectively, as PYPOWER's
  `makeB()` does);
- with `DC` (`dcpf()`), the linear real-power equations of each phase
  hold, with the self reactances of the links only (the diagonal of each
  link's series impedance; the mutual coupling is left out), voltage
  magnitudes at their initial values, the loads evaluated at the initial
  voltages, and no losses or reactive flows. Branches added with
  `magnitude` (fuses) use the magnitude of their self impedance in the DC
  method, since their reactance has the wrong sign there. Branches added
  with `self_impedance` (transformers whose series admittance blocks are
  not diagonal, such as delta-wye) use those impedances in place of the
  diagonal of `inv(-Yft)` in the DC method and in the fast-decoupled
  matrices, and a branch's `shift` (radians, the angle by which the to
  end lags the from end at no load) is a fixed angle difference in the
  DC power equations. The fast-decoupled methods cannot solve purely
  resistive branches (plain links, regulators), whose real power depends
  on voltage magnitudes rather than angles; they solve them as reactances
  of the same magnitude (`Network.rotated()`), a simplification whose
  effect is a rotation of the small voltage drop across those branches.

Bus types follow PYPOWER: `REF` buses keep their voltage, `PV` buses
their voltage magnitude, `PQ` buses neither. Each island needs at least
one `REF` bus; islands follow the same-phase conduction paths of the
branches, so a phase cut off from every source is an island even when
the mutual coupling of a line still ties it to the other phases.

Examples
--------

A balanced load at the end of a three-phase line with mutual coupling, and
an unbalanced one, solved with NR and with the fast-decoupled method:

    >>> import numpy as np
    >>> from powerflow.solver import Network, solve, nominal
    >>> Z = np.array([[0.3465+1.0179j, 0.1560+0.5017j, 0.1580+0.4236j],
    ...               [0.1560+0.5017j, 0.3375+1.0478j, 0.1535+0.3849j],
    ...               [0.1580+0.4236j, 0.1535+0.3849j, 0.3414+1.0348j]]) * 0.5
    >>> Y = np.linalg.inv(Z)
    >>> net = Network()
    >>> src = [net.add_bus(f"src.{p}", 2401.8, nominal(2401.8, k), "REF") for k, p in enumerate("ABC")]
    >>> dst = [net.add_bus(f"dst.{p}", 2401.8, nominal(2401.8, k), "PQ") for k, p in enumerate("ABC")]
    >>> net.add_branch(src, dst, Y, -Y, -Y, Y)
    >>> for k, s in enumerate((300e3+150e3j, 100e3+50e3j, 200e3+100e3j)):
    ...     net.add_wye_load(dst[k], S=s)
    >>> nr = solve(net, "NR")
    >>> nr.success, [round(float(abs(v)), 1) for v in nr.V[3:]]
    (True, [2364.0, 2416.0, 2367.9])
    >>> fd = solve(net, "FD_XB")
    >>> fd.success, bool(np.max(np.abs(fd.V - nr.V)) < 1e-3)
    (True, True)

Caveats
-------

- Fast-decoupled methods converge slowly or not at all when lines have
  high resistance-to-reactance ratios, as distribution lines often do;
  their iteration limit is the same as NR's.
- PYPOWER's NR and FD solvers do not limit `PV` bus reactive power.
- Split-phase (triplex) buses are not supported yet.

References
----------

- `pypower._pypower`: `newtonpf.py`, `fdpf.py`, `dcpf.py`, `makeB.py`
  (the XB and BX conventions)
- W. H. Kersting, *Distribution System Modeling and Analysis*, 4th ed.,
  CRC Press, 2017 (phase-frame line models)
"""

import math
import cmath
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components

from pypower._pypower.newtonpf import newtonpf
from pypower._pypower.fdpf import fdpf
from pypower._pypower.dcpf import dcpf
from pypower._pypower.ppoption import ppoption

METHODS = ("NR", "FD_XB", "FD_BX", "DC")
"""Solver methods `solve()` accepts"""

BUS_TYPES = ("PQ", "PV", "REF")
"""Bus types"""

PHASE_ANGLES = (0.0, -2*math.pi/3, 2*math.pi/3)
"""Nominal angles of phases A, B, C (radians)"""

def nominal(vbase:float, phase:int) -> complex:
    """Nominal phase-to-ground voltage of a phase (0, 1, 2 for A, B, C)"""
    return cmath.rect(vbase, PHASE_ANGLES[phase])

class SolverError(Exception):
    """A network that cannot be solved (no reference bus in an island,
    unknown method or bus type)"""

@dataclass
class Result:
    """Result of `solve()`"""

    V: np.ndarray # pylint: disable=invalid-name
    """Bus voltages (V), complex, in bus order"""

    success: bool
    """`True` when the solution converged"""

    iterations: int = 0
    """PYPOWER iterations (all calls)"""

    calls: int = 0
    """PYPOWER calls"""

    message: str = ""
    """Why the solution failed"""

    diverged: bool = False
    """`True` when the failed solution is not usable (a singular matrix, or
    voltages that are not finite); `False` when it only needs more
    iterations"""

@dataclass
class Network: # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """A three-phase network in phase coordinates (see the module
    description); values in SI units (V, A, VA, S)"""

    sbase: float = 1e6
    """Base power (VA) of the per-unit system"""

    labels: list[str] = field(default_factory=list)
    """Bus labels"""

    vbase: list[float] = field(default_factory=list)
    """Bus base voltages (V)"""

    v0: list[complex] = field(default_factory=list)
    """Bus initial (and `REF`/`PV` set point) voltages (V)"""

    types: list[str] = field(default_factory=list)
    """Bus types (`PQ`, `PV`, `REF`)"""

    branches: list[tuple[tuple[int,...],tuple[int,...],np.ndarray,np.ndarray,np.ndarray,np.ndarray]] = field(default_factory=list)
    """Branches as `(from buses, to buses, Yff, Yft, Ytf, Ytt)`; a bus
    index of -1 is a phase the branch does not connect"""

    magnitude: list[bool] = field(default_factory=list)
    """For each branch: `True` when the DC method uses the magnitude of its
    self series impedance rather than its reactance, for branches whose
    reactance has the wrong sign (fuses)"""

    impedances: list[np.ndarray|None] = field(default_factory=list)
    """For each branch: the self series impedance of each phase (ohms,
    3 values, as the diagonal of `inv(-Yft)` would be) used by the DC and
    fast-decoupled methods, or `None` to use the diagonal of `inv(-Yft)`"""

    shifts: list[float] = field(default_factory=list)
    """For each branch: the angle (radians) by which the to end lags the
    from end at no load, used by the DC method"""

    wye: list[tuple[int,complex,complex,complex,complex]] = field(default_factory=list)
    """Wye loads `(bus, S, I, Y, vnom)`"""

    delta: list[tuple[int,int,complex,complex,complex,complex]] = field(default_factory=list)
    """Delta loads `(bus a, bus b, S, I, Y, vnom)`"""

    split: list[tuple[int,int,complex,complex,complex,complex]] = field(default_factory=list)
    """Split-phase (line 1 to line 2) loads `(bus 1, bus 2, S, I, Y, vnom)`"""

    fixed: list[tuple[int,int,complex]] = field(default_factory=list)
    """Fixed-current loads `(bus a, bus b, I)`: a current `I` (A) drawn at
    bus `a` whatever the voltage (gridlabd's pre-rotated current), or
    across the two lines of a split-phase node (both buses draw `I`) when
    bus `b` is not -1"""

    paths: list[list[tuple[int,int,int,int]]|None] = field(default_factory=list)
    """For each branch: its conduction paths as `(end a, slot a, end b, slot
    b)` with end 0 the from end and 1 the to end, whose admittance is the
    negative of the block term between them, or `None` for the same slot
    at both ends (`(0, p, 1, p)`); a split-phase transformer conducts from
    its primary slot to both secondary slots, and the coupling between the
    two lines of a split-phase branch at one end is a path too, since the
    lines are in phase (so the fast-decoupled matrices and the DC method
    keep them)"""

    def add_bus(self, label:str, vbase:float, v0:complex, btype:str="PQ") -> int:
        """Add a bus; returns its index

        Arguments
        ---------
        - `label`: name used in messages
        - `vbase`: base (nominal line-to-neutral) voltage (V), positive
        - `v0`: initial voltage (V); the set point of `REF` buses and the
          magnitude set point of `PV` buses
        - `btype`: `PQ`, `PV`, or `REF`

        Exceptions
        ----------
        - `SolverError`: the base voltage is not positive or the type is
          not valid
        """
        if not vbase > 0:
            raise SolverError(f"bus {label}: base voltage {vbase} is not positive")
        if btype not in BUS_TYPES:
            raise SolverError(f"bus {label}: type '{btype}' is not valid")
        self.labels.append(label)
        self.vbase.append(float(vbase))
        self.v0.append(complex(v0))
        self.types.append(btype)
        return len(self.labels) - 1

    def add_branch(self, fbus:Any, tbus:Any, Yff:Any, Yft:Any, Ytf:Any, Ytt:Any, magnitude:bool=False, # pylint: disable=invalid-name,too-many-arguments,too-many-positional-arguments
            self_impedance:Any=None, shift:float=0.0, paths:list[tuple[int,...]]|None=None) -> None:
        """Add a branch: buses of phases A, B, C at each end (-1 for a phase
        not connected) and the 3x3 admittance blocks (S) such that
        `I_from = Yff V_from + Yft V_to` and `I_to = Ytf V_from + Ytt V_to`
        (currents into the branch); `magnitude`: see `Network.magnitude`;
        `self_impedance`: see `Network.impedances`; `shift`: see
        `Network.shifts`; `paths`: see `Network.paths`"""
        blocks = [np.asarray(x, dtype=complex).reshape(3, 3) for x in (Yff, Yft, Ytf, Ytt)]
        self.branches.append((tuple(int(x) for x in fbus), tuple(int(x) for x in tbus), *blocks))
        self.magnitude.append(bool(magnitude))
        self.impedances.append(None if self_impedance is None else np.asarray(self_impedance, dtype=complex).reshape(3))
        self.shifts.append(float(shift))
        self.paths.append(None if paths is None else [tuple(int(x) for x in ((0, path[0], 1, path[1]) if len(path) == 2 else path)) for path in paths])

    def add_wye_load(self, bus:int, S:complex=0j, I:complex=0j, Y:complex=0j, vnom:complex|None=None) -> None: # pylint: disable=invalid-name,too-many-arguments,too-many-positional-arguments
        """Add a phase-to-ground load: constant power `S` (VA), current
        `I` (A, at the nominal voltage `vnom`, gridlabd's convention: the
        current follows the voltage angle and the power the voltage
        magnitude), admittance `Y` (S); positive values draw power"""
        if vnom is None:
            vnom = complex(self.vbase[bus])
        self.wye.append((bus, complex(S), complex(I), complex(Y), complex(vnom)))

    def add_split_load(self, bus_1:int, bus_2:int, S:complex=0j, I:complex=0j, Y:complex=0j, vnom:complex|None=None) -> None: # pylint: disable=invalid-name,too-many-arguments,too-many-positional-arguments
        """Add a load across the two lines of a split-phase node, whose
        buses hold the line-to-neutral voltages in gridlabd's convention
        (line 2 measured from the neutral to the line, so the load voltage
        is `V_1 + V_2`); both buses draw its current (see `add_wye_load()`;
        `vnom` is the nominal 240 V voltage)"""
        if vnom is None:
            vnom = complex(self.vbase[bus_1]*2)
        self.split.append((bus_1, bus_2, complex(S), complex(I), complex(Y), complex(vnom)))

    def add_delta_load(self, bus_a:int, bus_b:int, S:complex=0j, I:complex=0j, Y:complex=0j, vnom:complex|None=None) -> None: # pylint: disable=invalid-name,too-many-arguments,too-many-positional-arguments
        """Add a phase-to-phase load from bus `a` to bus `b` (see
        `add_wye_load()`; `vnom` is the nominal phase-to-phase voltage)"""
        if vnom is None:
            vnom = complex(self.vbase[bus_a]*math.sqrt(3))
        self.delta.append((bus_a, bus_b, complex(S), complex(I), complex(Y), complex(vnom)))

    def add_fixed_load(self, bus_a:int, current:complex, bus_b:int=-1) -> None:
        """Add a fixed-current load: the current (A) drawn at bus `a`, or
        across the lines `a` and `b` of a split-phase node, whatever the
        voltage (see `Network.fixed`)"""
        self.fixed.append((bus_a, bus_b, complex(current)))

    #
    # Matrices
    #
    def rotated(self, index:int) -> bool:
        """`True` when a branch is purely resistive (its `Yft` is real and
        not 0), which the fast-decoupled methods solve as a reactance of the
        same magnitude (its blocks times `-j`)"""
        yft = self.branches[index][3]
        return bool(np.any(yft != 0) and not np.any(yft.imag))

    def blocks(self, index:int, rotate:bool=False) -> tuple[np.ndarray,np.ndarray,np.ndarray,np.ndarray]:
        """Admittance blocks of a branch; with `rotate`, a purely resistive
        branch's blocks times `-j` (see `Network.rotated()`)"""
        blocks = self.branches[index][2:]
        if rotate and self.rotated(index):
            return tuple(-1j*x for x in blocks)
        return blocks

    def ybus(self, loads:bool=True, rotate:bool=False) -> sp.csr_matrix: # pylint: disable=too-many-locals
        """Bus admittance matrix (S), with the constant-impedance loads
        when `loads` is true, and the purely resistive branches rotated
        when `rotate` is true (see `Network.rotated()`)"""
        n = len(self.labels)
        rows, cols, vals = [], [], []
        def stamp(i:int, j:int, y:complex) -> None:
            if i >= 0 and j >= 0 and y != 0:
                rows.append(i)
                cols.append(j)
                vals.append(y)
        for index, (fbus, tbus, *_) in enumerate(self.branches):
            yff, yft, ytf, ytt = self.blocks(index, rotate)
            for p in range(3):
                for q in range(3):
                    stamp(fbus[p], fbus[q], yff[p, q])
                    stamp(fbus[p], tbus[q], yft[p, q])
                    stamp(tbus[p], fbus[q], ytf[p, q])
                    stamp(tbus[p], tbus[q], ytt[p, q])
        if loads:
            for bus, _, _, y, _ in self.wye:
                stamp(bus, bus, y)
            for a, b, _, _, y, _ in self.delta:
                stamp(a, a, y)
                stamp(b, b, y)
                stamp(a, b, -y)
                stamp(b, a, -y)
            for a, b, _, _, y, _ in self.split:
                for i in (a, b):
                    for j in (a, b):
                        stamp(i, j, y)
        return sp.csr_matrix((vals, (rows, cols)), shape=(n, n), dtype=complex)

    def load_power(self, V:np.ndarray, real_only:bool=False) -> np.ndarray: # pylint: disable=invalid-name,too-many-locals
        """Power drawn at each bus (VA) by the constant-power,
        constant-current, and fixed-current loads at voltages `V` (V); with `real_only`, the
        constant-impedance loads are included too (for the DC method)"""
        S = np.zeros(len(self.labels), dtype=complex) # pylint: disable=invalid-name
        for bus, s, i, y, vnom in self.wye:
            v = V[bus]
            drawn = s + abs(v)*i.conjugate()*vnom/abs(vnom) if vnom != 0 else s
            if real_only:
                drawn += abs(v)**2 * y.conjugate()
            S[bus] += drawn
        for a, b, s, i, y, vnom in self.delta:
            vab = V[a] - V[b]
            if vab == 0:
                continue
            current = (s/vab).conjugate()
            if vnom != 0:
                current += (vnom*i.conjugate()*abs(vab)/(vab*abs(vnom))).conjugate()
            if real_only:
                current += y*vab
            S[a] += V[a]*current.conjugate()
            S[b] -= V[b]*current.conjugate()
        for a, b, s, i, y, vnom in self.split:
            v12 = V[a] + V[b]
            if v12 == 0:
                continue
            current = (s/v12).conjugate()
            if vnom != 0:
                current += (vnom*i.conjugate()*abs(v12)/(v12*abs(vnom))).conjugate()
            if real_only:
                current += y*v12
            S[a] += V[a]*current.conjugate()
            S[b] += V[b]*current.conjugate()
        for a, b, current in self.fixed:
            S[a] += V[a]*current.conjugate()
            if b >= 0:
                S[b] += V[b]*current.conjugate()
        return S

    def load_currents(self, V:np.ndarray) -> np.ndarray: # pylint: disable=invalid-name
        """Current (A) each bus draws at voltages `V` (V) for its loads and
        the branches it feeds: its loads plus the currents into the
        branches at their from ends (gridlabd's `current_inj` after the NR
        current update, where each link adds its `current_in` to its from
        node); at a bus no branch feeds, the current it supplies
        (`Network.injections()`)"""
        result = self.injections(V)
        for fbus_tbus, (_, current_out) in zip(self.branches, branch_currents(self, V)):
            for slot, bus in enumerate(fbus_tbus[1]):
                if bus >= 0:
                    result[bus] += current_out[slot]
        return result

    def injections(self, V:np.ndarray) -> np.ndarray: # pylint: disable=invalid-name
        """Current (A) each bus supplies at voltages `V` (V): into its
        branches and its constant-impedance loads (`Ybus V`) and its other
        loads (gridlabd's `current_inj` after `NR_current_update()`)"""
        current = np.asarray(self.ybus() @ V, dtype=complex).ravel()
        load = self.load_power(V)
        with np.errstate(divide="ignore", invalid="ignore"):
            return current + np.where(V != 0, np.conj(load/np.where(V != 0, V, 1)), 0)

    def islands(self) -> list[np.ndarray]:
        """Bus indexes of each island: buses joined by conduction paths,
        which are the same-phase terms of the branches (`Yft[p, p]` not 0);
        the mutual coupling between phases and phase-to-phase loads do not
        join islands, since they cannot supply a phase that has no
        conductor to a source"""
        n = len(self.labels)
        if n == 0:
            return []
        rows, cols = [], []
        for index in range(len(self.branches)):
            for path in self.conducting(index):
                rows.append(self.path_bus(index, path[0], path[1]))
                cols.append(self.path_bus(index, path[2], path[3]))
        graph = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))
        count, labels = connected_components(graph, directed=False)
        return [np.flatnonzero(labels == k) for k in range(count)]

    def series(self) -> list[tuple[int,int,complex,bool]]:
        """Series admittance of each branch phase to the same phase at the
        other end, as `(from bus, to bus, y, magnitude)` in S, taken from
        `-Yft` (the diagonal of the inverse of the series impedance, so the
        mutual coupling is in it; the fast-decoupled matrices use these)"""
        result = []
        for index in range(len(self.branches)):
            z = self.self_impedance(index)
            for path in self.conducting(index):
                ea, sa, eb, sb = path
                same = (ea, eb) == (0, 1) and sa == sb
                y = 1/z[sa] if z is not None and same and z[sa] != 0 else -self.block(index, ea, eb)[sa, sb]
                if self.rotated(index):
                    y = -1j*y
                result.append((self.path_bus(index, ea, sa), self.path_bus(index, eb, sb), y, self.magnitude[index]))
        return result

    def block(self, index:int, end_a:int, end_b:int) -> np.ndarray:
        """Admittance block of a branch between two ends (0 from, 1 to)"""
        return self.branches[index][2 + 2*end_a + end_b]

    def path_bus(self, index:int, end:int, slot:int) -> int:
        """Bus of a branch end's slot"""
        return self.branches[index][end][slot]

    def path_list(self, index:int) -> list[tuple[int,int,int,int]]:
        """`Network.paths` of a branch, or the same-slot paths"""
        paths = self.paths[index] if index < len(self.paths) else None
        return [(0, p, 1, p) for p in range(3)] if paths is None else paths

    def conducting(self, index:int) -> list[tuple[int,int,int,int]]:
        """The paths of a branch that connect two buses and conduct (their
        block term not 0)"""
        return [path for path in self.path_list(index) if self.path_bus(index, path[0], path[1]) >= 0
            and self.path_bus(index, path[2], path[3]) >= 0 and self.block(index, path[0], path[2])[path[1], path[3]] != 0]

    def self_impedance(self, index:int) -> np.ndarray|None:
        """`Network.impedances` of a branch (`None` when not set)"""
        return self.impedances[index] if index < len(self.impedances) else None

    def shift(self, index:int) -> float:
        """`Network.shifts` of a branch (0 when not set)"""
        return self.shifts[index] if index < len(self.shifts) else 0.0

    def self_impedances(self, index:int) -> dict[tuple[int,int,int,int],complex]:
        """Self series impedance of each path of a branch (ohms): for the
        same-slot paths, `Network.impedances` when set, else the diagonal of
        `inv(-Yft)`; for explicit paths, the inverse of the negative block
        term"""
        fbus, tbus, _, yft, _, _ = self.branches[index]
        if index < len(self.paths) and self.paths[index] is not None:
            return {path: complex(1/-self.block(index, path[0], path[2])[path[1], path[3]]) for path in self.conducting(index)}
        z = self.self_impedance(index)
        if z is None:
            return {(0, p, 1, p): v for p, v in _self_impedances(fbus, tbus, yft).items()}
        return {(0, p, 1, p): complex(z[p]) for p in range(3) if fbus[p] >= 0 and tbus[p] >= 0 and z[p] != 0}

    def is_magnitude(self, index:int) -> bool:
        """`Network.magnitude` of a branch (`False` when not set)"""
        return index < len(self.magnitude) and self.magnitude[index]

def _self_impedances(fbus:tuple[int,...], tbus:tuple[int,...], yft:np.ndarray) -> dict[int,complex]:
    """Diagonal terms of a branch's series impedance `inv(-Yft)` on the
    phases it connects, by phase (none when `Yft` is singular there)"""
    mask = [p for p in range(3) if fbus[p] >= 0 and tbus[p] >= 0]
    if not mask:
        return {}
    try:
        z = np.linalg.inv(-yft[np.ix_(mask, mask)])
    except np.linalg.LinAlgError:
        return {}
    return {p: complex(z[k, k]) for k, p in enumerate(mask) if z[k, k] != 0}

def _types(net:Network) -> tuple[np.ndarray,np.ndarray,np.ndarray]:
    types = np.array(net.types)
    ref = np.flatnonzero(types == "REF")
    pv = np.flatnonzero(types == "PV")
    pq = np.flatnonzero(types == "PQ")
    return ref, pv, pq

def _check(net:Network) -> None:
    types = np.array(net.types)
    orphans = [k for island in net.islands() if not np.any(types[island] == "REF") for k in island]
    if orphans:
        names = ", ".join(net.labels[k] for k in sorted(orphans)[:6]) + (", ..." if len(orphans) > 6 else "")
        raise SolverError(f"no swing bus found for {names}")

def _laplacian(n:int, items:list[tuple[int,int,float]], diag:np.ndarray|None=None) -> sp.csr_matrix:
    rows, cols, vals = [], [], []
    for i, j, b in items:
        rows += [i, j, i, j]
        cols += [i, j, j, i]
        vals += [b, b, -b, -b]
    matrix = sp.csr_matrix((vals, (rows, cols)), shape=(n, n), dtype=float)
    if diag is not None:
        matrix = matrix + sp.diags(diag)
    return matrix.tocsr()

def _pu(net:Network, rotate:bool=False) -> tuple[np.ndarray,sp.csr_matrix]:
    vb = np.array(net.vbase)
    scale = sp.diags(vb)
    return vb, (scale @ net.ybus(rotate=rotate) @ scale / net.sbase).tocsr()

def _xb(y:complex) -> complex:
    """Admittance of the reactance of an admittance (the XB convention:
    resistance left out)"""
    z = 1/y
    return 1/complex(0, z.imag) if z.imag != 0 else y

def _b(y:complex) -> float:
    """Susceptance term of B' and B'': `-Im y`, or `|y|` for a purely
    resistive branch (a plain link, a regulator), which would otherwise
    leave the matrix singular"""
    return -y.imag if y.imag != 0 else abs(y)

def _fd_matrices(net:Network, vb:np.ndarray, Ypu:sp.csr_matrix, method:str) -> tuple[sp.csr_matrix,sp.csr_matrix]: # pylint: disable=invalid-name
    """B' and B'' of the fast-decoupled method, phase by phase (no mutual
    coupling); B'' keeps each bus's total shunt admittance"""
    n = len(net.labels)
    full, reactance = [], []
    for i, j, y, _ in net.series():
        ypu = y*vb[i]*vb[j]/net.sbase
        full.append((i, j, _b(ypu)))
        reactance.append((i, j, _b(_xb(ypu))))
    shunt = -np.asarray(Ypu.sum(axis=1)).ravel().imag
    if method == "FD_XB":
        return _laplacian(n, reactance), _laplacian(n, full, shunt)
    return _laplacian(n, full), _laplacian(n, reactance, shunt)

def solve(net:Network, method:str="NR", tol:float=1e-8, max_it:int=500, max_outer:int=100) -> Result: # pylint: disable=too-many-locals,too-many-branches,too-many-return-statements
    """Solve a network

    Arguments
    ---------
    - `net`: the network
    - `method`: `NR`, `FD_XB`, `FD_BX`, or `DC`
    - `tol`: PYPOWER's mismatch tolerance (`PF_TOL`, per unit), also the
      tolerance on the change of the voltage-dependent injections between
      calls
    - `max_it`: PYPOWER's iteration limit per call (`PF_MAX_IT`,
      `PF_MAX_IT_FD`)
    - `max_outer`: calls at most, to settle the voltage-dependent loads

    Returns
    -------
    - `Result`: voltages and convergence

    Exceptions
    ----------
    - `SolverError`: the method is not valid or an island has no `REF` bus
    """
    if method not in METHODS:
        raise SolverError(f"solver method '{method}' is not valid")
    n = len(net.labels)
    if n == 0:
        return Result(np.zeros(0, dtype=complex), True)
    _check(net)
    ref, pv, pq = _types(net)
    vb, Ypu = _pu(net, method in ("FD_XB", "FD_BX")) # pylint: disable=invalid-name
    V0 = np.array(net.v0, dtype=complex) / vb # pylint: disable=invalid-name
    if method == "DC":
        return _solve_dc(net, vb, V0, ref, pv, pq)
    if len(pv) + len(pq) == 0:
        return Result(V0*vb, True)
    ppopt = ppoption(PF_TOL=tol, PF_MAX_IT=max_it, PF_MAX_IT_FD=max_it, VERBOSE=0, OUT_ALL=0)
    if method != "NR" and len(pq) > 0:
        Bp, Bpp = _fd_matrices(net, vb, Ypu, method) # pylint: disable=invalid-name
    V = V0.copy() # pylint: disable=invalid-name
    load = net.load_power(V*vb) / net.sbase
    total = 0
    for call in range(1, max_outer+1):
        Sbus = -load # pylint: disable=invalid-name
        try:
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                warnings.simplefilter("ignore")
                if method == "NR" or len(pq) == 0:
                    V, success, its = newtonpf(Ypu, Sbus, V, ref, pv, pq, ppopt) # pylint: disable=invalid-name
                else:
                    V, success, its = fdpf(Ypu, Sbus, V, Bp, Bpp, ref, pv, pq, ppopt) # pylint: disable=invalid-name
        except RuntimeError as err: # scipy: singular factor
            return Result(V*vb, False, total, call, f"{method} solver failed: {err}", True)
        V = np.array(V, dtype=complex).ravel() # pylint: disable=invalid-name
        total += int(its)
        if not np.all(np.isfinite(V)):
            return Result(V*vb, False, total, call, f"{method} solver diverged", True)
        if not success:
            return Result(V*vb, False, total, call, f"{method} solver did not converge in {its} iterations")
        new = net.load_power(V*vb) / net.sbase
        if np.max(np.abs(new - load), initial=0.0) < tol:
            return Result(V*vb, True, total, call)
        load = new
    return Result(V*vb, False, total, max_outer, f"voltage-dependent loads did not settle in {max_outer} solver calls")

def _solve_dc(net:Network, vb:np.ndarray, V0:np.ndarray, ref:np.ndarray, pv:np.ndarray, pq:np.ndarray) -> Result: # pylint: disable=invalid-name,too-many-arguments,too-many-positional-arguments,too-many-locals
    n = len(net.labels)
    branches = [(i, j, xpu, shift) for i, j, xpu, shift in _dc_branches(net, vb) if xpu != 0]
    B = _laplacian(n, [(i, j, 1/xpu) for i, j, xpu, _ in branches]).tocsr() # pylint: disable=invalid-name
    Pbus = -(net.load_power(V0*vb, real_only=True) / net.sbase).real # pylint: disable=invalid-name
    for i, j, xpu, shift in branches: # flow (Va_i - Va_j - shift)/x: B Va = P + shift/x at i, - at j
        Pbus[i] += shift/xpu
        Pbus[j] -= shift/xpu
    Va0 = np.angle(V0) # pylint: disable=invalid-name
    if len(pv) + len(pq) == 0:
        return Result(V0*vb, True)
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        Va = np.asarray(dcpf(B, Pbus, Va0, ref, pv, pq)).ravel() # pylint: disable=invalid-name
    if not np.all(np.isfinite(Va)):
        return Result(V0*vb, False, 0, 1, "DC solver failed (singular matrix)", True)
    return Result(np.abs(V0)*np.exp(1j*Va)*vb, True, 1, 1)

def dc_reactances(net:Network, vb:np.ndarray|None=None) -> list[tuple[int,int,float]]:
    """Per-unit self series reactance of each branch phase, as `(from bus,
    to bus, x)`, used by the DC method: the phase's diagonal term of the
    series impedance `inv(-Yft)` (the magnitude of that impedance when its
    reactance is 0)"""
    if vb is None:
        vb = np.array(net.vbase)
    return [(i, j, x) for i, j, x, _ in _dc_branches(net, vb)]

def _dc_branches(net:Network, vb:np.ndarray) -> list[tuple[int,int,float,float]]:
    """`dc_reactances()` with each branch phase's shift (radians)"""
    result = []
    for index in range(len(net.branches)):
        for (ea, sa, eb, sb), z in net.self_impedances(index).items():
            x = _dc_x(z, net.is_magnitude(index))
            i, j = net.path_bus(index, ea, sa), net.path_bus(index, eb, sb)
            result.append((i, j, x*net.sbase/(vb[i]*vb[j]), net.shift(index) if ea != eb else 0.0))
    return result

def _dc_x(z:complex, magnitude:bool) -> float:
    """Reactance the DC method uses for a self impedance: its imaginary
    part, or its magnitude for `magnitude` branches or when it has none"""
    return abs(z) if magnitude or z.imag == 0 else z.imag

def branch_currents(net:Network, V:np.ndarray, rotate:bool=False) -> list[tuple[np.ndarray,np.ndarray]]: # pylint: disable=invalid-name
    """Currents of each branch (A) at voltages `V` (V): `(I_in, I_out)`,
    the currents into the branch at its from end and out of it at its to
    end, by phase (0 for a phase not connected); `rotate` for a solution
    of the fast-decoupled methods (see `Network.rotated()`)"""
    result = []
    for index, (fbus, tbus, *_) in enumerate(net.branches):
        yff, yft, ytf, ytt = net.blocks(index, rotate)
        vf = np.array([V[k] if k >= 0 else 0j for k in fbus])
        vt = np.array([V[k] if k >= 0 else 0j for k in tbus])
        result.append((yff @ vf + yft @ vt, -(ytf @ vf + ytt @ vt)))
    return result

def dc_branch_power(net:Network, V:np.ndarray) -> list[np.ndarray]: # pylint: disable=invalid-name
    """Real power of each branch phase (W) in the DC solution at voltages
    `V` (V), from its from end to its to end, by from slot (0 for a phase
    not connected)"""
    result = []
    for index in range(len(net.branches)):
        flows = np.zeros(3)
        for (ea, sa, eb, sb), power in dc_path_power(net, V, index).items():
            if ea == 0:
                flows[sa] += power
            if eb == 0:
                flows[sb] -= power
        result.append(flows)
    return result

def dc_path_power(net:Network, V:np.ndarray, index:int) -> dict[tuple[int,int,int,int],float]: # pylint: disable=invalid-name
    """Real power (W) of each path of a branch in the DC solution, from end
    a to end b (see `Network.paths`)"""
    vb = np.array(net.vbase)
    result = {}
    for path, z in net.self_impedances(index).items():
        ea, sa, eb, sb = path
        i, j = net.path_bus(index, ea, sa), net.path_bus(index, eb, sb)
        x = _dc_x(z, net.is_magnitude(index))
        xpu = x*net.sbase/(vb[i]*vb[j])
        result[path] = (np.angle(V[i]) - np.angle(V[j]) - (net.shift(index) if ea != eb else 0.0))/xpu*net.sbase
    return result
