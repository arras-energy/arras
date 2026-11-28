# pylint: disable=line-too-long
"""@private Registration shared by the residential classes"""

from typing import Any

from arras.oclass import Class

from ._common import MODULE, TRL_UNKNOWN, EUC_IS110, EUC_IS220

EVENTS = ("init", "presync", "sync", "postsync", "commit")
"""Event handlers a class may have; each calls `residential.EVENT`"""

class ResidentialClass: # pylint: disable=too-few-public-methods
    """Base of the class behaviors: registration from class attributes

    Subclasses set `NAME`, `PARENT` (the name of the residential class
    they inherit from, gridlabd `PT_INHERIT`), `PASSCONFIG`, `TRL`,
    `PROPERTIES`, and `EVENTS` (the events of `EVENTS` that the class
    handles with a classmethod of the same name taking `(model, name, t)`).
    """

    NAME = ""
    """gridlabd class name"""

    PARENT: str|None = None
    """Name of the residential class this class inherits from"""

    PASSCONFIG = "AUTOLOCK"
    """Pass configuration"""

    TRL = TRL_UNKNOWN
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

def enduse_properties(prefix:str="", flags:str|None=None, defaults:dict[str,str]|None=None,
        description:str="the enduse load description") -> tuple[tuple[str,str,dict[str,Any]],...]:
    """The properties that the core's `enduse_publish()` publishes for an
    enduse member: the enduse itself (`load` when `prefix` is empty), then
    its parts, named `PREFIX.part` when `prefix` is given; `flags` and
    `description` are those of the enduse property, and `defaults` the
    values the class's `create()` sets, keyed on part name, over those
    of the core's `enduse_create()` (power factor and heat gain fraction
    1)"""
    defaults = {"power_factor": "1", "heatgain_fraction": "1", **(defaults or {})}
    parts = (
        ("energy[kVAh]", "complex", "the total energy consumed since the last meter reading"),
        ("power[kVA]", "complex", "the total power consumption of the load"),
        ("peak_demand[kVA]", "complex", "the peak power consumption since the last meter reading"),
        ("heatgain[Btu/h]", "double", "the heat transferred from the enduse to the parent"),
        ("cumulative_heatgain[Btu]", "double", "the cumulative heatgain from the enduse to the parent"),
        ("heatgain_fraction[pu]", "double", "the fraction of the heat that goes to the parent"),
        ("current_fraction[pu]", "double", "the fraction of total power that is constant current"),
        ("impedance_fraction[pu]", "double", "the fraction of total power that is constant impedance"),
        ("power_fraction[pu]", "double", "the fraction of the total power that is constant power"),
        ("power_factor", "double", "the power factor of the load"),
        ("constant_power[kVA]", "complex", "the constant power portion of the total load"),
        ("constant_current[kVA]", "complex", "the constant current portion of the total load"),
        ("constant_admittance[kVA]", "complex", "the constant admittance portion of the total load"),
        ("voltage_factor[pu]", "double", "the voltage change factor"),
        ("breaker_amps[A]", "double", "the rated breaker amperage"),
    )
    result: list[tuple[str,str,dict[str,Any]]] = [(prefix or "load", "enduse", prop(description, flags=flags))]
    for name, ptype, text in parts:
        base = name.split("[", maxsplit=1)[0]
        full = f"{prefix}.{name}" if prefix else name
        result.append((full, ptype, prop(text, defaults.get(base))))
    result.append((f"{prefix}.configuration" if prefix else "configuration", "set",
        prop("the load configuration options", defaults.get("configuration"),
            keywords=keywords(("IS110", EUC_IS110), ("IS220", EUC_IS220)))))
    return tuple(result)
