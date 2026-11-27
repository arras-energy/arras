# pylint: disable=line-too-long
"""Class `ductbank`: cable temperature in an underground duct bank

Syntax
------

    module powerflow {
        ground_temperature <real> degC;             // default 25
        warning_cable_temperature <real> degC;      // default 80
        alert_cable_temperature <real> degC;        // default 90
        ductbank_configuration_file "<file>";       // default ductbank_configurations.csv
        air_effective_conductivity <real> W/K*m;    // default 0.2
    }
    object ductbank {
        configuration "<name>";
        temperature_source "<object>.<property>";   // or a global
        surface_temperature <real> degC;
        channels <integer>;
        fill_R <real> K/W;              // also duct_R, air_R, insulation_R
        duct_area <real> m^2;
    }
    object underground_line {
        ...
        ductbank <ductbank>;
    }

Outputs: `heatgain` (W/m), `cable_temperature`, `peak_temperature`
(degC), and `cable_status` (`OK`, `WARNING`, `ALERT`, `UNKNOWN`).

Description
-----------

A `ductbank` models the temperature of the cables of the underground
lines whose `ductbank` property names it, as gridlabd's `ductbank` does:

- when it initializes, its `duct_area`, `fill_R`, `duct_R`, and
  `channels` that are 0 take the values of its `configuration` from
  `powerflow::ductbank_configuration_file` (columns `name`, `duct_area`,
  `fill_R`, `duct_R`, `channels`; a later row of a name overrides an
  earlier one), found in the search path or else among the package's
  data files; `surface_temperature`, `cable_temperature`, and
  `peak_temperature` start at `powerflow::ground_temperature` when the
  surface temperature is not set;
- at the first time step (`precommit`), each conductor (`A`, `B`, `C`,
  `N`) of each of its lines' configurations is a cable: its area (from
  `outer_diameter`) is added to the cables' area and its `insulation_R`
  is added in parallel to `insulation_R`; then the air area is `duct_area`
  less the cables' area, and `air_R` gets in parallel the air gap's
  resistance `d / air_effective_conductivity`, with `d = sqrt(air area /
  channels) / 2`;
- when each time step is committed, `surface_temperature` is read from
  `temperature_source` (in degC) when it is set, `heatgain` is the sum of
  its lines' `power_losses` magnitudes per meter of their length, and
  `cable_temperature = surface_temperature + heatgain / (fill_R + duct_R +
  air_R + insulation_R)` (`cable_status` `UNKNOWN` when that sum is not
  positive); `peak_temperature` is the largest cable temperature, and
  above `alert_cable_temperature` (or `warning_cable_temperature`) the
  status is `ALERT` (or `WARNING`), with a warning.

When it initializes, a duct bank fails when its configuration is not in
the file, when the file is missing or has an invalid header or row, when
`duct_area`, `fill_R`, `duct_R`, or `channels` is not positive, and when
its temperature source is not an object property or a global. The first
time step fails when the cables do not fit in the duct.

Caveats
-------

- The cable temperature divides the heat gain by the total thermal
  resistance, as gridlabd computes it, although a temperature rise is the
  heat gain times the resistance; gridlabd's configuration data and its
  autotests are calibrated to this formula, so it is kept.
- The heat gain is the magnitude of the lines' complex power losses, so it
  includes their reactive losses, as in gridlabd.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The heat gain is computed from the lines' losses when the duct bank
   commits; gridlabd clears it in `precommit()` and each line adds its
   losses in its own `commit()`, so the duct bank's temperature uses the
   lines that happen to commit before it.
2. A duct bank without a `configuration` uses its own values, as the
   documentation says; gridlabd looks up the empty name and crashes when
   it is not found (as it does for any name not found).
3. A configuration not found, a missing or invalid file, a value that is
   not positive, and an invalid temperature source fail the
   initialization; gridlabd writes the error and goes on.
4. Cables that do not fit fail the first time step; gridlabd writes the
   error at every time step and keeps the air gap's resistance.
5. Configuration rows that are blank or start with `#` are skipped.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/ductbank.cpp`, `ductbank.h`,
  `underground_line.cpp`, `docs/Module/Powerflow/Ductbank.md`,
  `module/powerflow/data/ductbank_configurations.csv`,
  `module/powerflow/autotest/test_ductbank.glm`
"""

import math
from typing import Any

from ._base import PowerflowClass, prop, keywords
from ._common import TS_NEVER, TS_INVALID, TRL_PROVEN, g, ref, msg, isa, object_state, get_int, get_double, get_complex, set_double, set_int, gl_error, PowerflowError
from .scheduled_load import find_data_file, source_property, source_value

CS_OK, CS_WARNING, CS_ALERT, CS_UNKNOWN = range(4)
"""`cable_status` values"""

HEADER = "name,duct_area,fill_R,duct_R,channels"

_CACHE: dict[str,dict[str,tuple[float,float,float,int]]] = {}

def read_configurations(path:str) -> dict[str,tuple[float,float,float,int]]:
    """The configurations `(duct_area, fill_R, duct_R, channels)` by name;
    raises `PowerflowError`"""
    if path not in _CACHE:
        with open(path, encoding="utf-8") as file:
            lines = file.read().splitlines()
        if not lines or lines[0].strip() != HEADER:
            raise PowerflowError(f"invalid header in ductbank configuration file '{path}' ({lines[0] if lines else ''})")
        result = {}
        for number, line in enumerate(lines[1:], 2):
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.split(",")
            try:
                result[fields[0]] = (float(fields[1]), float(fields[2]), float(fields[3]), int(fields[4]))
            except (ValueError, IndexError) as err:
                raise PowerflowError(f"{path}@{number}: invalid data ('{fields[0]}...')") from err
        _CACHE[path] = result
    return _CACHE[path]

def lines_of(model:Any, name:str) -> list[str]:
    """The underground lines in a duct bank"""
    return [x for x in model.objects if isa(model, x, "underground_line") and ref(model, x, "ductbank") == name]

class Ductbank(PowerflowClass):
    """Behavior of class `ductbank`"""

    NAME = "ductbank"
    TRL = TRL_PROVEN
    PASSCONFIG = "AUTOLOCK|OBSERVER"
    EVENTS = ("init", "precommit", "commit")
    PROPERTIES = (
        ("configuration", "char1024", prop("ductbank configuration name")),
        ("temperature_source", "char256", prop("source for surface temperature")),
        ("surface_temperature[degC]", "double", prop("ground temperature at the surface of fill")),
        ("channels", "int32", prop("number of channels in duct")),
        ("fill_R[K/W]", "double", prop("fill soil thermal resistance")),
        ("duct_R[K/W]", "double", prop("duct thermal resistance")),
        ("air_R[K/W]", "double", prop("air gap thermal resistance")),
        ("insulation_R[K/W]", "double", prop("cable insulation thermal")),
        ("duct_area[m^2]", "double", prop("cross sectional area of interior air space")),
        ("heatgain[W/m]", "double", prop("cable heat per unit length", flags="OUTPUT")),
        ("cable_temperature[degC]", "double", prop("cable temperature in duct", flags="OUTPUT")),
        ("peak_temperature[degC]", "double", prop("peak cable temperature in duct", flags="OUTPUT")),
        ("cable_status", "enumeration", prop("cable status", flags="OUTPUT", keywords=keywords(("OK", CS_OK), ("WARNING", CS_WARNING),
            ("ALERT", CS_ALERT), ("UNKNOWN", CS_UNKNOWN)))),
    )

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument,too-many-branches
        """`ductbank::create()` and `ductbank::init()`"""
        from .node import init_failed # pylint: disable=import-outside-toplevel
        try:
            if model.objects[name].get("surface_temperature") in (None, ""):
                ground = float(g(model, "ground_temperature") or 25.0)
                for prop_ in ("surface_temperature", "cable_temperature", "peak_temperature"):
                    set_double(model, name, prop_, ground)
            config = str(model.get_property(name, "configuration") or "").strip('"')
            if config:
                filename = str(g(model, "ductbank_configuration_file") or "ductbank_configurations.csv").strip('"')
                path = find_data_file(filename)
                if path is None:
                    raise PowerflowError(f"{name}: unable to open ductbank configuration file '{filename}'")
                try:
                    data = read_configurations(path)
                except PowerflowError as err:
                    raise PowerflowError(f"{name}: {err}") from err
                if config not in data:
                    raise PowerflowError(f"{name}: ductbank configuration '{config}' not found")
                for prop_, value in zip(("duct_area", "fill_R", "duct_R"), data[config]):
                    if get_double(model, name, prop_) == 0 and value > 0:
                        set_double(model, name, prop_, value)
                if get_int(model, name, "channels") == 0 and data[config][3] > 0:
                    set_int(model, name, "channels", data[config][3])
            for prop_ in ("duct_area", "fill_R", "duct_R", "channels"):
                if get_double(model, name, prop_) <= 0:
                    raise PowerflowError(f"{name}: {prop_} must be positive")
            source = None
            text = str(model.get_property(name, "temperature_source") or "").strip('"')
            if text:
                source = source_property(model, text)
                if source is None:
                    raise PowerflowError(f"{name}: temperature source '{text}' is not valid")
        except PowerflowError as err:
            init_failed(model, name, err)
            return False
        object_state(model, name).update(source=source, ready=True)
        return True

    @classmethod
    def precommit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument,too-many-locals
        """`ductbank::precommit()`: at the first time step, the cables and
        the air gap"""
        state = object_state(model, name)
        if not state.get("ready") or state.get("air"):
            return TS_NEVER
        area = 0.0
        insulation = get_double(model, name, "insulation_R")
        for line in lines_of(model, name):
            config = ref(model, line, "configuration")
            for x in "ABCN":
                conductor = ref(model, config, f"conductor_{x}") if config else None
                if conductor is None or model.objects[conductor].oclass.find_property("outer_diameter") is None:
                    continue
                diameter = get_double(model, conductor, "outer_diameter")/39.4
                area += diameter*diameter*math.pi/4
                r_value = get_double(model, conductor, "insulation_R")
                if r_value > 0:
                    insulation = 1/((1/insulation if insulation > 0 else 0) + 1/r_value)
        set_double(model, name, "insulation_R", insulation)
        duct = get_double(model, name, "duct_area")
        if area > duct:
            gl_error(f"{name}: cannot fit anymore cables (cable={area:.2g} m^2, open={0.0:.2g} m^2, total={duct:.2g})")
            return TS_INVALID
        air = duct - area
        d = math.sqrt(air/get_int(model, name, "channels"))/2
        airgap = get_double(model, name, "air_R")
        set_double(model, name, "air_R", 1/((1/airgap if airgap > 0 else 0) + float(g(model, "air_effective_conductivity") or 0.2)/d))
        state["air"] = air
        return TS_NEVER

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument,too-many-locals
        """`ductbank::commit()`, with the lines' heat gains"""
        state = object_state(model, name)
        if not state.get("ready"):
            return TS_NEVER
        heat = 0.0
        for line in lines_of(model, name):
            losses = abs(get_complex(model, line, "power_losses"))
            length = get_double(model, line, "length")*12*2.54/100
            heat += losses/length if length > 0 else losses
        set_double(model, name, "heatgain", heat)
        if state["source"] is not None:
            set_double(model, name, "surface_temperature", source_value(model, state["source"], "degC"))
        total = sum(get_double(model, name, x) for x in ("fill_R", "duct_R", "air_R", "insulation_R"))
        if total <= 0:
            set_int(model, name, "cable_status", CS_UNKNOWN)
            return TS_NEVER
        temperature = get_double(model, name, "surface_temperature") + heat/total
        set_double(model, name, "cable_temperature", temperature)
        if temperature > get_double(model, name, "peak_temperature"):
            set_double(model, name, "peak_temperature", temperature)
        out = msg(model, name)
        if temperature > float(g(model, "alert_cable_temperature") or 90.0):
            set_int(model, name, "cable_status", CS_ALERT)
            out.warning(f"cable temperature alert ({temperature:.0f} degC)")
        elif temperature > float(g(model, "warning_cable_temperature") or 80.0):
            set_int(model, name, "cable_status", CS_WARNING)
            out.warning(f"cable temperature warning ({temperature:.0f} degC)")
        else:
            set_int(model, name, "cable_status", CS_OK)
        return TS_NEVER

__all__ = ["Ductbank", "read_configurations"]
