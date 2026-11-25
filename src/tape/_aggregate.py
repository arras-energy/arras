# pylint: disable=line-too-long
"""@private Aggregates of a property over a group of objects

The gridlabd core's aggregation (`source/aggregate.cpp`, `GldAggregator`)
that collectors use: `AGGREGATOR(PROPERTY[.PART][UNIT])` over the objects
of a group expression. Group expressions are read with the find-language
subset of the `assert` package (`assert._find`, decision 8.6).
"""

import re
import math
import importlib
from typing import Any

from arras.exceptions import ArrasException

from ._common import Prop, TapeError, gl_error, find_unit, convert, angle, clock, to_timestamp, TS_NEVER

AGGREGATORS = {"min": "MIN", "max": "MAX", "avg": "AVG", "std": "STD", "sum": "SUM",
    "prod": "SUM", "mbe": "MBE", "mean": "MEAN", "var": "VAR", "skew": "SKEW", "kur": "KUR",
    "count": "COUNT", "gamma": "GAMMA"}
"""Aggregators by name (`prod` is `SUM`, as in gridlabd)"""

def find_group(model:Any, spec:str) -> list[str]:
    """Names of the objects of a group expression, in creation order

    Exceptions
    ----------
    - `TapeError`: the expression is not valid
    """
    finder = importlib.import_module("assert._find")
    try:
        return finder.find(model, spec)
    except ArrasException as err:
        raise TapeError(str(err)) from err

class Aggregate: # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """An aggregation (gridlabd `AGGREGATION`)

    Exceptions
    ----------
    - `TapeError`: the aggregation is not valid (after an error line)
    """

    def __init__(self, model:Any, aggregator:str, group:str):
        # pylint: disable=too-many-branches,too-many-statements
        self.model = model
        match = re.match(r"\s*([A-Za-z0-9_]{1,8})\(([][A-Za-z0-9_.^]{1,256})\)", aggregator)
        self.absolute = False
        if match is None:
            match = re.match(r"\s*([A-Za-z0-9_]{1,8})\|([][A-Za-z0-9_.^]{1,256})\|", aggregator)
            self.absolute = True
        if match is None:
            gl_error(f"aggregate group '{aggregator}' is not valid")
            raise TapeError("invalid aggregation")
        op, value = match.group(1), match.group(2)
        try:
            self.members = find_group(model, group)
        except TapeError:
            self.members = None # type: ignore[assignment]
        part = ""
        if self.members:
            first = self.members[0]
            if not Prop(model, first, value).is_valid and "." in value:
                value, part = value.rsplit(".", 1)
        self.unit = None
        unit_match = re.fullmatch(r"([A-Za-z0-9_]{1,32})\[([A-Za-z0-9_^]+)\]", value)
        if unit_match:
            self.unit = unit_match.group(2)
            if find_unit(self.unit) is None:
                gl_error(f"aggregate group '{value}' has invalid units ({self.unit})")
                raise TapeError("invalid aggregation")
            value = unit_match.group(1)
        if op.lower() not in AGGREGATORS:
            gl_error(f"aggregate group '{aggregator}' does not use a known aggregator")
            raise TapeError("invalid aggregation")
        self.op = AGGREGATORS[op.lower()]
        if self.members is None:
            gl_error(f"aggregate group expression '{group}' failed")
            raise TapeError("invalid aggregation")
        if not self.members:
            gl_error(f"aggregate group expression '{group}' results is an empty object list")
            raise TapeError("invalid aggregation")
        self.prop = value
        target = Prop(model, self.members[0], value)
        if not target.is_valid:
            gl_error(f"aggregate group property '{value}' is not found in the objects satisfying search criteria '{group}'")
            raise TapeError("invalid aggregation")
        if target.ptype in ("double", "randomvar", "loadshape"):
            if part:
                gl_error(f"aggregate group property '{value}' cannot have part '{part}'")
                raise TapeError("invalid aggregation")
            self.part = ""
        elif target.ptype in ("complex", "enduse"):
            if part not in ("real", "imag", "mag", "ang", "arg"):
                gl_error(f"aggregate group property '{value}' cannot have part '{part}'")
                raise TapeError("invalid aggregation")
            self.part = part
        else:
            gl_error(f"aggregate group property '{value}' cannot be aggregated")
            raise TapeError("invalid aggregation")
        self.native = target.native
        if self.unit is not None and self.native is None:
            gl_error(f"aggregate group property '{value}' is unitless and cannot be converted")
            raise TapeError("invalid aggregation")
        if self.unit is not None and convert(1.0, self.native, self.unit) is None: # type: ignore[arg-type]
            gl_error(f"aggregate group property '{value}' cannot use units '{self.unit}'")
            raise TapeError("invalid aggregation")

    def _in_service(self, name:str, now:int) -> bool:
        obj = self.model.objects[name]
        in_svc = obj.get("in_svc")
        out_svc = obj.get("out_svc")
        start = to_timestamp(self.model, in_svc) if in_svc not in (None, "", "INIT") else 0
        end = TS_NEVER if out_svc in (None, "", "NEVER") else to_timestamp(self.model, out_svc)
        return not (start >= now or end <= now)

    def value(self) -> float:
        """The aggregate (gridlabd `GldAggregator::get_value()`)

        Exceptions
        ----------
        - `TapeError`: the aggregator is `skew` or `kur`, which gridlabd
          does not implement
        """
        # pylint: disable=too-many-branches
        numerator = denominator = secondary = 0.0
        now = clock(self.model)
        for name in self.members:
            if not self._in_service(name, now):
                continue
            target = Prop(self.model, name, self.prop)
            if not target.is_valid:
                continue
            if self.part:
                value, _ = target.complex_value()
                x = {"real": value.real, "imag": value.imag, "mag": abs(value), "arg": angle(value),
                    "ang": angle(value)*180/math.pi}[self.part]
            else:
                x = target.double()
                if self.native is not None and self.unit is not None:
                    converted = convert(x, self.native, self.unit)
                    x = x if converted is None else converted
            if self.absolute:
                x = abs(x)
            if self.op == "MIN":
                if x < numerator or denominator == 0:
                    numerator = x
                denominator = 1
            elif self.op == "MAX":
                if x > numerator or denominator == 0:
                    numerator = x
                denominator = 1
            elif self.op == "COUNT":
                numerator += 1
                denominator = 1
            elif self.op == "MBE":
                denominator += 1
                numerator += x
                secondary += (x - secondary)/denominator
            elif self.op in ("AVG", "MEAN"):
                numerator += x
                denominator += 1
            elif self.op == "SUM":
                numerator += x
                denominator = 1
            elif self.op == "GAMMA":
                denominator += math.log(x) if x > 0 else -math.inf
                if numerator == 0 or secondary > x:
                    secondary = x
                numerator += 1
            elif self.op in ("STD", "VAR"):
                denominator += 1
                delta = x - secondary
                secondary += delta/denominator
                numerator += delta*(x - secondary)
        return self._result(numerator, denominator, secondary)

    def _result(self, numerator:float, denominator:float, secondary:float) -> float:
        # pylint: disable=too-many-return-statements
        try:
            if self.op == "GAMMA":
                return 1 + numerator/(denominator - numerator*math.log(secondary))
            if self.op == "STD":
                return math.sqrt(numerator/(denominator - 1))
            if self.op == "MBE":
                return numerator/denominator - secondary
            if self.op == "SKEW":
                raise TapeError("skewness aggregation is not implemented")
            if self.op == "KUR":
                raise TapeError("kurtosis aggregation is not implemented")
            return numerator/denominator
        except ZeroDivisionError:
            if numerator == 0:
                return math.nan
            return math.copysign(math.inf, numerator)
        except ValueError:
            return math.nan
