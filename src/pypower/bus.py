# pylint: disable=line-too-long
"""Class `bus`: a PYPOWER bus

Syntax
------

    object pypower.bus {
        bus_i <integer>;
        S <complex> MVA;
        type {UNKNOWN,PQ,PV,REF,NONE,PQREF};
        Pd <real> MW;
        Qd <real> MVAr;
        Gs <real> MW;
        Bs <real> MVAr;
        area <integer>;
        baseKV <real> kV;
        Vm <real> pu.kV;
        Va <real> deg;
        zone <integer>;
        Vmax <real> pu.kV;
        Vmin <real> pu.kV;
        weather_file "<file>";
        weather_variables "<property>[,...]";
        weather_resolution <real> s;
        weather_sensitivity "<property>:<variable>[<|><value>],<slope>[;...]";
    }

The outputs `lam_P`, `lam_Q`, `mu_Vmax`, `mu_Vmin` (OPF multipliers) and
the weather values `Sn`, `Sh`, `Sg` (W/m^2), `Wd` (deg), `Ws` (m/2), `Td`,
`Tw` (degC), `RH` (%), `PW` (in), `HI` (degF) are also published.

Description
-----------

A bus is a row of PYPOWER's bus table (columns `bus_i` to `Vmin`, and
`lam_P` to `mu_Vmin` when the OPF runs). Given a model, a bus is expected
to:

1. take the next bus number (1, 2, ... in initialization order) when
   `bus_i` is 0;
2. keep its base load `S`: when `S` is 0 at initialization it is set to
   `Pd+jQd`;
3. reset `Pd` and `Qd` to `S`, and `Gs` and `Bs` to 0, in its presync, so
   that loads, powerplants, and shunts below it can add to them;
4. receive `Vm` and `Va` from each solution;
5. with a `weather_file`, read its CSV rows (`timestamp,v1,v2,...`; lines
   that do not start with a digit are skipped) whose timestamps are a
   multiple of `weather_resolution`, and at each precommit copy the values
   of the first row at or after the clock to the properties named in
   `weather_variables`, asking to run again at the time of the next row;
6. at each precommit, apply each `weather_sensitivity` term
   `PROP:VAR[<|>VALUE],SLOPE` (`PROP` is `Pd` or `S.real`, `Qd` or
   `S.imag`; `VAR` a `double` property of the bus): remove the previous
   adjustment, then add `(VAR-VALUE)*SLOPE` (`VALUE` is 0 without a test)
   when the test holds or there is none.

Initialization fails (with an error) when the weather file cannot be read,
a weather variable or sensitivity source is not a property of the bus (or
not a `double`), or a sensitivity term is not valid.

Caveats
-------

- `Ws` is published in `m/2` and described as "Wind speed (m/2)", as
  gridlabd publishes it.
- Weather values are copied as they are in the file, in the units of the
  properties they are written to.
- The `bus_i` numbers count buses in initialization order; branches find
  their buses by number, so buses given numbers should be numbered 1 to N
  in creation order, as PYPOWER cases are.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. `S` is the base load that the description of `S`, `init()`, and
   `presync()` use. gridlabd publishes `S` at the address of `Pd`, so the
   published `S` reads and writes `Pd` and `Qd` while the base load is a
   separate member; the values recorded are the same while no load,
   powerplant, or shunt is below the bus.
2. The bus voltage used for branch currents and losses takes `Va` in
   degrees; gridlabd passes the degrees to `SetPolar()` as radians.

References
----------

- `arras-energy/gridlabd`: `module/pypower/bus.cpp`, `bus.h`
"""

import re
from typing import Any

from ._base import PypowerClass, prop, keywords, msg
from ._common import (TS_NEVER, object_state, module_state, get_double, get_complex, get_int,
    get_text, set_double, set_complex, set_int, notation)
from ._module import ensure_init
from ._weather import WeatherData

_NUM = r"\s*([-+]?(?:(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|inf(?:inity)?|nan))"
_SENSITIVITY_TEST = re.compile(rf"([^:]{{1,64}}+):([^<>]{{1,64}}+)(.){_NUM},{_NUM}", re.DOTALL)
"""`sscanf(term,"%64[^:]:%64[^<>]%c%lf,%lf")` (possessive, as `sscanf()` does not backtrack)"""
_SENSITIVITY = re.compile(rf"([^:]{{1,64}}+):([^,]{{1,64}}+),{_NUM}", re.DOTALL)
"""`sscanf(term,"%64[^:]:%64[^,],%lf")`"""

class Bus(PypowerClass):
    """Behavior of class `bus`"""

    NAME = "bus"
    PASSCONFIG = "PRETOPDOWN|AUTOLOCK|OBSERVER"
    PROPERTIES = (
        ("bus_i", "int32", prop("bus number (1 to 29997)")),
        ("S[MVA]", "complex", prop("base load demand not counting child objects, including weather sensitivities, copied to Pd,Qd by default (MVA)")),
        ("type", "enumeration", prop("bus type (1 = PQ, 2 = PV, 3 = ref, 4 = isolated)",
            keywords=keywords(("UNKNOWN", 0), ("PQ", 1), ("PV", 2), ("REF", 3), ("NONE", 4), ("PQREF", 1)))),
        ("Pd[MW]", "double", prop("real power demand (MW)", "0 MW", "OUTPUT")),
        ("Qd[MVAr]", "double", prop("reactive power demand (MVAr)", "0 MVAr", "OUTPUT")),
        ("Gs[MW]", "double", prop("shunt conductance (MW at V = 1.0 per unit)", "0 MW")),
        ("Bs[MVAr]", "double", prop("shunt susceptance (MVAr at V = 1.0 per unit)", "0 MVAr")),
        ("area", "int32", prop("area number, 1-100")),
        ("baseKV[kV]", "double", prop("base voltage (kV)", flags="REQUIRED")),
        ("Vm[pu.kV]", "double", prop("voltage magnitude (per unit)", "1 pu.V")),
        ("Va[deg]", "double", prop("voltage angle (degrees)", "0 deg")),
        ("zone", "int32", prop("loss zone (1-999)")),
        ("Vmax[pu.kV]", "double", prop("maximum voltage magnitude (per unit)", "1.2 pu.kV")),
        ("Vmin[pu.kV]", "double", prop("minimum voltage magnitude (per unit)", "0.8 pu.kV")),
        ("lam_P", "double", prop("Lagrange multiplier on real power mismatch (u/MW)", flags="OUTPUT")),
        ("lam_Q", "double", prop("Lagrange multiplier on reactive power mismatch (u/MVAr)", flags="OUTPUT")),
        ("mu_Vmax", "double", prop("Kuhn-Tucker multiplier on upper voltage limit (u/per unit)", flags="OUTPUT")),
        ("mu_Vmin", "double", prop("Kuhn-Tucker multiplier on lower voltage limit (u/per unit)", flags="OUTPUT")),
        ("weather_file", "char1024", prop("Source object for weather data")),
        ("weather_variables", "char1024", prop("Weather variable column names (col1,col2,...)")),
        ("weather_resolution[s]", "double", prop("Weather time downsampling resolution (s)", "3600 s")),
        ("Sn[W/m^2]", "double", prop("Solar direct normal irradiance (W/m^2)")),
        ("Sh[W/m^2]", "double", prop("Solar horizontal irradiance (W/m^2)")),
        ("Sg[W/m^2]", "double", prop("Solar global irradiance (W/m^2)")),
        ("Wd[deg]", "double", prop("Wind direction (deg)")),
        ("Ws[m/2]", "double", prop("Wind speed (m/2)")),
        ("Td[degC]", "double", prop("Dry-bulb air temperature (degC)")),
        ("Tw[degC]", "double", prop("Wet-bulb air temperature (degC)")),
        ("RH[%]", "double", prop("Relative humidity (%)")),
        ("PW[in]", "double", prop("Precipitable_water (in)")),
        ("HI[degF]", "double", prop("Heat index (degF)")),
        ("weather_sensitivity", "char1024", prop("Weather sensitivities {PROP: VAR[ REL VAL],SLOPE[; ...]}")),
    )
    EVENTS = ("init", "precommit", "presync")

    @staticmethod
    def _new() -> dict[str,Any]:
        return {"V": complex(0, 0), "weather": WeatherData(), "sensitivities": []}

    @classmethod
    def state(cls, model:Any, name:str) -> dict[str,Any]:
        """State of a bus: `V` (complex voltage, per unit), `weather`
        (records), `sensitivities` (terms, last added first)"""
        return object_state(model, name, cls._new)

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`bus::init()`"""
        # pylint: disable=too-many-return-statements,too-many-locals,too-many-branches
        if not ensure_init(model):
            return False
        out = msg(model, name)
        state = cls.state(model, name)
        if get_int(model, name, "bus_i") == 0:
            mod = module_state(model)
            mod.last_i += 1
            set_int(model, name, "bus_i", mod.last_i)
        base = get_complex(model, name, "S")
        pd, qd = get_double(model, name, "Pd"), get_double(model, name, "Qd")
        if base.real == 0.0 and base.imag == 0.0:
            out.verbose(f"copying load ({pd:g}{qd:+g}j) to baseload S")
            set_complex(model, name, "S", complex(pd, qd), notation(model, name, "S"))
        else:
            out.verbose(f"using baseload S = {base.real:g}{base.imag:+g}j")
        file = get_text(model, name, "weather_file")
        if file:
            if not state["weather"].load(model, name, file, get_text(model, name, "weather_variables"),
                    get_double(model, name, "weather_resolution"), out):
                out.error(f"unable to load weather_file '{file}'")
                return False
        oclass = model.objects[name].oclass
        for term in [x for x in get_text(model, name, "weather_sensitivity").split(";") if x]:
            match = _SENSITIVITY_TEST.match(term)
            if match:
                propname, varname, test, cutoff, slope = match.group(1), match.group(2), match.group(3), float(match.group(4)), float(match.group(5))
            else:
                match = _SENSITIVITY.match(term)
                if not match:
                    out.error(f"weather_sensitivity '{term}' in not valid")
                    return False
                propname, varname, test, cutoff, slope = match.group(1), match.group(2), "@", 0.0, float(match.group(3))
            source = oclass.find_property(varname)
            if source is None:
                out.error(f"weather_sensitivity source '{varname}' is not valid")
                return False
            if source.ptype != "double":
                out.error(f"weather_sensitivity source '{varname}' is not a double")
                return False
            if propname in ("Pd", "S.real"):
                part = "real"
            elif propname in ("Qd", "S.imag"):
                part = "imag"
            else:
                out.error(f"property '{propname}' is not valid")
                return False
            state["sensitivities"].insert(0, {"def": term, "part": part, "source": varname,
                "slope": slope, "test": test, "cutoff": cutoff, "last": 0.0})
        return True

    @classmethod
    def precommit(cls, model:Any, name:str, t:int) -> int:
        """`bus::precommit()`: weather values and sensitivities"""
        state = cls.state(model, name)
        weather = state["weather"]
        weather.get(model, name, t, msg(model, name))
        if state["sensitivities"]:
            base = get_complex(model, name, "S")
            parts = {"real": base.real, "imag": base.imag}
            for term in state["sensitivities"]:
                parts[term["part"]] -= term["last"]
                source = get_double(model, name, term["source"])
                test, cutoff = term["test"], term["cutoff"]
                if (test == "<" and source < cutoff) or (test == ">" and source > cutoff) or test == "@":
                    term["last"] = (source - cutoff)*term["slope"]
                    parts[term["part"]] += term["last"]
                else:
                    term["last"] = 0.0
            set_complex(model, name, "S", complex(parts["real"], parts["imag"]), notation(model, name, "S"))
        return weather.next_time() if weather.records else TS_NEVER

    @classmethod
    def presync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`bus::presync()`: reset the loads to the base load"""
        base = get_complex(model, name, "S")
        set_double(model, name, "Pd", base.real)
        set_double(model, name, "Qd", base.imag)
        set_double(model, name, "Gs", 0.0)
        set_double(model, name, "Bs", 0.0)
        msg(model, name).verbose(f"resetting loads to S=({base.real:g}{base.imag:+g}j) and shunts to 0j")
        return TS_NEVER

def add_load(model:Any, name:str, p:float, q:float) -> None:
    """`bus::add_load()`"""
    msg(model, name).verbose(f"add_load(P={p:g},Q={q:g})")
    set_double(model, name, "Pd", get_double(model, name, "Pd") + p)
    set_double(model, name, "Qd", get_double(model, name, "Qd") + q)
