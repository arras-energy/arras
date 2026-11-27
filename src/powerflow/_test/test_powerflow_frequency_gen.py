"""Class `frequency_gen`: registration, initialization, the load it reads,
the step response, governor delay and ramp, the return to nominal, small
changes, and the hourly statistics"""
# pylint: disable=missing-function-docstring,line-too-long

import math

import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model
from powerflow.frequency_gen import FrequencyGen, MATCHED, GOV_DELAY, GEN_RAMP

VNOM = 2401.7771
T0 = 1577836800

def test_registration():
    Model().read_glm("module powerflow;\n")
    fg = Class.find("frequency_gen", module="powerflow")
    assert fg.parent is None and fg.trl == 6 and fg.find_property("phases") is None
    assert fg.find_property("M").unit == "pu.s" and fg.find_property("FreqChange").unit == "Hz/s"
    assert fg.find_property("Frequency_Mode").default == "AUTO" and fg.find_property("Num_Resp_Eqs").default == "20"

def test_load_power(helpers):
    """The real power the parent draws for its loads and the links it feeds
    (gridlabd's current_inj)"""
    glm = f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object test_line {{ name l01; phases ABCN; from n0; to n1; length 2000; }}
object node {{ name n1; phases ABCN; nominal_voltage {VNOM}; }}
object load {{ name ld; parent n1; phases ABCN; nominal_voltage {VNOM}; constant_power_A 1000000; constant_power_B 1000000; constant_power_C 1000000; }}
object frequency_gen {{ name f0; parent n0; Rated_power 10 MW; }}
object frequency_gen {{ name f1; parent n1; Rated_power 10 MW; }}
"""
    r = helpers.run(glm)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert powerflow.get_double(m, "f0", "Load_power") == pytest.approx(powerflow.get_complex(m, "l01", "power_in").real, rel=1e-9)
    assert powerflow.get_double(m, "f1", "Load_power") == pytest.approx(3e6, rel=1e-6)
    assert powerflow.get_double(m, "f0", "Gen_power") == pytest.approx(powerflow.get_double(m, "f0", "Load_power"), rel=1e-9)
    assert powerflow.get_double(m, "f0", "Frequency") == 60

@pytest.fixture(name="gen")
def fixture_gen(helpers, monkeypatch):
    """A frequency_gen driven second by second with a load it is given"""
    glm = f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object frequency_gen {{ name fg; parent n0; Rated_power 10 MW; Ramp_rate 100 kW/s; }}
"""
    m = helpers.run(glm, lines=False).model
    load = {"value": 1e6}
    monkeypatch.setattr(FrequencyGen, "load_power", classmethod(lambda cls, model, name: load["value"]))
    history = []
    def step(seconds:range, value:float|None=None) -> list[tuple[float,float,int]]:
        if value is not None:
            load["value"] = value
        for k in seconds:
            FrequencyGen.presync(m, "fg", T0 + k)
            FrequencyGen.postsync(m, "fg", T0 + k)
            FrequencyGen.commit(m, "fg", T0 + k)
            history.append((powerflow.get_double(m, "fg", "Frequency"), powerflow.get_double(m, "fg", "Gen_power"),
                powerflow._common.object_state(m, "fg")["cond"])) # pylint: disable=protected-access
        return history
    return m, step

def test_step_response(gen):
    """A load step beyond the deadband: a step response with time constant
    M/D, the governor delay, the ramp at Ramp_rate, and the return to
    nominal once matched"""
    _, step = gen
    step(range(10))
    history = step(range(10, 200), 1.5e6)
    k, tau = 1/0.75, 10/0.75
    assert history[9][0] == 60 and history[10][2] == MATCHED
    assert history[11][0] == pytest.approx(60*(1 + (-0.05)*k*(1 - math.exp(-1/tau))))
    assert history[12][2] == GOV_DELAY
    ramp = [x for x in history if x[2] == GEN_RAMP]
    assert ramp and ramp[1][1] - ramp[0][1] == pytest.approx(100e3)
    assert history[-1][1] == 1.5e6 and history[-1][2] == MATCHED
    assert history[-1][0] == pytest.approx(60, abs=1e-6)
    assert min(x[0] for x in history) < 58.5

def test_small_change(gen):
    """A change within the deadband moves the persistent constant"""
    _, step = gen
    step(range(5))
    history = step(range(5, 8), 1e6 + 500)
    assert history[-1][2] == MATCHED and history[-1][1] == 1e6
    assert history[-1][0] == pytest.approx(60*(1 - 500/10e6/0.75))

def test_statistics(gen):
    """24-hour and 168-hour means and standard deviations of the hourly
    samples (the 168-hour deviation over all 168 samples)"""
    m, _ = gen
    state = powerflow._common.object_state(m, "fg") # pylint: disable=protected-access
    samples = [59.9 + 0.001*k for k in range(168)]
    for value in samples:
        m.set_property("fg", "Frequency", str(value))
        FrequencyGen.statistics(m, "fg")
    day = samples[-24:]
    assert powerflow.get_double(m, "fg", "avg24") == pytest.approx(sum(day)/24)
    assert powerflow.get_double(m, "fg", "std24") == pytest.approx(math.sqrt(sum((x - sum(day)/24)**2 for x in day)/23))
    mean = sum(samples)/168
    assert powerflow.get_double(m, "fg", "avg168") == pytest.approx(mean)
    assert powerflow.get_double(m, "fg", "std168") == pytest.approx(math.sqrt(sum((x - mean)**2 for x in samples)/167))
    assert state["loc"] == 0

def test_off(gen):
    m, step = gen
    m.set_property("fg", "Frequency_Mode", "OFF")
    history = step(range(5), 2e6)
    assert all(x[0] == 60 for x in history)

@pytest.mark.parametrize("glm, message", [
    ("object frequency_gen { name fg; }", "Parented object needs to be a node of some sort."),
    (f"object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}\nobject frequency_gen {{ name fg; parent n0; D 0; }}", "The load-damping constant for the frequency_gen object must be non-zero!"),
])
def test_init_errors(helpers, glm, message):
    r = helpers.run(glm, lines=False)
    assert any(message in x and "init_frequency_gen(obj=" in x for x in helpers.errors(r)), r.stderr
