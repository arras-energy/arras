"""@private Registration shared by the powerflow classes"""

from typing import Any

from arras.oclass import Class

from ._common import MODULE, TRL_PROVEN

EVENTS = ("init", "precommit", "presync", "sync", "postsync", "commit")
"""Event handlers a class may have; each calls `powerflow.EVENT`"""

class PowerflowClass: # pylint: disable=too-few-public-methods
    """Base of the class behaviors: registration from class attributes

    Subclasses set `NAME`, `PARENT` (the name of the powerflow class they
    inherit from, gridlabd `PT_INHERIT`), `PASSCONFIG`, `TRL`,
    `PROPERTIES`, and `EVENTS` (the events of `EVENTS` that the class
    handles with a classmethod of the same name taking `(model, name, t)`).
    A Python subclass of a behavior class inherits its handlers, so the
    classes still to be ported (`line`, `meter`, ...) subclass `Link` or
    `Node`.
    """

    NAME = ""
    """gridlabd class name"""

    PARENT: str|None = None
    """Name of the powerflow class this class inherits from"""

    PASSCONFIG = "AUTOLOCK"
    """Pass configuration"""

    TRL = TRL_PROVEN
    """Technology readiness level"""

    PROPERTIES: tuple[tuple[str,str,dict[str,Any]],...] = ()
    """Published properties as `(name, type, Class.publish() options)`, in
    gridlabd's publication order, without the inherited ones"""

    EVENTS: tuple[str,...] = ()
    """Events the class handles"""

    @classmethod
    def register(cls, module:Any) -> Any:
        """Register the class for `module` (an `arras.module.Module`) with
        its parent class, properties, and event handlers"""
        oclass = module.register_class(cls.NAME, passconfig=cls.PASSCONFIG)
        oclass.trl = cls.TRL
        if cls.PARENT is not None:
            parent = Class.find(cls.PARENT, module=MODULE)
            if parent is not None:
                oclass.set_parent(parent)
        for name, ptype, options in cls.PROPERTIES:
            oclass.publish(name, ptype, **options)
        for event in cls.EVENTS:
            oclass.set_event(event, f"python:{MODULE}.{event}")
        return oclass

def prop(description:str|None=None, default:str|None=None, flags:str|None=None,
        **kwargs:Any) -> dict[str,Any]:
    """`Class.publish()` options"""
    options: dict[str,Any] = dict(kwargs)
    if description is not None:
        options["description"] = description
    if default is not None:
        options["default"] = default
    if flags is not None:
        options["flags"] = flags
    return options

def keywords(*items:tuple[str,int]) -> dict[str,int]:
    """Keywords in the order gridlabd lists them (reverse publication
    order); `items` are `(name, value)` in publication order"""
    return dict(reversed(items))
