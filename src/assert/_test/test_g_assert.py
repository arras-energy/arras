"""Tests of the `assert` class"""

import importlib

import pytest

from arras import exitcodes

TEST = """
class test {
    double x[MW];
    int16 i16;
    int32 i32;
    int64 i64;
    char32 c32;
    bool b;
    object o;
    complex z[V];
    timestamp ts;
    enumeration {A=0, B=1} e;
    set {X=1, Y=2} s;
    randomvar r;
    double note;
}
"""

def check(run, props:str, asserts:str, *args:str):
    """Run one test object with the given properties and assert objects"""
    return run(TEST + f"object test {{ name t; {props} {asserts} }}", *args)

def ok(runner):
    """`True` when the run succeeded"""
    return runner.returncode == exitcodes.SUCCESS

@pytest.mark.parametrize("props,assertion,expected", [
    # real numbers: within is the tolerance of == and !=
    ("x 50;", 'target x; relation "=="; value 50.4; within 0.5;', True),
    ("x 50;", 'target x; relation "=="; value 50.4; within 0.3;', False),
    ("x 50;", 'target x; relation "=="; value 50.4;', False),
    ("x 50;", 'target x; relation "!="; value 50.4; within 0.3;', True),
    ("x 50;", 'target x; relation "!="; value 50.4; within 0.5;', False),
    ("x 50;", 'target x; relation "=="; value "50000 kW";', True),
    ("x 50;", 'target x; relation ">="; value 50;', True),
    ("x 50;", 'target x; relation "<"; value 50;', False),
    ("x 50;", 'target x; relation "inside"; lower 50; upper 50;', True),
    ("x 50;", 'target x; relation "outside"; lower 50; upper 51;', False),
    ("x 50;", 'target x; relation "inside"; lower 49; upper "";', False),
    ("x 50;", 'target x; relation "outside"; lower 49; upper "";', True),
    # value and lower share storage: the one set last is used
    ("x 3;", 'target x; relation "=="; value 1; lower 3;', True),
    ("x 3;", 'target x; relation "=="; lower 3; value 1;', False),
    # complex values compare their real part
    ("z 120+50j;", 'target z; relation "=="; value 120;', True),
    ("z 120+50j;", 'target z; relation "=="; value "120+0j";', True),
    ("z 120+50j;", 'target z; relation ">"; value "121+0j";', False),
    # integers compare their low 32 bits; int16 its unsigned 16 bits
    ("i32 -5;", 'target i32; relation "<"; value 0;', True),
    ("i64 4294967296;", 'target i64; relation "=="; value 0;', True),
    ("i64 4294967296;", 'target i64; relation "<"; value 1;', True),
    ("i16 -1;", 'target i16; relation "<"; value 0;', False),
    ("i16 -1;", 'target i16; relation "=="; value 65535;', True),
    # strings compare bytes
    ('c32 "b";', 'target c32; relation ">"; value "a";', True),
    ('c32 "b";', 'target c32; relation "inside"; lower "a"; upper "c";', True),
    ('c32 "abc";', 'target c32; relation "=="; value "abc";', True),
    # bool and object support == and !=
    ("b TRUE;", 'target b; relation "=="; value 1;', True),
    ("b TRUE;", 'target b; relation "<"; value 1;', False),
    ("o t;", 'target o; relation "=="; value t;', True),
    ("o t;", 'target o; relation "=="; value "test:0";', True),
    ("o t;", 'target o; relation "!="; value nobody;', True),
    ("", 'target o; relation "=="; value 0;', True),
    ("o t;", 'target o; relation ">"; value t;', False),
    # enumerations and sets
    ("e B;", 'target e; relation "=="; value B;', True),
    ("e B;", 'target e; relation "=="; value 1;', True),
    ("e B;", 'target e; relation "=="; value C;', False),
    ('s "X|Y";', 'target s; relation "=="; value 3;', True),
    ('s "X|Y";', 'target s; relation "=="; value "Y|X";', True),
    ('s "X";', 'target s; relation "=="; value "Z";', False),
    # timestamps
    ("ts '2001-07-04 12:34:56';", "target ts; relation \"==\"; value '2001-07-04 12:34:56';", True),
    ("ts '2001-07-04 12:34:56';", "target ts; relation \"<\"; value '2001-07-04 12:34:55';", False),
    # parts
    ("z 3+4j;", 'target z; part mag; relation "=="; value 5;', True),
    ("z 0+1j;", 'target z; part ang; relation "=="; value 90;', True),
    ("z 0+1j;", 'target z; part arg; relation "inside"; lower 1.5707; upper 1.5708;', True),
    ("z 3+4j;", 'target z; part imag; relation "=="; value 4.1; within 0.2;', True),
    ("z 3+4j;", 'target z; part foo; relation "=="; value 5;', False),
    ("x 1;", 'target x; part real; relation "=="; value 1;', False),
    ("ts '2001-07-04 12:34:56';", 'target ts; part hour; relation "=="; value 12;', True),
    ("ts '2001-07-04 12:34:56';", 'target ts; part isdst; relation "=="; value 1;', True),
    ("ts '2001-07-04 12:34:56';", 'target ts; part tzoffset; relation "=="; value 25200;', True),
    ("ts '2001-01-04 12:34:56';", 'target ts; part tzoffset; relation "=="; value 28800;', True),
    ("ts '2001-07-04 12:34:56';", 'target ts; part weekday; relation "=="; value 3;', True),
    ("ts '2001-07-04 12:34:56';", 'target ts; part yearday; relation "=="; value 184;', True),
    ("ts '2001-07-04 12:34:56';", 'target ts; part nanosecond; relation "=="; value 0;', True),
    ("ts '2001-07-04 12:34:56';", 'target ts; part minutes; relation ">"; value 16271000;', True),
    ("", 'target ts; part hour; relation "=="; value 0;', False),
    ("", 'target ts; part seconds; relation "=="; value 0;', True),
    ("o t;", 'target o; part id; relation "=="; value 0;', True),
    ("o t;", 'target o; part clock.year; relation "=="; value 2001;', True),
    ("o t;", 'target o; part out_svc.year; relation "=="; value 0;', False),
    ("o t;", 'target o; part schedule_skew; relation "=="; value 0;', True),
    ("o t;", 'target o; part latitude; relation "=="; value 0;', False),
    ("o t;", 'target o; part nothing; relation "=="; value 0;', False),
    ("", 'target o; part id; relation "=="; value 0;', False),
    ('r "type:uniform(2,5); min:1; max:9";', 'target r; part a; relation "=="; value 2;', True),
    ('r "type:uniform(2,5); min:1; max:9";', 'target r; part b; relation "=="; value 5;', True),
    ('r "type:uniform(2,5); min:1; max:9";', 'target r; part low; relation "=="; value 1;', True),
    ('r "type:uniform(2,5); min:1; max:9";', 'target r; part high; relation "=="; value 9;', True),
    ('r "type:normal(2)";', 'target r; part b; relation "=="; value 0;', True),
    ('r "type:uniform(2,5)";', 'target r; part value; relation "=="; value 0;', False),
    ('r "type:uniform(2,5)";', 'target r; relation "=="; value 0;', True),
    ('r "0.25";', 'target r; relation "=="; value 0.25;', True),
])
def test_relations(run, props, assertion, expected):
    """Comparisons follow the core's property comparison rules"""
    runner = check(run, props, f"object assert {{ {assertion} }};")
    assert ok(runner) == expected, runner.stderr

def test_failure_message(run):
    """A failure writes the object, target, part, value, relation, value, and within"""
    runner = check(run, "x 50; z 3+4j;", """
        object assert { name chk; target z; part mag; relation ">"; value 6; within 0.1; };""")
    assert runner.returncode == exitcodes.RUNERR
    assert runner.stderr[0] == "ERROR [2001-01-01 00:00:00 PST]: chk: chk: assert failed on 't.z.mag.3+4j' '>' '6' '0.1'"
    assert runner.stderr[1] == "ERROR [2001-01-01 00:00:00 PST]: object chk commit failed"

@pytest.mark.parametrize("status,expected,prefix", [
    ("TRUE", False, ""),
    ("FALSE", True, None),
    ("NONE", True, None),
    ("INIT", True, None),
    ("ERROR", False, "NOT "),
])
def test_status(run, status, expected, prefix):
    """`status` gives the desired outcome; NONE (INIT) skips the test and
    ERROR always fails"""
    runner = check(run, "x 1;", f'object assert {{ target x; relation "=="; value 2; status {status}; }};')
    assert ok(runner) == expected
    if prefix is not None:
        assert f"assert failed on {prefix}'t.x" in runner.stderr[0]

def test_conversion_warnings(run):
    """Values that cannot be converted, and unsupported relations, give
    warnings and fail"""
    runner = check(run, "x 50;", 'object assert { target x; relation "=="; value "50 V"; };')
    assert "WARNING [2001-01-01 00:00:00 PST]: property type 'double' cannot compare to value '50 V'" in runner.stderr[0]
    runner = check(run, "x 50;", 'object assert { target x; relation "inside"; lower 1; upper "x"; };')
    assert "cannot compare to value 'x'" in runner.stderr[0]
    runner = check(run, "b TRUE;", 'object assert { target b; relation "<"; value 1; };')
    assert runner.stderr[0] == "WARNING [2001-01-01 00:00:00 PST]: property type 'bool' does not support comparison operations or parts"
    runner = check(run, "z 1+1j;", 'object assert { target z; part foo; relation "<"; value 1; };')
    assert runner.stderr[0] == "ERROR [2001-01-01 00:00:00 PST]: part foo is not defined for type complex"
    runner = check(run, "i32 1;", 'object assert { target i32; relation "=="; value ""; };')
    assert "cannot compare to value ''" in runner.stderr[0]

def test_global_target(run):
    """An assert with no parent and no group tests a global variable"""
    runner = run('object assert { target clock; relation ">"; value "2000-01-01 00:00:00"; };')
    assert ok(runner), runner.stderr
    runner = run('object assert { target clock; relation "<"; value "2000-01-01 00:00:00"; };')
    assert "assert failed on 'global variable.clock..2001-01-01 00:00:00 PST'" in runner.stderr[0]

def test_missing_target(run):
    """A target that does not exist fails the initialization"""
    runner = run('object assert { target nosuch; relation "=="; value 1; };')
    assert runner.returncode == exitcodes.INIERR
    assert runner.stderr[0] == "ERROR [INIT]: init_assert(obj=0;unnamed): assert:0: target 'global' property 'nosuch' does not exist"
    runner = check(run, "", 'object assert { name chk; target nosuch; relation "=="; value 1; };')
    assert runner.stderr[0] == "ERROR [INIT]: init_assert(obj=1;chk): chk: target 't' property 'nosuch' does not exist"

def test_group(run):
    """`group` selects the targets"""
    objects = "object test:..3 { x 1; } object test { name other; x 2; groupid special; }"
    runner = run(TEST + objects + 'object assert { group "class=test"; target x; relation "<="; value 2; };')
    assert ok(runner), runner.stderr
    runner = run(TEST + objects + 'object assert { group "class=test"; target x; relation "=="; value 1; };')
    assert "assert failed on 'other.x..2'" in runner.stderr[0]
    runner = run(TEST + objects + 'object assert { group "class=test AND groupid=special"; target x; relation "=="; value 2; };')
    assert ok(runner), runner.stderr
    runner = run(TEST + objects + 'object assert { group "isa=test; id<2"; target x; relation "=="; value 1; };')
    assert ok(runner), runner.stderr
    runner = run(TEST + objects + 'object assert { group "name!=other"; target x; relation "=="; value 1; };')
    assert "property 'x' does not exist" in runner.stderr[0]  # the assert object itself is selected

@pytest.mark.parametrize("group,messages", [
    ("class=nosuch", ["class 'nosuch' not found", "init_assert(obj=4;unnamed): assert:4: group 'class=nosuch' is not valid"]),
    ("module=nosuch", ["module 'nosuch' not found", "group 'module=nosuch' is not valid"]),
    ("parent=nosuch", ["parent 'nosuch' not found", "group 'parent=nosuch' is not valid"]),
    ("flags=1", ["find expression refers to unknown or unsupported property 'flags'", "is not valid"]),
    ("name~x", ["find operator 'LIKE' is not supported", "is not valid"]),
    ("!!", ["find expression syntax error at '!!'", "is not valid"]),
    ("id=-1", ["id -1 is invalid", "is not valid"]),
])
def test_group_errors(run, group, messages):
    """Group specifications that are not valid fail the initialization"""
    runner = run(TEST + f'object test:..4 {{ x 1; }} object assert {{ group "{group}"; target x; relation "=="; value 1; }};')
    assert runner.returncode == exitcodes.INIERR
    for message, line in zip(messages, runner.stderr):
        assert message in line

@pytest.mark.parametrize("group,targets", [
    ("parent=p", ["test:1"]),
    ("rank>=5", ["test:1"]),
    ("rank<5 AND class=test", ["p"]),
    ("id>0 and id<2", ["test:1"]),
    ("parent=root", None),     # p and the assert object, which has no x
    ("module=assert", None),   # the assert object
])
def test_group_other_terms(run, group, targets):
    """Group terms on module, parent, rank, id"""
    runner = run(TEST + "object test { name p; x 1; object test { x 2; rank 5; }; }" +
        f'object assert {{ group "{group}"; target x; relation ">"; value 0; }};')
    if targets is None:
        assert runner.returncode == exitcodes.INIERR
        assert "property 'x' does not exist" in runner.stderr[0]
    else:
        assert ok(runner), runner.stderr
        state = importlib.import_module("assert._common").get_state(runner.model, "assert:2")
        assert [x.name for x in state.targets] == targets

def test_group_empty(run):
    """A group that selects nothing gives a warning"""
    runner = run(TEST + 'object test { x 1; } object assert { group "name=nobody"; target x; relation "=="; value 1; };')
    assert ok(runner)
    assert runner.stderr == ["WARNING [INIT]: assert:1: group 'name=nobody' contains no objects"]
    runner = run(TEST + 'object test { x 1; } object assert { group "name=nobody"; target x; relation "=="; value 1; flags 131072; };')
    assert runner.stderr == []

HOURLY = """
clock { timezone "America/Los_Angeles"; starttime "2001-01-01 00:00:00"; stoptime "2001-01-01 03:00:00"; }
module assert;
class tick { double x; on_sync "python:assert_test_random.hourly"; }
object tick { name t; x 1; }
"""

def test_start_stop(run):
    """Tests run only from `start` to `stop`"""
    runner = run(HOURLY + 'object assert { parent t; target x; relation "=="; value 2; start "2001-01-01 02:00:00"; };', header=False)
    assert runner.stderr[0].startswith("ERROR [2001-01-01 02:00:00 PST]: assert:1: assert:1: assert failed")
    runner = run(HOURLY + 'object assert { parent t; target x; relation "=="; value 2; start "2001-01-01 02:00:00 PST"; };', header=False)
    assert runner.stderr[0].startswith("ERROR [2001-01-01 02:00:00 PST]")
    runner = run(HOURLY + 'object assert { parent t; target x; relation "=="; value 2; stop "2000-12-31 23:00:00"; };', header=False)
    assert ok(runner) and runner.steps == 4
    runner = run(HOURLY + 'object assert { parent t; target x; relation "=="; value 2; start "2001-01-01 05:00:00"; };', header=False)
    assert ok(runner)

def test_hold(run):
    """`hold` delays failures, and verbose messages report the hold"""
    glm = HOURLY + 'object assert { parent t; target x; relation "=="; value 2; hold 1.5 h; flags 524288; };'
    runner = run(glm, "-v", header=False)
    assert runner.returncode == exitcodes.RUNERR
    lines = [x for x in runner.stderr if "assert:1" in x]
    assert lines[0] == "VERBOSE [INIT]: assert:1: group = ''"
    assert lines[1] == "VERBOSE [2001-01-01 00:00:00 PST]: assert:1: assert:1: assert t started at 978336000 with hold for 5400 s"
    assert lines[2].startswith("ERROR [2001-01-01 02:00:00 PST]: assert:1: assert:1: assert failed")

def test_verbose(run):
    """VERBOSE objects report passed tests and tests that are not run"""
    runner = check(run, "x 1;", """
        object assert { target x; relation "=="; value 1; };
        object assert { target x; relation "=="; value 2; status NONE; };""", "-v")
    assert ok(runner)
    assert not any("assert passed" in x for x in runner.stderr)
    runner = run('module assert { message_flags VERBOSE; }' + TEST + """object test { name t; x 1;
        object assert { target x; relation "=="; value 1; };
        object assert { target x; relation "=="; value 2; status NONE; }; }""", "-v")
    assert "VERBOSE [2001-01-01 00:00:00 PST]: assert:1: assert:1: assert passed on t" in runner.stderr
    assert "VERBOSE [2001-01-01 00:00:00 PST]: assert:2: assert:2: assert test is not being run" in runner.stderr

def test_quiet(run):
    """QUIET objects write no error, but still fail"""
    runner = run('module assert { message_flags QUIET; }' + TEST + """object test { x 1;
        object assert { target x; relation "=="; value 2; }; }""")
    assert runner.returncode == exitcodes.RUNERR
    assert not any("assert failed" in x for x in runner.stderr)
    runner = check(run, "x 1;", 'object assert { target x; relation "=="; value 2; flags "0x10000"; };')
    assert not any("assert failed" in x for x in runner.stderr)

def test_enduse(run):
    """Enduse values and parts"""
    glm = "class load { enduse u; }"
    runner = run(glm + 'object load { u "power_fraction:0.5; power.real:2; power.imag:1; current_fraction"; '
        'object assert { target u; part power_fraction; relation "=="; value 0.5; }; '
        'object assert { target u; part current_fraction; relation "=="; value 1; }; '
        'object assert { target u; part power.mag; relation "inside"; lower 2.23; upper 2.24; }; '
        'object assert { target u; part power.imag; relation "=="; value 1; }; '
        'object assert { target u; part total.real; relation "=="; value 0; }; '
        'object assert { target u; relation "=="; value 0; }; }')
    assert ok(runner), runner.stderr
    runner = run(glm + 'object load { u "3"; object assert { target u; relation "=="; value 3; }; '
        'object assert { target u; part motorA.foo; relation "=="; value 0; }; }')
    assert "part motorA.foo is not defined for type enduse" in runner.stderr[0]
