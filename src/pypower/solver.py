# pylint: disable=line-too-long
"""PYPOWER solver call

`solver(pf_case)` runs PYPOWER's power flow (`runpf()`) or optimal power
flow (`runopf()`) on the case data that the module collects from the
`bus`, `branch`, `gen`, `gencost`, and `dcline` objects, and returns the
case data with the solution, as gridlabd's `gridlabd.pypower_solver.solver()`
does (`module/pypower/pypower_solver.py`). The module calls it from its
`sync` solver; users do not normally call it.

Syntax
------

    from pypower.solver import solver
    result = solver(pf_case)

Arguments
---------
- `pf_case`: `dict` of case data and options: `version`, `baseMVA`,
  `bus`, `branch`, `gen` (lists of rows), optionally `gencost` (rows of
  `[model, startup, shutdown, "c1,c2,..."]`) and `dcline`, and the options
  in `OPTIONS`; keys named as PYPOWER options (`ppoption()`) override them

Returns
-------
- `dict`: `pf_case` with `bus`, `branch`, and the rows of the in-service
  generators of `gen` replaced by the solution
- `False`: the solver failed and `stop_on_failure` is true, or an
  exception was caught (its message is written to `stderr` as
  `EXCEPTION [FILE@LINE]: TYPE - MESSAGE`)

Description
-----------

Given `pf_case`, `solver()` is expected to:

1. read the options of `OPTIONS` from `pf_case`, defaulting to the values
   in `OPTIONS`;
2. build PYPOWER options from them: `PF_ALG` (`solver_method`: 1 NR, 2
   FD-XB, 3 FD-BX, 4 GS), `PF_TOL`, `PF_MAX_IT`, `PF_MAX_IT_FD`,
   `PF_MAX_IT_GS`, `ENFORCE_Q_LIMS`, `PF_DC`, the output options (all on
   when `verbose`, `VERBOSE` 3 when `debug`), and the PIPS options
   `PDIPM_MAX_IT`, `PDIPM_FEASTOL`, `PDIPM_GRADTOL`, `PDIPM_COMPTOL`,
   `PDIPM_COSTTOL`;
3. pass PYPOWER only the generators whose status (column 7) is 1, and the
   cost rows of those generators;
4. raise (and so return `False`) when no bus is of type REF or PV, or when
   `gencost` is given empty;
5. run `runopf()` when `gencost` is given, else `runpf()`;
6. when `save_case` is true, write the case data before the solution
   (`MODELNAME_casedata.FORMAT`) and the solution
   (`MODELNAME_results.FORMAT` and `MODELNAME_results_solver.json`), where
   `FORMAT` is `save_format` (`csv`: one file per table,
   `MODELNAME_casedata_bus.csv`, ...; `json`; `py`: the Python text of the
   data);
7. when the solver fails, write the solution and the diagnostics
   `MODELNAME_failed.txt` (generation, branch flow, and bus voltage limit
   violations), and return `False` if `stop_on_failure` is true;
8. when an exception is caught, write the case data to
   `MODELNAME_exception.FORMAT`, write the exception line, and return
   `False`.

Solver output that PYPOWER writes (with `verbose` or `debug`) and the
debug tables of the case data (with `debug` and `verbose`) are written to
the running simulation's `stdout` and `stderr` lines when a simulation is
running, else to the process's.

Examples
--------

A three-bus network with a slack generator on bus 1 and loads on buses 2
and 3:

    >>> from pypower.solver import solver
    >>> line = [0.01, 0.1, 0.02, 0, 0, 0, 0, 0, 1, -360, 360]
    >>> case = {"version": 2, "baseMVA": 100.0,
    ...     "bus": [[1, 3, 0, 0, 0, 0, 1, 1.0, 0, 230, 1, 1.1, 0.9],
    ...         [2, 1, 50, 20, 0, 0, 1, 1.0, 0, 230, 1, 1.1, 0.9],
    ...         [3, 1, 40, 10, 0, 0, 1, 1.0, 0, 230, 1, 1.1, 0.9]],
    ...     "branch": [[1, 2] + line, [2, 3] + line, [1, 3] + line],
    ...     "gen": [[1, 0, 0, 100, -100, 1.0, 100, 1, 200, 0] + [0]*11]}
    >>> result = solver(case)
    >>> [round(bus[7], 4) for bus in result["bus"]]
    [1.0, 0.9792, 0.983]
    >>> [round(bus[8], 3) for bus in result["bus"]]
    [0.0, -2.643, -2.462]
    >>> round(result["gen"][0][1], 2), round(result["gen"][0][2], 2)
    (90.46, 28.75)

Caveats
-------

- PYPOWER is vendored as `pypower._pypower` (PYPOWER 5.1.16, the version
  gridlabd pins), because this package takes PYPOWER's import name; see
  `src/pypower/_pypower/README.md` for the changes made for numpy 2 and
  current scipy.
- `dcline` data is passed to PYPOWER, which ignores it without the
  `toggle_dcline()` extension (as in gridlabd).
- PYPOWER's `runpf()` with `ENFORCE_Q_LIMS` raises `IndexError`
  (gridlabd's pinned numpy too), so `enforce_q_limits` makes the solver
  fail.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. Options are read from `pf_case` on each call. gridlabd stores them in
   the solver module's globals, so a value set by one call stays for later
   calls that do not give it (one run per process makes this invisible).
2. The numpy print options that the `py` save format uses are set only
   while the file is written; gridlabd sets them for the whole process
   when the solver module is imported.
3. An exception raised while the exception file is written (the case data
   is not built yet) is caught, written, and returns `None`, which the
   module treats as a solver call that returned nothing; gridlabd's
   solver raises it to the module, which does the same.

References
----------

- `arras-energy/gridlabd`: `module/pypower/pypower_solver.py`
- [PYPOWER](https://github.com/rwl/PYPOWER) `runpf.py`, `runopf.py`,
  `ppoption.py`
"""

import os
import io
import sys
import csv
import json
import contextlib
from math import sqrt
from typing import Any

import numpy as np
from numpy import array

from ._pypower.ppoption import ppoption
from ._pypower.runpf import runpf
from ._pypower.runopf import runopf

OPTIONS: dict[str,Any] = {
    "save_case": False,
    "debug": False,
    "verbose": False,
    "solver_method": 1,
    "solution_tolerance": 1e-08,
    "maximum_iterations_nr": 10,
    "maximum_iterations_fd": 30,
    "maximum_iterations_gs": 1000,
    "enforce_q_limits": False,
    "use_dc_powerflow": False,
    "save_format": "csv",
    "modelname": "pypower",
    "stop_on_failure": True,
    "maximum_iterations_opf": 20,
    "opf_feasibility_tolerance": 1e-06,
    "opf_gradient_tolerance": 1e-06,
    "opf_condition_tolerance": 1e-06,
    "opf_cost_tolerance": 1e-06,
}
"""Solver options and their defaults (gridlabd's solver module globals)"""

CSV_HEADERS = {
    "bus" : "bus_i,type,Pd,Qd,Gs,Bs,area,Vm,Va,baseKV,zone,Vmax,Vmin,lam_P,lam_Q,mu_Vmax,mu_Vmin",
    "branch" : "fbus,tbus,r,x,b,rateA,rateB,rateC,ratio,angle,status,angmin,angmax,Pfrom,Qfrom,Pto,Qto,mu_Sfrom,mu_Sto,mu_angmin,mu_angmax",
    "gen" : "bus,Pg,Qg,Qmax,Qmin,Vg,mBase,status,Pmax,Pmin,Pc1,Pc2,Qc1min,Qc1max,Qc2min,Qc2max,ramp_agc,ramp_10,ramp_30,ramp_q,apf,mu_Pmax,mu_Pmin,mu_Qmax,mu_Qmin",
    "gencost" : "model,startup,shutdown,parameters",
    "dcline" : "fbus,tbus,status,Pf,Pt,Qf,Qt,Vf,Vt,Pmin,Pmax,Qminf,Qmaxf,Qmint,Qmaxt,mu_Pmin,mu_Pmax,mu_Qminf,mu_Qmaxf,mu_Qmint,mu_Qmaxt,mu_mu_Pmin",
}
"""Column names of the CSV case files"""

class PypowerError(Exception):
    """Solver error (caught by `solver()`)"""

#
# Output to the running simulation
#
def _runner() -> Any:
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    return Runner.current()

def _emit(text:str, err:bool) -> None:
    """Write solver output lines to the running simulation, else to the
    process"""
    if not text:
        return
    current = _runner()
    if current is None:
        (sys.stderr if err else sys.stdout).write(text)
        return
    lines = text.splitlines()
    if err:
        current.stderr.extend(lines)
    else:
        current.stdout.extend(lines)

@contextlib.contextmanager
def _capture():
    """Collect what PYPOWER writes to `sys.stdout` and `sys.stderr` (also
    through the names its modules import from `sys`)"""
    out, err = io.StringIO(), io.StringIO()
    swapped = []
    for name, module in list(sys.modules.items()):
        if name.startswith(f"{__package__}._pypower."):
            for attr, buffer, stream in (("stdout", out, sys.stdout), ("stderr", err, sys.stderr)):
                if getattr(module, attr, None) is stream:
                    swapped.append((module, attr, stream))
                    setattr(module, attr, buffer)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            yield
    finally:
        for module, attr, stream in swapped:
            setattr(module, attr, stream)
        _emit(out.getvalue(), False)
        _emit(err.getvalue(), True)

#
# Case files
#
def write_case(data:dict, filename:str, diagnostics:bool=True) -> None:
    """Write case data or results to `filename` (`.py`, `.json`, or `.csv`,
    one file per table), and the failure diagnostics to `NAME.txt` when
    `diagnostics` is true"""
    # pylint: disable=too-many-branches
    name, ext = os.path.splitext(filename)
    if ext == ".py":
        with np.printoptions(threshold=np.inf, linewidth=np.inf, formatter={'float':lambda x:f"{x:.6g}"}):
            with open(filename, "w", encoding="utf-8") as fh:
                fh.write(str(data))
    elif ext == ".json":
        def fix(x):
            if hasattr(x, "tolist"):
                return x.tolist()
            if type(x) is list: # pylint: disable=unidiomatic-typecheck
                return [fix(y) for y in x]
            if type(x) is dict: # pylint: disable=unidiomatic-typecheck
                return dict(zip(list(x.keys()), fix(list(x.values()))))
            if type(x) in [int, str, bool, float, None]:
                return x
            raise PypowerError(f"cannot fix {type(x)}({x})")
        with open(filename, "w", encoding="utf-8") as fh:
            result = {}
            for key, value in data.items():
                result[key] = fix(value)
            json.dump(result, fh, indent=2)
    elif ext == ".csv":
        for key, value in data.items():
            if key in ["bus", "branch", "gen", "gencost", "dcline"]:
                with open(f"{name}_{key}.csv", "w", encoding="utf-8", newline="") as fh:
                    writer = csv.writer(fh, lineterminator="\r\n")
                    writer.writerow(CSV_HEADERS[key].split(','))
                    for row in value.tolist():
                        writer.writerow(row)
    if diagnostics:
        with open(f"{name}.txt", "w", encoding="utf-8") as fh:
            _diagnostics(data, fh)

def _diagnostics(data:dict, fh:Any) -> None:
    """Solver failure diagnostics: limit violations"""
    print("*** SOLVER FAILURE DIAGNOSTICS ***\n", file=fh)
    if "gen" in data and len(data["gen"]) > 0 and len(data["gen"][0]) > 9:
        violations = [x for x in sorted(data["gen"], key=lambda x:x[0])
            if (x[8] > x[9] and not x[9] <= x[1] <= x[8])
                or (x[4] > x[3] and not x[4] <= x[2] <= x[3])]
        if violations:
            print("Generation output violations:\n\n",
                "Bus     Pmin     Pg       Pmax       Qmin     Qg       Qmax\n",
                "-----   -------- -------- --------   -------- -------- -------- \n",
                *[f"{int(x[0]):5d}   {x[9]:8.1f} {x[1]:8.1f} {x[8]:8.1f}   {x[4]:8.1f} {x[2]:8.1f} {x[3]:8.1f}\n"
                    for x in violations], file=fh)
        else:
            print("- No generation violations detected", file=fh)
    else:
        print("! No generation data returned (enable verbose to see solver output)", file=fh)
    if "branch" in data and len(data["branch"]) > 0 and len(data["branch"][0]) > 13:
        violations = [x for x in sorted(data["branch"], key=lambda x:(x[0], x[1]))
            if max(x[5:8]) > 0 and max(sqrt(x[13]**2+x[14]**2), sqrt(x[15]**2+x[16]**2)) > max(x[5:8])]
        if violations:
            print("Branch flow violations:\n\n",
                "From  To      Pin      Qin        Pout     Qout       Smax\n",
                "----- -----   -------- --------   -------- --------   --------\n",
                *[f"{int(x[0]):5d} {int(x[1]):5d}   {x[13]:8.1f} {x[14]:8.1f}   {x[15]:8.1f} {x[16]:8.1f}   {max(x[5:8])}\n"
                    for x in violations], file=fh)
        else:
            print("- No flow violations detected", file=fh)
    else:
        print("! No branch data returned (enable verbose to see solver output)", file=fh)
    if "bus" in data and len(data["bus"]) > 0 and len(data["bus"][0]) > 12:
        violations = [x for x in sorted(data["bus"], key=lambda x:x[0])
            if x[11] > x[12] and not x[12] <= x[7] <= x[11]]
        if violations:
            print("Bus voltage violations:\n\n",
                "Bus   Vmin  Vmag  Vmax\n",
                "----- ----- ----- -----\n",
                *[f"{int(x[0]):5d} {x[12]:5.3f} {x[7]:5.3f} {x[11]:5.3f}\n"
                    for x in violations], file=fh)
        else:
            print("- No voltage violations detected", file=fh)
    else:
        print("! No bus data returned (enable verbose to see solver output)", file=fh)

def jsonify(data:Any, modelname:str="pypower") -> Any:
    """Results as gridlabd's solver writes them to
    `MODELNAME_results_solver.json`: tables as the names of their CSV files,
    other arrays as lists, numbers and text as they are"""
    # gridlabd's jsonify() replaces nested containers by their key and
    # fails on lists; both are reproduced as written there
    if type(data) is dict: # pylint: disable=unidiomatic-typecheck
        result = {}
        for x, y in data.items():
            if type(y) in [int, str, float, bool]:
                result[x] = y
            elif hasattr(y, "tolist"):
                if x in ["bus", "branch", "gen", "dcline"]:
                    result[x] = f"{modelname.replace(os.getcwd(), '.')}_results_{x}.csv"
                else:
                    result[x] = y.tolist()
            elif type(y) in [list, dict]:
                result[x] = jsonify(x, modelname)
    elif type(data) is list: # pylint: disable=unidiomatic-typecheck
        raise NameError("name 'y' is not defined")
    else:
        result = data
    return result

#
# Debug tables
#
def _debug_tables(casedata:dict, genmap:list[int]|None, which:str) -> str:
    """Debug tables of the case data, as gridlabd's solver prints them"""
    # pylint: disable=too-many-locals
    out = io.StringIO()
    if which == "bus":
        print("\n*** BUS DATA ***\n", file=out)
        print("BUS_I BUS_TYPE   PD      PQ      GS      BS    BUS_AREA  VM    VA   BASE_KV ZONE VMAX  VMIN", file=out)
        print("----- -------- ------- ------- ------- ------- -------- ----- ----- ------- ---- ----- -----", file=out)
        for row in sorted(casedata["bus"], key=lambda x:x[0]):
            print(f"{row[0]:5.0f} {['?','PQ','PV','REF','ISOLATED'][int(row[1])]:8.8s}"
                + f" {row[2]:7.1f} {row[3]:7.1f} {row[4]:7.1f} {row[5]:7.1f}"
                + f" {row[6]:8.0f} {row[7]:5.3f} {row[8]:5.1f} {row[9]:7.1f}"
                + f" {row[10]:4.0f} {row[11]:5.1f} {row[12]:5.1f}", file=out)
        print("\n*** BRANCH DATA ***\n", file=out)
        print("F_BUS T_BUS   BR_R     BR_X     BR_B   RATE_A RATE_B RATE_C  TAP  SHIFT BR_STATUS ANGMIN ANGMAX", file=out)
        print("----- ----- -------- -------- -------- ------ ------ ------ ----- ----- --------- ------ ------", file=out)
        for row in sorted(casedata["branch"], key=lambda x:(x[0], x[1])):
            print(f"{row[0]:5.0f} {row[1]:5.0f} {row[2]:8.5f} {row[3]:8.5f} {row[4]:8.5f}"
                + f" {row[5]:6.0f} {row[6]:6.0f} {row[7]:6.0f} {row[8]:5.2f} {row[9]:5.1f}"
                + f" {['OUT','IN'][int(row[10])]:9.9s} {row[11]:6.1f} {row[12]:6.1f}", file=out)
    elif which == "gen":
        print("\n*** GEN DATA ***\n", file=out)
        print("GEN   GEN_BUS    PG       QG      QMAX     QMIN   VG    MBASE GEN_STATUS PMAX  PMIN   PC1   PC2  QC1MIN QC1MAX QC2MIN QC2MAX RAMP_AGC RAMP_10 RAMP_30 RAMP_Q  APF ", file=out)
        print("----- ------- -------- -------- -------- -------- ----- ----- ---------- ----- ----- ----- ----- ------ ------ ------ ------ -------- ------- ------- ------ -----", file=out)
        for n, row in enumerate(casedata["gen"]):
            print(f"{float(genmap[n]):5.0f} {row[0]:7.0f} {row[1]:8.1f} {row[2]:8.1f} {row[3]:8.0f} {row[4]:8.0f}"
                + f" {row[5]:5.3f} {row[6]:5.0f} {['OUT','IN'][int(row[7])]:10.10s} {row[8]:5.0f} {row[9]:5.0f}"
                + f" {row[10]:5.0f} {row[11]:5.0f} {row[12]:6.1f} {row[13]:6.1f} {row[14]:6.1f} {row[15]:6.1f}"
                + f" {row[16]:8.1f} {row[17]:7.1f} {row[18]:7.1f} {row[19]:6.1f} {row[20]:5.2f}", file=out)
    elif which == "gencost":
        print("\n*** GENCOST DATA ***\n", file=out)
        print("GEN   MODEL STARTUP SHUTDOWN NCOST COST", file=out)
        print("----- ----- ------- -------- ----- -----------------------", file=out)
        for n, row in enumerate(casedata["gencost"]):
            print(f"{float(genmap[n]):5.0f} {['-','PWLF','POLY'][int(row[0])]:5.5s} {row[1]:7.2f} {row[2]:8.2f} {row[3]:5.0f} {','.join([str(x) for x in row[4:]])}", file=out)
    elif which == "dcline":
        print("\n*** DCLINE DATA ***\n", file=out)
        print("FBUS  TBUS  STATUS PFROM QFROM PTO   QTO   VFROM VTO   PMIN  PMAX  QMINF QMAXF QMINT QMAXT LOSS0 LOSS1", file=out)
        print("----- ----- ------ ----- ----- ----- ----- ----- ----- ----- ----- ----- ----- ----- ----- ----- -----", file=out)
        for row in casedata["dcline"]:
            print(f"{float(row[0]):5.0f} {float(row[1]):5.0f} {'IN    ' if row[2] else 'OUT   '} {row[3]:5.1f} {row[4]:5.1f} {row[5]:5.1f} {row[6]:5.1f} {row[7]:5.1f} {row[8]:5.1f} {row[9]:5.1f} {row[10]:5.1f} {row[11]:5.1f} {row[12]:5.1f} {row[13]:5.1f} {row[14]:5.1f} {row[15]:5.1f} {row[16]:5.3f}", file=out)
    return out.getvalue()

#
# Solver
#
def _options(pf_case:dict) -> dict[str,Any]:
    """Solver options from the case data"""
    opts = dict(OPTIONS)
    for key in opts:
        if key in pf_case:
            opts[key] = pf_case[key]
    return opts

def _ppoption(opts:dict[str,Any], pf_case:dict) -> dict:
    """PYPOWER options"""
    verbose = opts["verbose"]
    options = ppoption(
        PF_ALG = opts["solver_method"],
        PF_TOL = opts["solution_tolerance"],
        PF_MAX_IT = opts["maximum_iterations_nr"],
        PF_MAX_IT_FD = opts["maximum_iterations_fd"],
        PF_MAX_IT_GS = opts["maximum_iterations_gs"],
        ENFORCE_Q_LIMS = opts["enforce_q_limits"],
        PF_DC = opts["use_dc_powerflow"],
        OUT_ALL = 1 if verbose else 0,
        VERBOSE = 3 if opts["debug"] else 0,
        OUT_SYS_SUM = verbose,
        OUT_AREA_SUM = verbose,
        OUT_BUS = verbose,
        OUT_BRTANCH = verbose, # misspelled in gridlabd; ppoption() ignores it
        OUT_GEN = verbose,
        OUT_ALL_LIM = verbose,
        OUT_V_LIM = verbose,
        OUT_LINE_LIM = verbose,
        OUT_PG_LIM = verbose,
        OUT_QG_LIM = verbose,
        PDIPM_MAX_IT = opts["maximum_iterations_opf"],
        PDIPM_FEASTOL = opts["opf_feasibility_tolerance"],
        PDIPM_GRADTOL = opts["opf_gradient_tolerance"],
        PDIPM_COMPTOL = opts["opf_condition_tolerance"],
        PDIPM_COSTTOL = opts["opf_cost_tolerance"],
        )
    for key in options:
        if key in pf_case:
            options[key] = pf_case[key]
    return options

def solver(pf_case:dict) -> dict|bool|None:
    """Run the PYPOWER solver on case data (see the module documentation)"""
    with _capture():
        return _solve(pf_case)

def _solve(pf_case:dict) -> dict|bool|None:
    # pylint: disable=too-many-branches,too-many-statements,too-many-locals
    opts = _options(pf_case)
    debug, verbose, save_format = opts["debug"], opts["verbose"], opts["save_format"]
    modelname = opts["modelname"]
    try:
        if debug:
            for key in OPTIONS:
                if key in pf_case:
                    print("option", key, '=', pf_case[key], file=sys.stderr)
        options = _ppoption(opts, pf_case)
        if debug:
            print("ppoptions = {", file=sys.stderr)
            for x, y in options.items():
                print(f"             '{x}' = {repr(y)},", file=sys.stderr)
            print("            }", file=sys.stderr)

        casedata = {"version": str(pf_case['version']), "baseMVA": pf_case['baseMVA']}
        for name in ['bus', 'branch', 'dcline']:
            if name in pf_case:
                casedata[name] = array(pf_case[name])
        if debug and verbose:
            sys.stderr.write(_debug_tables(casedata, None, "bus"))

        genmap = []
        if 'gen' in pf_case:
            genmap = [n for n, x in enumerate(pf_case['gen']) if x[7] == 1]
            casedata['gen'] = array([pf_case['gen'][n] for n in genmap])
        if debug and verbose:
            sys.stderr.write(_debug_tables(casedata, genmap, "gen"))

        if 'gencost' in pf_case and 'gen' in pf_case:
            costdata = []
            for cost in [x for n, x in enumerate(pf_case['gencost']) if pf_case['gen'][n][7] == 1]:
                costs = [float(x) for x in cost[3].split(',')]
                costdata.append([int(cost[0]), cost[1], cost[2], len(costs)])
                costdata[-1].extend(costs)
            casedata['gencost'] = array(costdata)
            if debug and verbose:
                print("")
                sys.stderr.write(_debug_tables(casedata, genmap, "gencost"))

        if debug and verbose and 'dcline' in casedata:
            print("")
            sys.stderr.write(_debug_tables(casedata, genmap, "dcline"))

        if opts["save_case"]:
            write_case(casedata, f"{modelname}_casedata.{save_format}", False)

        if len([x[0] for x in casedata['bus'] if x[1] in [2, 3]]) == 0:
            raise PypowerError("no REF or PV bus found")

        if 'gencost' in casedata:
            if len(casedata['gencost']) > 0:
                results = runopf(casedata, options)
                success = results['success']
            else:
                raise PypowerError("cannot solve OPF without gencost data")
        else:
            results, success = runpf(casedata, options)

        if opts["save_case"]:
            write_case(results, f"{modelname}_results.{save_format}", False)
            with open(f"{modelname}_results_solver.json", "w", encoding="utf-8") as fh:
                json.dump(jsonify(results, modelname), fh, indent=2)

        if not success:
            write_case(results, f"{modelname}_failed.{save_format}")
            if opts["stop_on_failure"]:
                return False

        for name in ['bus', 'branch']:
            pf_case[name] = results[name].tolist()
        for n, m in enumerate(genmap):
            pf_case['gen'][m] = results['gen'][n].tolist()
        return pf_case

    except Exception: # pylint: disable=broad-exception-caught
        e_type, e_value, e_trace = sys.exc_info()
        try:
            write_case(casedata, f"{modelname}_exception.{save_format}", False) # pylint: disable=used-before-assignment
        except Exception: # pylint: disable=broad-exception-caught
            e_type, e_value, e_trace = sys.exc_info()
            _exception_line(e_type, e_value, e_trace, debug)
            return None
        _exception_line(e_type, e_value, e_trace, debug)
        return False

def _exception_line(e_type:Any, e_value:Any, e_trace:Any, debug:bool) -> None:
    """The exception line gridlabd's solver writes, with the traceback when
    `debug` is true"""
    print(f"EXCEPTION [{os.path.basename(e_trace.tb_frame.f_code.co_filename)}@{e_trace.tb_lineno}]: {e_type.__name__} - {e_value}", file=sys.stderr, flush=True)
    if debug:
        import traceback # pylint: disable=import-outside-toplevel
        traceback.print_exception(e_type, e_value, e_trace, file=sys.stderr)
