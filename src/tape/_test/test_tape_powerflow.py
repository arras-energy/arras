"""Violation recorders, metrics collectors, and metrics collector writers,
with GLM classes standing in for the powerflow and residential classes"""

import json

import pytest

from arras import exitcodes
from arras.runner import Runner
from tape.metrics_collector import metrics, _out_of_limit

PHASES = "set {A=1, B=2, C=4, N=8, S=112, G=128, D=256} phases"

CLASSES = f"""
class node {{ {PHASES}; double nominal_voltage[V]; complex voltage_A[V]; complex voltage_B[V]; complex voltage_C[V]; }}
class triplex_node {{ {PHASES}; double nominal_voltage[V]; complex voltage_12[V]; }}
class triplex_meter {{ {PHASES}; double nominal_voltage[V]; complex voltage_1[V]; complex voltage_2[V]; complex voltage_12[V];
    double measured_real_power[W]; double measured_reactive_power[VAr]; double price; }}
class meter {{ {PHASES}; double nominal_voltage[V]; enumeration {{PQ=0, PV=1, SWING=2}} bustype; complex voltage_A[V]; complex voltage_B[V]; complex voltage_C[V];
    complex voltage_AB[V]; complex voltage_BC[V]; complex voltage_CA[V]; double measured_real_power[W]; double measured_reactive_power[VAr];
    complex measured_power[VA]; double price; }}
class transformer_configuration {{ double power_rating[kVA]; double powerA_rating[kVA]; double powerB_rating[kVA]; double powerC_rating[kVA]; }}
class transformer {{ {PHASES}; object from; object to; object configuration; complex power_out[VA]; complex power_out_A[VA];
    complex power_out_B[VA]; complex power_out_C[VA]; complex power_in[VA]; complex current_out_A[A]; complex current_out_B[A];
    complex current_out_C[A]; set {{UNKNOWN=0, AF=1, AR=2, AN=3, BF=16, BR=32, BN=48, CF=256, CR=512, CN=768}} flow_direction;
    complex power_losses[VA]; }}
class overhead_line_conductor {{ double rating.summer.continuous[A]; }}
class line_configuration {{ object conductor_A; object conductor_B; object conductor_C; double rating.summer.continuous[A]; }}
class overhead_line {{ {PHASES}; object from; object to; object configuration; complex current_out_A[A]; complex current_out_B[A]; complex current_out_C[A]; }}
class underground_line {{ {PHASES}; object from; object to; object configuration; complex current_out_A[A]; }}
class triplex_line_conductor {{ double rating.summer.continuous[A]; }}
class triplex_line_configuration {{ object conductor_1; object conductor_2; double rating.summer.continuous[A]; }}
class triplex_line {{ {PHASES}; object from; object to; object configuration; complex current_out_A[A]; complex current_out_B[A]; }}
class inverter {{ {PHASES}; complex VA_Out[VA]; complex phaseA_V_Out[V]; complex phaseB_V_Out[V]; complex phaseC_V_Out[V]; }}
class house {{ double total_load[kW]; double hvac_load[kW]; double air_temperature[degF]; double cooling_setpoint[degF]; double heating_setpoint[degF]; }}
class waterheater {{ double actual_load[kW]; }}
class capacitor {{ double cap_A_switch_count; double cap_B_switch_count; double cap_C_switch_count; }}
class regulator {{ double tap_A_change_count; double tap_B_change_count; double tap_C_change_count; }}
class substation {{ enumeration {{PQ=0, PV=1, SWING=2}} bustype; complex distribution_load[VA]; }}
class other {{ double x; }}
"""

NETWORK = """
object node { name n1; phases ABC; nominal_voltage 120; voltage_A 130; voltage_B 120; voltage_C 100; }
object node { name n2; phases A; nominal_voltage 120; voltage_A 120; }
object node { name n3; phases A; nominal_voltage 120; voltage_A 140; }
object triplex_node { name tn1; phases AS; nominal_voltage 120; voltage_12 260; }
object triplex_meter { name tm1; groupid commercialMeter; phases AS; nominal_voltage 120; voltage_1 125; voltage_2 125; voltage_12 260; }
object transformer_configuration { name tc; powerA_rating 10; }
object transformer_configuration { name tcs; power_rating 10; }
object transformer { name x1; phases A; from n1; to n2; configuration tc; power_out_A 12000; current_out_A 900; flow_direction AR; power_in 1000+1000j; }
object transformer { name x2; phases AS; from n1; to tm1; configuration tcs; power_out 15000; }
object overhead_line_conductor { name c1; rating.summer.continuous 100; }
object line_configuration { name lc; conductor_A c1; rating.summer.continuous 50; }
object overhead_line { name l1; phases AB; from n2; to n3; configuration lc; current_out_A 120; current_out_B 60; }
object underground_line { name u1; phases A; from n2; to n3; configuration lc; current_out_A 200; }
object triplex_line_conductor { name tc1; rating.summer.continuous 100; }
object triplex_line_configuration { name tlc; conductor_1 tc1; conductor_2 tc1; }
object triplex_line { name tl1; phases AS; from n2; to tm1; configuration tlc; current_out_A 150; current_out_B 50; }
object inverter { name inv1; phases A; phaseA_V_Out 120; }
object inverter { name inv2; phases AS; phaseB_V_Out 120; }
"""

LIMITS = """xfrmr_thermal_limit_upper 1.1; xfrmr_thermal_limit_lower 0; line_thermal_limit_upper 1.1; line_thermal_limit_lower 0;
    node_instantaneous_voltage_limit_upper 1.05; node_instantaneous_voltage_limit_lower 0.95;
    node_continuous_voltage_limit_upper 1.05; node_continuous_voltage_limit_lower 0.95; node_continuous_voltage_interval 0;
    secondary_dist_voltage_rise_upper_limit 0.01; secondary_dist_voltage_rise_lower_limit -0.5;
    substation_breaker_A_limit 1000; substation_pf_lower_limit 0.9;
    inverter_v_chng_per_interval_upper_bound 0.05; inverter_v_chng_per_interval_lower_bound -0.05; inverter_v_chng_interval 0;"""

def test_violations(helpers, monkeypatch):
    """Each violation check, the log rows, and the summary (`tm1` is also a
    commercial meter, whose `voltage_A` it lacks, so it is 0)"""
    monkeypatch.setenv("USER", "tester")
    glm = CLASSES + NETWORK + f'object violation_recorder {{ file "v.csv"; summary "s.csv"; virtual_substation x1; violation_flag ALLVIOLATIONS; interval -1; echo TRUE; {LIMITS} }}'
    runner = helpers.run(glm, stop="2020-01-01 00:00:00")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    rows = [x.split(",", 1)[1] for x in helpers.lines("v.csv") if not x.startswith("#")]
    assert rows == [
        "VIOLATION1, 1.200000, 1.100000, 0.000000, x1, transformer, A, Power violates thermal limit.",
        "VIOLATION1, 1.500000, 1.100000, 0.000000, x2, transformer, S, Power violates thermal limit.",
        "VIOLATION1, 1.200000, 1.100000, 0.000000, l1, overhead_line, A, Current violates thermal limit.",
        "VIOLATION1, 1.200000, 1.100000, 0.000000, l1, overhead_line, B, Current violates thermal limit.",
        "VIOLATION1, 2.000000, 1.100000, 0.000000, u1, underground_line, A, Current violates thermal limit.",
        "VIOLATION1, 1.500000, 1.100000, 0.000000, tl1, triplex_line, S1, Current violates thermal limit.",
        "VIOLATION2, 1.083333, 1.050000, 0.950000, n1, node, A, Per unit voltage violates limit.",
        "VIOLATION2, 0.833333, 1.050000, 0.950000, n1, node, C, Per unit voltage violates limit.",
        "VIOLATION2, 1.166667, 1.050000, 0.950000, n3, node, A, Per unit voltage violates limit.",
        "VIOLATION2, 1.083333, 1.050000, 0.950000, tn1, triplex_node, S, Per unit voltage violates limit.",
        "VIOLATION2, 1.083333, 1.050000, 0.950000, tm1, triplex_meter, S, Per unit voltage violates limit.",
        "VIOLATION4, 900.000000, 500.000000, 0.000000, x1, transformer, A, Reverse flow current warning.",
        "VIOLATION5, 900.000000, 750.000000, 0.000000, x1, transformer, A, Reverse flow current violates limit.",
        "VIOLATION7, -1.083333, 0.010000, -0.500000, tm1 n1, triplex_meter node, A, Per unit voltage difference between objects violates limit.",
        "VIOLATION8, 0.707107, 1.000000, 0.900000, x1, transformer,, Power factor violates limit.",
    ]
    assert runner.stdout[0].startswith("VIOLATION1, 1.200000")
    summary = helpers.lines("s.csv")
    assert summary[2] == "# user...... tester"
    assert summary[4:] == ["VIOLATION1 TOTAL,6", "    TRANSFORMER (2 of 2 transformers in violation),2",
        "    OVERHEAD LINE (1 of 1 lines in violation),2", "    UNDERGROUND LINE (1 of 1 lines in violation),1",
        "    TRIPLEX LINE (1 of 1 lines in violation),1", "VIOLATION2 TOTAL,5", "    NODE (2 of 3 nodes in violation),3",
        "    TRIPLEX NODE (1 of 1 nodes in violation),1", "    TRIPLEX METER (1 of 1 meters in violation),1",
        "    COMMERCIAL METER (0 of 1 meters in violation),0", "VIOLATION3 TOTAL,0",
        "    TRIPLEX NODE (0 of 1 nodes in violation),0", "    TRIPLEX METER (0 of 1 meters in violation),0",
        "    COMMERCIAL METER (0 of 1 meters in violation),0", "VIOLATION4 TOTAL,1", "VIOLATION5 TOTAL,1",
        "VIOLATION6 TOTAL (0 of 2 inverters in violation),0", "VIOLATION7 TOTAL,1",
        "    TRIPLEX METER (0 of 1 meters in violation),0", "    COMMERCIAL METER (1 of 1 meters in violation),1", "VIOLATION8 TOTAL,1"]

def test_violation_dynamic(helpers, monkeypatch):
    """Continuous voltage (3) and inverter voltage change (6) violations
    over time, sampled every 10 minutes, with a limit on the rows"""
    import sys, types # pylint: disable=import-outside-toplevel,multiple-imports
    def sync(name, t):
        model = Runner.current().model
        step = (t - 1577836800)//600
        model.set_property("inv1", "phaseA_V_Out", 120 + 10*step)
        model.set_property("tn1", "voltage_12", 260 if step else 240)
        return t + 600
    monkeypatch.setitem(sys.modules, "tape_test_dynamic", types.SimpleNamespace(sync=sync))
    glm = CLASSES + NETWORK + 'object other { on_sync "python:tape_test_dynamic.sync"; }\n' \
        + f'object violation_recorder {{ file "v.csv"; summary "s.csv"; violation_flag "VIOLATION3|VIOLATION6"; interval 600; limit 3; violation_delay 600; {LIMITS} }}'
    runner = helpers.run(glm, stop="2020-01-01 01:00:00")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    text = helpers.lines("v.csv")
    assert text[-1] == "# end of file"
    rows = [x for x in text if not x.startswith("#")]
    assert len(rows) == 3
    assert rows[0].startswith("2020-01-01 00:20:00 UTC,VIOLATION3, 1.083333")
    assert any(",VIOLATION6, 0.076923, 0.050000, -0.050000, inv1, inverter, A, Voltage change between 0s intervals violates limit." in x for x in rows)

def test_violation_options(helpers):
    """Default file names, no monitored link, every pass, and errors"""
    m = helpers.model(CLASSES + 'object violation_recorder { violation_flag ALLVIOLATIONS; interval 0; }')
    m.globals.set("warn", "TRUE")
    runner = Runner(model=m)
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert any("auto-generating 'violation_recorder-violation-log.csv'" in x for x in runner.stderr)
    assert any("no reverse flow violations will be reported" in x for x in runner.stderr)
    assert helpers.lines("violation_recorder-violation-summary.csv")[4] == "VIOLATION1 TOTAL,0"
    for glm, message in (("strict TRUE;", "no filename defined in strict mode"), ('file "x.csv"; strict TRUE;', "no summary defined in strict mode"),
            ('file "x.csv"; summary "y.csv"; interval -2;', "invalid write_interval"),
            ('file "/nonexistent/x.csv"; summary "y.csv"; strict TRUE;', "unable to open file")):
        runner = helpers.run(f'object violation_recorder {{ {glm} }}')
        assert runner.returncode == exitcodes.INIERR
        assert any(message in x for x in runner.stderr), runner.stderr

@pytest.mark.parametrize("parent, glm, expected", [
    ("triplex_meter", "phases AS; nominal_voltage 120; voltage_1 120; voltage_2 120; voltage_12 240; measured_real_power 1000; measured_reactive_power 100; price 0.1;",
        [1000.0, 1000.0, 1000.0, 1000.0, 100.0, 100.0, 100.0, 100.0, 1000.0*5/3600, 100.0*5/3600, 1000.0*5/3600*0.1/1000, 240.0, 240.0, 240.0,
        120.0, 120.0, 120.0, 0.0, 0.0, 0.0, 5.0, 0, 0.0, 0, 5.0, 0, 0.0, 0, 0.0, 0]),
    ("house", "total_load 5; hvac_load 3; air_temperature 72; cooling_setpoint 75; heating_setpoint 70;",
        [3.0, 3.0, 3.0, 3.0, 5.0, 5.0, 5.0, 5.0, 72.0, 72.0, 72.0, 72.0, -3.0, 2.0, 0.0, 0.0, 0.0, 0.0]),
    ("capacitor", "cap_A_switch_count 1; cap_B_switch_count 2;", [3.0]),
    ("regulator", "tap_C_change_count 4;", [4.0]),
])
def test_metrics(helpers, parent, glm, expected):
    """Metrics of each kind of parent"""
    runner = helpers.run(CLASSES + f'object {parent} {{ name "P"; {glm} object metrics_collector {{ name "mc"; interval 5; }}; }}', stop="2020-01-01 00:00:10")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert metrics(runner.model, "mc") == pytest.approx(expected)

def test_metrics_writer(helpers):
    """The JSON files of a writer for meters, houses with water heaters,
    inverters, capacitors, regulators, and the swing bus"""
    glm = CLASSES + """
object meter { name "m"; phases ABC; nominal_voltage 120; voltage_A 120; voltage_B 120; voltage_C 120; voltage_AB 208; voltage_BC 208; voltage_CA 208;
    measured_real_power 1000; object metrics_collector { interval 5; }; }
object meter { name "swing"; bustype SWING; measured_power 1000+500j; object metrics_collector { interval 5; }; }
object house { name "h"; total_load 2; object metrics_collector { interval 5; }; object waterheater { actual_load 4; object metrics_collector { interval 5; }; }; }
object inverter { name "pv"; VA_Out 100+10j; object metrics_collector { interval 5; }; }
object capacitor { name "c"; object metrics_collector { interval 5; }; }
object regulator { name "r"; object metrics_collector { interval 5; }; }
object transformer { name "x"; power_losses -10+5j; }
object metrics_collector_writer { filename "out.json"; interval 5; }
"""
    runner = helpers.run(glm, stop="2020-01-01 00:00:10")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    houses = json.load(open("house_out.json", encoding="utf-8"))
    assert houses["10"]["h"][4:6] == [0.0, 0.0] and houses["10"]["h"][0] == 2.0 and houses["10"]["h"][14] == 4.0
    assert houses["Metadata"]["waterheater_load_median"] == {"index": 17, "units": "kW"}
    feeder = json.load(open("substation_out.json", encoding="utf-8"))
    assert feeder["10"]["swing"][:2] == [1000.0, 1000.0] and feeder["10"]["swing"][10] == 0.0
    meters = json.load(open("billing_meter_out.json", encoding="utf-8"))
    assert meters["StartTime"] == "2020-01-01 00:00:00 UTC" and meters["10"]["m"][11] == 208.0
    text = open("inverter_out.json", encoding="utf-8").read()
    assert text.endswith("}\n\n")
    assert '"pv" : [ 100.0, 100.0, 100.0, 100.0, 10.0, 10.0, 10.0, 10.0 ]' in text
    assert json.load(open("capacitor_out.json", encoding="utf-8"))["5"] == {"c": [0.0]}

@pytest.mark.parametrize("glm, message", [
    ('object metrics_collector { interval 5; }', "must have a parent"),
    ('object other { object metrics_collector { interval 5; }; }', "allows only these parents"),
    ('object house { object metrics_collector { interval 0; }; }', "invalid interval of 0"),
    ('object substation { object metrics_collector { interval 5; }; }', "it must be a SWING bus"),
    ('object metrics_collector_writer { filename "x.json"; interval 0; }', "invalid interval of 0"),
    ('object metrics_collector_writer { filename "x.json"; interval 5; }', "No metrics_collector objects were found"),
    ('object house { object metrics_collector { interval 5; }; }\nobject metrics_collector_writer { filename "x.json"; interval 10; }', "should be the same"),
])
def test_metrics_errors(helpers, glm, message):
    """Metrics collector and writer initialization errors"""
    runner = helpers.run(CLASSES + glm, stop="2020-01-01 00:00:10")
    assert runner.returncode == exitcodes.INIERR
    assert any(message in x for x in runner.stderr), runner.stderr

def test_metrics_default_writer_file(helpers):
    """A writer without a file name makes one up"""
    m = helpers.model(CLASSES + 'object house { object metrics_collector { interval 5; }; }\nobject metrics_collector_writer { interval 5; }', stop="2020-01-01 00:00:05")
    m.globals.set("warn", "TRUE")
    runner = Runner(model=m)
    assert any("auto-generating 'metrics_collector_writer-2-metrics_collector_output.json'" in x for x in runner.stderr)

def test_out_of_limit():
    """`findOutLimit()` durations and counts"""
    assert _out_of_limit(-1.0, [1.0], True, 0.5) == (0.0, 0)
    assert _out_of_limit(-1.0, [0.0, 1.0, 1.0, 0.0], True, 0.5) == (2.0, 2)
    assert _out_of_limit(-1.0, [0.0, 1.0, 1.0, 0.0], False, 0.5) == (2.0, 2)
    assert _out_of_limit(0.0, [1.0, 0.5, 0.5, 0.0], True, 0.5) == (1.5, 2)
    assert _out_of_limit(1.0, [0.5, 1.0, 0.5], True, 0.5) == (3.0, 3)
