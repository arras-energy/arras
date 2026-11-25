"""The `pypower` controllers module and object controllers"""

import pytest

from arras import exitcodes

CONTROLLERS = '''
import sys
calls = []

def on_init():
    return INIT

def on_precommit(data):
    calls.append(("precommit", data["t"]))
    return PRECOMMIT

def on_sync(data):
    calls.append(("sync", data["t"]))
    return SYNC

def on_commit(data):
    calls.append(("commit", data["t"]))
    return COMMIT

def on_term():
    calls.append(("term",))
    return TERM

def raises(obj, **kwargs):
    raise RuntimeError("controller failed")

def not_dict(obj, **kwargs):
    return 5

def bad_property(obj, **kwargs):
    return {"nothing": 1, "t": kwargs["t"] + 600}

def bad_value(obj, **kwargs):
    return {"status": "MAYBE"}

def set_load(obj, **kwargs):
    calls.append(("load", obj, sorted(kwargs)))
    return {"P": 5+1j} if kwargs["P"] == 0 else {}

def open_relay(obj, **kwargs):
    calls.append(("relay", obj, kwargs["status"]))
    return {"status": 1, "t": kwargs["t"] + 3600}

not_callable = 5
'''

def controllers(helpers, init="True", precommit="-1", sync="-1", commit="-1", term="None", extra="") -> None:
    """Write `controllers.py`"""
    text = CONTROLLERS
    for key, value in (("INIT", init), ("PRECOMMIT", precommit), ("SYNC", sync), ("COMMIT", commit), ("TERM", term)):
        text = text.replace(f"return {key}", f"return {value}")
    helpers.write("controllers.py", text + extra)

def run(helpers, glm:str="", stop:str="2020-01-01 00:00:00"):
    """Run the three-bus network with the controllers module"""
    return helpers.run(helpers.THREE_BUS + 'module pypower { controllers "controllers"; controllers_path "."; }\n' + glm, stop=stop)

def module():
    """The controllers module of the last run"""
    import sys # pylint: disable=import-outside-toplevel
    return sys.modules["controllers"]

def test_module_functions(helpers):
    """`on_precommit`, `on_sync`, `on_commit`, and `on_term` are called with
    the solver data; the sync time is an event (the precommit time is lost
    when the first solution makes the time step iterate)"""
    controllers(helpers, precommit="data['t'] + 1800", sync="data['t'] + 3600")
    runner = run(helpers, stop="2020-01-01 01:00:00")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert [x[0] for x in module().calls] == ["precommit", "sync", "sync", "commit", "precommit", "sync", "commit", "term"]
    assert runner.steps == 2

@pytest.mark.parametrize("kwargs, code, message", [
    ({"init": "False"}, exitcodes.INIERR, "controllers.on_init() failed (returned False)"),
    ({"init": "1"}, exitcodes.INIERR, "controllers.on_init() returned non-boolean value"),
    ({"init": "None"}, exitcodes.INIERR, "controllers.on_init() returned non-boolean value"),
    ({"init": "1/0"}, exitcodes.INIERR, "ZeroDivisionError: division by zero"),
    ({"sync": "'x'"}, exitcodes.RUNERR, "controllers.on_sync(data) returned value that is not a valid timestamp"),
    ({"sync": "data['t'] - 1"}, exitcodes.RUNERR, "returned a timestamp earlier than on_sync time"),
    ({"sync": "1/0"}, exitcodes.RUNERR, "ZeroDivisionError"),
    ({"precommit": "data['t'] - 1"}, exitcodes.RUNERR, "returned a timestamp earlier than precommit time"),
    ({"commit": "data['t']"}, exitcodes.RUNERR, "model commit failed"),
])
def test_module_errors(helpers, kwargs, code, message):
    """Controllers module errors"""
    controllers(helpers, **kwargs)
    runner = run(helpers)
    assert runner.returncode == code, runner.stderr
    assert any(message in x for x in helpers.errors(runner)), runner.stderr

def test_halt(helpers):
    """A time of 0 halts the run when `stop_on_failure` is true"""
    controllers(helpers, sync="0")
    runner = run(helpers, "module pypower { stop_on_failure TRUE; }")
    assert runner.returncode == exitcodes.RUNERR
    assert any("controllers.on_sync(data) halted the simulation" in x for x in helpers.errors(runner))

def test_term_result(helpers):
    """A result from `on_term` is ignored with a warning; an exception is
    an error line"""
    controllers(helpers, term="5")
    runner = run(helpers)
    assert any("ignored return value from on_term()" in x for x in helpers.warnings(runner))
    controllers(helpers, term="1/0")
    runner = run(helpers)
    assert any("ZeroDivisionError" in x for x in helpers.errors(runner))

def test_not_callable(helpers):
    """Module functions that are not callable fail the initialization"""
    controllers(helpers, extra="on_sync = 5\n")
    runner = run(helpers)
    assert runner.returncode == exitcodes.INIERR
    assert any("controllers.on_sync is not callable" in x for x in helpers.errors(runner))
    helpers.write("controllers.py", "on_init = 5\n")
    runner = run(helpers)
    assert any("controllers.on_init is not callable" in x for x in helpers.errors(runner))

def test_missing_module(helpers):
    """A controllers module that cannot be imported fails the
    initialization"""
    runner = helpers.run(helpers.THREE_BUS + 'module pypower { controllers "no_such_controllers"; }')
    assert runner.returncode == exitcodes.INIERR
    assert any("ModuleNotFoundError" in x for x in helpers.errors(runner))

def test_load_controller(helpers):
    """A load controller gets the load's values and sets its properties;
    the load asks to run again when it sets properties without a time"""
    controllers(helpers)
    runner = run(helpers, 'object load { name l1; parent b2; status ONLINE; controller "set_load"; }')
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    calls = [x for x in module().calls if x[0] == "load"]
    assert calls[0][1] == "l1"
    assert calls[0][2] == ["I", "P", "S", "V", "Z", "response", "status", "t"]
    assert runner.model.get_property("l1", "P") == "5+1j"

def test_relay_controller(helpers):
    """A relay controller opens the relay, which takes its branch out"""
    controllers(helpers)
    runner = run(helpers, 'object relay { name r1; parent l13; controller "open_relay"; }')
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert runner.model.get_property("r1", "status") in ("1", "OPEN")
    assert runner.model.get_property("l13", "status") == "OUT"

@pytest.mark.parametrize("controller, code, message", [
    ("raises", exitcodes.SUCCESS, "RuntimeError: controller failed"),
    ("not_dict", exitcodes.RUNERR, "controller return value not a property update dictionary"),
    ("bad_property", exitcodes.RUNERR, "controller return property 'nothing' is not valid"),
    ("nothing", exitcodes.INIERR, "pypower controller 'nothing' is not found"),
    ("not_callable", exitcodes.INIERR, "pypower controller 'not_callable' is not callable"),
])
def test_object_controller_errors(helpers, controller, code, message):
    """Object controller errors"""
    controllers(helpers)
    runner = run(helpers, f'object powerplant {{ parent b2; status ONLINE; controller "{controller}"; }}')
    assert runner.returncode == code, runner.stderr
    assert any(message in x for x in helpers.errors(runner)), runner.stderr

def test_controller_value_not_accepted(helpers):
    """A value that a property does not accept is a warning"""
    controllers(helpers)
    runner = run(helpers, 'object load { parent b2; status ONLINE; controller "bad_value"; }')
    assert any("controller return value status='MAYBE' is not accepted" in x for x in helpers.warnings(runner))

def test_controller_exception_stops(helpers):
    """A controller exception stops the run when `stop_on_failure` is
    true"""
    controllers(helpers)
    runner = run(helpers, 'module pypower { stop_on_failure TRUE; } object relay { parent l13; controller "raises"; }')
    assert runner.returncode == exitcodes.RUNERR

def test_scada(helpers):
    """A SCADA object shares its points (points not found are ignored),
    records them to the historian, and writes them back"""
    controllers(helpers, extra='''
def on_sync(data):
    scada["s1"]["b2.Pd"] = "45"
    return -1
''')
    runner = run(helpers, "object scada { name s1; point b2.Vm; point b2.Pd; point nothing.x; write TRUE; record TRUE; }")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert runner.model.get_property("s1", "point") == "b2.Vm,b2.Pd,nothing.x"
    assert set(module().scada["s1"]) == {"b2.Vm", "b2.Pd"}
    assert float(runner.model.get_property("b2", "Pd")) == 45
    assert len(module().historian["s1"]) == 1

def test_scada_no_controllers(helpers):
    """A SCADA object needs the controllers module"""
    runner = helpers.run(helpers.THREE_BUS + "object scada { point b2.Vm; }")
    assert runner.returncode == exitcodes.INIERR
    assert any("unable to find global controllers" in x for x in helpers.errors(runner))
