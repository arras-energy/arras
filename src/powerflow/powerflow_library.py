"""Class `powerflow_library`: the base of the powerflow library objects

Description
-----------

gridlabd registers `powerflow_library` with no properties, between
`powerflow_object` and `node`. The library classes (`line_configuration`,
`line_spacing`, the conductor classes, `transformer_configuration`,
`regulator_configuration`, `restoration`, `power_metrics`,
`pole_configuration`) derive from it in C++ but do not inherit its (empty)
publication, so their classes have no parent class. It is registered here
so that the module's classes keep gridlabd's registration order; its
objects do nothing.

The behavior classes of the library classes derive from `LibraryObject`,
whose `on_init` handler runs the class's `check()` and writes gridlabd's
`INIT_CATCHALL()` message when it raises `PowerflowError`.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/powerflow_library.cpp`
"""

from typing import Any

from ._base import PowerflowClass
from ._common import SM_FBS, SM_NR, SOLVER_METHODS, g, PowerflowError

class PowerflowLibrary(PowerflowClass): # pylint: disable=too-few-public-methods
    """Behavior of class `powerflow_library`"""

    NAME = "powerflow_library"
    PASSCONFIG = "NOSYNC"

class LibraryObject(PowerflowLibrary):
    """Base of the library classes that check their objects at
    initialization"""

    EVENTS = ("init",)

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`on_init` handler: `True`, or `False` after gridlabd's
        `INIT_CATCHALL()` message"""
        from .node import init_failed # pylint: disable=import-outside-toplevel
        try:
            cls.check(model, name)
        except PowerflowError as err:
            init_failed(model, name, err)
            return False
        return True

    @classmethod
    def check(cls, model:Any, name:str) -> None:
        """Initialization checks (raise `PowerflowError`); none by default"""

def method_label(model:Any) -> str:
    """Solver method named in messages: `NR` for NR and FBS (which is
    solved with NR), the keyword for the others"""
    method = g(model, "solver_method")
    if method in (SM_NR, SM_FBS, None):
        return "NR"
    return next((key for key, value in SOLVER_METHODS.items() if value == method), "NR")
