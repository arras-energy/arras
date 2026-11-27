# pylint: disable=line-too-long
"""@private Module solvers: the network of the model's nodes and links,
solved by `powerflow.solver` (replacing gridlabd's `solver_nr()`)"""

from typing import Any

import numpy as np

from ._common import (MODULE, TS_NEVER, TS_INVALID, PHASE_D, PHASE_BITS, PQ, PV, SWING,
    SWING_PQ, SM_FBS, SM_GS, SM_NR, SM_FD_XB, SM_FD_BX, SM_DC, CEH_IGNORE, CEH_COLLAPSE, BEHAVIORS,
    runner, gl_error, gl_warning, gl_verbose, g, objects_of, ref, get_int, get_double, get_complex)
from .solver import Network, SolverError, solve, nominal, branch_currents, dc_path_power
from .node import top_node

METHOD_NAMES = {SM_NR: "NR", SM_FD_XB: "FD_XB", SM_FD_BX: "FD_BX", SM_DC: "DC"}
"""PYPOWER solver of each `powerflow::solver_method` value (`FBS` is solved
with NR)"""

PF_TOL = 1e-8
"""PYPOWER mismatch tolerance (per unit of 1 MVA)"""

PRE = "prerotated_current"
"""Load kind of the fixed (pre-rotated) currents: the node accumulators
`prerotated_current_X` and the `load_terms()` key"""

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
        self.network: Any = None # (network, buses, voltages) of the last converged solution

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

def isolated(model:Any) -> set[tuple[str,int]]:
    """Phases `(top node, phase index)` taken out of the network by
    switching devices (`Link.SWITCH`): the phases a device does not connect
    now, at its to node, when the to node has no other link (gridlabd
    `link::NR_init()`, strictly radial mode)"""
    counts: dict[str,int] = {}
    links = objects_of(model, "link")
    ends = {}
    for name in links:
        fnode = top_node(model, ref(model, name, "from"))
        tnode = top_node(model, ref(model, name, "to"))
        ends[name] = tnode
        for node in ((fnode,) if fnode == tnode else (fnode, tnode)):
            counts[node] = counts.get(node, 0) + 1
    result = set()
    for name in links:
        cls = behavior(model, name)
        if not cls.SWITCH or counts.get(ends[name], 0) != 1:
            continue
        removed = (get_int(model, name, "phases") & 0x07) & ~cls.connected_phases(model, name)
        result |= {(ends[name], k) for k, bit in enumerate(PHASE_BITS) if removed & bit}
    for name in links:
        result |= behavior(model, name).isolates(model, name)
    return result

def sourced(model:Any) -> set[str]:
    """Top nodes whose voltages a source link sets (`Link.SOURCE`): `REF`
    buses at the voltages the link writes"""
    return {top_node(model, ref(model, name, "to")) for name in objects_of(model, "link")
        if behavior(model, name).SOURCE and behavior(model, name).closed(model, name)}

def bus_currents(model:Any, name:str) -> list[complex]|None:
    """Currents (A) the top node of a node draws on each bus slot for its
    loads and the links it feeds in the last converged solution
    (`Network.load_currents()`, gridlabd's `current_inj`), or `None` before
    one"""
    network = _state().network
    if network is None:
        return None
    net, buses, V = network # pylint: disable=invalid-name
    current = net.load_currents(V)
    top = top_node(model, name)
    return [complex(current[buses[(top, k)]]) if (top, k) in buses else 0j for k in range(3)]

def build(model:Any, state:ModuleState, dead:set[tuple[str,int]]|None=None) -> tuple[Network,dict[tuple[str,int],int],list[str]]:
    """Network of the model: buses of the top nodes' phases (except the
    `dead` ones), branches of the closed links, loads of the nodes and
    their children"""
    # pylint: disable=too-many-locals,too-many-branches
    dead = dead or set()
    net = Network()
    buses: dict[tuple[str,int],int] = {}
    nodes = objects_of(model, "node")
    sources = sourced(model)
    for name in nodes:
        if top_node(model, name) != name:
            continue
        bustype = get_int(model, name, "bustype")
        btype = "REF" if bustype in (SWING, SWING_PQ) or name in sources else ("PV" if bustype == PV else "PQ")
        for slot, label, vbase, v0 in behavior(model, name).bus_slots(model, name):
            if (name, slot) not in dead:
                buses[(name, slot)] = net.add_bus(f"{name}.{label}", vbase, v0, btype)
    extra: dict[str,dict[tuple[str,str],complex]] = {}
    for name in objects_of(model, "link"):
        for node, kind, suffix, value in behavior(model, name).node_loads(model, name):
            terms = extra.setdefault(node, {})
            terms[(kind, suffix)] = terms.get((kind, suffix), 0j) + value
    for name in nodes:
        _add_loads(model, name, net, buses, extra.get(name))
    links = []
    for name in objects_of(model, "link"):
        cls = behavior(model, name)
        if not cls.closed(model, name) or cls.SOURCE:
            continue
        fnode = top_node(model, ref(model, name, "from"))
        tnode = top_node(model, ref(model, name, "to"))
        key = cls.admittance_key(model, name)
        cached = state.admittances.get(name)
        if cached is None or cached[0] != key:
            cached = (key, cls.admittance(model, name))
            state.admittances[name] = cached
        fslots, tslots = cls.bus_slots(model, name)
        fbus = [buses.get((fnode, k), -1) if k >= 0 else -1 for k in fslots]
        tbus = [buses.get((tnode, k), -1) if k >= 0 else -1 for k in tslots]
        impedance, shift = cls.dc_model(model, name)
        net.add_branch(fbus, tbus, *cached[1], magnitude=cls.MAGNITUDE, self_impedance=impedance, shift=shift, paths=cls.paths(model, name))
        links.append(name)
    return net, buses, links

def _add_loads(model:Any, name:str, net:Network, buses:dict[tuple[str,int],int], extra:dict[tuple[str,str],complex]|None=None) -> None: # pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
    """Loads of a node (and the `extra` terms links put on it,
    `Link.node_loads()`), on the buses of its top node"""
    top = top_node(model, name)
    vbase = get_double(model, top, "nominal_voltage")
    delta = get_int(model, name, "phases") & PHASE_D == PHASE_D
    cls = behavior(model, name)
    terms = dict(cls.load_terms(model, name))
    for key, term in (extra or {}).items():
        terms[key] = terms.get(key, 0j) + term
    def value(kind:str, suffix:str) -> complex:
        prop_ = f"{kind}_{suffix}"
        stored = get_complex(model, name, prop_) if model.objects[name].oclass.find_property(prop_) else 0j
        return stored + terms.get((kind, suffix), 0j)
    if cls.split(model, name):
        angle = (0.0, -2*np.pi/3, 2*np.pi/3)[behavior(model, top).base_phase(model, top)]
        vnom = complex(np.cos(angle), np.sin(angle))*vbase
        one, two, both = cls.SUFFIXES
        for slot, suffix in ((0, one), (1, two)):
            s, i, y = (value(kind, suffix) for kind in ("power", "current", "shunt"))
            if (s, i, y) != (0, 0, 0) and (top, slot) in buses:
                net.add_wye_load(buses[(top, slot)], s, i, y, vnom)
        s, i, y = (value(kind, both) for kind in ("power", "current", "shunt"))
        if (s, i, y) != (0, 0, 0) and (top, 0) in buses and (top, 1) in buses:
            net.add_split_load(buses[(top, 0)], buses[(top, 1)], s, i, y, 2*vnom)
        for slot, suffix in ((0, one), (1, two)):
            fixed = value(PRE, suffix)
            if fixed != 0 and (top, slot) in buses:
                net.add_fixed_load(buses[(top, slot)], fixed)
        fixed = value(PRE, both)
        if fixed != 0 and (top, 0) in buses and (top, 1) in buses:
            net.add_fixed_load(buses[(top, 0)], fixed, buses[(top, 1)])
        return
    def wye(k:int, suffix:str) -> None:
        s, i, y = (value(kind, suffix) for kind in ("power", "current", "shunt"))
        if (s, i, y) != (0, 0, 0) and (top, k) in buses:
            net.add_wye_load(buses[(top, k)], s, i, y, nominal(vbase, k))
    def phase_to_phase(k:int, suffix:str) -> None:
        a, b = PAIRS[k]
        s, i, y = (value(kind, suffix) for kind in ("power", "current", "shunt"))
        if (s, i, y) != (0, 0, 0) and (top, a) in buses and (top, b) in buses:
            net.add_delta_load(buses[(top, a)], buses[(top, b)], s, i, y, nominal(vbase, a) - nominal(vbase, b))
    for k, x in enumerate("ABC"):
        if delta:
            phase_to_phase(k, x)
        else:
            wye(k, x)
        wye(k, f"{x}N")
        phase_to_phase(k, ("AB", "BC", "CA")[k])
        fixed = value(PRE, x)
        if fixed != 0 and (top, k) in buses:
            net.add_fixed_load(buses[(top, k)], fixed)

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
    for name in nodes + objects_of(model, "link"):
        behavior(model, name).before_solve(model, name, t0)
    try:
        dead = isolated(model)
        net, buses, links = build(model, state, dead)
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
        _write_voltages(model, nodes, buses, result.V, dead)
        _write_flows(model, net, links, result.V, method)
        return t0
    changed = _write_voltages(model, nodes, buses, result.V, dead)
    _write_flows(model, net, links, result.V, method)
    state.network = (net, buses, result.V)
    for name in nodes + objects_of(model, "link"):
        if behavior(model, name).after_solve(model, name, t0):
            changed = True
    if changed:
        return t0
    events = [t for t in (behavior(model, name).next_event(model, name) for name in nodes + objects_of(model, "link")) if t is not None and t > t0]
    return -min(events) if events else TS_NEVER

def _write_voltages(model:Any, nodes:list[str], buses:dict[tuple[str,int],int], V:np.ndarray, dead:set[tuple[str,int]]) -> bool: # pylint: disable=invalid-name,too-many-arguments,too-many-positional-arguments
    changed = False
    for name in nodes:
        top = top_node(model, name)
        values = {}
        for slot in range(3):
            index = buses.get((top, slot))
            if index is None and (top, slot) not in dead:
                continue
            values[slot] = 0j if index is None else complex(V[index])
        if behavior(model, name).write_voltages(model, name, values):
            changed = True
    return changed

def _write_flows(model:Any, net:Network, links:list[str], V:np.ndarray, method:str) -> None: # pylint: disable=invalid-name,too-many-locals
    from .link import write_flows # pylint: disable=import-outside-toplevel
    dc = method == "DC"
    currents = branch_currents(net, V, method in ("FD_XB", "FD_BX"))
    for index, name in enumerate(links):
        fbus, tbus = net.branches[index][0], net.branches[index][1]
        vf = np.array([V[k] if k >= 0 else 0j for k in fbus])
        vt = np.array([V[k] if k >= 0 else 0j for k in tbus])
        if dc:
            s_in, s_out = np.zeros(3, dtype=complex), np.zeros(3, dtype=complex)
            for (ea, sa, eb, sb), power in dc_path_power(net, V, index).items():
                for end, slot, sign in ((ea, sa, 1), (eb, sb, -1)):
                    if end == 0:
                        s_in[slot] += sign*power
                    else:
                        s_out[slot] -= sign*power
            with np.errstate(divide="ignore", invalid="ignore"):
                i_in = np.where(vf != 0, np.conj(s_in/np.where(vf != 0, vf, 1)), 0)
                i_out = np.where(vt != 0, np.conj(s_out/np.where(vt != 0, vt, 1)), 0)
            write_flows(model, name, s_in, s_out, i_in, i_out, lossless=True)
        else:
            i_in, i_out = currents[index]
            behavior(model, name).set_flows(model, name, vf, vt, i_in, i_out)
    zero = np.zeros(3, dtype=complex)
    for name in objects_of(model, "link"):
        if name not in links:
            write_flows(model, name, zero, zero, zero, zero)

__all__ = ["ModuleState", "solver_init", "solver_sync", "build", "behavior", "method_name", "bus_currents", "sourced", "SM_NR", "PQ"]
