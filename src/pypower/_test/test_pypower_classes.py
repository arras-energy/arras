"""The `pypower` classes: behavior and initialization errors"""

import os

import pytest

from arras import exitcodes

def value(runner, name:str, prop:str) -> float:
    """A property value as a number"""
    return float(str(runner.model.get_property(name, prop)).split()[0])

def init_error(helpers, glm:str, message:str, **kwargs) -> None:
    """The model fails to initialize with an error that contains
    `message`"""
    runner = helpers.run(glm, **kwargs)
    assert runner.returncode == exitcodes.INIERR, runner.stderr
    assert any(message in line for line in helpers.errors(runner)), runner.stderr

#
# Network
#
def test_three_bus(helpers):
    """The solution of the three-bus network, its losses, and the branch
    currents in gridlabd's polar notation"""
    runner = helpers.run(helpers.THREE_BUS)
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert value(runner, "b2", "Vm") == pytest.approx(0.9792, abs=1e-4)
    assert value(runner, "b3", "Va") == pytest.approx(-2.462, abs=1e-3)
    assert value(runner, "g1", "Pg") == pytest.approx(90.46, abs=0.01)
    assert [value(runner, n, "bus_i") for n in ("b1", "b2", "b3")] == [1, 2, 3]
    assert [value(runner, "l23", p) for p in ("fbus", "tbus")] == [2, 3]
    assert runner.model.get_property("l12", "current").endswith("d")
    losses = sum(value(runner, n, "loss") for n in ("l12", "l23", "l13"))
    assert float(runner.model.globals.get("pypower::total_loss").split()[0]) == pytest.approx(losses, rel=1e-5)
    assert runner.model.globals.get("pypower::solver_status") == "SUCCESS"
    assert runner.model.globals.get("pypower::generation_shortfall") == "+0 MW"

def test_no_branches(helpers):
    """Without branches the module does nothing"""
    runner = helpers.run("object bus { name b1; baseKV 1 kV; }")
    assert runner.returncode == exitcodes.SUCCESS
    assert runner.model.globals.get("pypower::solver_status") == "INIT"

def test_maximum_timestep(helpers):
    """`maximum_timestep` solves again every interval"""
    runner = helpers.run(helpers.THREE_BUS + "module pypower { maximum_timestep 600; }",
        stop="2020-01-01 01:00:00")
    assert runner.returncode == exitcodes.SUCCESS
    assert runner.steps == 7

def test_solver_failure_stops(helpers):
    """A solver failure stops the run when `stop_on_failure` is true;
    otherwise the solver returns its unconverged solution, which is used,
    as in gridlabd"""
    glm = helpers.THREE_BUS + "module pypower { maximum_iterations 1; solution_tolerance 1e-30; stop_on_failure %s; }"
    runner = helpers.run(glm % "TRUE")
    assert runner.returncode == exitcodes.RUNERR
    assert "pypower solver failed (see 'pypower_failed.txt'" in helpers.errors(runner)[0]
    assert runner.model.globals.get("pypower::solver_status") == "FAILED"
    runner = helpers.run(glm % "FALSE")
    assert runner.returncode == exitcodes.SUCCESS
    assert os.path.exists("pypower_failed.txt")

def test_opf(helpers):
    """With `enable_opf` and gencost objects the OPF runs (with tight
    tolerances: the defaults are gridlabd's loose ones) and its multipliers
    are received; a missing gencost is a warning"""
    glm = helpers.THREE_BUS.replace("rateA 100 MVA", "rateA 250 MVA") + """
        module pypower { enable_opf TRUE; maximum_iterations_opf 100; opf_feasibility_tolerance 1e-6;
            opf_gradient_tolerance 1e-6; opf_condition_tolerance 1e-6; opf_cost_tolerance 1e-6; }
        object gencost { parent g1; model POLYNOMIAL; costs "0.01,10,0"; }
        """
    runner = helpers.run(glm)
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert value(runner, "b2", "lam_P") > 10
    assert value(runner, "g1", "Pg") == pytest.approx(90.31, abs=0.01)
    runner = helpers.run(helpers.THREE_BUS + "module pypower { enable_opf TRUE; }")
    assert any("requires the number of gencost records (0)" in x for x in helpers.warnings(runner))

def test_verbose(helpers):
    """Module and object messages follow the `verbose` global and the
    message flags"""
    runner = helpers.run(helpers.THREE_BUS + "module pypower { message_flags VERBOSE; }", "-v")
    assert any("pypower::update_solution" in x for x in runner.stderr)
    assert any("b2: resetting loads" in x for x in runner.stderr)

#
# Bus
#
def test_bus_base_load(helpers):
    """`S` is the base load: set from `Pd`, `Qd` when 0, and used to reset
    them; a load below the bus adds to it"""
    runner = helpers.run(helpers.THREE_BUS + """
        object load { parent b2; P 10+5j MVA; status ONLINE; }
        object bus { name b4; baseKV 230 kV; S 3+1j MVA; }
        """)
    assert runner.model.get_property("b2", "S") == "50.0+20.0i"
    assert value(runner, "b2", "Pd") == pytest.approx(60)
    assert value(runner, "b4", "Pd") == pytest.approx(3)

WEATHER = """timestamp,Td,RH
2020-01-01 00:00:00 UTC,10,50
2020-01-01 00:30:00 UTC,11,51
2020-01-01 01:00:00 UTC,12,52
2020-01-01 02:00:00 UTC,30,53
"""

def test_bus_weather(helpers):
    """A bus reads its weather file at the resolution and applies its
    sensitivities"""
    helpers.write("weather.csv", WEATHER)
    runner = helpers.run(helpers.THREE_BUS + """
        modify b2.weather_file weather.csv;
        modify b2.weather_variables Td,RH;
        modify b2.weather_sensitivity "S.real:Td>11,2;Qd:RH,0.5";
        module pypower { maximum_timestep 3600; }
        """, stop="2020-01-01 03:00:00")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert value(runner, "b2", "Td") == 30
    assert runner.model.get_property("b2", "S") == "88.0+46.5i"

@pytest.mark.parametrize("modify, message", [
    ('weather_file missing.csv', "file 'missing.csv' open for read failed"),
    ('weather_variables Tx', "weather variable 'Tx' is not valid"),
    ('weather_sensitivity "S.real:Tx,1"', "weather_sensitivity source 'Tx' is not valid"),
    ('weather_sensitivity "S.real:type,1"', "weather_sensitivity source 'type' is not a double"),
    ('weather_sensitivity "Gs:Td,1"', "property 'Gs' is not valid"),
    ('weather_sensitivity "S.real"', "weather_sensitivity 'S.real' in not valid"),
])
def test_bus_errors(helpers, modify, message):
    """Bus initialization errors"""
    helpers.write("weather.csv", WEATHER)
    extra = "modify b2.weather_file weather.csv;\n" if "weather_variables" in modify else ""
    init_error(helpers, helpers.THREE_BUS + extra + f"modify b2.{modify};", message)

def test_weather_file_errors(helpers):
    """Timestamps that are not valid or out of order fail the read"""
    helpers.write("bad.csv", "timestamp,Td\n2020-01-01 00:00:00 UTC,1\n2019-01-01 00:00:00 UTC,2\n")
    init_error(helpers, "object weather { file bad.csv; variables Td; }", "duplicate or out-of-sequence timestamp")
    helpers.write("bad.csv", "timestamp,Td\n2020-13-01 00:00:00 UTC,1\n")
    init_error(helpers, "object weather { file bad.csv; variables Td; }", "timestamp '2020-13-01 00:00:00 UTC' is not valid")
    helpers.write("empty.csv", "timestamp,Td\n")
    init_error(helpers, "object weather { file empty.csv; variables Td; }", "unable to load weather_file 'empty.csv'")

def test_weather_object(helpers):
    """A weather object plays its file (its precommit times are not events,
    as in gridlabd, so a recorder drives the clock); the data ends with a
    warning"""
    helpers.write("weather.csv", WEATHER)
    runner = helpers.run("""object weather { name w; file weather.csv; variables Td,RH; resolution 1800 s; }
        module tape; object recorder { parent w; property Td; file w.csv; interval 1800; }""",
        stop="2020-01-01 03:00:00")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert value(runner, "w", "Td") == 30
    assert any("weather data ended unexpectedly" in x for x in helpers.warnings(runner))

#
# Branch
#
@pytest.mark.parametrize("glm, message", [
    ("object branch { to b1; rateA 1; }", "from bus not specified"),
    ("object weather { name w; } object branch { from w; to b1; rateA 1; }", "from object 'w' is not a pypower bus"),
    ("object branch { from b1; to b2; rateA -1; }", "rateA must be non-negative"),
    ("object branch { from b1; to b2; rateA 1; ratio -1; }", "turns ratio must be non-negative"),
    ("module pypower { autosize_angle -1; } object branch { from b1; to b2; rateA 1; }", "autosize_angle must be non-negative"),
    ("module pypower { autosize_angle 0.5; } object branch { from b1; to b2; }", "rateA 0.0 MW is not specified but is needed for autosizing"),
])
def test_branch_errors(helpers, glm, message):
    """Branch initialization errors"""
    init_error(helpers, "object bus { name b1; baseKV 1 kV; } object bus { name b2; baseKV 1 kV; }\n" + glm, message)

def test_branch_autosize(helpers):
    """Autosizing raises the ratings and sizes a line from the distance
    between its buses; lines without locations get a warning"""
    runner = helpers.run("""
        module pypower { autosize_angle 1.5; }
        object bus { name b1; baseKV 69 kV; latitude 37; longitude -122; type REF; }
        object bus { name b2; baseKV 69 kV; latitude 37.5; longitude -122; Pd 1 MW; }
        object bus { name b3; baseKV 69 kV; }
        object gen { parent b1; Pmax 100 MW; }
        object branch { name l1; from b1; to b2; rateA 100 MVA; rateB 50 MVA; rateC 60 MVA; }
        object branch { name l2; from b2; to b3; rateA 100 MVA; }
        """)
    assert value(runner, "l1", "rateB") == 100 and value(runner, "l1", "rateC") == 100
    assert value(runner, "l1", "x") == pytest.approx((0.699-0.0008*69)*34.55/(69*69/100), rel=1e-3)
    assert any("autosize_angle should not be 90 deg or greater" in x for x in helpers.warnings(runner))
    assert any("unable to compute default line r/x/b" in x for x in helpers.warnings(runner))
    assert any("rateB is less than rateA" in x for x in helpers.warnings(runner))

#
# Generators and costs
#
@pytest.mark.parametrize("glm, message", [
    ("object gen { name g; }", "parent bus not specified"),
    ("object weather { name w; } object gen { parent w; }", "parent object 'w' is not a pypower bus"),
    ("object gen { parent b1; bus 7; }", "parent object 'b1' bus index mismatch"),
    ("object gencost { model POLYNOMIAL; }", "parent does not trace back to a pypower.gen object"),
    ("object gen { name g; parent b1; } object gencost { parent g; }", "cost model must be PIECEWISE or POLYNOMIAL"),
    ("object gen { name g; parent b1; } object gencost { parent g; model POLYNOMIAL; startup -1; }", "startup cost must be non-negative"),
    ("object gen { name g; parent b1; } object gencost { parent g; model POLYNOMIAL; shutdown -1; }", "shutdown cost must be non-negative"),
])
def test_gen_errors(helpers, glm, message):
    """Generator and cost model errors"""
    init_error(helpers, "object bus { name b1; baseKV 1 kV; bus_i 1; }\n" + glm, message)

def test_gencost_conflict(helpers):
    """A second, different cost model on a generator is an error that does
    not stop the initialization; the run ends with `RUNERR`"""
    runner = helpers.run("""object bus { name b1; baseKV 1 kV; bus_i 1; } object gen { name g; parent b1; }
        object gencost { parent g; model POLYNOMIAL; costs 1; } object gencost { parent g; model POLYNOMIAL; costs 2; }""")
    assert runner.returncode == exitcodes.RUNERR
    assert helpers.errors(runner) == ["ERROR [INIT]: g: unable to add to different gencost models"]

def test_gen_out_of_service(helpers):
    """A generator out of service keeps its output"""
    runner = helpers.run(helpers.THREE_BUS + "object gen { name g2; parent b2; status OUT_OF_SERVICE; Pg 5 MW; }")
    assert runner.returncode == exitcodes.SUCCESS
    assert value(runner, "g2", "Pg") == 5

#
# DC lines
#
def test_dcline(helpers):
    """DC line losses are inferred or defaulted, the output follows the
    control point and limits, and an `OUT` line carries nothing"""
    runner = helpers.run(helpers.THREE_BUS + """
        object dcline { name d1; from b1; to b3; Sfrom 10+1j MVA; Sto 9+1j MVA; Pmax 20 MW; Qminf -5; Qmaxf 5; }
        object dcline { name d2; from b1; to b3; Sfrom 10 MVA; Sto 5 MVA; loss1 0.1; Pmax 20 MW; Qmaxf 5; control FROM; }
        object dcline { name d3; from b1; to b3; Pmax 20; }
        object dcline { name d4; from b1; to b3; Sfrom 1; Sto 1; loss1 0.1; status OUT; }
        """)
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert value(runner, "d1", "loss1") == pytest.approx(0.9)
    assert value(runner, "d3", "loss1") == pytest.approx(0.05)
    assert runner.model.get_property("d4", "Sfrom") == "0.0+0.0j"
    assert any("is inconsistent with" in x for x in helpers.warnings(runner))

def test_dcline_errors(helpers):
    """DC line initialization errors"""
    init_error(helpers, "object bus { name b1; baseKV 1 kV; } object dcline { to b1; }", "from bus not specified")
    init_error(helpers, "object bus { name b1; baseKV 1 kV; } object weather { name w; } object dcline { from b1; to w; }",
        "to object 'w' is not a pypower bus")

#
# Loads and powerplants
#
def test_load_status(helpers):
    """Curtailed loads add their reduced demand, offline loads nothing; the
    load voltage follows the bus"""
    runner = helpers.run(helpers.THREE_BUS + """
        object load { name l1; parent b2; P 10 MVA; status CURTAILED; response 0.5; }
        object load { name l2; parent b3; P 10 MVA; status OFFLINE; }
        object load { name l3; parent b3; Vn 200 kV; P 1; status ONLINE; }
        """)
    assert value(runner, "b2", "Pd") == pytest.approx(55)
    assert value(runner, "b3", "Pd") == pytest.approx(41)
    assert value(runner, "l1", "Vn") == 230
    assert runner.model.get_property("l2", "V") == "0.0+0.0j"
    assert any("Vn differs from bus baseKV" in x for x in helpers.warnings(runner))

def test_load_errors(helpers):
    """Load initialization errors"""
    init_error(helpers, "object weather { name w; } object load { parent w; }", "parent 'w' is not a pypower bus object")
    init_error(helpers, "object load { name l; }", "nominal voltage not specified or inferred from bus")

def test_powerplant_bus(helpers):
    """A powerplant on a bus is a negative load; storage charges"""
    runner = helpers.run(helpers.THREE_BUS + """
        object powerplant { name p1; parent b2; status ONLINE; S 10+2j MVA; storage_capacity 10 MWh;
            charging_capacity 5 MW; state_of_charge 0.5; fuel COAL; variable_cost 1; }
        module pypower { maximum_timestep 3600; }
        """, stop="2020-01-01 02:00:00")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert value(runner, "b2", "Pd") == pytest.approx(40)
    assert value(runner, "p1", "state_of_charge") == pytest.approx(1.0)

def test_powerplant_gen(helpers):
    """Dispatchable powerplants add their output and derated capacity
    (180 MW at 30 degC) to their generator at each presync (so the totals
    grow with the iterations of a time step, as in gridlabd), ramp, and
    post their costs"""
    runner = helpers.run(helpers.THREE_BUS + """
        object weather { name w; Td 30 degC; }
        object powerplant { name p1; parent g1; status ONLINE; operating_capacity 200 MW; ramp_rate -1 MW/min;
            weather w; Tnominal 20 degC; Tcutoff 40 degC; derating 0.01 pu/degC; fuel NG; variable_cost 20;
            startup_cost 1; fixed_cost 2; }
        object gencost { name c1; parent g1; model POLYNOMIAL; costs "0,1,0"; }
        module pypower { maximum_timestep 3600; with_emissions TRUE; }
        """, stop="2020-01-01 03:00:00")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    pmax = value(runner, "g1", "Pmax")
    assert pmax > 0 and pmax % 180 == pytest.approx(0)
    assert value(runner, "g1", "Qmax") == pytest.approx(0.2*pmax)
    assert value(runner, "p1", "ramp_rate") == 1
    assert runner.model.get_property("c1", "costs") == "0.000000,20.000000,2.000000"
    assert value(runner, "p1", "total_cost") > 0
    assert any("no emissions rate given" in x for x in helpers.warnings(runner))

@pytest.mark.parametrize("glm, message", [
    ("object powerplant { name p; }", "powerplant must have a bus or gen parent"),
    ("object weather { name w; } object powerplant { parent w; }", "parent 'w' is not a pypower bus or gen object"),
    ("object bus { name x; } object powerplant { parent b1; weather x; derating 1; Tcutoff 10; }", "object 'x' is not a pypower weather object"),
    ("object weather { name w; } object powerplant { parent b1; weather w; derating 1; Tcutoff 10; Tnominal 20; }", "Tcutoff is not greater than Tnominal"),
    ("object weather { name w; } object powerplant { parent b1; weather w; derating -1; Tcutoff 30; Tnominal 20; }", "derating must be non-negative"),
])
def test_powerplant_errors(helpers, glm, message):
    """Powerplant initialization errors"""
    init_error(helpers, "object bus { name b1; baseKV 1 kV; }\n" + glm, message)

#
# Powerlines, transformers, relays, shunts
#
@pytest.mark.parametrize("glm, message", [
    ("object powerline { parent br; length 1; impedance 1+1j; } object powerline { parent br; length 1; impedance 1+1j; }",
        "parent 'br' cannot accept more than one child component"),
    ("object powerline { name p; length 1; impedance 1+1j; composition SERIES; } object powerline { parent p; length 1; }",
        "parent 'p' non-zero impedance would be overwritten"),
    ("object powerline { name p; } object powerline { parent p; length 1; }", "parent 'p' does not specify powerline composition"),
    ("object powerline { parent b1; length 1; }", "parent 'b1' is not a pypower branch or powerline"),
    ("object powerline { parent br; length 0; impedance 1+1j; }", "line length must be positive"),
    ("object transformer { impedance 0; rated_power 1; }", "transformer impedance must be positive"),
    ("object transformer { impedance 1; susceptance -1; rated_power 1; }", "transformer susceptance cannot be negative"),
    ("object transformer { parent b1; impedance 1; rated_power 1; }", "parent 'b1' is not a pypower branch"),
    ("object transformer { parent br; impedance 1; rated_power 1; } object transformer { parent br; impedance 1; rated_power 1; }",
        "branch 'br' cannot accept more than one child component"),
    ("object relay { parent b1; }", "relay parent must by a pypower branch"),
    ("object relay { parent br; controller f; }", "unable to find global controllers"),
])
def test_component_errors(helpers, glm, message):
    """Powerline, transformer, and relay initialization errors"""
    init_error(helpers, """object bus { name b1; baseKV 1 kV; } object bus { name b2; baseKV 1 kV; }
        object branch { name br; from b1; to b2; rateA 1; }\n""" + glm, message)

def test_components(helpers):
    """A transformer sets its branch; a relay without controller sets its
    branch's status; components without parents warn"""
    runner = helpers.run(helpers.THREE_BUS + """
        object transformer { parent l13; impedance 0.01+0.2j Ohm; rated_power 50 MVA; tap_ratio 1.3; phase_shift 400; }
        object relay { parent l23; status OPEN; }
        object relay { name r0; }
        object powerline { name p0; length 1; }
        object transformer { name t0; impedance 1; rated_power 1; }
        """)
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert value(runner, "l13", "x") == pytest.approx(0.2)
    assert value(runner, "l13", "ratio") == pytest.approx(1.3)
    assert runner.model.get_property("l23", "status") == "OUT"
    text = "\n".join(helpers.warnings(runner))
    for message in ("tap ratio outside reasonable range", "phase shift value 400 seems unlikely", "relay has no controller",
            "relay without parent does nothing", "powerline without parent does nothing", "transformer without parent branch"):
        assert message in text

def test_transformer_tap(helpers):
    """A tap ratio that is not positive stops the run"""
    runner = helpers.run(helpers.THREE_BUS + "object transformer { parent l13; impedance 1; rated_power 1; tap_ratio 0; }")
    assert runner.returncode == exitcodes.RUNERR
    assert any("tap ratio must be positive" in x for x in helpers.errors(runner))

def test_powerline_out(helpers):
    """A powerline `OUT` takes its branch out of service"""
    runner = helpers.run(helpers.THREE_BUS + "object powerline { parent l13; length 2 mile; impedance 0.01+0.1j Ohm/mile; status OUT; }")
    assert runner.model.get_property("l13", "status") == "OUT"

@pytest.mark.parametrize("glm, message", [
    ("control_mode DISCRETE_VAR;", "advanced control modes not supported yet"),
    ("control_mode DISCRETE_V; voltage_low 1.1; voltage_high 1.0;", "voltage_low is greater than voltage_high"),
    ("control_mode DISCRETE_V; voltage_low 1.0; voltage_high 1.001;", "voltage_low is within minimum_voltage_"),
    ("steps_1 1; dwell_time 1;", "zero admittance step values are not valid"),
    ("steps_2 1; dwell_time 1;", "multiple control blocks not supported yet"),
    ("", "dwell_time must be positive"),
    ("control_mode CONTINUOUS_V; voltage_low 0.9; voltage_high 1.1; dwell_time 1;", "control_gain (0) must be positive"),
    ("control_mode DISCRETE_V; voltage_low 0.9; voltage_high 1.1; dwell_time 1;", "steps_1 must be positive"),
    ("remote_bus w; dwell_time 1;", "remote_bus is not a pypower bus"),
])
def test_shunt_errors(helpers, glm, message):
    """Shunt initialization errors"""
    init_error(helpers, "object bus { name b1; baseKV 1 kV; } object weather { name w; }\n"
        f"object shunt {{ parent b1; {glm} }}", message)
    init_error(helpers, "object shunt { dwell_time 1; }", "parent bus must be specified")

def test_shunt_fixed(helpers):
    """A fixed shunt adds its admittance to the bus; an offline shunt has
    none"""
    runner = helpers.run(helpers.THREE_BUS + """
        object shunt { name s1; parent b2; status ONLINE; output REAL; admittance 5 MVAr; dwell_time 60; }
        object shunt { name s2; parent b3; status OFFLINE; admittance 5 MVAr; dwell_time 60; }
        """)
    assert value(runner, "b2", "Pd") == pytest.approx(55)
    assert value(runner, "s2", "admittance") == 0

#
# Geodata
#
GEODATA = """timestamp,9q8yy,9q9p1
2020-01-01 00:00:00 UTC,1,2
2020-01-01 01:00:00 UTC,3,4
"""

def test_geodata(helpers):
    """Values are written to the nearest objects by class and by name"""
    helpers.write("geo.csv", GEODATA)
    runner = helpers.run(helpers.THREE_BUS + """
        modify b2.latitude 37.77; modify b2.longitude -122.42;
        modify b3.latitude 37.87; modify b3.longitude -122.27;
        object geodata { file geo.csv; target "bus::Gs,b3.Bs,b3.Bs,b2.Pd"; scale 2; }
        """, stop="2020-01-01 01:00:00")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    text = "\n".join(helpers.warnings(runner))
    assert "object 'b1' does not have any geodata" in text
    assert "ignoring duplicate reference to object 'b3.Bs'" in text
    assert "writing to 'b2' output 'Pd'" in text

@pytest.mark.parametrize("file, target, message", [
    (None, "b1.Pd", "file 'missing.csv' is not found"),
    (GEODATA, "", "target is not specified"),
    (GEODATA, "nothing::x", "class 'nothing' is not valid"),
    (GEODATA, "x.y", "object 'x' not found"),
    (GEODATA, "x", "target 'x' is not valid"),
    (GEODATA, "b1.nothing", "unable to find property 'nothing' in object 'b1'"),
    (GEODATA, "bus::nothing", "unable to find property 'nothing' in object 'b1'"),
    ("time,9q8yy\n", "b1.Pd", "column 0 must be 'timestamp'"),
    ("timestamp,9qa8y\n", "b1.Pd", "geocode '9qa8y' is not valid"),
    ("timestamp,9q8yy\nbad,1\n", "b1.Pd", "invalid timestamp 'bad'"),
    ("timestamp,9q8yy\n2020-01-01 00:00:00 UTC,x\n", "b1.Pd", "invalid float value 'x"),
    ("timestamp,9q8yy\n2020-01-01 00:00:00 UTC,1,2\n", "b1.Pd", "unexpected extra data"),
    ("timestamp,9q8yy,9q9p1\n2020-01-01 00:00:00 UTC,1\n", "b1.Pd", "missing data"),
])
def test_geodata_errors(helpers, file, target, message):
    """Geodata initialization errors"""
    if file is not None:
        helpers.write("geo.csv", file)
    init_error(helpers, f"""object bus {{ name b1; baseKV 1 kV; latitude 37.7; longitude -122.4; }}
        object geodata {{ file {'geo.csv' if file else 'missing.csv'}; target "{target}"; }}""", message)

def test_saved_files(helpers):
    """`save_case` writes the case data in the chosen format"""
    runner = helpers.run(helpers.THREE_BUS + "module pypower { save_case TRUE; save_format PY; }")
    assert runner.returncode == exitcodes.SUCCESS
    assert os.path.exists("pypower_casedata.py") and os.path.exists("pypower_results.py")
