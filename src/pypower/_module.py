# pylint: disable=line-too-long
"""@private Module solvers: data exchange with the PYPOWER solver and the
controllers module (gridlabd `module/pypower/pypower.cpp`)"""

import os
import sys
import math
import cmath
import importlib
import importlib.machinery
import importlib.util
from typing import Any, Callable

from ._common import (MODULE, TS_NEVER, TS_INVALID, runner, gl_error, gl_warning, gl_verbose,
    gl_debug, python_error, global_value, set_global, objects_of, get_double, get_int, get_complex,
    get_text, set_double, set_complex, isa)

SS_INIT, SS_SUCCESS, SS_FAILED = range(3)
"""Solver status values (`pypower::solver_status`)"""

SAVE_FORMATS = ("csv", "json", "py")
"""Save format names by `pypower::save_format` value"""

MAXITER_NAMES = ("maximum_iterations_nr", "maximum_iterations_fd", "maximum_iterations_fd", "maximum_iterations_gs")
"""Solver option set by `pypower::maximum_iterations` for each solver method"""

BUS_FIELDS = (("bus_i", int, True), ("type", int, True), ("Pd", float, True), ("Qd", float, True),
    ("Gs", float, True), ("Bs", float, True), ("area", int, False), ("Vm", float, False),
    ("Va", float, False), ("baseKV", float, False), ("zone", int, False), ("Vmax", float, False),
    ("Vmin", float, False))
"""Bus columns 0 to 12: property, type (`int` is a `Long`), counted as a
change by `update_solution()`"""

BUS_OPF_FIELDS = (("lam_P", float), ("lam_Q", float), ("mu_Vmax", float), ("mu_Vmin", float))
"""Bus columns 13 to 16 (OPF)"""

BRANCH_FIELDS = (("fbus", int, True), ("tbus", int, True), ("r", float, True), ("x", float, True),
    ("b", float, True), ("rateA", float, None), ("rateB", float, None), ("rateC", float, None),
    ("ratio", float, True), ("angle", float, True), ("status", int, True), ("angmin", float, True),
    ("angmax", float, True))
"""Branch columns 0 to 12 (`None`: a change only when the OPF runs)"""

GEN_FIELDS = (("bus", int, True), ("Pg", float, True), ("Qg", float, True), ("Qmax", float, True),
    ("Qmin", float, True), ("Vg", float, True), ("mBase", float, True), ("status", int, True),
    ("Pmax", float, True), ("Pmin", float, True), ("Pc1", float, True), ("Pc2", float, True),
    ("Qc1min", float, True), ("Qc1max", float, True), ("Qc2min", float, True), ("Qc2max", float, True),
    ("ramp_agc", float, False), ("ramp_10", float, False), ("ramp_30", float, False),
    ("ramp_q", float, False), ("apf", float, False))
"""Gen columns 0 to 20"""

GEN_OPF_FIELDS = (("mu_Pmax", float), ("mu_Pmin", float), ("mu_Qmax", float), ("mu_Qmin", float))
"""Gen columns 21 to 24 (OPF)"""

DCLINE_OPF_FIELDS = ("mu_Pmin", "mu_Pmax", "mu_Qminf", "mu_Qmaxf", "mu_Qmint", "mu_Qmaxt")
"""Dcline columns 17 to 22 (OPF)"""

def g(model:Any, name:str) -> Any:
    """Value of global `pypower::NAME`"""
    return global_value(model, f"{MODULE}::{name}")

def cdiv(a:complex, b:complex) -> complex:
    """Complex division as gridlabd's `complex` class divides (`nan` for a
    zero divisor)"""
    if b == 0:
        return complex(math.nan, math.nan)
    return a / b

class ModuleState: # pylint: disable=too-many-instance-attributes
    """State of the module for one model (gridlabd's module globals)"""

    def __init__(self, model:Any):
        self.model = model
        self.objects: dict[str,Any] = {}
        """Object states keyed on name"""
        self.initialized = False
        """Module initialization (`on_init()`) done"""
        self.init_ok = True
        """Result of the module initialization"""
        self.last_i = 0
        """Last automatic bus number"""
        self.buses: list[str] = []
        self.branches: list[str] = []
        self.gens: list[str] = []
        self.gencosts: list[str] = []
        self.dclines: list[str] = []
        self.data: dict[str,Any] = {}
        self.busdata: list[list] = []
        self.branchdata: list[list] = []
        self.gendata: list[list] = []
        self.gencostdata: list[list]|None = None
        self.dclinedata: list[list]|None = None
        self.result: Any = None
        """Last solver result (`None` before the first solution)"""
        self.solved = False
        """The solver was called (gridlabd's `static PyObject *result` is set)"""
        self.controllers: Any = None
        self.py_globals: dict[str,Any]|None = None
        self.py_precommit: Callable|None = None
        self.py_sync: Callable|None = None
        self.py_commit: Callable|None = None
        self.py_term: Callable|None = None

    def collect(self) -> None:
        """Lists of the solver objects in creation order (gridlabd adds each
        object to its list in `create()`)"""
        model = self.model
        self.buses = objects_of(model, "bus")
        self.branches = objects_of(model, "branch")
        self.gens = objects_of(model, "gen")
        self.gencosts = objects_of(model, "gencost")
        self.dclines = objects_of(model, "dcline")

    def opf_needed(self, t:int) -> bool:
        """`opf_needed()`"""
        interval = float(g(self.model, "opf_update_interval") or 0.0)
        return bool(g(self.model, "enable_opf")) and (interval == 0 or math.fmod(t, interval) == 0)

#
# Initialization
#
def ensure_init(model:Any) -> bool:
    """Initialize the module once per model, before its first object is
    initialized, as gridlabd's `init_all()` calls `module_initall()` before
    initializing objects; returns the result"""
    from ._common import module_state # pylint: disable=import-outside-toplevel
    state = module_state(model)
    if not state.initialized:
        state.initialized = True
        state.collect()
        state.init_ok = on_init(state)
    return state.init_ok

def _modelname(model:Any) -> str|None:
    """Model name without its extension (`modelname` global, else the
    model file the run read)"""
    name = str(model.globals.get("modelname") or "")
    if not name:
        args = [x for x in runner().args if os.path.splitext(x)[1] in (".glm", ".json")]
        name = args[0] if args else ""
    if not name:
        return None
    root, ext = os.path.splitext(name)
    return root if ext else name

def _import_controllers(name:str, path:str) -> Any:
    """Import the controllers module (a fresh module object for each
    run), with `path` added to `sys.path` as gridlabd does"""
    if path and path not in sys.path:
        sys.path.append(path)
    sys.modules.pop(name, None)
    importlib.invalidate_caches()
    spec = importlib.machinery.PathFinder.find_spec(name, sys.path + [os.getcwd()])
    if spec is None or spec.loader is None:
        return importlib.import_module(name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def on_init(state:ModuleState) -> bool:
    """gridlabd `on_init()`"""
    # pylint: disable=too-many-return-statements,too-many-branches,too-many-statements
    model = state.model
    enable_opf = bool(g(model, "enable_opf"))
    if enable_opf and len(state.gens) != len(state.gencosts):
        gl_warning(f"pypower OPF solver requires the number of gencost records ({len(state.gencosts)}) to match the number of gen records ({len(state.gens)})")

    controllers = str(g(model, "controllers") or "").strip('"')
    if controllers:
        try:
            state.controllers = _import_controllers(controllers, str(g(model, "controllers_path") or "").strip('"'))
        except Exception as err: # pylint: disable=broad-exception-caught
            python_error(err)
            return False
        state.py_globals = vars(state.controllers)
        on_init_ = state.py_globals.get("on_init")
        if on_init_ is not None:
            if not callable(on_init_):
                gl_error(f"{controllers}.on_init is not callable")
                return False
            try:
                result = on_init_()
            except Exception as err: # pylint: disable=broad-exception-caught
                python_error(err)
                return False
            if result is None:
                gl_error(f"{controllers}.on_init() returned non-boolean value (expected True or False)")
                return False
            if isinstance(result, bool):
                if not result:
                    gl_error(f"{controllers}.on_init() failed (returned False)")
                    return False
            else:
                gl_error(f"{controllers}.on_init() returned non-boolean value (expected True or False)")
                return False
        for hook in ("precommit", "sync", "commit", "term"):
            call = state.py_globals.get(f"on_{hook}")
            if call is not None and not callable(call):
                gl_error(f"{controllers}.on_{hook} is not callable")
                return False
            setattr(state, f"py_{hook}", call)

    # first time setup of arrays
    data = state.data
    data["version"] = int(g(model, "version"))
    data["baseMVA"] = float(g(model, "baseMVA"))
    state.busdata = [[0.0]*(17 if enable_opf else 13) for _ in state.buses]
    data["bus"] = state.busdata
    state.branchdata = [[0.0]*13 for _ in state.branches]
    data["branch"] = state.branchdata
    state.gendata = [[0.0]*(25 if enable_opf else 21) for _ in state.gens]
    data["gen"] = state.gendata
    if enable_opf:
        state.gencostdata = [[0.0]*4 for _ in state.gencosts]
        data["gencost"] = state.gencostdata
    if state.dclines:
        state.dclinedata = [[0.0]*23 for _ in state.dclines]
        data["dcline"] = state.dclinedata

    # options
    data["verbose"] = bool(model.globals.getvalue("verbose"))
    data["debug"] = bool(model.globals.getvalue("debug"))
    solver_method = int(g(model, "solver_method"))
    data["solver_method"] = solver_method
    maximum_iterations = int(g(model, "maximum_iterations") or 0)
    if maximum_iterations > 0 and 0 < solver_method <= 4:
        data[MAXITER_NAMES[solver_method-1]] = maximum_iterations
    solution_tolerance = float(g(model, "solution_tolerance") or 0.0)
    if solution_tolerance > 0.0:
        data["solution_tolerance"] = solution_tolerance
    data["enforce_q_limits"] = bool(g(model, "enforce_q_limits"))
    data["use_dc_powerflow"] = bool(g(model, "use_dc_powerflow"))
    data["save_case"] = bool(g(model, "save_case"))
    data["save_format"] = SAVE_FORMATS[int(g(model, "save_format"))]
    modelname = _modelname(model)
    if modelname is not None:
        data["modelname"] = modelname
    data["stop_on_failure"] = bool(g(model, "stop_on_failure"))
    data["maximum_iterations_opf"] = int(g(model, "maximum_iterations_opf"))
    for name in ("opf_feasibility_tolerance", "opf_gradient_tolerance", "opf_condition_tolerance", "opf_cost_tolerance"):
        data[name] = float(g(model, name))
    return True

#
# Data exchange
#
def _long(item:Any) -> int:
    """`PyLong_AsLong()`: -1 (with an error gridlabd ignores) for an item
    that is not an integer"""
    return item if isinstance(item, int) and not isinstance(item, bool) else -1

def _value(model:Any, name:str, prop:str, kind:type) -> Any:
    if kind is int:
        return get_int(model, name, prop)
    return get_double(model, name, prop)

def _send(row:list, index:int, value:Any, kind:type, resolution:float) -> bool:
    """Send a value if it differs from the item by more than the
    resolution (gridlabd `SENDX()`, `SEND()`); returns `True` when sent"""
    item = row[index]
    old = _long(item) if kind is int else float(item)
    if abs(value - old) > resolution:
        row[index] = int(value) if kind is int else float(value)
        return True
    return False

def _gen_state(model:Any, name:str) -> dict:
    from .gen import Gen # pylint: disable=import-outside-toplevel
    return Gen.state(model, name)

def _call_controller(state:ModuleState, t0:int, command:Callable, name:str) -> int:
    """Call a controller module function with the data and check its
    result (the end of gridlabd `update_controller()` and the controller
    call of `update_solution()`)"""
    controllers = str(g(state.model, "controllers") or "").strip('"')
    state.data["t"] = t0
    try:
        ts = command(state.data)
    except Exception as err: # pylint: disable=broad-exception-caught
        python_error(err)
        return TS_INVALID
    if not isinstance(ts, int):
        gl_error(f"{controllers}.{name}(data) returned value that is not a valid timestamp")
        return TS_INVALID
    t1 = int(ts)
    if t1 < 0:
        t1 = TS_NEVER
    elif t1 == 0 and g(state.model, "stop_on_failure"):
        gl_error(f"{controllers}.{name}(data) halted the simulation")
        return TS_INVALID
    elif t1 < t0:
        gl_error(f"{controllers}.{name}(data) returned a timestamp earlier than {name} time t0={t0}")
        return TS_INVALID
    return t1

def update_controller(state:ModuleState, t0:int, command:Callable, name:str) -> int:
    """gridlabd `update_controller()`: send the object values that differ,
    then call the controller"""
    # pylint: disable=too-many-locals,too-many-branches
    model = state.model
    res = float(g(model, "solver_update_resolution"))
    opf = state.opf_needed(t0)
    for n, obj in enumerate(state.buses):
        row = state.busdata[n]
        for index, (prop, kind, _) in enumerate(BUS_FIELDS):
            _send(row, index, _value(model, obj, prop, kind), kind, res)
        if opf:
            for index, (prop, kind) in enumerate(BUS_OPF_FIELDS, 13):
                _send(row, index, _value(model, obj, prop, kind), kind, res)
    for n, obj in enumerate(state.branches):
        row = state.branchdata[n]
        for index, (prop, kind, _) in enumerate(BRANCH_FIELDS):
            _send(row, index, _value(model, obj, prop, kind), kind, res)
    for n, obj in enumerate(state.gens):
        row = state.gendata[n]
        for index, (prop, kind, _) in enumerate(GEN_FIELDS):
            _send(row, index, _value(model, obj, prop, kind), kind, res)
        if opf:
            for index, (prop, kind) in enumerate(GEN_OPF_FIELDS, 21):
                _send(row, index, _value(model, obj, prop, kind), kind, res)
    if state.gencostdata is not None:
        for obj in state.gens:
            cost = _gen_state(model, obj)["cost"]
            if cost is None:
                gl_warning(f"pypower.{name}(t={t0}) missing cost data for generator '{obj}'")
                continue
            row = state.gencostdata[state.gencosts.index(cost)]
            _send(row, 0, get_int(model, cost, "model"), int, res)
            _send(row, 1, get_double(model, cost, "startup"), float, res)
            _send(row, 2, get_double(model, cost, "shutdown"), float, res)
            costs = get_text(model, cost, "costs")
            if row[3] != costs:
                row[3] = costs
    if state.dclinedata is not None:
        for n, obj in enumerate(state.dclines):
            row = state.dclinedata[n]
            sfrom, sto = get_complex(model, obj, "Sfrom"), get_complex(model, obj, "Sto")
            if sfrom.real >= sto.real:
                _send(row, 0, get_int(model, obj, "fbus"), int, res)
                _send(row, 1, get_int(model, obj, "tbus"), int, res)
            else:
                _send(row, 0, get_int(model, obj, "tbus"), int, res)
                _send(row, 1, get_int(model, obj, "fbus"), int, res)
            _dcline_send(model, obj, row, res, opf)
    return _call_controller(state, t0, command, name)

def _dcline_send(model:Any, obj:str, row:list, res:float, opf:bool) -> int:
    """Send dcline columns 2 to 16 (and 17 to 22 when `opf`); returns the
    number of values sent"""
    sfrom, sto = get_complex(model, obj, "Sfrom"), get_complex(model, obj, "Sto")
    count = 0
    count += _send(row, 2, get_int(model, obj, "status"), int, res)
    for index, value in ((3, sfrom.real), (4, sfrom.imag), (5, sto.real), (6, sto.imag)):
        count += _send(row, index, value, float, res)
    for index, prop in enumerate(("Vfrom", "Vto", "Pmin", "Pmax", "Qminf", "Qmaxf", "Qmint", "Qmaxt", "loss0", "loss1"), 7):
        count += _send(row, index, get_double(model, obj, prop), float, res)
    if opf:
        for index, prop in enumerate(DCLINE_OPF_FIELDS, 17):
            count += _send(row, index, get_double(model, obj, prop), float, res)
    return count

def _send_solution(state:ModuleState, t0:int, do_opf:bool) -> int:
    """Send the object values to the solver data; returns the number of
    changes (the first part of gridlabd `update_solution()`)"""
    # pylint: disable=too-many-locals,too-many-branches
    model, data = state.model, state.data
    res = float(g(model, "solver_update_resolution"))
    n_changes = 0
    gl_verbose("updating bus data")
    data["bus"] = state.busdata
    for n, obj in enumerate(state.buses):
        row = state.busdata[n]
        for index, (prop, kind, change) in enumerate(BUS_FIELDS):
            old = row[index]
            value = _value(model, obj, prop, kind)
            if _send(row, index, value, kind, res) and change:
                gl_debug(f"pypower.update_solution(t={t0}): sending bus {n} {prop}, updating from {_long(old) if kind is int else float(old):f} to {value:f}")
                n_changes += 1
    gl_verbose("updating branch data")
    data["branch"] = state.branchdata
    for n, obj in enumerate(state.branches):
        row = state.branchdata[n]
        for index, (prop, kind, change) in enumerate(BRANCH_FIELDS):
            if _send(row, index, _value(model, obj, prop, kind), kind, res) and (do_opf if change is None else change):
                n_changes += 1
    gl_verbose("updating gen data")
    data["gen"] = state.gendata
    for n, obj in enumerate(state.gens):
        row = state.gendata[n]
        for index, (prop, kind, change) in enumerate(GEN_FIELDS):
            if _send(row, index, _value(model, obj, prop, kind), kind, res) and change:
                n_changes += 1
    if state.gencostdata is not None:
        gl_verbose("updating gencost data")
        data["gencost"] = state.gencostdata
        for n, obj in enumerate(state.gencosts):
            row = state.gencostdata[n]
            for index, prop, kind in ((0, "model", int), (1, "startup", float), (2, "shutdown", float)):
                if _send(row, index, _value(model, obj, prop, kind), kind, res) and do_opf:
                    n_changes += 1
            costs = get_text(model, obj, "costs")
            if row[3] != costs:
                row[3] = costs
                n_changes += 1
    if state.dclinedata is not None:
        gl_verbose("updating dcline data")
        data["dcline"] = state.dclinedata
        for n, obj in enumerate(state.dclines):
            row = state.dclinedata[n]
            n_changes += _send(row, 0, get_int(model, obj, "fbus"), int, res)
            n_changes += _send(row, 1, get_int(model, obj, "tbus"), int, res)
            n_changes += _dcline_send(model, obj, row, res, False)
    return n_changes

def _recv(model:Any, obj:str, prop:str, value:float, res:float, state_values:dict|None=None) -> bool: # pylint: disable=too-many-arguments,too-many-positional-arguments
    """Receive a solver value if it differs by more than the resolution
    (gridlabd `RECV()`); `state_values` holds values that gridlabd keeps in
    members that are not published; returns `True` when changed"""
    old = state_values[prop] if state_values is not None else get_double(model, obj, prop)
    if abs(old - value) > res:
        if state_values is not None:
            state_values[prop] = value
        else:
            set_double(model, obj, prop, value)
        return True
    return False

def _receive_solution(state:ModuleState, result:dict, t0:int, do_opf:bool) -> int|None: # pylint: disable=unused-argument
    """Copy the solution back to the objects (the second part of gridlabd
    `update_solution()`); returns the number of changes, or `None` when
    the result has no data"""
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    model = state.model
    res = float(g(model, "solver_update_resolution"))
    base_mva = float(g(model, "baseMVA"))
    n_changes = 0
    busdata = result.get("bus")
    if state.buses and busdata is None:
        gl_error("pypower solver did not return any bus data")
        return None
    gl_verbose("reading bus data")
    from .bus import Bus # pylint: disable=import-outside-toplevel
    for n, obj in enumerate(state.buses):
        row = busdata[n]
        if not math.isnan(float(row[7])):
            _recv(model, obj, "Vm", float(row[7]), res)
        if not math.isnan(float(row[8])):
            _recv(model, obj, "Va", float(row[8]), res)
        if do_opf:
            for index, (prop, _) in enumerate(BUS_OPF_FIELDS, 13):
                _recv(model, obj, prop, float(row[index]), res)
        Bus.state(model, obj)["V"] = cmath.rect(get_double(model, obj, "Vm"), math.radians(get_double(model, obj, "Va")))

    gl_verbose("reading branch data")
    total_loss = 0.0
    for n, obj in enumerate(state.branches):
        fbus_id = get_int(model, obj, "fbus") - 1
        tbus_id = get_int(model, obj, "tbus") - 1
        if not 0 <= fbus_id < len(state.buses):
            gl_warning(f"pypower::on_sync(): from bus {fbus_id} on branch {n} is not valid")
        elif not 0 <= tbus_id < len(state.buses):
            gl_warning(f"pypower::on_sync(): to bus {tbus_id} on branch {n} is not valid")
        else:
            z = complex(get_double(model, obj, "r"), get_double(model, obj, "x"))
            dv = Bus.state(model, state.buses[fbus_id])["V"] - Bus.state(model, state.buses[tbus_id])["V"]
            current = cdiv(dv, z)
            set_complex(model, obj, "current", current*base_mva, "d")
            loss = abs(dv*current.conjugate()) / base_mva
            set_double(model, obj, "loss", loss)
            total_loss += loss
        if do_opf:
            rows = result.get("branch")
            if rows is not None and len(rows[n]) >= 21:
                for index, prop in enumerate(("mu_sfrom", "mu_sto", "mu_angmin", "mu_angmax"), 17):
                    _recv(model, obj, prop, float(rows[n][index]), res)
    set_global(model, f"{MODULE}::total_loss", total_loss)

    gl_verbose("reading gencost data")
    gendata = result.get("gen")
    if state.gencosts and gendata is None:
        gl_error("pypower solver did not return any gen data")
        return None
    shortfall = 0.0
    gl_verbose("reading gen data")
    for n, obj in enumerate(state.gens):
        row = gendata[n]
        gen = _gen_state(model, obj)
        if do_opf and gen["plant_count"] > 0:
            n_changes += _recv(model, obj, "Ps", float(row[1]), res, gen)
            n_changes += _recv(model, obj, "Qs", float(row[2]), res, gen)
        else:
            n_changes += _recv(model, obj, "Pg", float(row[1]), res)
            n_changes += _recv(model, obj, "Qg", float(row[2]), res)
        _recv(model, obj, "apf", float(row[20]), res)
        if do_opf and len(row) > 24:
            for index, (prop, _) in enumerate(GEN_OPF_FIELDS, 21):
                _recv(model, obj, prop, float(row[index]), res)
        shortfall += max(get_double(model, obj, "Pg") - get_double(model, obj, "Pmax"), 0.0)
    set_global(model, f"{MODULE}::generation_shortfall", shortfall)

    if state.dclines and do_opf:
        gl_verbose("reading dcline data")
        rows = result.get("dcline", state.dclinedata)
        for n, obj in enumerate(state.dclines):
            row = rows[n]
            if len(row) > 22:
                for index, prop in ((17, "mu_Pmax"), (18, "mu_Pmin"), (19, "mu_Qminf"), (20, "mu_Qmaxf"), (21, "mu_Qmint"), (22, "mu_Qmaxt")):
                    _recv(model, obj, prop, float(row[index]), res)
    gl_verbose(f"{n_changes} changes detected")
    return n_changes

def _set_status(model:Any, value:int) -> None:
    set_global(model, f"{MODULE}::solver_status", ("INIT", "SUCCESS", "FAILED")[value])

def update_solution(state:ModuleState, t0:int) -> int:
    """gridlabd `update_solution()`"""
    # pylint: disable=too-many-return-statements,too-many-branches
    from .solver import solver # pylint: disable=import-outside-toplevel
    model = state.model
    gl_verbose(f"pypower::update_solution(t0='{model.globals.timestamp_to_string(t0)}')")
    do_opf = state.opf_needed(t0)
    gl_verbose(f"opf_needed() -> {'TRUE' if do_opf else 'FALSE'}")
    n_changes = _send_solution(state, t0, do_opf)

    t1 = TS_NEVER
    if state.py_sync is not None:
        gl_verbose("updating controller")
        t1 = _call_controller(state, t0, state.py_sync, "on_sync")
        if t1 == TS_INVALID:
            return TS_INVALID

    if not state.solved or state.result is None or n_changes > 0:
        n_changes = 0
        gl_verbose("running pypower solver")
        state.solved = True
        state.result = solver(state.data)
        result = state.result
        if result is not None:
            if result is False:
                _set_status(model, SS_FAILED)
                if g(model, "stop_on_failure"):
                    name = os.path.basename(state.data.get("modelname", "pypower"))
                    gl_error(f"pypower solver failed (see '{name}_failed.txt' for solver failure diagnostics)")
                    return TS_INVALID
                gl_warning("pypower solver failed (pypower::stop_on_failure is FALSE)")
                return TS_NEVER
            if not isinstance(result, dict):
                gl_error("pypower solver returned invalid result type (not a dict)")
                _set_status(model, SS_FAILED)
                return TS_INVALID
            _set_status(model, SS_SUCCESS)
            changes = _receive_solution(state, result, t0, do_opf)
            if changes is None:
                _set_status(model, SS_FAILED)
                return TS_INVALID
            n_changes = changes

    if state.result is None and g(model, "stop_on_failure"):
        gl_warning("pypower solver failed with no result (enable verbose for diagnostics)")
        _set_status(model, SS_FAILED)
        return TS_INVALID
    if state.result is None:
        gl_warning("pypower solver failed (no result with pypower::stop_on_failure FALSE)")
        _set_status(model, SS_FAILED)
    else:
        _set_status(model, SS_SUCCESS)
    if n_changes > 0:
        gl_debug(f"{n_changes} values changed, requesting resolve")
        return t0
    maximum_timestep = float(g(model, "maximum_timestep") or 0.0)
    t2 = int(t0 + maximum_timestep) if maximum_timestep > 0 else TS_NEVER
    return min(t1, t2)

#
# Solvers
#
def _model() -> Any:
    return runner().model

def _state() -> ModuleState:
    from ._common import module_state # pylint: disable=import-outside-toplevel
    return module_state(_model())

def _clock(t:int) -> str:
    return _model().globals.timestamp_to_string(t)

def solver_init() -> bool:
    """Module `init` solver: initializes the module if no object did"""
    return ensure_init(_model())

def solver_precommit(t0:int) -> int:
    """Module `precommit` solver (gridlabd `on_precommit()`)"""
    state = _state()
    gl_verbose(f"pypower::on_precommit(t0='{_clock(t0)}')")
    if not state.buses or not state.branches:
        return TS_NEVER
    t1 = update_controller(state, t0, state.py_precommit, "precommit") if state.py_precommit else TS_NEVER
    maximum_timestep = float(g(state.model, "maximum_timestep") or 0.0)
    if maximum_timestep > 0:
        t1 = min(int(t0 + maximum_timestep), t1)
    interval = float(g(state.model, "opf_update_interval") or 0.0)
    if interval > 0:
        t1 = min(t1, int((math.floor(t0/interval)+1)*interval))
    gl_verbose(f"pypower::on_precommit(t0='{_clock(t0)}') -> '{_clock(t1) if t1 != TS_INVALID else 'INVALID'}'")
    return t1

def solver_sync(t0:int) -> int:
    """Module `sync` solver (gridlabd `on_sync()`)"""
    state = _state()
    gl_verbose(f"pypower::on_sync(t0='{_clock(t0)}')")
    if not state.buses or not state.branches:
        return TS_NEVER
    t1 = update_solution(state, t0)
    gl_verbose(f"pypower::on_sync(t0='{_clock(t0)}') -> '{_clock(t1) if t1 != TS_INVALID else 'INVALID'}'")
    return t1

def solver_commit(t0:int) -> bool:
    """Module `commit` solver (gridlabd `on_commit()`)"""
    state = _state()
    result = True
    gl_verbose(f"pypower::on_commit(t0='{_clock(t0)}')")
    if state.buses and state.branches and state.py_commit is not None:
        if update_controller(state, t0, state.py_commit, "commit") <= t0:
            result = False
    gl_verbose(f"pypower::on_commit(t0='{_clock(t0)}') -> 1")
    return result

def solver_term() -> None:
    """Module `term` solver (gridlabd `on_term()`)"""
    state = _state()
    if state.py_term is None:
        return
    try:
        result = state.py_term()
    except Exception as err: # pylint: disable=broad-exception-caught
        python_error(err)
        return
    if result is not None:
        gl_warning("ignored return value from on_term()")

def is_bus(model:Any, name:str|None) -> bool:
    """`True` for a pypower bus"""
    return isa(model, name, "bus")
