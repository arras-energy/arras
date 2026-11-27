# pylint: disable=line-too-long
"""Class `load_tracker`: feedback scaling of a load toward a setpoint

Syntax
------

    object load_tracker {
        target <object>;
        target_property "<property>";
        operation {REAL,IMAGINARY,MAGNITUDE,ANGLE};   // complex properties
        full_scale <real>;
        setpoint <real>;
        deadband <real>;        // percent of full scale, 1 to 50
        damping <real>;
    }

Outputs: `output`, the scaling value, and `feedback`, the value tracked.

Description
-----------

A `load_tracker` adjusts its `output` so that a property of another
object (`target_property` of `target`, a `double`, `complex`, or integer
property, of any module) tracks `setpoint`, as gridlabd's `load_tracker`
does; `output` is meant to scale the load that drives the property (for
example through a transform). The feedback is the property's value; of a
complex property its real or imaginary part, its angle, or its magnitude
(negative when the real part is negative, `MAGNITUDE`, the default).

Before each solution (`presync`) it reads the feedback and sets `output`:
0 when `setpoint` is 0; `setpoint / full_scale` when the feedback is 0;
otherwise, when the error `|setpoint - feedback| / full_scale` exceeds
`deadband` percent, `output` is multiplied by `1 + (setpoint - feedback)
/ feedback / (1 + damping)`. After each solution (`postsync`) it reads
the feedback again and asks for another pass at the same time while the
error exceeds the deadband.

When it initializes, a load tracker is expected to fail when `target` is
not set, when `target_property` is not a property of the target or not a
`double`, `complex`, `int16`, `int32`, or `int64`, when `full_scale` is
0, when `deadband` is outside 1% to 50%, or when `damping` is negative;
then to set `output` to `setpoint / full_scale`.

Caveats
-------

- When nothing uses `output`, or the target cannot reach the setpoint,
  the passes go on until the iteration limit, as in gridlabd.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The pass after a solution is asked for with every solver method;
   gridlabd asks for it only with FBS, and with NR when the admittance
   did not change (`NR_admit_change`).

References
----------

- `arras-energy/gridlabd`: `module/powerflow/load_tracker.cpp`,
  `load_tracker.h`
"""

import cmath
from typing import Any

from ._base import PowerflowClass, prop, keywords
from ._common import TS_NEVER, ref, object_state, get_int, get_double, get_complex, set_double, PowerflowError

REAL, IMAGINARY, MAGNITUDE, ANGLE = range(4)
"""`operation` values"""

TYPES = ("double", "complex", "int16", "int32", "int64")
"""Target property types supported"""

class LoadTracker(PowerflowClass):
    """Behavior of class `load_tracker`"""

    NAME = "load_tracker"
    TRL = 9 # TRL_PROVEN
    PASSCONFIG = "PRETOPDOWN|BOTTOMUP|POSTTOPDOWN|UNSAFE_OVERRIDE_OMIT|AUTOLOCK"
    EVENTS = ("init", "presync", "postsync")
    PROPERTIES = (
        ("target", "object", prop("target object to track the load of")),
        ("target_property", "char256", prop("property on the target object representing the load")),
        ("operation", "enumeration", prop("operation to perform on complex property types", "MAGNITUDE",
            keywords=keywords(("REAL", REAL), ("IMAGINARY", IMAGINARY), ("MAGNITUDE", MAGNITUDE), ("ANGLE", ANGLE)))),
        ("full_scale", "double", prop("magnitude of the load at full load, used for feed-forward control")),
        ("setpoint", "double", prop("load setpoint to track to")),
        ("deadband", "double", prop("percentage deadband", "1.0")),
        ("damping", "double", prop("load setpoint to track to", "0.0")),
        ("output", "double", prop("output scaling value")),
        ("feedback", "double", prop("the feedback signal, for reference purposes")),
    )

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`load_tracker::init()`"""
        from .node import init_failed # pylint: disable=import-outside-toplevel
        try:
            target = ref(model, name, "target")
            if target is None:
                raise PowerflowError("Target object not set")
            prop_ = str(model.get_property(name, "target_property") or "").strip('"')
            found = model.objects[target].oclass.find_property(prop_)
            if found is None:
                raise PowerflowError(f'Unable to find property "{prop_}" in object {target}')
            if found.ptype not in TYPES:
                raise PowerflowError("Unsupported property type.  Supported types are complex, double and integer")
            if get_double(model, name, "full_scale") == 0:
                raise PowerflowError("The full_scale property must be non-zero")
            deadband = get_double(model, name, "deadband")
            if deadband < 1.0 or deadband > 50.0:
                raise PowerflowError("Deadband must be in the range 1% to 50%")
            if get_double(model, name, "damping") < 0:
                raise PowerflowError("Damping must greater than or equal to 0.0")
        except PowerflowError as err:
            init_failed(model, name, err)
            return False
        object_state(model, name).update(target=target, prop=prop_, ptype=found.ptype)
        set_double(model, name, "output", get_double(model, name, "setpoint")/get_double(model, name, "full_scale"))
        return True

    @classmethod
    def update_feedback(cls, model:Any, name:str) -> float:
        """gridlabd `update_feedback_variable()`"""
        state = object_state(model, name)
        target, prop_, ptype = state["target"], state["prop"], state["ptype"]
        if ptype == "complex":
            value = get_complex(model, target, prop_)
            operation = get_int(model, name, "operation")
            if operation == REAL:
                feedback = value.real
            elif operation == IMAGINARY:
                feedback = value.imag
            elif operation == ANGLE:
                feedback = cmath.phase(value)
            else:
                feedback = -abs(value) if value.real < 0 else abs(value)
        elif ptype == "double":
            feedback = get_double(model, target, prop_)
        else:
            feedback = float(get_int(model, target, prop_))
        set_double(model, name, "feedback", feedback)
        return feedback

    @classmethod
    def outside(cls, model:Any, name:str, feedback:float) -> bool:
        """`True` when the error exceeds the deadband"""
        error = abs(get_double(model, name, "setpoint") - feedback)/get_double(model, name, "full_scale")
        return error > get_double(model, name, "deadband")/100.0

    @classmethod
    def presync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`load_tracker::presync()`: the output"""
        if "target" not in object_state(model, name):
            return TS_NEVER
        feedback = cls.update_feedback(model, name)
        setpoint, full_scale = get_double(model, name, "setpoint"), get_double(model, name, "full_scale")
        output = get_double(model, name, "output")
        if setpoint == 0:
            output = 0.0
        elif feedback == 0:
            output = setpoint/full_scale
        elif cls.outside(model, name, feedback):
            output *= 1.0 + (setpoint - feedback)/feedback/(1.0 + get_double(model, name, "damping"))
        set_double(model, name, "output", output)
        return TS_NEVER

    @classmethod
    def postsync(cls, model:Any, name:str, t:int) -> int:
        """`load_tracker::postsync()`: another pass while outside the
        deadband"""
        if "target" not in object_state(model, name):
            return TS_NEVER
        return t if cls.outside(model, name, cls.update_feedback(model, name)) else TS_NEVER

__all__ = ["LoadTracker"]
