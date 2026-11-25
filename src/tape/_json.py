"""@private JSON text as jsoncpp's `Json::StyledWriter` writes it

Object members in key order, 3-space indentation, `" : "` after keys,
arrays on one line when they are short (`rightMargin_` 74) and hold no
non-empty arrays or objects, and doubles with `%.17g` (with `.0` added
when there is no `.` or `e`), as the jsoncpp bundled with gridlabd
(`third_party/jsonCpp/jsoncpp.cpp`) writes them.
"""

import json
import math
from typing import Any

RIGHT_MARGIN = 74
"""`StyledWriter::rightMargin_`"""

INDENT = 3
"""`StyledWriter::indentSize_`"""

def value_text(value:Any) -> str: # pylint: disable=too-many-return-statements
    """A scalar as jsoncpp writes it"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "null"
        if math.isinf(value):
            return "1e+9999" if value > 0 else "-1e+9999"
        text = f"{value:.17g}"
        if "." not in text and "e" not in text:
            text += ".0"
        return text
    return json.dumps(str(value), ensure_ascii=False)

class _Writer:
    """`Json::StyledWriter` state: the document and the indentation"""

    def __init__(self):
        self.document = ""
        self.indent = ""

    def write_indent(self) -> None:
        """`writeIndent()`"""
        if self.document:
            last = self.document[-1]
            if last == " ":
                return
            if last != "\n":
                self.document += "\n"
        self.document += self.indent

    def with_indent(self, text:str) -> None:
        """`writeWithIndent()`"""
        self.write_indent()
        self.document += text

    def value(self, value:Any) -> None:
        """`writeValue()`"""
        if isinstance(value, dict):
            if not value:
                self.document += "{}"
                return
            self.with_indent("{")
            self.indent += " "*INDENT
            keys = sorted(value)
            for index, key in enumerate(keys):
                self.with_indent(json.dumps(str(key), ensure_ascii=False))
                self.document += " : "
                self.value(value[key])
                if index + 1 < len(keys):
                    self.document += ","
            self.indent = self.indent[:-INDENT]
            self.with_indent("}")
        elif isinstance(value, list):
            self.array(value)
        else:
            self.document += value_text(value)

    def array(self, values:list[Any]) -> None:
        """`writeArrayValue()` and `isMultineArray()`"""
        if not values:
            self.document += "[]"
            return
        multiline = len(values)*3 >= RIGHT_MARGIN \
            or any(isinstance(x, (list, dict)) and x for x in values)
        children = []
        if not multiline:
            children = [self._child(x) for x in values]
            multiline = 4 + (len(values) - 1)*2 + sum(len(x) for x in children) >= RIGHT_MARGIN
        if multiline:
            self.with_indent("[")
            self.indent += " "*INDENT
            for index, item in enumerate(values):
                if children:
                    self.with_indent(children[index])
                else:
                    self.write_indent()
                    self.value(item)
                if index + 1 < len(values):
                    self.document += ","
            self.indent = self.indent[:-INDENT]
            self.with_indent("]")
        else:
            self.document += "[ " + ", ".join(children) + " ]"

    @staticmethod
    def _child(value:Any) -> str:
        if isinstance(value, dict):
            return "{}"
        if isinstance(value, list):
            return "[]"
        return value_text(value)

def styled(value:Any) -> str:
    """`Json::StyledWriter::write()`: the text of `value` with a newline"""
    writer = _Writer()
    writer.value(value)
    return writer.document + "\n"
