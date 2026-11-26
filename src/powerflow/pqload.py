# pylint: disable=line-too-long
"""Class `pqload`: a load whose ZIP components follow the weather

Syntax
------

    object pqload {
        phases {A,B,C}[D|N];
        nominal_voltage <real> V;
        weather <climate object>;
        Zp <real> ohm;          // constant terms, and the _T, _H, _S, _W, _R
        Zq <real> F;            //   sensitivities, of the impedance (real and
        Im <real> A;            //   imaginary parts), the current (magnitude
        Ia <real> deg;          //   and angle), and the power (real and
        Pp <real> W;            //   reactive)
        Pq <real> VAr;
        // and the other properties of load
    }

Description
-----------

A `pqload` is a `load` (gridlabd `PT_INHERIT "load"`) whose loads are
computed before each solution, as gridlabd's `pqload::sync()` does: the
inputs are the weather object's `temperature`, `humidity`, `solar_flux`,
`wind_speed`, and `rainfall` (0 without a weather object) and 1 for the
constant terms; each output is the sum of its sensitivities times the
inputs. Then on every phase:

- `constant_power_X = Pp + j Pq`;
- `constant_current_X` has magnitude `Im` and angle `Ia` (degrees) from
  the phase's voltage;
- `constant_impedance_X = Zp + j Zq` when it is not 0 (the impedance is
  kept otherwise).

The inputs and outputs are published (`input_temp` ... `input_rain`,
`output_imped_p` ... `output_power_q`, `output_impedance`,
`output_current`, `output_power`).

When it initializes, a pqload is expected to warn when the model has no
`climate` object (or more than one); with a `weather` object it uses the
first climate object instead (gridlabd's assignment), with an error for
each of `temperature`, `humidity`, `solar_flux`, `wind_speed`, and
`rainfall` it lacks; then initialize as a `load`.

Caveats
-------

- gridlabd's `schedule` of `pqload` is not published and not used.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The constant current turns with the voltage once: the network applies
   the voltage angle to the current referred to the nominal angle;
   gridlabd adds the voltage angle to `constant_current_X`, which its NR
   solver rotates again with the voltage. `constant_current_X` is
   published as gridlabd computes it.
2. A missing weather property fails the initialization (except
   `rainfall`, as in gridlabd); gridlabd writes the error and returns 0
   from `init()`.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/pqload.cpp`, `pqload.h`
"""

import cmath
import math
from typing import Any

from ._base import prop
from ._common import msg, ref, objects_of, object_state, get_double, get_complex, set_complex, set_double, PowerflowError
from .load import Load
from .zipload import TRL_PROTOTYPE

WEATHER = (("temperature", "input_temp"), ("humidity", "input_humid"), ("solar_flux", "input_solar"),
    ("wind_speed", "input_wind"), ("rainfall", "input_rain"))
"""Weather properties and the inputs they set"""

GROUPS = (("Zp", ("ohm/degF", "ohm/%", "ohm*h/Btu", "ohm/mph", "ohm*h/in", "ohm")),
    ("Zq", ("F/degF", "F/%", "F*h/Btu", "F/mph", "F*h/in", "F")),
    ("Im", ("A/degF", "A/%", "A*h/Btu", "A/mph", "A*h/in", "A")),
    ("Ia", ("deg/degF", "deg/%", "deg*h/Btu", "deg/mph", "deg*h/in", "deg")),
    ("Pp", ("W/degF", "W/%", "W*h/Btu", "W/mph", "W*h/in", "W")),
    ("Pq", ("VAr/degF", "VAr/%", "VAr*h/Btu", "VAr/mph", "VAr*h/in", "VAr")))
"""Sensitivity groups and the units gridlabd publishes for `_T`, `_H`,
`_S`, `_W`, `_R`, and the constant term"""

SUFFIXES = ("_T", "_H", "_S", "_W", "_R", "")

OUTPUTS = (("output_imped_p", "Ohm"), ("output_imped_q", "Ohm"), ("output_current_m", "A"),
    ("output_current_a", "deg"), ("output_power_p", "W"), ("output_power_q", "VAr"))

class PQLoad(Load):
    """Behavior of class `pqload`"""

    NAME = "pqload"
    PARENT = "load"
    TRL = TRL_PROTOTYPE
    PROPERTIES = (
        ("weather", "object", prop()),
        ("T_nominal[degF]", "double", prop(default="-459.67 degF")),
        *((f"{group}{suffix}[{unit}]", "double", prop()) for group, units in GROUPS for suffix, unit in zip(SUFFIXES, units)),
        *((f"{name}[{unit}]", "double", prop(access="REFERENCE")) for name, unit in (("input_temp", "degF"), ("input_humid", "%"),
            ("input_solar", "Btu/h"), ("input_wind", "mph"), ("input_rain", "in/h"))),
        *((f"{name}[{unit}]", "double", prop(access="REFERENCE")) for name, unit in OUTPUTS),
        ("output_impedance[ohm]", "complex", prop(access="REFERENCE")),
        ("output_current[A]", "complex", prop(access="REFERENCE")),
        ("output_power[VA]", "complex", prop(access="REFERENCE")),
    )

    @classmethod
    def init_node(cls, model:Any, name:str) -> None:
        """`pqload::init()`"""
        out = msg(model, name)
        climates = objects_of(model, "climate")
        if not climates:
            out.warning("pqload: no climate data found")
        elif len(climates) > 1:
            out.warning(f"pqload: {len(climates)} climates found, using first one defined")
        weather = ref(model, name, "weather")
        if weather is not None and climates:
            weather = climates[0]
            model.objects[name]["weather"] = weather
        names = []
        if weather is not None:
            missing = 0
            for prop_, _ in WEATHER:
                if model.objects[weather].oclass.find_property(prop_):
                    names.append(prop_)
                else:
                    out.error(f"Unable to find {prop_} property in weather object!")
                    missing += prop_ != "rainfall"
            if missing:
                raise PowerflowError("pqload weather object is missing properties")
        object_state(model, name).update(pq_weather=weather, pq_names=names)
        super().init_node(model, name)

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        """`pqload::sync()`, then the load's values"""
        # pylint: disable=too-many-locals
        state = object_state(model, name)
        if "pq_names" in state:
            weather, names = state["pq_weather"], state["pq_names"]
            inputs = []
            for prop_, input_ in WEATHER:
                value = get_double(model, weather, prop_) if weather is not None and prop_ in names else 0.0
                set_double(model, name, input_, value)
                inputs.append(value)
            inputs.append(1.0)
            outputs = [sum(get_double(model, name, f"{group}{suffix}")*value for suffix, value in zip(SUFFIXES, inputs)) for group, _ in GROUPS]
            for (prop_, _), value in zip(OUTPUTS, outputs):
                set_double(model, name, prop_, value)
            impedance = complex(outputs[0], outputs[1])
            current = cmath.rect(outputs[2], math.radians(outputs[3]))
            power = complex(outputs[4], outputs[5])
            set_complex(model, name, "output_impedance", impedance)
            set_complex(model, name, "output_current", current)
            set_complex(model, name, "output_power", power)
            for k, x in enumerate("ABC"):
                set_complex(model, name, f"constant_power_{x}", power)
                angle = cmath.phase(get_complex(model, name, f"voltage_{x}"))
                set_complex(model, name, f"constant_current_{x}", cmath.rect(outputs[2], math.radians(outputs[3]) + angle))
                state.setdefault("pq_angle", [0.0]*3)[k] = angle
                if impedance != 0:
                    set_complex(model, name, f"constant_impedance_{x}", impedance)
        super().before_solve(model, name, t0)

    @classmethod
    def load_terms(cls, model:Any, name:str) -> dict[tuple[str,str],complex]:
        """The load's terms, with the constant currents referred to their
        phases' nominal angles"""
        terms = super().load_terms(model, name)
        angles = object_state(model, name).get("pq_angle")
        if angles:
            for k, x in enumerate("ABC"):
                if ("current", x) in terms:
                    terms[("current", x)] *= cmath.exp(1j*((0.0, -2*math.pi/3, 2*math.pi/3)[k] - angles[k]))
        return terms

__all__ = ["PQLoad"]
