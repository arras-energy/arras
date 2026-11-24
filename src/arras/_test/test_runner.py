"""Tests of arras.runner"""
# pylint: disable=missing-function-docstring,redefined-outer-name,protected-access,unused-argument,line-too-long,use-implicit-booleaness-not-comparison

import os
import json
import doctest
import threading

import pytest

import arras.runner
import arras.globals
from arras import exitcodes
from arras.main import main
from arras.oclass import Class
from arras.model import Model
from arras.module import Module
from arras.runner import Runner, RunnerError, TS_INVALID, TS_NEVER

H = 3600
START = 1577836800 # 2020-01-01 00:00:00 UTC
LOG = []
STATE = {}

@pytest.fixture(autouse=True)
def registry():
    """Start and end each test with empty class and module registries and log"""
    Class.reset()
    Module.reset()
    LOG.clear()
    STATE.clear()
    yield
    Class.reset()
    Module.reset()

def make(body:str="", stop:str="2020-01-01 03:00:00 UTC", classes:str="class thing { double x; }") -> Model:
    model = Model()
    model.read_glm(f"""
clock {{
    starttime "2020-01-01 00:00:00 UTC";
    stoptime "{stop}";
}}
{classes}
{body}
""")
    return model

#
# Handlers (called as python:test_runner.NAME)
#
def hourly(name, t):
    LOG.append(("sync", name, t))
    return t + H

def log_presync(name, t):
    LOG.append(("presync", name, t))

def log_sync(name, t):
    LOG.append(("sync", name, t))
    return t + H

def log_postsync(name, t):
    LOG.append(("postsync", name, t))

def log_precommit(name, t):
    LOG.append(("precommit", name, t))
    return t

def log_commit(name, t):
    LOG.append(("commit", name, t))

def log_init(name, t):
    LOG.append(("init", name, t))
    return True

def log_finalize(name, t):
    LOG.append(("finalize", name, t))

def iterate_once(name, t):
    LOG.append(("sync", name, t))
    if STATE.get(name) != t:
        STATE[name] = t
        return t
    return t + H

def always_now(name, t):
    return t

def backwards(name, t):
    return t - 1

def invalid(name, t):
    return TS_INVALID

def soft_hourly(name, t):
    LOG.append(("sync", name, t))
    return -(t + H)

def soft_three(name, t):
    LOG.append(("sync", name, t))
    return -(t + H) if t < START + 2*H else None

def three_steps(name, t):
    LOG.append(("sync", name, t))
    return t + H if t < START + 2*H else None

def plus_one(name, t):
    LOG.append(("sync", name, t))
    return t + 1

def commit_now(name, t):
    return t

def commit_half(name, t):
    return t + H // 2

def commit_zero(name, t):
    return 0

def commit_invalid(name, t):
    return TS_INVALID

def precommit_early(name, t):
    return t - 1

def init_false(name, t):
    return False

def init_defer_once(name, t):
    LOG.append(("init", name, t))
    if name not in STATE:
        STATE[name] = True
        return 2
    return True

def init_defer(name, t):
    return 2

def init_bad(name, t):
    return "yes"

def finalize_fail(name, t):
    LOG.append(("finalize", name, t))
    raise ValueError("cannot close")

def raises(name, t):
    raise RuntimeError("broken")

def returns_bool(name, t):
    return True

def returns_text(name, t):
    return "soon"

def current(name, t):
    runner = Runner.current()
    LOG.append((runner is not None, runner.model.get_property(name, "x")))
    runner.error("from handler")
    runner.warning("careful")

GATE = threading.Event()

def gated(name, t):
    GATE.wait(5)
    return t + H

NOT_CALLABLE = 42

#
# Module
#
def test_doctest():
    result = doctest.testmod(arras.runner)
    assert result.failed == 0

def test_constants():
    assert arras.runner.TS_NEVER == arras.globals.TS_NEVER
    assert arras.runner.TS_ZERO == arras.globals.TS_ZERO
    assert [event for event, _ in arras.runner.PASSES] == ["presync", "sync", "postsync"]

def test_arguments():
    with pytest.raises(RunnerError):
        Runner(1)
    with pytest.raises(RunnerError):
        Runner(model="model.glm")
    with pytest.raises(RunnerError):
        Runner(model=make(), progress=42)
    with pytest.raises(RunnerError, match="'when'"):
        Runner(model=make(), progress=lambda when: None)
    with pytest.raises(RunnerError):
        Runner(model=make(), progress=lambda timestamp, /: None)

#
# Time series
#
def test_hourly():
    model = make('object thing { name "a"; on_sync "python:test_runner.hourly"; }')
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.SUCCESS
    assert [t for _, _, t in LOG] == [START, START+H, START+2*H, START+3*H]
    assert runner.steps == 4
    assert runner.clock == START + 3*H
    assert not runner.running and not runner.stopped
    assert model.globals.get("clock") == "2020-01-01 03:00:00 UTC"
    assert model.get_property("a", "clock") == "2020-01-01 03:00:00 UTC"
    assert model.globals.getvalue("progress") == 1.0
    assert runner.stderr == [] and runner.stdout == []
    assert Runner.current() is None
    assert "returncode=0" in repr(runner)

def test_pass_order():
    handlers = "".join(f' on_{e} "python:test_runner.log_{e}";' for e in ("init", "precommit", "presync", "sync", "postsync", "commit", "finalize"))
    model = make(f'object thing {{ name "p";{handlers} object thing {{ name "c";{handlers} }}; }}', stop="2020-01-01 00:00:00 UTC")
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.SUCCESS
    assert [(e, n) for e, n, _ in LOG] == [
        ("init", "p"), ("init", "c"),
        ("precommit", "p"), ("precommit", "c"),
        ("presync", "p"), ("presync", "c"),
        ("sync", "c"), ("sync", "p"),
        ("postsync", "p"), ("postsync", "c"),
        ("commit", "p"), ("commit", "c"),
        ("finalize", "p"), ("finalize", "c"),
        ]

def test_rank_header():
    model = make('''
object thing { name "a"; on_sync "python:test_runner.log_sync"; }
object thing { name "b"; rank 5; on_sync "python:test_runner.log_sync"; }
''', stop="2020-01-01 00:00:00 UTC")
    Runner(model=model)
    assert [n for _, n, _ in LOG] == ["a", "b"]
    LOG.clear()
    model.set_property("a", "parent", "b")
    assert Runner(model=model)._ranks(["a", "b"]) == {"a": 0, "b": 5}
    assert [n for _, n, _ in LOG] == ["a", "b"]

def test_iteration():
    model = make('object thing { name "a"; on_sync "python:test_runner.iterate_once"; }', stop="2020-01-01 01:00:00 UTC")
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.SUCCESS
    assert [t for _, _, t in LOG] == [START, START, START+H, START+H]
    assert runner.steps == 2

def test_iteration_limit():
    model = make('object thing { name "a"; on_sync "python:test_runner.always_now"; on_finalize "python:test_runner.log_finalize"; }')
    runner = Runner("-D", "iteration_limit=5", "-v", model=model)
    assert runner.returncode == exitcodes.RUNERR
    assert runner.stderr[-1] == "ERROR [2020-01-01 00:00:00 UTC]: convergence iteration limit reached at 2020-01-01 00:00:00 UTC"
    assert any("iteration limit imminent" in line for line in runner.stderr)
    assert LOG == [("finalize", "a", START)]
    assert runner.steps == 0

@pytest.mark.parametrize("handler,message", [
    ("backwards", "object a stopped its clock (its sync handler returned 1577836799)"),
    ("invalid", "object a stopped its clock (its sync handler returned -1)"),
    ("returns_bool", "object a sync handler returned True, not a timestamp"),
    ("returns_text", "object a sync handler returned 'soon', not a timestamp"),
    ("raises", "object a sync handler 'python:test_runner.raises' failed: RuntimeError: broken"),
    ("missing", "python handler 'test_runner.missing' not found"),
    ("NOT_CALLABLE", "python handler 'test_runner.NOT_CALLABLE' is not callable"),
    ])
def test_sync_failures(handler, message):
    model = make(f'object thing {{ name "a"; on_sync "python:test_runner.{handler}"; }}')
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.RUNERR
    assert message in runner.stderr[-1]

def test_bad_handler_spec():
    model = make('object thing { name "a"; on_sync "python:nodot"; }')
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.RUNERR
    assert "is not MODULE.FUNCTION" in runner.stderr[-1]

def test_soft_events():
    model = make('object thing { name "a"; on_sync "python:test_runner.soft_hourly"; }')
    assert Runner(model=model).returncode == exitcodes.SUCCESS
    assert [t for _, _, t in LOG] == [START, START+H, START+2*H, START+3*H]
    LOG.clear()
    model.globals.set("stoptime", "NEVER")
    model.set_property("a", "on_sync", "python:test_runner.soft_three")
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.SUCCESS
    assert [t for _, _, t in LOG] == [START]
    LOG.clear()
    Module("m", clockupdate=lambda t: t)
    assert Runner(model=model).steps == 1
    assert [t for _, _, t in LOG] == [START]

def test_stoptime_never():
    model = make('object thing { name "a"; on_sync "python:test_runner.three_steps"; }', stop="NEVER")
    calls = []
    runner = Runner(model=model, progress=lambda timestamp, percent: calls.append((timestamp, percent)))
    assert runner.returncode == exitcodes.SUCCESS
    assert [t for _, _, t in LOG] == [START, START+H, START+2*H]
    assert calls == [(START, None), (START+H, None), (START+2*H, None), (START+2*H, 100.0)]

def test_stoptime_zero_and_order():
    model = make('object thing { name "a"; on_sync "python:test_runner.three_steps"; }')
    model.globals.set("stoptime", 0)
    assert Runner(model=model).returncode == exitcodes.SUCCESS
    assert model.globals.get("stoptime") == "NEVER"
    model.globals.set("stoptime", START - H)
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.INIERR
    assert "stoptime is before starttime" in runner.stderr[-1]
    model.globals.set("stoptime", START)
    model.globals.set("iteration_limit", 0)
    assert Runner(model=model).returncode == exitcodes.INIERR

def test_minimum_timestep():
    model = make('object thing { name "a"; on_sync "python:test_runner.plus_one"; }', stop="2020-01-01 00:30:00 UTC")
    runner = Runner("-D", "minimum_timestep=900", model=model)
    assert runner.returncode == exitcodes.SUCCESS
    assert [t for _, _, t in LOG] == [START, START+900, START+1800]

def test_service_times():
    model = make('''object thing { name "a"; in_svc "2020-01-01 01:00:00 UTC"; out_svc "2020-01-01 02:00:00 UTC";
        on_sync "python:test_runner.hourly"; }''')
    assert Runner(model=model).returncode == exitcodes.SUCCESS
    assert [t for _, _, t in LOG] == [START+H, START+2*H]

def test_commit():
    model = make('object thing { name "a"; on_sync "python:test_runner.hourly"; on_commit "python:test_runner.commit_half"; }', stop="2020-01-01 01:00:00 UTC")
    assert Runner(model=model).returncode == exitcodes.SUCCESS
    assert [t for _, _, t in LOG] == [START, START+H]
    model.set_property("a", "on_commit", "python:test_runner.commit_now")
    assert Runner(model=model).returncode == exitcodes.SUCCESS
    for handler, message in (("commit_zero", "model commit failed"), ("commit_invalid", "object a commit failed")):
        model.set_property("a", "on_commit", f"python:test_runner.{handler}")
        runner = Runner(model=model)
        assert runner.returncode == exitcodes.RUNERR
        assert runner.stderr[-1].endswith(message)

def test_precommit_failure():
    model = make('object thing { name "a"; on_precommit "python:test_runner.precommit_early"; }')
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.RUNERR
    assert "object a precommit failed (returned 1577836799)" in runner.stderr[-1]

def test_init():
    model = make('object thing { name "a"; on_init "python:test_runner.init_false"; on_sync "python:test_runner.hourly"; }')
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.INIERR
    assert runner.stderr[-1].endswith("object a initialization failed")
    assert not LOG
    model.set_property("a", "on_init", "python:test_runner.init_bad")
    assert "not True, False, None, or 2" in Runner(model=model).stderr[-1]
    model.set_property("a", "on_init", "python:test_runner.init_defer")
    runner = Runner("-D", "init_max_defer=3", model=model)
    assert runner.returncode == exitcodes.INIERR
    assert "deferred too many times (init_max_defer=3)" in runner.stderr[-1]
    model.set_property("a", "on_init", "python:test_runner.raises")
    assert Runner(model=model).returncode == exitcodes.INIERR

def test_init_deferral():
    model = make('''
object thing { name "a"; on_init "python:test_runner.init_defer_once"; }
object thing { name "b"; on_init "python:test_runner.log_init"; }
''')
    assert Runner(model=model).returncode == exitcodes.SUCCESS
    assert [n for _, n, _ in LOG] == ["a", "b", "a"]

def test_finalize_failure():
    model = make('''
object thing { name "a"; on_finalize "python:test_runner.finalize_fail"; }
object thing { name "b"; on_finalize "python:test_runner.log_finalize"; }
''')
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.RUNERR
    assert [n for _, n, _ in LOG] == ["a", "b"]
    assert "cannot close" in runner.stderr[0]
    assert runner.stderr[-1].endswith("finalize failed for a")

def test_class_handler():
    model = make('''
object thing { name "a"; }
object thing { name "b"; on_sync "python:test_runner.log_sync"; }
''', stop="2020-01-01 00:00:00 UTC", classes='class thing { double x; on_sync "python:test_runner.hourly"; }')
    assert Runner(model=model).returncode == exitcodes.SUCCESS
    assert sorted(LOG) == [("sync", "a", START), ("sync", "b", START)]

def test_current_and_messages():
    model = make('object thing { name "a"; x 2; on_init "python:test_runner.current"; }')
    runner = Runner("-w", "-w", model=model)
    assert runner.returncode == exitcodes.SUCCESS
    assert LOG == [(True, "2")]
    assert runner.stderr == ["ERROR [INIT]: from handler", "WARNING [INIT]: careful"]
    runner = Runner("-w", model=model)
    assert runner.stderr == ["ERROR [INIT]: from handler"]

def test_shell_handler():
    model = make('object thing { name "a"; on_sync "echo $OBJECT $CLOCK $PORT; echo note >&2"; }', stop="2020-01-01 00:00:00 UTC")
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.SUCCESS
    assert runner.stdout == [f"a {START} 0"]
    assert runner.stderr == ["note"]
    model.set_property("a", "on_sync", "exit 3")
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.RUNERR
    assert runner.stderr[-1].endswith("object a sync handler 'exit 3' failed with code 3")

def test_import_from_working_folder(tmp_path, monkeypatch):
    (tmp_path / "runner_cwd_handlers.py").write_text("def sync(name, t):\n    return t + 3600\n")
    monkeypatch.chdir(tmp_path)
    model = make('object thing { name "a"; on_sync "python:runner_cwd_handlers.sync"; }')
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.SUCCESS
    assert runner.steps == 4
    model.set_property("a", "on_sync", "python:runner_cwd_missing.sync")
    assert Runner(model=model).returncode == exitcodes.RUNERR

def test_unexpected_exception(monkeypatch):
    def broken(self, initialize_only):
        raise ValueError("bug")
    monkeypatch.setattr(Runner, "_simulate", broken)
    runner = Runner(model=make('object thing { name "a"; }'))
    assert runner.returncode == exitcodes.EXCEPTION
    assert runner.stderr == ["ERROR [INIT]: ValueError: bug"]

#
# Command line
#
GLM = """
clock {
    starttime "2020-01-01 00:00:00 UTC";
    stoptime "2020-01-01 02:00:00 UTC";
}
class thing { double x; }
object thing { name "a"; x ${XVALUE}; on_sync "python:test_runner.hourly"; }
"""

@pytest.fixture
def glm(tmp_path):
    path = tmp_path / "model.glm"
    path.write_text(GLM)
    return str(path)

def test_command_line(glm, tmp_path):
    out = str(tmp_path / "out.json")
    runner = Runner("-v", "--define=strictnames=FALSE", "--define", "XVALUE=3", glm, "-o", out)
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert runner.model.get_property("a", "x") == "3"
    assert runner.steps == 3
    with open(out, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["objects"]["a"]["clock"] == "2020-01-01 02:00:00 UTC"
    assert any("model saved to" in line for line in runner.stderr)
    assert any(line.startswith("VERBOSE [INIT]: model file") for line in runner.stderr)
    out = str(tmp_path / "out.glm")
    assert Runner("-D", "strictnames=FALSE", "-D", "XVALUE=1", glm, f"--output={out}").returncode == exitcodes.SUCCESS
    assert os.path.exists(out)

@pytest.mark.parametrize("args,code,message", [
    ((), exitcodes.ARGERR, "no model file specified"),
    (("-D",), exitcodes.ARGERR, "command line option '-D' is missing its value"),
    (("--define=nosuchglobal=1",), exitcodes.ARGERR, "command line option '--define nosuchglobal=1'"),
    (("--profile",), exitcodes.ARGERR, "command line option '--profile' is not supported"),
    (("nosuchfile.glm",), exitcodes.LDERR, "nosuchfile.glm"),
    (("model.txt",), exitcodes.LDERR, "file type '.txt' is not supported"),
    ])
def test_command_line_errors(args, code, message):
    calls = []
    runner = Runner(*args, progress=lambda **kw: calls.append(kw))
    assert runner.returncode == code
    assert message in runner.stderr[-1]
    assert calls == [{"timestamp": None, "percent": None, "stdout": [], "stderr": runner.stderr}]

def test_check_compile_initialize(glm, tmp_path):
    model = make('object thing { name "a"; on_init "python:test_runner.log_init"; on_sync "python:test_runner.hourly"; }')
    out = str(tmp_path / "out.glm")
    assert Runner("-C", "-o", out, model=model).returncode == exitcodes.SUCCESS
    assert not LOG and os.path.exists(out)
    assert Runner("-I", model=model).returncode == exitcodes.SUCCESS
    assert LOG == [("init", "a", START)]
    model.read_glm('object thing { name "b"; parent "a"; }')
    model.objects["b"]["parent"] = "nosuch"
    runner = Runner("-c", model=model)
    assert runner.returncode == exitcodes.LDERR
    assert runner.stderr[-1].endswith("model check found 1 problem(s)")

def test_output_error(tmp_path):
    model = make('object thing { name "a"; }')
    runner = Runner("-o", str(tmp_path / "nosuchfolder" / "out.glm"), model=model)
    assert runner.returncode == exitcodes.IOERR
    assert "unable to save model" in runner.stderr[-1]

def test_message_flags():
    model = make('object thing { name "a"; on_sync "python:test_runner.hourly"; }')
    runner = Runner("--debug", "-v", model=model)
    assert any(line.startswith("DEBUG [2020-01-01 00:00:00 UTC]: object a sync handler") for line in runner.stderr)
    assert runner.stderr[-1] == "VERBOSE [2020-01-01 03:00:00 UTC]: simulation ended after 4 time step(s)"
    runner = Runner("-q", model=model)
    assert runner.stderr == []
    runner = Runner("-q", "--debug", "-v", model=make('object thing { name "a"; on_sync "python:test_runner.hourly"; }'))
    assert runner.stderr == []

def test_main(glm, capsys):
    assert main(["-D", "strictnames=FALSE", "-D", "XVALUE=2", glm, "-v"]) == exitcodes.SUCCESS
    err = capsys.readouterr().err
    assert "simulation ended after 3 time step(s)" in err
    assert main(["--nosuch"]) == exitcodes.ARGERR
    assert "'--nosuch' is not supported" in capsys.readouterr().err
    model = make('object thing { name "a"; on_sync "echo hello"; }', stop="2020-01-01 00:00:00 UTC")
    model.write_glm(glm)
    assert main([glm]) == exitcodes.SUCCESS
    assert capsys.readouterr().out == "hello\n"

def test_main_exception(monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise RunnerError("bad")
    monkeypatch.setattr(arras.runner, "Runner", broken)
    assert main([]) == exitcodes.EXCEPTION
    assert "EXCEPTION" in capsys.readouterr().err

#
# Progress and background runs
#
def test_progress_arguments():
    model = make('object thing { name "a"; on_sync "python:test_runner.hourly"; on_commit "echo step $CLOCK"; }', stop="2020-01-01 01:00:00 UTC")
    calls = []
    def progress(stdout, stderr, extra=None):
        calls.append((stdout, stderr))
    assert Runner("-v", model=model, progress=progress).returncode == exitcodes.SUCCESS
    assert [out for out, _ in calls] == [[f"step {START}"], [f"step {START+H}"], []]
    assert calls[-1][1] == ["VERBOSE [2020-01-01 01:00:00 UTC]: simulation ended after 2 time step(s)"]
    assert calls[0][1] == ["VERBOSE [INIT]: simulation started"]
    calls.clear()
    Runner(model=model, progress=lambda *args, **kwargs: calls.append(sorted(kwargs)))
    assert calls[0] == ["percent", "stderr", "stdout", "timestamp"]
    calls.clear()
    Runner(model=model, progress=lambda: calls.append("called"))
    assert calls == ["called"] * 3

def test_progress_stop():
    model = make('object thing { name "a"; on_sync "python:test_runner.hourly"; on_finalize "python:test_runner.log_finalize"; }')
    runner = Runner(model=model, progress=lambda timestamp: timestamp < START + H)
    assert runner.returncode == exitcodes.RUNERR
    assert runner.stopped
    assert runner.steps == 2
    assert runner.stderr[-1].endswith("simulation stopped at 2020-01-01 01:00:00 UTC")
    assert LOG[-1] == ("finalize", "a", START + H)

def test_progress_raises():
    model = make('object thing { name "a"; on_sync "python:test_runner.hourly"; }')
    def progress(percent):
        if percent is not None and percent > 0:
            raise KeyError("x")
    runner = Runner(model=model, progress=progress)
    assert runner.returncode == exitcodes.RUNERR
    assert "progress callback failed: KeyError" in runner.stderr[0]
    def final(percent):
        if percent == 100.0:
            raise KeyError("y")
    runner = Runner(model=model, progress=final)
    assert runner.returncode == exitcodes.RUNERR
    assert "progress callback failed: KeyError: 'y'" in runner.stderr[-1]

def test_background():
    GATE.clear()
    model = make('object thing { name "a"; on_sync "python:test_runner.gated"; }')
    calls = []
    runner = Runner(model=model, background=True, progress=lambda timestamp, percent: calls.append((timestamp, percent)))
    assert runner.running
    assert runner.returncode is None
    assert runner.wait(0.05) is None
    GATE.set()
    assert runner.wait(5) == exitcodes.SUCCESS
    assert not runner.running
    assert calls == [(START, 0.0), (START+H, 33.333333), (START+2*H, 66.666667), (START+3*H, 100.0), (START+3*H, 100.0)]
    assert Runner.current() is None

def test_background_stop():
    GATE.clear()
    model = make('object thing { name "a"; on_sync "python:test_runner.gated"; }')
    runner = Runner(model=model, background=True)
    runner.stop()
    GATE.set()
    assert runner.wait(5) == exitcodes.RUNERR
    assert runner.stopped
    assert runner.steps == 1

#
# Module solvers, internal items, and heartbeats
#
def logger(event, result=None):
    def call(*args):
        LOG.append((event,) + args)
        return result
    return call

def test_module_order():
    Module("m", init=logger("m.init", True), precommit=logger("m.precommit", TS_NEVER),
        presync=logger("m.presync", TS_NEVER), sync=logger("m.sync", TS_NEVER),
        postsync=logger("m.postsync", TS_NEVER), commit=logger("m.commit", True),
        term=logger("m.term"), clockupdate=lambda t: LOG.append(("m.clockupdate", t)) or t)
    handlers = "".join(f' on_{e} "python:test_runner.log_{e}";' for e in ("init", "precommit", "presync", "sync", "postsync", "commit", "finalize"))
    model = make(f'object thing {{ name "a";{handlers} }}', stop="2020-01-01 00:00:00 UTC")
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert [x[0] for x in LOG] == ["init", "m.init", "precommit", "m.precommit", "m.presync", "presync",
        "sync", "m.sync", "m.postsync", "postsync", "commit", "m.commit", "m.clockupdate", "finalize", "m.term"]
    assert ("m.sync", START) in LOG and ("m.clockupdate", START + 1) in LOG

def test_module_events():
    Module("m", sync=lambda t: t + H // 2)
    model = make('object thing { name "a"; on_sync "python:test_runner.log_sync"; }', stop="2020-01-01 01:00:00 UTC")
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.SUCCESS
    assert [t for _, _, t in LOG] == [START, START+H//2, START+H]
    Module.reset()
    Module("m", presync=lambda t: -(t + H // 2))
    LOG.clear()
    assert Runner(model=model).steps == 3

@pytest.mark.parametrize("solvers,code,message", [
    ({"presync": lambda t: TS_INVALID}, exitcodes.RUNERR, "module on_presync failed"),
    ({"postsync": lambda t: t - 1}, exitcodes.RUNERR, "module on_postsync returned 1577836799, before the clock"),
    ({"sync": lambda t: True}, exitcodes.RUNERR, "module on_sync failed: ModuleError"),
    ({"init": lambda: False}, exitcodes.INIERR, "module initialization failed"),
    ({"init": lambda: 1/0}, exitcodes.INIERR, "module on_init failed: ZeroDivisionError"),
    ({"commit": lambda t: False}, exitcodes.RUNERR, "model commit failed"),
    ({"precommit": lambda t: 0}, exitcodes.RUNERR, "module on_precommit failed"),
    ({"precommit": lambda t: TS_INVALID}, exitcodes.RUNERR, "module on_precommit failed"),
    ({"precommit": lambda t: t - 1}, exitcodes.RUNERR, "module on_precommit returned 1577836799, before the clock"),
    ({"clockupdate": lambda t: START}, exitcodes.RUNERR, "module clock_update returned 1577836800, not after the clock"),
    ({"term": lambda: 1/0}, exitcodes.RUNERR, "module on_term failed: ZeroDivisionError"),
    ])
def test_module_failures(solvers, code, message):
    Module("m", **solvers)
    runner = Runner(model=make('object thing { name "a"; }'))
    assert runner.returncode == code
    assert message in runner.stderr[-1]

def test_module_precommit_events():
    Module("m", precommit=lambda t: LOG.append(("m.precommit", t)) or t + 1200, term=logger("m.term"))
    model = make('object thing { name "a"; }', stop="2020-01-01 00:40:00 UTC")
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.SUCCESS
    assert [t for _, t in LOG[:-1]] == [START, START+1200, START+2400]
    assert LOG[-1] == ("m.term",)
    Module.reset()
    LOG.clear()
    Module("m", precommit=lambda t: LOG.append(("m.precommit", t)) or t)
    assert Runner(model=model).steps == 1

def test_clock_update():
    Module("m", clockupdate=lambda t: min(t, Runner.current().clock + 600))
    model = make('object thing { name "a"; on_sync "python:test_runner.log_sync"; }', stop="2020-01-01 00:30:00 UTC")
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.SUCCESS
    assert [t for _, _, t in LOG] == [START, START+600, START+1200, START+1800]

def test_deltamode_warning():
    Module("m", deltamode_desired=lambda flags: 0)
    runner = Runner(model=make('object thing { name "a"; }'))
    assert runner.returncode == exitcodes.SUCCESS
    assert runner.stderr == ["WARNING [INIT]: deltamode is not supported; deltamode solvers are not called"]

def test_internal_items():
    Module.add_internal("schedule", logger("schedule", -1))
    calls = []
    Module.add_internal("schedule", lambda t: calls.append(t) or t + 900)
    Module.add_internal("transform", lambda t: calls.append(("transform", t)) or TS_NEVER, source="DOUBLE")
    model = make('object thing { name "a"; on_presync "python:test_runner.log_presync"; }', stop="2020-01-01 00:30:00 UTC")
    Module.internals["schedule"].pop(0)
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert [t for _, _, t in LOG] == [START, START+900, START+1800]
    assert calls[:4] == [START, ("transform", START), ("transform", START), ("transform", START)]
    Module.reset()
    Module.add_internal("enduse", lambda t: t - 10)
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.RUNERR
    assert runner.stderr[-1].endswith("internal property sync failure")

def test_heartbeat():
    module = Module("hb")
    module.register_class("beacon")
    module.set_heartbeat("beacon", lambda obj: LOG.append(("heartbeat", obj["id"])) or Runner.current().clock + 1200)
    model = Model()
    model.read_glm("""
clock { starttime "2020-01-01 00:00:00 UTC"; stoptime "2020-01-01 00:40:00 UTC"; }
object beacon { name "b1"; heartbeat 1; }
object beacon { name "b2"; }
""")
    runner = Runner(model=model)
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert runner.steps == 3
    assert LOG == [("heartbeat", "0")] * 3

#
# Python module event handlers
#
PYMOD = """
import test_runner
def on_init(t):
    test_runner.LOG.append(("init", t))
    return True
def on_precommit(t):
    test_runner.LOG.append(("precommit", t))
    return t
def on_presync(t):
    test_runner.LOG.append(("presync", t))
    return test_runner.TS_NEVER
def on_sync(t):
    test_runner.LOG.append(("sync", t))
    return t + 1800
def on_postsync(t):
    test_runner.LOG.append(("postsync", t))
    return 9223372036854775807
def on_commit(t):
    test_runner.LOG.append(("commit", t))
    return True
def on_term(t):
    test_runner.LOG.append(("term", t))
"""

def pymodel(name, stop="2020-01-01 00:30:00 UTC"):
    return make(f"module {name};", stop=stop)

def test_python_module(tmp_path, monkeypatch):
    (tmp_path / "pymod_events.py").write_text(PYMOD)
    monkeypatch.chdir(tmp_path)
    runner = Runner("-v", model=pymodel("pymod_events"))
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert [e for e, _ in LOG] == ["init", "precommit", "presync", "sync", "postsync", "commit",
        "precommit", "presync", "sync", "postsync", "commit", "term"]
    assert [t for e, t in LOG if e == "sync"] == [START, START+1800]
    assert "VERBOSE [INIT]: python module 'pymod_events' loaded ok" in runner.stderr
    assert Module.find("pymod_events").has_solver("on_sync")

def test_python_module_pythonpath(tmp_path):
    folder = tmp_path / "lib"
    folder.mkdir()
    (folder / "pymod_path.py").write_text("def on_sync(t):\n    return t + 600\non_presync = 3\n")
    runner = Runner("-D", f"pythonpath={folder}", model=pymodel("pymod_path"))
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert runner.steps == 4
    assert runner.stderr == ["ERROR [INIT]: pymod_path.py: on_presync is not callable"]

def test_python_module_userdir(tmp_path, monkeypatch):
    folder = tmp_path / "user" / "lib"
    folder.mkdir(parents=True)
    (folder / "pymod_shared.py").write_text("def on_sync(t):\n    return t + 600\n")
    monkeypatch.setenv("ARRAS_USERDIR", str(tmp_path / "user"))
    monkeypatch.chdir(tmp_path)
    runner = Runner(model=pymodel("pymod_shared"))
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert runner.steps == 4

def test_python_module_skipped(tmp_path, monkeypatch):
    (tmp_path / "pymod_user.py").write_text(PYMOD)
    monkeypatch.chdir(tmp_path)
    Module("pymod_user", sync=lambda t: TS_NEVER)
    assert Runner(model=pymodel("pymod_user")).returncode == exitcodes.SUCCESS
    assert not LOG
    assert Runner(model=pymodel("pymod_absent")).returncode == exitcodes.SUCCESS
    assert Module.find("pymod_absent") is None

@pytest.mark.parametrize("source,code,message", [
    ("def on_sync(t):\n    raise ValueError('x')\n", exitcodes.RUNERR, "python {name}.on_sync(1577836800) failed: ValueError: x"),
    ("def on_sync(t):\n    return 'later'\n", exitcodes.RUNERR, "python {name}.on_sync(1577836800) returned an invalid type (expected int)"),
    ("def on_init(t):\n    return False\n", exitcodes.INIERR, "python {name}.on_init(1577836800) returned False"),
    ("def on_init(t):\n    raise ValueError('x')\n", exitcodes.INIERR, "python {name}.on_init(1577836800) failed: ValueError: x"),
    ("def on_commit(t):\n    return 0\n", exitcodes.RUNERR, "python {name}.on_commit(1577836800) returned False"),
    ("def on_precommit(t):\n    return False\n", exitcodes.RUNERR, "python {name}.on_precommit(1577836800) returned False"),
    ("def on_precommit(t):\n    return True\n", exitcodes.SUCCESS, "simulation ended"),
    ("def on_precommit(t):\n    raise ValueError('x')\n", exitcodes.RUNERR, "module on_precommit failed"),
    ("def on_term(t):\n    raise ValueError('x')\n", exitcodes.SUCCESS, "python {name}.on_term(1577836800) failed: ValueError: x"),
    ("def on_sync(t:\n", exitcodes.INIERR, "{name}.py: python module import failed: SyntaxError"),
    ])
def test_python_module_failures(tmp_path, monkeypatch, source, code, message):
    name = f"pymod_fail_{abs(hash(source))}"
    (tmp_path / f"{name}.py").write_text(source)
    monkeypatch.chdir(tmp_path)
    runner = Runner("-v", model=pymodel(name, stop="2020-01-01 00:00:00 UTC"))
    assert runner.returncode == code
    assert any(message.format(name=name) in line for line in runner.stderr), runner.stderr
