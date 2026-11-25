"""@private Registration shared by the tape classes"""

from typing import Any

from ._common import MODULE

EVENTS = ("init", "precommit", "presync", "sync", "postsync", "commit", "finalize")
"""Event handlers a class may have; each calls `tape.EVENT`"""

class TapeClass: # pylint: disable=too-few-public-methods
    """Base of the class behaviors: registration from class attributes

    Subclasses set `NAME`, `PASSCONFIG`, `TRL`, `PROPERTIES`, and `EVENTS`
    (the events of `EVENTS` that the class handles with a classmethod of
    the same name taking `(model, name, t)`).
    """

    NAME = ""
    """gridlabd class name"""

    PASSCONFIG = "NOSYNC"
    """Pass configuration"""

    TRL = 0
    """Technology readiness level"""

    PROPERTIES: tuple[tuple[str,str,dict[str,Any]],...] = ()
    """Published properties as `(name, type, Class.publish() options)`, in
    gridlabd's publication order"""

    EVENTS: tuple[str,...] = ()
    """Events the class handles"""

    @classmethod
    def register(cls, module:Any) -> Any:
        """Register the class for `module` (an `arras.module.Module`) with
        its properties and event handlers"""
        oclass = module.register_class(cls.NAME, passconfig=cls.PASSCONFIG)
        oclass.trl = cls.TRL
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

def keywords(*names:str, values:tuple[int,...]|None=None) -> dict[str,int]:
    """Keywords in the order gridlabd lists them (reverse publication
    order); `names` are given in publication order with values 0, 1, ...
    unless `values` are given"""
    items = list(zip(names, values if values is not None else range(len(names))))
    return dict(reversed(items))
