# pylint: disable=line-too-long
"""Class `scada`: points shared with the controllers module

Syntax
------

    object pypower.scada {
        point <object>.<property>;
        [point <object>.<property>; ...]
        write {TRUE,FALSE};
        record {TRUE,FALSE};
    }

Description
-----------

A SCADA object gives the controllers module (`pypower::controllers`) the
values of a list of points, and optionally takes values back. Given a
model, a SCADA object is expected to:

1. keep each `point` given (the property is a method: each value adds a
   point, and reading it gives the points joined with commas);
2. refuse to initialize when there is no controllers module;
3. add its points `dict` to the controllers module's global `scada` (a
   `dict` keyed on object name, created when missing) and, with `record`,
   its historian `dict` to the global `historian`;
4. at each precommit, set each point's entry to the property's value text
   (as gridlabd writes it, e.g. `-4.98259 deg`) and, with `record`, add a
   copy of the points `dict` to the historian keyed on the clock;
5. at each commit, with `write`, set each point's property from the text
   of its entry (an entry that is missing or not accepted is an error).

Points that are not found are ignored.

References
----------

- `arras-energy/gridlabd`: `module/pypower/scada.cpp`, `scada.h`
"""

from typing import Any

from ._base import PypowerClass, prop, msg
from ._common import TS_NEVER, object_state, module_state, get_int, get_text, from_string
from ._module import ensure_init

def _point(model:Any, text:str) -> tuple[str,str]|None:
    """`(object, property)` of a point `OBJECT.PROPERTY`, or `None` when
    it is not found"""
    for n, char in enumerate(text):
        if char == "." and text[:n] in model.objects:
            obj, propname = text[:n], text[n+1:]
            if model.objects[obj].oclass.find_property(propname) is not None or propname in ("latitude", "longitude"):
                return obj, propname
    return None

class Scada(PypowerClass):
    """Behavior of class `scada`"""

    NAME = "scada"
    PASSCONFIG = "POSTTOPDOWN|AUTOLOCK|OBSERVER"
    PROPERTIES = (
        ("point", "method", prop("Enable access to point specified as object <name>:<property>")),
        ("write", "bool", prop("Enable write to point")),
        ("record", "bool", prop("Enable recording of point to historian")),
    )
    EVENTS = ("init", "precommit", "commit")

    @classmethod
    def state(cls, model:Any, name:str) -> dict[str,Any]:
        """State of a SCADA object: `points` (names), `scada` (point
        values), `historian` (copies of them keyed on time)"""
        return object_state(model, name, lambda: {"points": [], "scada": {}, "historian": {}})

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`scada::init()`"""
        if not ensure_init(model):
            return False
        state = cls.state(model, name)
        state["points"] = [x for x in get_text(model, name, "point").split(",") if x]
        py_globals = module_state(model).py_globals
        if py_globals is None:
            msg(model, name).error("unable to find global controllers")
            return False
        py_globals.setdefault("scada", {})[name] = state["scada"]
        historian = py_globals.setdefault("historian", {})
        if get_int(model, name, "record"):
            historian[name] = state["historian"]
        return True

    @classmethod
    def precommit(cls, model:Any, name:str, t:int) -> int:
        """`scada::precommit()`: read the points"""
        from tape._common import Prop, TapeError # pylint: disable=import-outside-toplevel
        state = cls.state(model, name)
        for point in state["points"]:
            target = _point(model, point)
            if target is not None:
                try:
                    state["scada"][point] = Prop(model, target[0], target[1]).to_string()
                except TapeError:
                    pass
        if get_int(model, name, "record"):
            state["historian"][t] = dict(state["scada"])
        return TS_NEVER

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`scada::commit()`: write the points"""
        if not get_int(model, name, "write"):
            return TS_NEVER
        state = cls.state(model, name)
        out = msg(model, name)
        for point in state["points"]:
            target = _point(model, point)
            if target is None:
                continue
            value = state["scada"].get(point)
            if value is None:
                out.error(f"scada write of {point} = '(null)' failed")
            elif not from_string(model, target[0], target[1], str(value)):
                out.error(f"scada write of {point} = '{value}' invalid")
        return TS_NEVER
