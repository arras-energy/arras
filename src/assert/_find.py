# pylint: disable=line-too-long
"""@private Object search expressions for the `assert` `group` property

Reproduces the part of gridlabd's find language (`find_pgm_new()` and
`expression()` in `source/find.cpp`) that names objects by header values:
terms `NAME OP VALUE` joined by `;`, `AND`, or `and`, where `NAME` is
`class`, `isa`, `groupid`, `module`, `id`, `name`, `parent`, or `rank`, and
`OP` is one of `=`, `!=`, `<`, `>`, `<=`, `>=`.
"""

import re
from typing import Any

from ._common import AssertError

_OPS = {"!=": "NE", "<=": "LE", ">=": "GE", "!~": "UNLIKE", "=": "EQ", "<": "LT", ">": "GT",
    "~": "LIKE", ":": "ISA"}
_TERM = re.compile(r"\s*([A-Za-z0-9_]+)\s*(!=|<=|>=|!~|=|<|>|~|:)\s*([^;\n\s]+)\s*")
_JOIN = re.compile(r"\s*(?:;|AND|and)")

def _test(op:str, x:Any, value:Any) -> bool:
    # pylint: disable=too-many-return-statements
    if op == "EQ":
        return x == value
    if op == "NE":
        return x != value
    if op == "LT":
        return x < value
    if op == "GT":
        return x > value
    if op == "LE":
        return x <= value
    if op == "GE":
        return x >= value
    raise AssertError(f"find operator '{op}' is not supported")

def find(model:Any, spec:str) -> list[str]:
    """Names of the objects of `model` that match `spec`, in creation order

    Exceptions
    ----------
    - `AssertError`: the expression is not valid or refers to a class,
      module, or parent that is not found
    """
    # pylint: disable=too-many-branches
    terms = []
    pos = 0
    while pos < len(spec):
        match = _TERM.match(spec, pos)
        if match is None:
            if spec[pos:].strip():
                raise AssertError(f"find expression syntax error at '{spec[pos:pos+15]}'")
            break
        terms.append((match.group(1), _OPS[match.group(2)], match.group(3).strip("'\"")))
        pos = match.end()
        join = _JOIN.match(spec, pos)
        if join is not None:
            pos = join.end()
    if not terms:
        raise AssertError(f"find expression '{spec}' is not valid")
    from arras.oclass import Class # pylint: disable=import-outside-toplevel
    names = sorted(model.objects, key=lambda name: model.objects[name].id)
    for pname, op, value in terms:
        if pname in ("class", "isa"):
            oclass = Class.find(value)
            if oclass is None:
                raise AssertError(f"class '{value}' not found")
            if pname == "isa":
                names = [x for x in names if model.objects[x].oclass.isa(value)]
            else:
                names = [x for x in names if _test(op, model.objects[x].oclass is oclass, True)]
        elif pname == "module":
            if value not in model.modules:
                raise AssertError(f"module '{value}' not found")
            names = [x for x in names if _test(op, model.objects[x].oclass.module, value)]
        elif pname in ("id", "rank"):
            number = int(value) if value.lstrip("-").isdigit() else 0
            if number < 0:
                raise AssertError(f"{pname} {value} is invalid")
            names = [x for x in names if _test(op, model.objects[x].id if pname == "id" else int(model.objects[x].get("rank") or 0), number)]
        elif pname in ("name", "groupid"):
            names = [x for x in names if _test(op, (x if pname == "name" else model.objects[x].get("groupid") or ""), value)]
        elif pname == "parent":
            if value not in model.objects and value not in ("root", "ROOT"):
                raise AssertError(f"parent '{value}' not found")
            parent = value if value in model.objects else None
            names = [x for x in names if _test(op, model.objects[x].get("parent") or None, parent)]
        else:
            raise AssertError(f"find expression refers to unknown or unsupported property '{pname}'")
    return names
