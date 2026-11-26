"""Class `powerflow_library`: the base of the powerflow library objects

Description
-----------

gridlabd registers `powerflow_library` with no properties, between
`powerflow_object` and `node`; the configuration classes (`line_configuration`,
...) derive from it in C++ but do not inherit its (empty) publication. It is
registered here so that the module's classes keep gridlabd's registration
order; its objects do nothing.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/powerflow_library.cpp`
"""

from ._base import PowerflowClass

class PowerflowLibrary(PowerflowClass): # pylint: disable=too-few-public-methods
    """Behavior of class `powerflow_library`"""

    NAME = "powerflow_library"
    PASSCONFIG = "NOSYNC"
