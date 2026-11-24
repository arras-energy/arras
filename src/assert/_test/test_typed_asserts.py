"""Tests of the `double_assert`, `int_assert`, `complex_assert`, and
`enum_assert` classes"""

import sys
import types

import pytest

from arras import exitcodes
from arras.runner import Runner

TEST = """
class test {
    double x[MW];
    double y;
    int16 i16;
    int32 i32;
    int64 i64;
    complex z[V];
    enumeration {A=0, B=1, C=2} e;
    set {X=1, Y=2} s;
}
"""

def check(run, props:str, asserts:str, *args:str, header:bool=True):
    """Run one test object `t` with the given properties and assert objects"""
    return run(TEST + f"object test {{ name t; {props} {asserts} }}", *args, header=header)

def last_error(runner) -> str:
    """Message of the first error line"""
    return next(x for x in runner.stderr if x.startswith("ERROR")).split("]: ", 1)[1]

#
# double_assert
#
@pytest.mark.parametrize("props,assertion,error", [
    ("x 50;", "target x; value 50.5; within 1;", None),
    ("x 50;", "target x; value 52; within 1;", "Assert failed on t: x 50 not within 1.000000 of given value 52"),
    ("x 50;", "target x; value 50.5; within 1; status ASSERT_FALSE;", "Assert failed on t: x 50 is within 1.000000 of given value 50.5"),
    ("x 50;", "target x; value 52; within 1; status ASSERT_FALSE;", None),
    ("x 50;", "target x; value 52; within 1; status ASSERT_NONE;", None),
    ("x 50;", "target x; value 100; within 0.5; within_mode WITHIN_RATIO;", None),
    ("x 50;", "target x; value 100; within 0.4; within_mode WITHIN_RATIO;", "Assert failed on t: x 50 not within 40.000000 of given value 100"),
    ("x 0.0005;", "target x; value 0; within 1; within_mode WITHIN_RATIO;", None),
    ("x 0.002;", "target x; value -1; within 1; within_mode WITHIN_RATIO;", "Assert failed on t: x 0.002 not within 0.001000 of given value -1"),
    ("x nan;", "target x; value 0; within 1;", "Assert failed on t: x nan not within 1.000000 of given value 0"),
    ("x nan;", "target x; value 0; within 1; status ASSERT_FALSE;", "Assert failed on t: x nan is within 1.000000 of given value 0"),
    ("i32 1;", "target i32; value 1; within 1;", "Specified target i32 for t is not valid."),
    ("x 1;", "target nosuch; value 1; within 1;", "Specified target nosuch for t is not valid."),
])
def test_double_assert(run, props, assertion, error):
    """double_assert tolerance modes, outcomes, and messages"""
    runner = check(run, props, f"object double_assert {{ {assertion} }};")
    if error is None:
        assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    else:
        assert runner.returncode == exitcodes.RUNERR
        assert last_error(runner) == error

@pytest.mark.parametrize("within", ["0", "-1"])
def test_double_assert_init(run, within):
    """double_assert refuses a within of zero or less"""
    runner = check(run, "x 1;", f"object double_assert {{ name d; target x; value 1; within {within}; }};")
    assert runner.returncode == exitcodes.INIERR
    assert last_error(runner) == "init_double_assert(obj=1;d): A non-positive value has been specified for within."

def test_double_assert_global(run):
    """A double_assert without a parent tests a global variable"""
    runner = run("object double_assert { target progress; value 0; within 1; };")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    runner = run("object double_assert { target progress; value 5; within 1; };")
    assert last_error(runner) == "Assert failed on global: progress 0 not within 1.000000 of given value 5"

def test_double_assert_verbose(run):
    """double_assert verbose messages carry the object name"""
    runner = run("module assert { message_flags VERBOSE; }" + TEST + """object test { name t; x 1;
        object double_assert { target x; value 1; within 1; };
        object double_assert { target x; value 1; within 1; status ASSERT_NONE; }; }""", "-v")
    assert "VERBOSE [2001-01-01 00:00:00 PST]: double_assert:1: Assert passed on t" in runner.stderr
    assert "VERBOSE [2001-01-01 00:00:00 PST]: double_assert:2: Assert test is not being run on t" in runner.stderr

ONCE = """
clock { timezone "America/Los_Angeles"; starttime "2001-01-01 00:00:00"; stoptime "2001-01-01 04:00:00"; }
module assert { message_flags VERBOSE; }
"""

@pytest.fixture(name="changer")
def fixture_changer():
    """Handler module `assert_test_once`: `sync(name, t)` sets the `value`
    of object `chk` to `5` at 02:00 and asks for an event every hour"""
    def sync(name, t): # pylint: disable=unused-argument
        runner = Runner.current()
        if runner.model.globals.timestamp_to_string(t).startswith("2001-01-01 02:00"):
            runner.model.set_property("chk", "value", "5")
        return t + 3600
    sys.modules["assert_test_once"] = types.SimpleNamespace(sync=sync)
    yield
    del sys.modules["assert_test_once"]

@pytest.mark.parametrize("cname,value,within,error", [
    ("double_assert", "1", "0.5", "Assert failed on t: x 1 not within 0.500000 of given value 5"),
    ("int_assert", "1", "0", "Assert failed on t: i32 1 not within 0 of given value 5"),
    ("complex_assert", "1+0j", "0.5", "Assert failed on t: real part of z 1 not within 0.500000 of given value 5"),
])
def test_once(run, changer, cname, value, within, error): # pylint: disable=unused-argument
    """ONCE_TRUE runs the test once, then only when `value` changes"""
    target = {"double_assert": "x", "int_assert": "i32", "complex_assert": "z"}[cname]
    glm = ONCE + TEST.replace("set {X=1, Y=2} s;", 'set {X=1, Y=2} s; on_sync "python:assert_test_once.sync";') + \
        f"object test {{ name t; x 1; i32 1; z 1+0j; object {cname} {{ name chk; target {target}; value {value}; within {within}; once ONCE_TRUE; }}; }}"
    runner = run(glm, "-v", header=False)
    assert runner.returncode == exitcodes.RUNERR
    assert last_error(runner) == error
    assert runner.model.get_property("chk", "once") == "ONCE_DONE"
    skipped = [x for x in runner.stderr if "Assert skipped with ONCE logic" in x]
    assert [x.split("]")[0] for x in skipped] == ["VERBOSE [2001-01-01 01:00:00 PST"]
    assert any(x.startswith("ERROR [2001-01-01 02:00:00 PST]") for x in runner.stderr)

def test_once_false(run):
    """ONCE_FALSE (the default) runs the test at every time step"""
    runner = check(run, "x 1;", "object double_assert { target x; value 1; within 1; once ONCE_DONE; };")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr

#
# int_assert
#
@pytest.mark.parametrize("props,assertion,error", [
    ("i32 4;", "target i32; value 4; within 1;", None),
    ("i16 4;", "target i16; value 5; within 1;", None),
    ("i64 4;", "target i64; value 6; within 1;", "Assert failed on t: i64 4 not within 1 of given value 6"),
    ("i32 4;", "target i32; value 4; within 1; status ASSERT_FALSE;", "Assert failed on t: i32 4 is within 1 of given value 4"),
    ("i32 4;", "target i32; value 4; within 0; status ASSERT_FALSE;", None),
    ("i32 4;", "target i32; value 10; within 0; status ASSERT_NONE;", None),
    ("i32 13;", "target i32; value 10; within 0; within_mode WITHIN_RATIO;", "Assert failed on t: i32 13 not within 1 of given value 10"),
    ("i32 13;", "target i32; value 10; within 3; within_mode WITHIN_RATIO;", None),
    # negative int32 values are read as unsigned 32-bit numbers
    ("i32 -5;", "target i32; value -5; within 0;", "Assert failed on t: i32 -5 not within 0 of given value -5"),
    ("x 1;", "target x; value 1; within 1;", "Specified target x for t is not valid."),
])
def test_int_assert(run, props, assertion, error):
    """int_assert tolerance modes, outcomes, messages, and the unsigned
    reading of value and within"""
    runner = check(run, props, f"object int_assert {{ {assertion} }};")
    if error is None:
        assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    else:
        assert runner.returncode == exitcodes.RUNERR
        assert last_error(runner) == error

def test_int_assert_warning(run):
    """A difference beyond 32 bits gives a warning"""
    runner = check(run, "i32 -5;", "object int_assert { target i32; value -5; within 0; };")
    assert "WARNING [2001-01-01 00:00:00 PST]: int_assert may be incorrect, difference range outside 32-bit abs() range" in runner.stderr

def test_int_assert_negative_within(run):
    """A negative within is read as a large unsigned number, so the
    initialization check never fails; the tolerance is then its low 32
    bits as an int, so the test always fails"""
    runner = check(run, "i32 4;", "object int_assert { target i32; value 4; within -1; };")
    assert runner.returncode == exitcodes.RUNERR
    assert last_error(runner) == "Assert failed on t: i32 4 not within -1 of given value 4"

def test_int_assert_verbose(run):
    """int_assert verbose messages carry the object name"""
    runner = run("module assert { message_flags VERBOSE; }" + TEST + """object test { name t; i32 1;
        object int_assert { target i32; value 1; within 0; };
        object int_assert { target i32; value 1; within 0; status ASSERT_NONE; }; }""", "-v")
    assert "VERBOSE [2001-01-01 00:00:00 PST]: int_assert:1: Assert passed on t" in runner.stderr
    assert "VERBOSE [2001-01-01 00:00:00 PST]: int_assert:2: Assert test is not being run on t" in runner.stderr

def test_int_assert_global(run):
    """An int_assert without a parent tests a global variable"""
    runner = run("object int_assert { target iteration_limit; value 100; within 0; };")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr

#
# complex_assert
#
@pytest.mark.parametrize("props,assertion,error", [
    ("z 120+1j;", "target z; value 120+1j; within 0.5;", None),
    ("z 120+1j;", "target z; value 121+1j; within 0.5;", "Assert failed on t: real part of z 120 not within 0.500000 of given value 121"),
    ("z 120+1j;", "target z; value 120+2j; within 0.5;", "Assert failed on t: imaginary part of z +1i not within 0.500000 of given value +2i"),
    ("z 120+1j;", "target z; value 120+2j; within 0.5; operation REAL;", None),
    ("z 120+1j;", "target z; value 121+1j; within 0.5; operation IMAGINARY;", None),
    ("z 120+1j;", "target z; value 125+1j; within 1; status ASSERT_FALSE;", "Assert failed on t: imaginary part of z +1i is within 1.000000 of given value +1i"),
    ("z 120+1j;", "target z; value 120.5+5j; within 1; status ASSERT_FALSE;", "Assert failed on t: real part of z 120 is within 1.000000 of given value 120.5"),
    ("z 120+1j;", "target z; value 125+5j; within 1; status ASSERT_FALSE;", None),
    ("z 3+4j;", "target z; value 5; within 0.1; operation MAGNITUDE;", None),
    ("z 3+4j;", "target z; value 5; within 0.1; operation MAGNITUDE; status ASSERT_FALSE;", "Assert failed on t: Magnitude of z 5 is within 0.100000 of given value 5"),
    ("z 1+1j;", "target z; value 2+2j; within 0.1; operation ANGLE; status ASSERT_FALSE;", "Assert failed on t: Angle of z 0.785398 is within 0.100000 of given value 0.785398"),
    ("z 1+1j;", "target z; value 2+2j; within 0.1; operation ANGLE;", None),
    ("z 1+1j;", "target z; value 1+1j; within 0.1; status ASSERT_NONE; operation MAGNITUDE;", None),
    # the value has no unit: it is not converted from kV
    ("z 120+1j;", "target z; value 0.12+0.001j; within 0.5;", "Assert failed on t: real part of z 120 not within 0.500000 of given value 0.12"),
    ("x 1;", "target x; value 1; within 1;", "Specified target x for t is not valid."),
])
def test_complex_assert(run, props, assertion, error):
    """complex_assert operations, outcomes, and messages"""
    runner = check(run, props, f"object complex_assert {{ {assertion} }};")
    if error is None:
        assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    else:
        assert runner.returncode == exitcodes.RUNERR
        assert last_error(runner) == error

def test_complex_assert_init(run):
    """complex_assert refuses a within of zero or less"""
    runner = check(run, "z 1;", "object complex_assert { target z; value 1; };")
    assert runner.returncode == exitcodes.INIERR
    assert last_error(runner) == "init_complex_assert(obj=1;unnamed): A non-positive value has been specified for within."

def test_complex_value_forms(run):
    """Complex values in rectangular, polar degree, and polar radian form,
    and with a unit on the target"""
    runner = check(run, "z 0+2j;", """
        object complex_assert { target z; value 2+90d; within 1e-9; };
        object complex_assert { target z; value 2+1.5707963267948966r; within 1e-9; };
        object complex_assert { target z; value 0+2i; within 1e-9; };""")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    runner = check(run, "z 0.12+0j kV;", "object complex_assert { target z; value 120; within 1e-9; };")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr

def test_complex_assert_verbose(run):
    """complex_assert verbose messages have no object name (gl_verbose)"""
    runner = check(run, "z 1;", """
        object complex_assert { target z; value 1; within 1; };
        object complex_assert { target z; value 1; within 1; status ASSERT_NONE; };""", "-v")
    assert "VERBOSE [2001-01-01 00:00:00 PST]: Assert passed on t" in runner.stderr
    assert "VERBOSE [2001-01-01 00:00:00 PST]: Assert test is not being run on t" in runner.stderr

#
# enum_assert
#
@pytest.mark.parametrize("props,assertion,error", [
    ("e B;", "target e; value 1;", None),
    ("e B;", "target e; value 2;", "Assert failed on t: e=1 did not match 2"),
    ("e B;", "target e; value 1; status ASSERT_FALSE;", "Assert failed on t: e=1 did match 1"),
    ("e B;", "target e; value 2; status ASSERT_FALSE;", None),
    ("e B;", "target e; value 2; status ASSERT_NONE;", None),
    ('s "X";', "target s; value 1;", "Specified target s for t is not valid."),
])
def test_enum_assert(run, props, assertion, error):
    """enum_assert outcomes and messages"""
    runner = check(run, props, f"object enum_assert {{ {assertion} }};")
    if error is None:
        assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    else:
        assert runner.returncode == exitcodes.RUNERR
        assert last_error(runner) == error

def test_enum_assert_verbose(run):
    """enum_assert verbose messages have no object name (gl_verbose)"""
    runner = check(run, "e A;", """
        object enum_assert { target e; value 0; };
        object enum_assert { target e; value 0; status ASSERT_FALSE; };""", "-v")
    assert "VERBOSE [2001-01-01 00:00:00 PST]: Assert passed on t" in runner.stderr
    runner = check(run, "e A;", "object enum_assert { target e; value 0; status ASSERT_NONE; };", "-v")
    assert "VERBOSE [2001-01-01 00:00:00 PST]: Assert test is not being run on t" in runner.stderr
    runner = check(run, "e A;", "object enum_assert { target e; value 1; status ASSERT_FALSE; };", "-v")
    assert "VERBOSE [2001-01-01 00:00:00 PST]: Assert passed on t" in runner.stderr

def test_enum_assert_global(run):
    """An enum_assert without a parent tests a global variable"""
    runner = run("object enum_assert { target dateformat; value 0; };")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
