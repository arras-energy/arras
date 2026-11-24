"""Tests of the private helpers of the `assert` package"""

import importlib

import pytest

from arras import exitcodes
from arras.model import Model

common = importlib.import_module("assert._common")
compare = importlib.import_module("assert._compare")

def test_to_double():
    """Numbers with units, as convert_to_double() reads them"""
    assert common.to_double("1.5 MW", "kW") == pytest.approx(1500.0)
    assert common.to_double(" 2e3") == 2000.0
    assert common.to_double("nan") != common.to_double("nan")
    with pytest.raises(common.AssertError, match="unit given to unitless property"):
        common.to_double("1 MW")
    with pytest.raises(common.AssertError, match="unit conversion failed"):
        common.to_double("1 MW", "V")
    with pytest.raises(common.AssertError, match="is not a number"):
        common.to_double("abc")
    assert common.atof("12abc") == 12.0
    assert common.atof("abc") == 0.0

@pytest.mark.parametrize("text,value", [
    ("", 0j),
    ("3", 3+0j),
    ("3+4j", 3+4j),
    ("3-4i", 3-4j),
    ("(3+4j)", 3+4j),
    ("2+90d", 2j),
    ("1+0j kV", 1000+0j),
    ("1.5 kV", 1.5+0j),  # sscanf() stops before the unit when there is no imaginary part
])
def test_to_complex(text, value):
    """Complex numbers, as convert_to_complex() reads them"""
    assert common.to_complex(text, "V") == pytest.approx(value)

@pytest.mark.parametrize("text", ["abc", "3+4", "3+4x"])
def test_to_complex_errors(text):
    """Complex numbers that are not valid"""
    with pytest.raises(common.AssertError, match="format is not valid"):
        common.to_complex(text)

def test_parse_flags():
    """Set values as keywords or numbers"""
    assert common.parse_flags(None, common.MESSAGE_FLAGS) == 0
    assert common.parse_flags(5, common.MESSAGE_FLAGS) == 5
    assert common.parse_flags("0x10000", common.MESSAGE_FLAGS) == 0x10000
    assert common.parse_flags("QUIET|VERBOSE", common.MESSAGE_FLAGS) == 0x90000

def test_to_timestamp():
    """Timestamps, also with an abbreviation of the model's time zone"""
    model = Model()
    model.globals.set("timezone_locale", "America/Los_Angeles")
    assert common.to_timestamp(model, "'2001-01-01 00:00:00'") == 978336000
    assert common.to_timestamp(model, "2001-01-01 00:00:00 PST") == 978336000
    # the hour that occurs twice when daylight saving time ends
    pdt = common.to_timestamp(model, "2001-10-28 01:30:00 PDT")
    pst = common.to_timestamp(model, "2001-10-28 01:30:00 PST")
    assert pst - pdt == 3600
    with pytest.raises(common.AssertError, match="is not a valid timestamp"):
        common.to_timestamp(model, "2001-01-01 00:00:00 XYZ")
    with pytest.raises(common.AssertError, match="is not a valid timestamp"):
        common.to_timestamp(model, "nonsense words")

def test_target():
    """Targets of header properties, ids, and missing objects"""
    model = Model()
    model.read_glm("class test { double x; } object test { name t; latitude 37; }")
    target = common.Target(model, "t", "latitude")
    assert target.ptype == "double" and target.double() == 37.0
    assert common.Target(model, "t", "id").text() == "0"
    assert not common.Target(model, "nobody", "x").is_valid
    assert common.Target(model, "t", "x").double() == 0.0
    assert common.Target(model, "t", "x").owner == "t"
    assert common.Target(model, None, "clock").owner == "global variable"

def test_operators():
    """Operators that the class tests do not reach"""
    assert compare._float_op(compare.TCOP_LE, 1.0, 1.0, None) # pylint: disable=protected-access
    assert compare._float_op(compare.TCOP_GE, 1.0, 1.0, None) # pylint: disable=protected-access
    assert compare._ordered_op(compare.TCOP_LE, 1, 1, None) # pylint: disable=protected-access
    assert compare._ordered_op(compare.TCOP_GE, 1, 1, None) # pylint: disable=protected-access
    assert compare._scan_char('"abcdefghij"', 8) == "abcdefgh" # pylint: disable=protected-access
    assert compare._scan_char("abcdefghij\nx", 8) == "abcdefgh" # pylint: disable=protected-access
    with pytest.raises(common.AssertError):
        compare._scan_int("+-1", "x") # pylint: disable=protected-access

TYPES = """
clock { starttime "2001-01-01 00:00:00 UTC"; stoptime "2001-01-01 00:00:00 UTC"; }
module assert;
class test {
    enumeration {A=0, B=1} e;
    set {XX=1, YY=2} s;
    bool b;
    object o;
    string str;
    double_array d;
    loadshape l;
}
"""

@pytest.mark.parametrize("props,assertion,expected", [
    ("e B;", 'target e; relation "=="; value 0x1;', True),
    ('s "XX|YY";', 'target s; relation "=="; value 0x3;', True),
    ('s "XX|YY";', 'target s; relation "=="; value "XX|YY";', True),
    ("b FALSE;", 'target b; relation "=="; value MAYBE;', False),
    ("o t;", 'target o; relation "=="; value "test:9";', False),
    ('str "hello";', 'target str; relation "=="; value hello;', True),
    ('d "1,2";', 'target d; relation "=="; value 1;', False),
    ('l "3";', 'target l; relation "=="; value 3;', True),
])
def test_other_types(props, assertion, expected):
    """Comparisons of the remaining property types"""
    model = Model()
    model.read_glm(TYPES + f"object test {{ name t; {props} object assert {{ {assertion} }}; }}")
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    runner = Runner(model=model)
    assert (runner.returncode == exitcodes.SUCCESS) == expected, runner.stderr

def test_quoted_object():
    """An object name in double quotes"""
    model = Model()
    model.read_glm(TYPES + 'object test { name t; o t; object assert { target o; relation "=="; value t; }; }')
    model.set_property("assert:1", "value", '"t"')
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    assert Runner(model=model).returncode == exitcodes.SUCCESS
