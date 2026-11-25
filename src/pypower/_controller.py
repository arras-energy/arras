"""@private Object controllers: Python functions of the controllers module
that `load`, `powerplant`, and `relay` objects call (gridlabd's controller
code in `load.cpp`, `powerplant.cpp`, `relay.cpp`)"""

from typing import Any, Callable

from ._common import (MODULE, TS_NEVER, TS_INVALID, module_state, global_value, python_error,
    from_string, python_text, get_text, Messages)

def find(model:Any, name:str, required:bool=False) -> Callable|None|bool:
    """The controller function named by the object's `controller`
    property: the function, `None` when there is none to call, or `False`
    (with an error) when it cannot be used; with `required` (relays), no
    controllers module is an error"""
    out = Messages(model, name)
    controller = get_text(model, name, "controller")
    py_globals = module_state(model).py_globals
    if required and py_globals is None:
        out.error("unable to find global controllers")
        return False
    if py_globals is None or not controller:
        return None
    function = py_globals.get(controller)
    if function is None:
        out.error(f"pypower controller '{controller}' is not found")
        return False
    if not callable(function):
        out.error(f"pypower controller '{controller}' is not callable")
        return False
    return function

def call(model:Any, name:str, controller:Callable, kwargs:dict[str,Any], t0:int, # pylint: disable=too-many-arguments,too-many-positional-arguments
        on_set:str="count") -> tuple[int,int]|None:
    """Call a controller with the object name and `kwargs`, and set the
    properties it returns; returns `(t1, number of properties set)`, or
    `None` when the controller raised and `pypower::stop_on_failure` is
    true. `on_set` is `count` (loads: a value not accepted is a warning),
    `quiet` (powerplants: the same, not counted), or `iterate` (relays:
    no warning; each property set asks to run again at `t0`)"""
    out = Messages(model, name)
    t1, nchanges = TS_NEVER, 0
    try:
        result = controller(name, **kwargs)
    except Exception as err: # pylint: disable=broad-exception-caught
        python_error(err)
        if global_value(model, f"{MODULE}::stop_on_failure"):
            return None
        return t1, nchanges
    if not isinstance(result, dict):
        out.error("controller return value not a property update dictionary")
        return t1, nchanges
    for key, value in result.items():
        key = str(key)
        if key == "t":
            try:
                t1 = int(float(value))
            except (TypeError, ValueError):
                t1 = TS_INVALID
            continue
        if model.objects[name].oclass.find_property(key) is None:
            out.error(f"controller return property '{key}' is not valid")
            continue
        text = python_text(value)
        accepted = from_string(model, name, key, text)
        if on_set == "iterate":
            t1 = t0
        else:
            if not accepted:
                out.warning(f"controller return value {key}='{text}' is not accepted")
            if on_set == "count":
                nchanges += 1
    return t1, nchanges
