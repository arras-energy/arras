# pylint: disable=line-too-long
"""@private Base of the assert classes"""

from typing import Any

from arras.oclass import Class

from ._common import MODULE, Target, runner, object_flags

TRL_PROVEN = 9
"""Technology readiness level of the assert classes (gridlabd `TRL_PROVEN`)"""

PASSCONFIG = "AUTOLOCK|OBSERVER"
"""Pass configuration of the assert classes (gridlabd
`PC_AUTOLOCK|PC_OBSERVER`)"""

class AssertClass:
    """Behavior of the objects of one gridlabd class of the assert module

    Subclasses set `NAME` and `PROPERTIES` and implement `init()` and
    `commit()`, which the `assert` package's `init` and `commit` event
    handlers call with the model and the object name.
    """

    NAME = ""
    """gridlabd class name"""

    PROPERTIES: tuple[tuple[str,str,dict[str,Any]],...] = ()
    """Published properties as `(name, type, Class.publish() options)`, in
    gridlabd's publication order"""

    @classmethod
    def register(cls, module:Any) -> Class:
        """Register the class for `module` (an `arras.module.Module`) with
        its properties and event handlers"""
        oclass = module.register_class(cls.NAME, passconfig=PASSCONFIG)
        oclass.trl = TRL_PROVEN
        for name, ptype, options in cls.PROPERTIES:
            oclass.publish(name, ptype, **options)
        oclass.set_event("init", f"python:{MODULE}.init")
        oclass.set_event("commit", f"python:{MODULE}.commit")
        return oclass

    @classmethod
    def init(cls, model:Any, name:str) -> bool:
        """Initialize an object; `False` fails the initialization"""
        raise NotImplementedError

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int:
        """Commit an object at time `t`; returns the time of its next event
        (`TS_NEVER`), or `TS_INVALID` or 0 for a failure"""
        raise NotImplementedError

    #
    # Helpers
    #
    @staticmethod
    def flags(model:Any, name:str) -> int:
        """Message flags of the object"""
        return object_flags(model, name)

    @staticmethod
    def parent(model:Any, name:str) -> str|None:
        """Parent object name, or `None`"""
        return model.objects[name].get("parent") or None

    @classmethod
    def find_target(cls, model:Any, name:str, types:tuple[str,...]) -> tuple[str,str,Target]|None:
        """Target of an object of a typed assert class: its parent's
        `target` property, or the global variable when it has no parent

        Returns
        -------
        - `(str,str,Target)`: the parent name (`global` when there is none),
          the target name, and the target
        - `None`: the target is not found or not of one of `types` (an error
          is written, as the typed classes write it)
        """
        parent = cls.parent(model, name)
        pname = parent or "global"
        target = cls.get(model, name, "target")
        prop = Target(model, parent, target)
        if not prop.is_valid or prop.ptype not in types:
            runner().error(f"Specified target {target} for {pname} is not valid.")
            return None
        return pname, target, prop

    @classmethod
    def init_failed(cls, model:Any, name:str, message:str) -> bool:
        """Report an exception thrown by an object's `init()` as the
        gridlabd `INIT_CATCHALL()` macro does, and fail the initialization"""
        obj = model.objects[name]
        label = "unnamed" if name == f"{obj.oclass.name}:{obj.id}" else name
        runner().error(f"init_{cls.NAME}(obj={obj.id};{label}): {message}")
        return False

    @staticmethod
    def get(model:Any, name:str, prop:str) -> str:
        """Property value as text ("" when it has none)"""
        value = model.get_property(name, prop)
        return "" if value is None else str(value)

    @staticmethod
    def get_alias(model:Any, name:str, props:tuple[str,...]) -> str:
        """Value of properties that share storage in gridlabd: the one set
        last, else the class default of the first"""
        obj = model.objects[name]
        found = None
        for key in obj:
            if key in props:
                found = key
        value = model.get_property(name, found or props[0])
        return "" if value is None else str(value)

    @staticmethod
    def keyword(model:Any, name:str, prop:str) -> int:
        """Value of an enumeration property"""
        spec = model.objects[name].oclass.find_property(prop)
        text = model.get_property(name, prop)
        text = "0" if text in (None, "") else str(text).strip()
        if text in spec.keywords:
            return spec.keywords[text]
        return int(text, 0)

    @staticmethod
    def set_keyword(model:Any, name:str, prop:str, value:int) -> None:
        """Set an enumeration property to the first keyword with `value`
        (as gridlabd prints it)"""
        spec = model.objects[name].oclass.find_property(prop)
        key = next((k for k, v in spec.keywords.items() if v == value), str(value))
        model.set_property(name, prop, key)
