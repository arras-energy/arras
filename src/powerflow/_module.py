# pylint: disable=line-too-long
"""@private Module solvers: the network of the model's nodes and links,
solved by `powerflow.solver` (replacing gridlabd's `solver_nr()`)"""

from typing import Any

import numpy as np

from pypower._common import notation

from ._common import (MODULE, TS_NEVER, TS_INVALID, PHASE_D, PHASE_S, PHASE_BITS, PQ, PV, SWING,
    SWING_PQ, SM_FBS, SM_GS, SM_NR, SM_FD_XB, SM_FD_BX, SM_DC, CEH_IGNORE, CEH_COLLAPSE, BEHAVIORS,
    runner, gl_error, gl_warning, gl_verbose, g, objects_of, ref, get_int, get_double, get_complex,
    set_complex)
from .solver import Network, SolverError, solve, nominal, branch_currents, dc_branch_power
from .node import set_line_voltages, top_node

METHOD_NAMES = {SM_NR: "NR", SM_FD_XB: "FD_XB", SM_FD_BX: "FD_BX", SM_DC: "DC"}
"""PYPOWER solver of each `powerflow::solver_method` value (`FBS` is solved
with NR)"""

PF_TOL = 1e-8
"""PYPOWER mismatch tolerance (per unit of 1 MVA)"""

PAIRS = ((0, 1), (1, 2), (2, 0))
"""Phase pairs of the phase-to-phase loads AB, BC, CA"""

class ModuleState: # pylint: disable=too-few-public-methods
    """State of the module for one model"""

    def __init__(self, model:Any):
        self.model = model
        self.objects: dict[str,Any] = {}
        """Object states keyed on name"""
        self.reset()

    def reset(self) -> None:
        """Clear the run state (kept: object states)"""
        self.admittances: dict[str,tuple[tuple,Any]] = {} # link admittance blocks by link name, with their key
        self.solutions = 0 # solver calls in the run
        self.last: Any = None # last solver result

def behavior(model:Any, name:str) -> Any:
    """Behavior class of an object: that of its class, or of the nearest
    class it inherits from that has one"""
    oclass = model.objects[name].oclass
    while oclass is not None:
        if oclass.name in BEHAVIORS and oclass.module == MODULE:
            return BEHAVIORS[oclass.name]
        oclass = getattr(oclass, "parent", None)
    raise SolverError(f"object '{name}' is not a powerflow object")

def _model() -> Any:
    return runner().model

def _state() -> ModuleState:
    from ._common import module_state # pylint: disable=import-outside-toplevel
    return module_state(_model())

def method_name(model:Any) -> str:
    """PYPOWER method for the model's `powerflow::solver_method`"""
    method = g(model, "solver_method")
    if method in (SM_FBS, None):
        return "NR"
    return METHOD_NAMES.get(method, "NR")

def solver_init() -> bool:
    """Module `init` solver: deprecation of `FBS`"""
    model = _model()
    state = _state()
    state.reset()
    if not objects_of(model, "node"):
        return True
    method = g(model, "solver_method")
    if method == SM_FBS:
        gl_warning("powerflow::solver_method FBS is deprecated; the NR solver is used instead")
    elif method == SM_GS:
        gl_error("Gauss_Seidel is a deprecated solver and has been removed")
        return False
    return True

def build(model:Any, state:ModuleState) -> tuple[Network,dict[tuple[str,int],int],list[str]]:
    """Network of the model: buses of the top nodes' phases, branches of
    the closed links, loads of the nodes and their children"""
    # pylint: disable=too-many-locals,too-many-branches
    net = Network()
    buses: dict[tuple[str,int],int] = {}
    nodes = objects_of(model, "node")
    for name in nodes:
        if top_node(model, name) != name:
            continue
        phases = get_int(model, name, "phases")
        if phases & PHASE_S == PHASE_S:
            raise SolverError(f"node {name}: split-phase nodes are not supported yet")
        vbase = get_double(model, name, "nominal_voltage")
        bustype = get_int(model, name, "bustype")
        btype = "REF" if bustype in (SWING, SWING_PQ) else ("PV" if bustype == PV else "PQ")
        for k, bit in enumerate(PHASE_BITS):
            if phases & bit:
                v0 = get_complex(model, name, f"voltage_{'ABC'[k]}")
                if v0 == 0:
                    v0 = nominal(vbase, k)
                buses[(name, k)] = net.add_bus(f"{name}.{'ABC'[k]}", vbase, v0, btype)
    for name in nodes:
        _add_loads(model, name, net, buses)
    links = []
    for name in objects_of(model, "link"):
        cls = behavior(model, name)
        if not cls.closed(model, name):
            continue
        fnode = top_node(model, ref(model, name, "from"))
        tnode = top_node(model, ref(model, name, "to"))
        key = cls.admittance_key(model, name)
        cached = state.admittances.get(name)
        if cached is None or cached[0] != key:
            cached = (key, cls.admittance(model, name))
            state.admittances[name] = cached
        mask = cls.phase_mask(model, name)
        fbus = [buses.get((fnode, k), -1) if mask[k] else -1 for k in range(3)]
        tbus = [buses.get((tnode, k), -1) if mask[k] else -1 for k in range(3)]
        net.add_branch(fbus, tbus, *cached[1])
        links.append(name)
    return net, buses, links

def _add_loads(model:Any, name:str, net:Network, buses:dict[tuple[str,int],int]) -> None:
    """Loads of a node, on the buses of its top node"""
    top = top_node(model, name)
    vbase = get_double(model, top, "nominal_voltage")
    delta = get_int(model, name, "phases") & PHASE_D == PHASE_D
    def wye(k:int, suffix:str) -> None:
        s, i, y = (get_complex(model, name, f"{kind}_{suffix}") for kind in ("power", "current", "shunt"))
        if (s, i, y) != (0, 0, 0) and (top, k) in buses:
            net.add_wye_load(buses[(top, k)], s, i, y, nominal(vbase, k))
    def phase_to_phase(k:int, suffix:str) -> None:
        a, b = PAIRS[k]
        s, i, y = (get_complex(model, name, f"{kind}_{suffix}") for kind in ("power", "current", "shunt"))
        if (s, i, y) != (0, 0, 0) and (top, a) in buses and (top, b) in buses:
            net.add_delta_load(buses[(top, a)], buses[(top, b)], s, i, y, nominal(vbase, a) - nominal(vbase, b))
    for k, x in enumerate("ABC"):
        if delta:
            phase_to_phase(k, x)
        else:
            wye(k, x)
        wye(k, f"{x}N")
        phase_to_phase(k, ("AB", "BC", "CA")[k])

def solver_sync(t0:int) -> int:
    """Module `sync` solver: build and solve the network, then write the
    node voltages and link flows; ask to iterate when a voltage changed by
    more than its node's `maximum_voltage_error`"""
    # pylint: disable=too-many-locals,too-many-return-statements
    model = _model()
    state = _state()
    nodes = objects_of(model, "node")
    if not nodes:
        return TS_NEVER
    method = method_name(model)
    try:
        net, buses, links = build(model, state)
        result = solve(net, method, tol=PF_TOL, max_it=max(1, int(g(model, "NR_iteration_limit") or 500)))
    except (SolverError, np.linalg.LinAlgError) as err:
        gl_error(f"powerflow: {err}")
        return TS_INVALID
    state.solutions += 1
    state.last = result
    gl_verbose(f"powerflow: {method} solution {state.solutions} at {t0}: {'converged' if result.success else 'failed'} in {result.iterations} iterations ({result.calls} calls)")
    if not result.success and result.diverged:
        # gridlabd node::sync(), bad_computation
        handling = g(model, "convergence_error_handling")
        if handling == CEH_IGNORE:
            gl_warning(f"Newton-Raphson method is unable to converge to a solution at this operation point ({result.message})")
            return TS_NEVER
        if handling == CEH_COLLAPSE:
            gl_error("convergence_error_handling==COLLAPSE is not yet supported")
        gl_error(f"Newton-Raphson method is unable to converge to a solution at this operation point ({result.message})")
        return TS_INVALID
    if not result.success:
        # gridlabd node::sync(), solver_nr() result < 0: keep the voltages reached and iterate
        gl_verbose(f"Newton-Raphson failed to converge, sticking at same iteration ({result.message}).")
        _write_voltages(model, nodes, buses, result.V)
        _write_flows(model, net, links, result.V, method == "DC")
        return t0
    changed = _write_voltages(model, nodes, buses, result.V)
    _write_flows(model, net, links, result.V, method == "DC")
    return t0 if changed else TS_NEVER

def _write_voltages(model:Any, nodes:list[str], buses:dict[tuple[str,int],int], V:np.ndarray) -> bool: # pylint: disable=invalid-name
    changed = False
    for name in nodes:
        top = top_node(model, name)
        maxerr = get_double(model, name, "maximum_voltage_error")
        for k, x in enumerate("ABC"):
            index = buses.get((top, k))
            if index is None:
                continue
            prop = f"voltage_{x}"
            old = get_complex(model, name, prop)
            if abs(V[index] - old) > maxerr:
                changed = True
            set_complex(model, name, prop, complex(V[index]), notation(model, name, prop))
        set_line_voltages(model, name)
    return changed

def _write_flows(model:Any, net:Network, links:list[str], V:np.ndarray, dc:bool) -> None: # pylint: disable=invalid-name,too-many-locals
    from .link import write_flows # pylint: disable=import-outside-toplevel
    if dc:
        powers = dc_branch_power(net, V)
    currents = branch_currents(net, V)
    for index, name in enumerate(links):
        fbus, tbus = net.branches[index][0], net.branches[index][1]
        vf = np.array([V[k] if k >= 0 else 0j for k in fbus])
        vt = np.array([V[k] if k >= 0 else 0j for k in tbus])
        if dc:
            s = powers[index].astype(complex)
            with np.errstate(divide="ignore", invalid="ignore"):
                i_in = np.where(vf != 0, np.conj(s/np.where(vf != 0, vf, 1)), 0)
                i_out = np.where(vt != 0, np.conj(s/np.where(vt != 0, vt, 1)), 0)
            write_flows(model, name, s, s, i_in, i_out)
        else:
            i_in, i_out = currents[index]
            behavior(model, name).set_flows(model, name, vf, vt, i_in, i_out)
    zero = np.zeros(3, dtype=complex)
    for name in objects_of(model, "link"):
        if name not in links:
            write_flows(model, name, zero, zero, zero, zero)

__all__ = ["ModuleState", "solver_init", "solver_sync", "build", "behavior", "method_name", "SM_NR", "PQ"]
