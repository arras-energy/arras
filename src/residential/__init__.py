# pylint: disable=line-too-long
"""Arras Energy `residential` module

The `residential` package implements the gridlabd `residential` module in
Python. Its objects describe homes and the loads in them: a `house` models
the indoor temperatures of a home with the equivalent thermal parameter
(ETP) model, its heating, cooling, and ventilation system and thermostat,
and a panel whose circuits supply the HVAC system and the enduse loads
attached to the house; the house posts the panel's load to its parent
`triplex_meter`, so that the `powerflow` module solves the network with
it, and takes its circuit voltages from the meter. During an
`arras.runner.Runner` simulation, users run the houses with the weather
of a `climate` object.

This first version implements `residential_enduse` (the base of the
enduse loads), `house`, and `ZIPload`. The other enduse classes
(`waterheater`, `lights`, `plugload`, ...) and the implicit enduses are to
be added as behavior classes that derive from
`residential.residential_enduse.ResidentialEnduse`.

Syntax
------

    module residential {
        implicit_enduses NONE;
        default_outdoor_temperature <real> degF;
        default_humidity <real> %;
        system_dwell_time <real> s;
        ANSI_voltage_check {TRUE,FALSE};
        message_flags {QUIET,WARNING,DEBUG,VERBOSE}[|...];
        ...
    }

Classes
-------

| Class | Python class | Does |
| ----- | ------------ | ---- |
| `residential_enduse` | `residential.residential_enduse.ResidentialEnduse` | base of the enduse loads: the enduse load attached to a house panel circuit |
| `house` | `residential.house.House` | home with ETP thermal model, HVAC system, thermostat, and panel |
| `ZIPload` | `residential.zipload.ZIPload` | enduse with constant power, current, and impedance parts, duty cycle and demand response modes |

Globals
-------

- `residential::implicit_enduses`: the implicit enduses of every house;
  only `NONE` is accepted (the default, `TYPICAL`, makes houses fail to
  initialize, because implicit enduses need loadshapes and schedules,
  which `arras` does not model).
- `residential::default_outdoor_temperature` (74 degF),
  `default_humidity` (75), and `default_solar` (0 Btu/sf): the weather of
  houses when the model has no `climate` object.
- `residential::system_dwell_time` (1 s): houses round their next
  thermal event up to a multiple of it.
- `residential::ANSI_voltage_check` (true): warn when a circuit voltage
  is outside 88% to 106% of nominal.
- `residential::default_etp_iterations` (100): iterations of the solver
  for the time of the next thermal event.
- `residential::sump_humidity_factor`, `sump_rainfall_factor`,
  `sump_snowmelt_factor`: rates at which a sump pit fills.
- `residential::curtailment_enduses` and `curtailment_active`: enduses
  turned off while curtailment is active.
- `residential::house_high_temperature_warning` (95 degF): the event
  temperature of a house without cooling whose air temperature rises.
- `residential::message_flags`, which is ORed into the flags of every
  object when its messages are written.
- The other globals of gridlabd's module, which are created so that
  models that set them load; they are not used yet.

Description
-----------

Users load the module from GLM (`module residential;`) or with
`arras.model.Model.load_module("residential")`. The package is an
`arras.modules` entry point, so when a model loads the module, `load()` is
expected to:

1. load the module in `arras.module.Module.registry`, and add one enduse
   internal item (`arras.module.Module.add_internal("enduse", ...)`) that
   accumulates the energy and heat gain of every residential enduse at
   each time, before the object passes, as gridlabd's `enduse_syncall()`
   does;
2. register the classes for module `residential` in
   `arras.oclass.Class.registry` (unless they are registered already), in
   gridlabd's registration order, `house` and `ZIPload` inheriting from
   `residential_enduse`, with the properties, types, units, keywords,
   defaults, flags, descriptions, pass configurations, and technology
   readiness levels that gridlabd publishes; and
3. create the globals in the model.

Error messages are written as gridlabd's `gl_error()` writes them, and make
the run end with exit code `RUNERR`.

Examples
--------

A house with a ZIP load on a swing triplex meter, for one day without
weather data (74 degF outdoors); the panel supplies the ZIP load and the
HVAC system:

    >>> from arras import Model, Runner, Class
    >>> import residential
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm('''
    ... clock { timezone "UTC"; starttime "2020-01-01 00:00:00 UTC"; stoptime "2020-01-02 00:00:00 UTC"; }
    ... module powerflow;
    ... module residential { implicit_enduses NONE; }
    ... object triplex_meter { name m1; phases AS; nominal_voltage 120; bustype SWING;
    ...     object house { name h1; air_temperature 70; mass_temperature 70;
    ...         object ZIPload { base_power 1.0; power_fraction 1; current_fraction 0; impedance_fraction 0; heat_fraction 0.5; };
    ...     };
    ... }
    ... ''')
    >>> [oclass.name for oclass in residential.classes()]
    ['residential_enduse', 'house', 'ZIPload']
    >>> Runner(model=m).returncode
    0
    >>> m.get_property("h1", "system_mode") in ("OFF", "COOL")
    True
    >>> residential.get_complex(m, "h1", "panel.power").real >= 1.0
    True
    >>> Class.reset()

Caveats
-------

- The objects get their behavior from class event handlers and the
  module's internal item, so they work only in `arras.runner.Runner`
  simulations; calling the handlers outside a run raises
  `ResidentialError`.
- Only `residential_enduse`, `house`, and `ZIPload` are implemented. The
  other classes of gridlabd's module (`appliance`, `waterheater`,
  `lights`, `refrigerator`, `clotheswasher`, `dishwasher`,
  `occupantload`, `plugload`, `microwave`, `range`, `freezer`, `dryer`,
  `evcharger`, `thermal_storage`, `evcharger_det`, `rbsa`), implicit
  enduses, loadshapes, the panel dump, the smart breaker method, and
  deltamode are not implemented.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. Only the implemented classes are registered, so `house` and `ZIPload`
   come second and third (gridlabd registers `appliance` second, `house`
   third, and `ZIPload` sixteenth).
2. `residential::default_line_voltage` and `default_line_current` are
   `char256` globals holding the first element of gridlabd's three
   `complex` values as text, and `default_solar` is a `double` holding the
   first of gridlabd's nine values (the horizontal surface), because
   `arras.globals` has no array or `complex` globals.
3. `residential::thermostat_control_warning` and `paneldump_resolution`
   are published by gridlabd as `double` at the addresses of a `bool` and
   an `int64` (`warn_control`, `paneldump_interval`); `arras` publishes
   them as their own `double` values (1 and 0). Neither is used.
4. See each class's module for the differences that remain.

References
----------

- `arras-energy/gridlabd`: `module/residential/` (`init.cpp`,
  `residential.h`, `residential_enduse.cpp`, `house_e.cpp`,
  `zipload.cpp`), `source/enduse.cpp`
- [Residential module](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Residential.md)
  (`docs/Module/Residential.md`)
"""

from typing import Any

from arras.module import Module
from arras.oclass import Class

from ._common import (MODULE, MESSAGE_FLAGS, BEHAVIORS, TS_NEVER, ResidentialError, runner, behavior, isa,
    get_complex, get_double, get_int)
from .residential_enduse import ResidentialEnduse
from .house import House
from .zipload import ZIPload

CLASSES = (ResidentialEnduse, House, ZIPload)
"""Behavior of each class of the module, in gridlabd's registration order"""

for _cls in CLASSES:
    BEHAVIORS[_cls.NAME] = _cls

def _rev(*items:tuple[str,int]) -> dict[str,int]:
    return dict(reversed(items))

GLOBALS: tuple[tuple[str,Any,str,dict[str,Any]],...] = (
    ("message_flags", None, "set", {"keywords": MESSAGE_FLAGS, "description": "module message control flags"}),
    ("default_line_voltage", "+240+0j V", "char256", {"description": "line voltage to use when no circuit is attached"}),
    ("default_line_current", "+0+0j A", "char256", {"description": "line current calculated when no circuit is attached"}),
    ("default_outdoor_temperature", 74.0, "double", {"unit": "degF", "description": "outdoor air temperature when no climate data is found"}),
    ("default_humidity", 75.0, "double", {"unit": "%", "description": "humidity when no climate data is found"}),
    ("default_solar", 0.0, "double", {"unit": "Btu/sf", "description": "solar gains when no climate data is found"}),
    ("default_etp_iterations", 100, "int64", {"description": "number of iterations ETP solver will run"}),
    ("ANSI_voltage_check", True, "bool", {"description": "enable or disable messages about ANSI voltage limit violations in the house"}),
    ("enable_subsecond_models", False, "bool", {"description": "Enable deltamode capabilities within the residential module"}),
    ("deltamode_timestep", 10000000.0, "double", {"unit": "ns", "description": "Desired minimum timestep for deltamode-related simulations"}),
    ("all_house_delta", False, "bool", {"description": "Modeling convenient - enables all houses in deltamode"}),
    # house
    ("implicit_enduses", "TYPICAL", "set", {"keywords": _rev(("ALL", 0x071f0307), ("TYPICAL", 0x03170303), ("LIGHTS", 0x00000001), ("PLUGS", 0x00000002),
        ("OCCUPANCY", 0x00000004), ("DISHWASHER", 0x00000100), ("MICROWAVE", 0x00000200), ("FREEZER", 0x00010000), ("REFRIGERATOR", 0x00020000),
        ("RANGE", 0x00040000), ("EVCHARGER", 0x00080000), ("WATERHEATER", 0x00100000), ("CLOTHESWASHER", 0x01000000), ("DRYER", 0x02000000),
        ("SUMP", 0x04000000), ("NONE", 0))}),
    ("implicit_enduse_source", "ELCAP2010", "enumeration", {"keywords": _rev(("ELCAP1990", 0), ("ELCAP2010", 1), ("RBSA2014", 2), ("RBSA2014_DISCRETE", 3), ("EIA2015", 4))}),
    ("house_low_temperature_warning", 55.0, "double", {"unit": "degF", "description": "the low house indoor temperature at which a warning will be generated"}),
    ("house_high_temperature_warning", 95.0, "double", {"unit": "degF", "description": "the high house indoor temperature at which a warning will be generated"}),
    ("thermostat_control_warning", 1.0, "double", {"description": "boolean to indicate whether a warning is generated when indoor temperature is out of control limits"}),
    ("system_dwell_time", 1.0, "double", {"unit": "s", "description": "the heating/cooling system dwell time interval for changing system state"}),
    ("aux_cutin_temperature", 10.0, "double", {"unit": "degF", "description": "the outdoor air temperature below which AUX heating is used"}),
    ("paneldump_filename", "paneldump.csv", "char1024", {"description": "the name of the file into which the paneldump is saved"}),
    ("paneldump_interval", 0, "int64", {"description": "the interval at which the paneldump is performed (0:disabled; <0:difference; >0:integral)"}),
    ("paneldump_resolution", 0.0, "double", {"description": "the resolution at which the paneldump is performed (differences less than this are ignored)"}),
    ("sump_humidity_factor", 0.01, "double", {"unit": "pu/%/h", "description": "the rate at which the sump level rises as a function of relative humidity"}),
    ("sump_rainfall_factor", 1.0, "double", {"unit": "pu/in/day", "description": "the rate at which the sump level rises as a function of rainfall"}),
    ("sump_snowmelt_factor", 0.1, "double", {"unit": "pu/in/day", "description": "the rate at which the sump level rises as a function of snowmelt"}),
    ("curtailment_enduses", "DISHWASHER|MICROWAVE|RANGE|EVCHARGER|CLOTHESWASHER|DRYER", "char1024", {"description": "list of implicit enduses that are active in houses"}),
    ("curtailment_active", False, "bool", {"description": "flag to indicate that enduse curtailment is active"}),
)
"""Module globals `residential::NAME` in gridlabd's creation order (module
`init()`, then the class constructors): name, default, type, and
`Globals.create()` options"""

__all__ = ["ResidentialError", "ResidentialEnduse", "House", "ZIPload", "load", "classes",
    "init", "presync", "sync", "postsync", "enduse_syncall", "get_complex", "get_double", "get_int",
    "residential_enduse", "house", "zipload"]

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
    if not any(item[0] is enduse_syncall for item in Module.internals["enduse"]):
        Module.add_internal("enduse", enduse_syncall)
    for cls in CLASSES:
        if Class.find(cls.NAME, module=MODULE) is None:
            cls.register(module)
    globs = model.globals
    for name, value, ptype, options in GLOBALS:
        gname = f"{MODULE}::{name}"
        if not globs.isdefined(gname):
            globs.create(gname, value, ptype=ptype, **options)

def classes() -> list[Class]:
    """Classes registered for the module, in registration order"""
    return [oclass for oclass in Class.registry if oclass.module == MODULE]

def enduse_syncall(t1:int) -> int:
    """The enduse internal item: for every residential enduse of the
    running model (the `load` of each `residential_enduse` and the
    `panel` of each `house`), gridlabd's `enduse_sync(PC_PRETOPDOWN)`:
    `energy` accumulates `power`, `cumulative_heatgain` accumulates
    `heatgain` over the time since the last call, and `heatgain` is cleared
    when the time advanced; returns `TS_NEVER`"""
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    current = Runner.current()
    if current is None:
        return TS_NEVER
    model = current.model
    for name in list(model.objects):
        if not isa(model, name, "residential_enduse"):
            continue
        cls = behavior(model, name)
        m = cls.members(model, name)
        m.read()
        enduses = [m.load] + ([m.total] if isa(model, name, "house") else [])
        for e in enduses:
            if e.t_last > 0:
                dt = (t1 - e.t_last)/3600
                e.energy += e.total*dt
                e.cumulative_heatgain += e.heatgain*dt
                if dt > 0.0:
                    e.heatgain = 0.0
            e.t_last = t1
        m.write()
    return TS_NEVER

def _call(event:str, name:str, t:int) -> Any:
    model = runner().model
    return getattr(behavior(model, name), event)(model, name, t)

def init(name:str, t:int) -> bool|int:
    """`on_init` event handler

    Exceptions
    ----------
    - `ResidentialError`: no simulation is running, or the object is not a
      residential object
    """
    return _call("init", name, t)

def presync(name:str, t:int) -> int:
    """`on_presync` event handler (`house`)"""
    return _call("presync", name, t)

def sync(name:str, t:int) -> int:
    """`on_sync` event handler"""
    return _call("sync", name, t)

def postsync(name:str, t:int) -> int:
    """`on_postsync` event handler (`house`)"""
    return _call("postsync", name, t)
