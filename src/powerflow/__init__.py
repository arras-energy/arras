# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Arras Energy `powerflow` module

The `powerflow` package implements the gridlabd `powerflow` module in
Python. Its objects describe a three-phase distribution network: nodes
(buses with phase-to-ground and phase-to-phase loads) and links (branches
between nodes). During an `arras.runner.Runner` simulation, users solve
the unbalanced three-phase power flow of the network at each time step
with PYPOWER's Newton-Raphson, fast-decoupled, or DC solvers, which
replace gridlabd's own Newton-Raphson solver.

This first version implements the base of gridlabd's class hierarchy:
`powerflow_object`, `node`, and `link`, then `fuse` and `line`, and the
library classes (`powerflow_library` and the configuration, spacing,
conductor, `restoration`, `power_metrics`, and `pole_configuration`
classes), and the `overhead_line`, `underground_line`, and
`triplex_line` subclasses of `line`, `transformer`, `regulator`, and
`switch` with its subclasses `recloser` and `sectionalizer`, the
`capacitor`, `load`, and `meter` subclasses of `node`, and the triplex
classes (`triplex_node`, `triplex_meter`, `triplex_load`, with
`triplex_line` and the center-tapped transformer solved on split-phase
buses), the weather-driven loads `pqload`, `zipload`, and
`triplex_zipload`, the `substation` and `motor` nodes, the `vfd`
and `series_reactor` links, `volt_var_control`, `frequency_gen`,
`emissions`, `switch_coordinator`, `load_tracker`, and the `voltdump`, `currdump`, and
`billdump` writers. The other classes ( loads, meters, triplex nodes, ...) derive from these
and are to be added as behavior classes that derive from
`powerflow.node.Node`, `powerflow.link.Link`, and `powerflow.line.Line`.

Syntax
------

    module powerflow {
        solver_method {NR,FD_XB,FD_BX,DC,FBS};
        NR_iteration_limit <integer>;
        default_maximum_voltage_error <real>;
        default_resistance <real> Ohm;
        convergence_error_handling {FATAL,IGNORE,COLLAPSE};
        message_flags {QUIET,WARNING,DEBUG,VERBOSE}[|...];
        ...
    }

Classes
-------

| Class | Python class | Does |
| ----- | ------------ | ---- |
| `powerflow_object` | `powerflow.powerflow_object.PowerflowObject` | abstract base: phases, nominal voltage |
| `powerflow_library` | `powerflow.powerflow_library.PowerflowLibrary` | empty base of the library objects |
| `node` | `powerflow.node.Node` | bus with loads; voltages from the solution |
| `link` | `powerflow.link.Link` | branch between two nodes; flows from the solution |
| `capacitor` | `powerflow.capacitor.Capacitor` | node with switched shunt capacitors (manual, voltage, VAr, VAr-voltage, or current control) |
| `fuse` | `powerflow.fuse.Fuse` | link whose phases blow above a current limit and are replaced later |
| `meter` | `powerflow.meter.Meter` | node that meters the power through it: energy, demand, interval statistics, bills |
| `line` | `powerflow.line.Line` | link with the impedance and capacitance of a `line_configuration` and a length |
| `line_spacing` | `powerflow.line_spacing.LineSpacing` | distances between the wires of a line |
| `overhead_line` | `powerflow.overhead_line.OverheadLine` | line whose matrices come from overhead conductors and spacing (Carson's equations) |
| `underground_line` | `powerflow.underground_line.UndergroundLine` | line whose matrices come from concentric-neutral or tape-shielded cables and spacing |
| `overhead_line_conductor` | `powerflow.overhead_line_conductor.OverheadLineConductor` | overhead conductor data |
| `underground_line_conductor` | `powerflow.underground_line_conductor.UndergroundLineConductor` | underground cable data |
| `line_configuration` | `powerflow.line_configuration.LineConfiguration` | line impedance and capacitance matrices per mile |
| `transformer_configuration` | `powerflow.transformer_configuration.TransformerConfiguration` | transformer ratings and impedances |
| `load` | `powerflow.load.Load` | node with constant power, current, and impedance loads (or their ZIP form) |
| `regulator_configuration` | `powerflow.regulator_configuration.RegulatorConfiguration` | voltage regulator settings |
| `transformer` | `powerflow.transformer.Transformer` | link with gridlabd's NR admittance of a wye-wye, delta-delta, delta-wye, or single-phase transformer |
| `regulator` | `powerflow.regulator.Regulator` | link of a step voltage regulator, with manual, output voltage, remote node, or line drop compensation control |
| `triplex_node` | `powerflow.triplex_node.TriplexNode` | split-phase node (lines 1 and 2, grounded neutral) |
| `triplex_meter` | `powerflow.triplex_meter.TriplexMeter` | triplex node that meters the power through it |
| `triplex_line` | `powerflow.triplex_line.TriplexLine` | split-phase secondary line joining lines 1 and 2 of triplex nodes |
| `triplex_line_configuration` | `powerflow.triplex_line_configuration.TriplexLineConfiguration` | triplex line conductors or impedance matrix |
| `triplex_line_conductor` | `powerflow.triplex_line_conductor.TriplexLineConductor` | triplex conductor data |
| `emissions` | `powerflow.emissions.Emissions` | merit-order generation mix and emissions of a meter's energy |
| `load_tracker` | `powerflow.load_tracker.LoadTracker` | feedback scaling output tracking a setpoint of another object's property |
| `triplex_load` | `powerflow.triplex_load.TriplexLoad` | triplex node with constant power, current, and impedance loads (or their ZIP form) |
| `switch_coordinator` | `powerflow.switch_coordinator.SwitchCoordinator` | coordinated toggling or direct setting of armed switches |
| `switch` | `powerflow.switch.Switch` | link with a banked or individual switch on each phase |
| `substation` | `powerflow.substation.Substation` | swing node set from sequence voltages or a `pypower` load, metering the distribution load |
| `pqload` | `powerflow.pqload.PQLoad` | load whose impedance, current, and power follow the weather |
| `voltdump` | `powerflow.voltdump.VoltDump` | CSV dump of the node voltages |
| `series_reactor` | `powerflow.series_reactor.SeriesReactor` | link with an uncoupled series impedance on each phase |
| `restoration` | `powerflow.restoration.Restoration` | post-fault reconfiguration settings (initialization; the algorithm needs `fault_check`) |
| `frequency_gen` | `powerflow.frequency_gen.FrequencyGen` | system frequency answering the load at a node (inertia, damping, governor, ramp) |
| `volt_var_control` | `powerflow.volt_var_control.VoltVarControl` | integrated volt-VAr control of regulator taps and capacitor banks |
| `motor` | `powerflow.motor.Motor` | node with a single-phase or three-phase induction motor (steady-state models) |
| `billdump` | `powerflow.billdump.BillDump` | CSV dump of the meters' previous monthly bills |
| `power_metrics` | `powerflow.power_metrics.PowerMetrics` | IEEE 1366 reliability indices, computed when the reliability module calls it |
| `currdump` | `powerflow.currdump.CurrDump` | CSV dump of the link currents |
| `recloser` | `powerflow.recloser.Recloser` | switch with reclosing settings (reclosing needs `fault_check`) |
| `sectionalizer` | `powerflow.sectionalizer.Sectionalizer` | switch that opens after an upstream recloser (needs `fault_check`) |
| `triplex_zipload` | `powerflow.triplex_zipload.TriplexZipLoad` | triplex load whose ZIP form follows the weather and a schedule |
| `vfd` | `powerflow.vfd.VFD` | variable frequency drive: a voltage source at its output frequency, its output power plus losses drawn at its input |
| `pole_configuration` | `powerflow.pole_configuration.PoleConfiguration` | utility pole design data |
| `zipload` | `powerflow.zipload.ZipLoad` | load whose ZIP form follows the weather and a schedule |

Globals
-------

- `powerflow::solver_method`: `NR` (Newton-Raphson, PYPOWER `newtonpf()`,
  the default), `FD_XB`, `FD_BX` (fast-decoupled, PYPOWER `fdpf()`), `DC`
  (PYPOWER `dcpf()`); `FBS` (forward-backward sweep) is deprecated and
  solved with NR, with a warning; `GS` is an error, as in gridlabd.
- `powerflow::NR_iteration_limit`: PYPOWER iteration limit of each solver
  call (500).
- `powerflow::default_maximum_voltage_error`: the `maximum_voltage_error`
  of nodes that do not set one, per unit of their nominal voltage (1e-6);
  `powerflow::maximum_voltage_error` is the same global.
- `powerflow::default_resistance`: resistance of a base-class link on each
  phase (1e-4 Ohm).
- `powerflow::line_capacitance`: include the shunt capacitance of lines
  (false); `powerflow::nominal_frequency`: the frequency of that
  capacitance's admittance (60 Hz).
- `powerflow::convergence_error_handling`: when a solution cannot be used
  (a singular matrix, or voltages that are not finite), `FATAL` writes an
  error and fails the run, `IGNORE` warns and keeps the last voltages,
  `COLLAPSE` writes that it is not supported and then acts as `FATAL`, as
  gridlabd does.
- `powerflow::message_flags`, which is ORed into the flags of every object
  when its messages are written.
- The other globals of gridlabd's module and of the three classes, which
  are created so that models that set them load; the solver does not use
  them yet.

Description
-----------

Users load the module from GLM (`module powerflow;`) or with
`arras.model.Model.load_module("powerflow")`. The package is an
`arras.modules` entry point, so when a model loads the module, `load()` is
expected to:

1. load the module in `arras.module.Module.registry` with the solvers
   `init` and `sync`;
2. register the classes for module `powerflow` in
   `arras.oclass.Class.registry` (unless they are registered already), in
   gridlabd's registration order, `node` and `link` inheriting from
   `powerflow_object`, and `fuse` and `line` from `link`, with the properties, types, units, keywords,
   defaults, flags, descriptions, pass configurations, and technology
   readiness levels that gridlabd publishes; and
3. create the globals in the model.

During a run, the module is expected to:

1. at initialization (after the objects), warn when `solver_method` is
   `FBS`, and fail when it is `GS`;
2. at each sync (after the objects' syncs), when the model has nodes:
   build the three-phase network of the nodes and the closed links
   (`powerflow.solver`), solve it with the PYPOWER solver of
   `solver_method`, and write the node voltages and the link flows;
3. ask to iterate the time step when a node voltage changed by more than
   the node's `maximum_voltage_error`, so that objects that read voltages
   see the solution, and otherwise ask for no event;
4. when the solver reaches `NR_iteration_limit` without converging, keep
   the voltages reached and iterate the time step (the run's
   `iteration_limit` ends it), as gridlabd does; when the solution cannot
   be used, act as `convergence_error_handling` says; a bus not connected
   to a `SWING` or `SWING_PQ` node is an error.

Error messages are written as gridlabd's `gl_error()` writes them, and make
the run end with exit code `RUNERR`; a failed solution also fails the
run, as gridlabd's does.

Examples
--------

An unbalanced load on a three-phase node, fed through a link from a swing
node:

    >>> from arras import Model, Runner, Class
    >>> import powerflow
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm('''
    ... clock { starttime "2020-01-01 00:00:00 UTC"; stoptime "2020-01-01 00:00:00 UTC"; }
    ... module powerflow;
    ... object node { name n1; phases ABCN; nominal_voltage 2401.8; bustype SWING; }
    ... object link { from n1; to n2; phases ABCN; }
    ... object node { name n2; phases ABCN; nominal_voltage 2401.8; power_A 100000+50000j; power_B 50000; }
    ... ''')
    >>> [oclass.name for oclass in powerflow.classes()]
    ['powerflow_object', 'powerflow_library', 'node', 'link', 'capacitor', 'fuse', 'meter', 'line', 'line_spacing', 'overhead_line', 'underground_line', 'overhead_line_conductor', 'underground_line_conductor', 'line_configuration', 'transformer_configuration', 'transformer', 'load', 'regulator_configuration', 'regulator', 'triplex_node', 'triplex_meter', 'triplex_line', 'triplex_line_configuration', 'triplex_line_conductor', 'switch_coordinator', 'switch', 'substation', 'pqload', 'voltdump', 'series_reactor', 'restoration', 'frequency_gen', 'volt_var_control', 'motor', 'billdump', 'power_metrics', 'currdump', 'recloser', 'sectionalizer', 'emissions', 'load_tracker', 'triplex_load', 'triplex_zipload', 'vfd', 'pole_configuration', 'zipload']
    >>> Runner(model=m).returncode
    0
    >>> m.get_property("link:1", "flow_direction")
    'CN|BF|AF'
    >>> round(abs(powerflow.get_complex(m, "link:1", "power_in")))
    158114
    >>> Class.reset()

Caveats
-------

- The objects get their behavior from class event handlers and the module
  solvers, so they work only in `arras.runner.Runner` simulations; calling
  the handlers outside a run raises `PowerflowError`.
- PYPOWER is the version vendored in `pypower._pypower` (5.1.16); numpy and
  scipy are required.
- Only the classes listed above are implemented. Split-phase
  (triplex) nodes, deltamode, faults and reliability, frequency
  measurement, GFA, violation recording, the matrix dumps, and the solver
  profiler are not implemented; their globals and properties are
  published.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The power flow is solved by PYPOWER on a three-phase bus admittance
   matrix (`powerflow.solver`), not by gridlabd's `solver_nr()`.
2. `solver_method` defaults to `NR` (gridlabd: `FBS`), and `FBS` is solved
   with NR, after a warning. Links therefore do not set ranks or parents
   for `FBS`.
3. `solver_method` has the keywords `FD_XB`, `FD_BX`, and `DC`, which
   gridlabd does not have. With `DC`, link flows have no losses or
   reactive power, and voltage magnitudes stay at their initial values.
4. The module solves the network in its `sync` solver, after the objects'
   syncs; gridlabd solves it in the swing node's sync. The result is the
   same, since gridlabd's swing node has the highest rank.
5. `powerflow::fault_impedance` and `powerflow::ground_impedance` are
   `char256` globals holding the complex value as text (`+1e-06+0j Ohm`),
   because `arras.globals` has no `complex` globals; gridlabd publishes
   them as `complex` in ohms. Neither is used yet.
6. See each class's module for the differences that remain.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/` (`init.cpp`,
  `powerflow.h`, `powerflow_object.cpp`, `powerflow_library.cpp`,
  `node.cpp`, `link.cpp`, `fuse.cpp`, `line.cpp`, the library classes'
  `.cpp` files, `solver_nr.cpp`)
- [Powerflow module](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Powerflow.md)
  (`docs/Module/Powerflow.md`)
- [PYPOWER](https://github.com/rwl/PYPOWER)
"""

from typing import Any

from arras.module import Module
from arras.oclass import Class

from ._common import (MODULE, MESSAGE_FLAGS, SOLVER_METHODS, BEHAVIORS, PowerflowError, runner,
    get_complex, get_double)
from ._module import solver_init, solver_sync, behavior
from .powerflow_object import PowerflowObject
from .powerflow_library import PowerflowLibrary
from .node import Node
from .link import Link
from .capacitor import Capacitor
from .fuse import Fuse
from .meter import Meter
from .line import Line
from .line_spacing import LineSpacing
from .overhead_line import OverheadLine
from .underground_line import UndergroundLine
from .triplex_line import TriplexLine
from .transformer import Transformer
from .regulator import Regulator
from .load import Load
from .triplex_node import TriplexNode
from .triplex_meter import TriplexMeter
from .triplex_load import TriplexLoad
from .pqload import PQLoad
from .zipload import ZipLoad
from .triplex_zipload import TriplexZipLoad
from .switch import Switch
from .recloser import Recloser
from .sectionalizer import Sectionalizer
from .overhead_line_conductor import OverheadLineConductor
from .underground_line_conductor import UndergroundLineConductor
from .line_configuration import LineConfiguration
from .transformer_configuration import TransformerConfiguration
from .regulator_configuration import RegulatorConfiguration
from .triplex_line_configuration import TriplexLineConfiguration
from .triplex_line_conductor import TriplexLineConductor
from .restoration import Restoration
from .substation import Substation
from .series_reactor import SeriesReactor
from .volt_var_control import VoltVarControl
from .frequency_gen import FrequencyGen
from .emissions import Emissions
from .voltdump import VoltDump
from .currdump import CurrDump
from .billdump import BillDump
from .switch_coordinator import SwitchCoordinator
from .load_tracker import LoadTracker
from .motor import Motor
from .vfd import VFD
from .power_metrics import PowerMetrics
from .pole_configuration import PoleConfiguration, CLIMATE_IMPACT_ZONES
from . import solver

CLASSES = (PowerflowObject, PowerflowLibrary, Node, Link, Capacitor, Fuse, Meter, Line, LineSpacing, OverheadLine, UndergroundLine,
    OverheadLineConductor, UndergroundLineConductor, LineConfiguration, TransformerConfiguration,
    Transformer, Load, RegulatorConfiguration, Regulator, TriplexNode, TriplexMeter, TriplexLine, TriplexLineConfiguration, TriplexLineConductor,
    SwitchCoordinator, Switch, Substation, PQLoad, VoltDump, SeriesReactor, Restoration, FrequencyGen, VoltVarControl, Motor, BillDump, PowerMetrics, CurrDump, Recloser, Sectionalizer, Emissions, LoadTracker, TriplexLoad, TriplexZipLoad, VFD, PoleConfiguration,
    ZipLoad)
"""Behavior of each class of the module, in gridlabd's registration order"""

for _cls in CLASSES:
    BEHAVIORS[_cls.NAME] = _cls

def _rev(*items:tuple[str,int]) -> dict[str,int]:
    return dict(reversed(items))

GLOBALS: tuple[tuple[str,Any,str,dict[str,Any]],...] = (
    ("message_flags", None, "set", {"keywords": MESSAGE_FLAGS, "description": "module message control flags"}),
    ("show_matrix_values", False, "bool", {}),
    ("primary_voltage_ratio", 60.0, "double", {"unit": "pu"}),
    ("nominal_frequency", 60.0, "double", {"unit": "Hz"}),
    ("require_voltage_control", False, "bool", {}),
    ("geographic_degree", 0.0, "double", {}),
    ("fault_impedance", "+1e-06+0j Ohm", "char256", {}),
    ("ground_impedance", "+1e-06+0j Ohm", "char256", {}),
    ("warning_underfrequency", 55.0, "double", {"unit": "Hz"}),
    ("warning_overfrequency", 65.0, "double", {"unit": "Hz"}),
    ("warning_undervoltage", 0.8, "double", {"unit": "V"}),
    ("warning_overvoltage", 1.2, "double", {"unit": "V"}),
    ("warning_voltageangle", 2.0, "double", {}),
    ("maximum_voltage_error", 1e-6, "double", {"unit": "V"}),
    ("solver_method", "NR", "enumeration", {"keywords": _rev(*SOLVER_METHODS.items())}),
    ("NR_matrix_file", "", "char256", {}),
    ("NR_matrix_output_interval", "NEVER", "enumeration", {"keywords": _rev(("NEVER", 0), ("ONCE", 1), ("PER_CALL", 2), ("ALL", 3))}),
    ("NR_matrix_output_references", False, "bool", {}),
    ("NR_matrix_output_rhs", False, "bool", {"description": "Flag to indicate if the RHS (delta-current-injections) should be output to the matrix dump"}),
    ("NR_island_failure_handled", False, "bool", {"description": "Indicates if an island fails if it should be removed from service"}),
    ("line_capacitance", False, "bool", {}),
    ("line_limits", True, "bool", {}),
    ("lu_solver", "", "char256", {}),
    ("NR_iteration_limit", 500, "int64", {}),
    ("NR_deltamode_iteration_limit", 10, "int64", {}),
    ("NR_superLU_procs", 1, "int32", {}),
    ("default_maximum_voltage_error", None, "alias", {"target": "maximum_voltage_error"}),
    ("default_maximum_power_error", 0.0001, "double", {"unit": "pu"}),
    ("NR_admit_change", True, "bool", {}),
    ("enable_subsecond_models", False, "bool", {"description": "Enable deltamode capabilities within the powerflow module"}),
    ("all_powerflow_delta", False, "bool", {"description": "Forces all powerflow objects that are capable to participate in deltamode"}),
    ("deltamode_timestep", 10000000.0, "double", {"unit": "ns", "description": "Desired minimum timestep for deltamode-related simulations"}),
    ("current_frequency", 60.0, "double", {"unit": "Hz", "description": "Current system-level frequency of the powerflow system"}),
    ("master_frequency_update", False, "bool", {"description": "Tracking variable to see if an object has become the system frequency updater"}),
    ("enable_frequency_dependence", False, "bool", {"description": "Flag to enable frequency-based variations in impedance values of lines and loads"}),
    ("default_resistance", 1e-4, "double", {"unit": "Ohm"}),
    ("enable_inrush", False, "bool", {"description": "Flag to enable in-rush calculations for lines and transformers in deltamode"}),
    ("low_voltage_impedance_level", 0.7, "double", {"unit": "pu", "description": "Lower limit of voltage (in per-unit) at which all load types are converted to impedance for in-rush calculations"}),
    ("enable_mesh_fault_current", False, "bool", {"description": "Flag to enable mesh-based fault current calculations"}),
    ("convergence_error_handling", "FATAL", "enumeration", {"keywords": _rev(("FATAL", 0), ("IGNORE", 1), ("COLLAPSE", 2)), "description": "Flag to handle convergence error"}),
    ("solver_profile_enable", False, "bool", {"description": "Flag to enable NR solver profiler"}),
    ("solver_profile_filename", "solver_nr_profile.txt", "char1024", {"description": "Name of NR solver profile file"}),
    ("solver_profile_headers_included", True, "bool", {"description": "Flag to include headers in NR solver profile file"}),
    ("solver_headers", "timestamp,duration[microsec],iteration,bus_count,branch_count,error", "char1024", {"description": "Headers in NR solver profile file"}),
    ("solver_profile_csv", False, "bool", {"description": "Flag output solver profile in CSV format"}),
    ("solver_py_config", "solver_py.conf", "char1024", {"description": "PY solver configuration file location"}),
    ("solver_dump_enable", False, "bool", {"description": "flag to enable bus/branch dump when solvers fails"}),
    ("zipload_data", "ziploads.csv", "char1024", {"description": "zipload load data file pathname"}),
    ("zipload_temperature", "temperature", "char32", {"description": "zipload weather temperature property name[unit]"}),
    ("zipload_humidity", "humidity", "char32", {"description": "zipload weather humidity property name[unit]"}),
    ("zipload_solar", "solar_flux", "char32", {"description": "zipload weather solar property name[unit]"}),
    ("zipload_wind", "wind_speed", "char32", {"description": "zipload weather wind property name[unit]"}),
    ("zipload_rain", "rainfall", "char32", {"description": "zipload weather rain property name[unit]"}),
    ("maximum_voltage_deviation", 0.5, "double", {"unit": "pu.V", "description": "maximum voltage deviation per unit nominal voltage before ZIP loads are cut off"}),
    ("geocode_find", 0, "int32", {"description": "geocode find method (<0 = none, 0 = nearest, >0 = exact geocode precision)"}),
    # powerflow_object
    ("violation_record", "", "char1024", {"description": "file in which to record violations of limits and ratings"}),
    ("violation_count", 0, "int32", {"description": "count of violations recorded"}),
    ("violation_active", 0, "int32", {"description": "count of currently active violations"}),
    ("violation_watchset", "ALL", "set", {"keywords": _rev(("NONE", 0x0000), ("LOAD", 0x0001), ("NODE", 0x00ff), ("LINE", 0x0100),
        ("XFRM", 0x0200), ("VREG", 0x0400), ("LINK", 0xff00), ("ALL", 0xffff)), "description": "object sets to watch for violations"}),
    # node
    ("voltage_violation_threshold", 0.05, "double", {"unit": "pu"}),
    ("undervoltage_violation_threshold", 0.0, "double", {"unit": "pu"}),
    ("overvoltage_violation_threshold", 0.0, "double", {"unit": "pu"}),
    ("voltage_fluctuation_threshold", 0.03, "double", {"unit": "pu"}),
    ("DER_violation_test", "ANY", "enumeration", {"keywords": _rev(("ANY", 0), ("ALL", 1))}),
    # link
    ("default_continuous_rating", 1000.0, "double", {"unit": "A"}),
    ("default_emergency_rating", 2000.0, "double", {"unit": "A"}),
    ("default_violation_rating", 0.0, "double", {"unit": "A"}),
    # triplex_meter
    ("market_price_name", "current_market.clearing_price", "char1024", {}),
    # pole_configuration (keywords in gridlabd's table order)
    ("climate_impact_zone", "NONE", "enumeration", {"keywords": dict(CLIMATE_IMPACT_ZONES), "description": "pole deterioration climate impact zone"}),
)
"""Module globals `powerflow::NAME` in gridlabd's creation order (module
`init()`, then the class constructors): name, default, type, and
`Globals.create()` options; type `alias` is a second name of the global
`target`, as gridlabd publishes two names for one variable"""

__all__ = ["PowerflowError", "PowerflowObject", "PowerflowLibrary", "Node", "Link", "Fuse", "Line",
    "LineSpacing", "OverheadLine", "UndergroundLine", "TriplexLine", "Transformer", "Regulator", "Switch", "Recloser", "Sectionalizer", "Capacitor", "Load", "Meter", "TriplexNode", "TriplexMeter", "TriplexLoad", "PQLoad", "ZipLoad", "TriplexZipLoad", "OverheadLineConductor", "UndergroundLineConductor", "LineConfiguration",
    "TransformerConfiguration", "RegulatorConfiguration", "TriplexLineConfiguration", "TriplexLineConductor", "Restoration",
    "PowerMetrics", "PoleConfiguration", "Substation", "SeriesReactor", "FrequencyGen", "VoltVarControl", "Emissions", "VoltDump", "CurrDump", "BillDump", "SwitchCoordinator", "LoadTracker", "Motor", "VFD", "load", "classes", "init", "precommit", "presync", "sync", "postsync", "commit", "behavior", "solver",
    "powerflow_object", "powerflow_library", "node", "link", "fuse", "line", "line_spacing", "overhead_line", "underground_line", "triplex_line", "transformer", "regulator", "switch", "recloser", "sectionalizer", "capacitor", "meter", "triplex_node", "triplex_meter", "triplex_load", "pqload", "zipload", "triplex_zipload",
    "overhead_line_conductor", "underground_line_conductor", "line_configuration",
    "transformer_configuration", "regulator_configuration", "triplex_line_configuration", "triplex_line_conductor", "restoration",
    "power_metrics", "pole_configuration", "substation", "series_reactor", "frequency_gen", "volt_var_control", "emissions", "voltdump", "currdump", "billdump", "switch_coordinator", "load_tracker", "motor", "vfd", "get_complex", "get_double"]

def load(model:Any) -> None:
    """Load the module into a model (the `arras.modules` entry point that
    `arras.model.Model.load_module()` calls)

    Arguments
    ---------
    - `model`: `arras.model.Model` that loads the module

    Exceptions
    ----------
    - `arras.oclass.ClassError`: a class of the module cannot be registered
    """
    module = Module.load(MODULE)
    module.set_solver("init", solver_init)
    module.set_solver("sync", solver_sync)
    for cls in CLASSES:
        if Class.find(cls.NAME, module=MODULE) is None:
            cls.register(module)
    globs = model.globals
    for name, value, ptype, options in GLOBALS:
        gname = f"{MODULE}::{name}"
        if globs.isdefined(gname):
            continue
        if ptype == "alias":
            globs._alias[gname] = f"{MODULE}::{options['target']}" # pylint: disable=protected-access
        else:
            globs.create(gname, value, ptype=ptype, **options)

def classes() -> list[Class]:
    """Classes registered for the module, in registration order"""
    return [oclass for oclass in Class.registry if oclass.module == MODULE]

def _call(event:str, name:str, t:int) -> Any:
    model = runner().model
    try:
        cls = behavior(model, name)
    except solver.SolverError as err:
        raise PowerflowError(str(err)) from err
    return getattr(cls, event)(model, name, t)

def precommit(name:str, t:int) -> int:
    """`on_precommit` event handler (`switch_coordinator`)"""
    return _call("precommit", name, t)

def presync(name:str, t:int) -> int:
    """`on_presync` event handler (`volt_var_control`)"""
    return _call("presync", name, t)

def postsync(name:str, t:int) -> int:
    """`on_postsync` event handler (`volt_var_control`)"""
    return _call("postsync", name, t)

def sync(name:str, t:int) -> int:
    """`on_sync` event handler (the dump classes)"""
    return _call("sync", name, t)

def commit(name:str, t:int) -> int:
    """`on_commit` event handler (`frequency_gen`, the dump classes)"""
    return _call("commit", name, t)

def init(name:str, t:int) -> bool|int:
    """`on_init` event handler

    Exceptions
    ----------
    - `PowerflowError`: no simulation is running, or the object is not a
      powerflow object
    """
    return _call("init", name, t)
