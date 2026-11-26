"""The powerflow library classes: spacings, conductors, transformer and
regulator configurations, restoration, power metrics, and pole
configurations"""
# pylint: disable=missing-function-docstring,line-too-long

import os

import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model
from powerflow.pole_configuration import PoleConfiguration

LIBRARY = ["line_spacing", "overhead_line_conductor", "underground_line_conductor", "line_configuration",
    "transformer_configuration", "regulator_configuration", "triplex_line_configuration", "triplex_line_conductor", "restoration",
    "power_metrics", "pole_configuration"]

def test_registration():
    """Library classes in gridlabd's order, without a parent class, with
    the readiness levels and defaults gridlabd gives them; the
    `climate_impact_zone` global"""
    m = Model()
    m.read_glm("module powerflow;\n")
    names = [x.name for x in powerflow.classes()]
    assert [x for x in names[names.index("line_spacing"):] if not x.endswith("_line")] == LIBRARY
    for name in LIBRARY:
        assert getattr(Class.find(name, module="powerflow"), "parent", None) is None
    assert Class.find("restoration", module="powerflow").trl == 7
    assert Class.find("power_metrics", module="powerflow").trl == 8
    assert Class.find("triplex_line_conductor", module="powerflow").find_property("rating.summer.emergency").default == "212.1 A"
    assert Class.find("pole_configuration", module="powerflow").find_property("pole_length").default == "45 ft"
    assert list(Class.find("pole_configuration", module="powerflow").find_property("pole_type").keywords) == ["STEEL", "CONCRETE", "WOOD"]
    assert Class.find("transformer_configuration", module="powerflow").find_property("shunt_impedance").default == "+1e+09+1e+09j pu.Ohm"
    assert Class.find("power_metrics", module="powerflow").find_property("ASAI").default == "1"
    assert m.globals.get("powerflow::climate_impact_zone") == "NONE"
    assert list(m.globals.find("powerflow::climate_impact_zone").keywords) == ["NONE", "LOW", "MODERATE", "INTERMEDIATE", "HIGH", "EXTREME"]

def run(helpers, glm, module=""):
    return helpers.run(glm, module=module, lines=False)

def test_valid_objects(helpers):
    """Valid objects of every library class initialize"""
    r = run(helpers, """
        object line_spacing { name ls; distance_AB 2.5; distance_BC 4.5; distance_AC 7; distance_AN 5.66; distance_BN 4.27; distance_CN 5; }
        object overhead_line_conductor { name oc; geometric_mean_radius 0.0244; resistance 0.306; diameter 0.721; }
        object underground_line_conductor { name uc; outer_diameter 1.29; conductor_gmr 0.0171; conductor_diameter 0.567; conductor_resistance 0.41; neutral_gmr 0.0020800; neutral_diameter 0.0640837; neutral_resistance 14.8722; neutral_strands 13; }
        object triplex_line_conductor { name tc; resistance 0.97; geometric_mean_radius 0.0111; }
        object transformer_configuration { name xc; connect_type WYE_WYE; install_type PADMOUNT; primary_voltage 4160; secondary_voltage 480; power_rating 500; resistance 0.011; reactance 0.02; }
        object regulator_configuration { name rc; connect_type WYE_WYE; raise_taps 16; lower_taps 16; band_center 122; band_width 2; regulation 0.10; Control OUTPUT_VOLTAGE; }
        object restoration { name rs; }
        object power_metrics { name pm; }
        object pole_configuration { name pc; treatment_method CCA; }
        """, module="climate_impact_zone HIGH;")
    assert r.returncode == 0, r.stderr
    m = r.model
    assert powerflow.get_double(m, "xc", "powerA_rating") == pytest.approx(500/3)
    assert powerflow.get_complex(m, "xc", "impedance") == pytest.approx(0.011+0.02j)
    assert powerflow.get_double(m, "pc", "degradation_rate") == pytest.approx(0.047)
    assert powerflow.get_double(m, "pm", "base_time_value") == 60
    assert any("Attempt to parse double CSV array resulted in an empty array" in x for x in helpers.warnings(r))

def test_transformer_aliases(helpers):
    """`resistance`/`reactance` and `impedance` share their value, the last
    one set winning, as gridlabd's shared storage does"""
    r = run(helpers, """
        object transformer_configuration { name a; connect_type WYE_WYE; primary_voltage 4160; secondary_voltage 480; power_rating 500; impedance 0.01+0.06j; reactance 0.08; }
        object transformer_configuration { name b; connect_type WYE_WYE; primary_voltage 4160; secondary_voltage 480; power_rating 500; reactance 0.08; impedance 0.01+0.06j; }
        object transformer_configuration { name c; connect_type WYE_WYE; primary_voltage 4160; secondary_voltage 480; power_rating 500; resistance 0.02; reactance 0.05; shunt_resistance 500; }
        """)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert powerflow.get_complex(m, "a", "impedance") == pytest.approx(0.01+0.08j)
    assert powerflow.get_double(m, "a", "resistance") == pytest.approx(0.01)
    assert powerflow.get_complex(m, "b", "impedance") == pytest.approx(0.01+0.06j)
    assert powerflow.get_double(m, "b", "reactance") == pytest.approx(0.06)
    assert powerflow.get_complex(m, "c", "impedance") == pytest.approx(0.02+0.05j)
    assert powerflow.get_complex(m, "c", "shunt_impedance") == pytest.approx(500+1e9j)

def test_transformer_center_tapped(helpers):
    """Losses give the impedances of a center-tapped transformer; a missing
    secondary impedance copies the other"""
    r = run(helpers, """
        object transformer_configuration { name ct; connect_type SINGLE_PHASE_CENTER_TAPPED; primary_voltage 7200; secondary_voltage 120; power_rating 600; powerA_rating 600; no_load_loss 0.004; full_load_loss 0.012; impedance1 0.012+0.0068j; }
        """)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert powerflow.get_complex(m, "ct", "impedance") == pytest.approx(0.012+0.054j)
    assert powerflow.get_complex(m, "ct", "shunt_impedance") == pytest.approx(250+1125j)
    assert powerflow.get_complex(m, "ct", "impedance2") == pytest.approx(0.012+0.0068j)
    warnings = helpers.warnings(r)
    assert any("reactance_resistance_ratio was not set and defaulted to 4.5" in x for x in warnings)
    assert any("impedance1 was defined, but impedance2 was not -- assuming they are equal" in x for x in warnings)

def test_transformer_shunt_warning(helpers):
    """The shunt warning for connections other than WYE_WYE appears only
    when the shunt impedance is not the default"""
    base = "connect_type DELTA_DELTA; primary_voltage 4160; secondary_voltage 480; power_rating 500; impedance 0.01+0.06j;"
    r = run(helpers, f"object transformer_configuration {{ name a; {base} }} object transformer_configuration {{ name b; {base} shunt_impedance 1000+1000j; }}")
    assert r.returncode == 0, r.stderr
    shunt = [x for x in helpers.warnings(r) if "does not support shunt_impedance" in x]
    assert len(shunt) == 1 and "(b)" in shunt[0]

def test_pole_diameter(helpers):
    m = helpers.model("object pole_configuration { name pc; }", lines=False)
    assert PoleConfiguration.pole_diameter(m, "pc", 4.5) == pytest.approx(32.5/3.14*(1 - 0.58))
    assert PoleConfiguration.pole_diameter(m, "pc", 45) == 0

def test_restoration_output_file(helpers):
    with open("restore.txt", "w", encoding="utf-8") as file:
        file.write("old")
    r = run(helpers, 'object restoration { name rs; output_filename "restore.txt"; }')
    assert r.returncode == 0, r.stderr
    assert os.path.getsize("restore.txt") == 0

TRANSFORMER = "primary_voltage 4160; secondary_voltage 480; power_rating 500; impedance 0.01+0.06j;"

@pytest.mark.parametrize("glm,module,message", [
    ("object overhead_line_conductor { name oc; geometric_mean_radius 0.02; diameter 0.7; }", "", "init_overhead_line_conductor(obj=0;oc): overhead_line_conductor:0 - oc - NR: resistance is zero"),
    ("object overhead_line_conductor { name oc; geometric_mean_radius 0.02; diameter 0.7; }", "solver_method FD_XB;", "overhead_line_conductor:0 - oc - FD_XB: resistance is zero"),
    ("object triplex_line_conductor { name tc; }", "solver_method FBS;", "triplex_line_conductor:0 - tc - NR: resistance is zero"),
    ("object underground_line_conductor { name uc; outer_diameter 0.5; conductor_diameter 0.6; neutral_diameter 0.1; conductor_resistance 0.4; }", "", "outer_diameter was specified as less than the conductor_diameter"),
    ("object underground_line_conductor { name uc; outer_diameter 1; conductor_diameter 0.6; neutral_diameter 1.1; conductor_resistance 0.4; }", "", "outer_diameter was specified as less than the neutral_diameter"),
    ("object underground_line_conductor { name uc; outer_diameter 1; conductor_diameter 0.6; neutral_diameter 0.1; conductor_resistance 0.4; shield_thickness 0.1; }", "", "shield_diameter was specified as less than the tapeshield_thickness"),
    ("object underground_line_conductor { name uc; outer_diameter 1; conductor_diameter 0.6; neutral_diameter 0.1; }", "solver_method DC;", "underground_line_conductor:0 - uc - DC: conductor_resistance is zero"),
    ("object underground_line_conductor { name uc; outer_diameter 1; conductor_diameter 0.6; neutral_diameter 0.1; conductor_resistance 0.4; insulation_R 0; }", "", "insulation_R must be positive"),
    (f"object transformer_configuration {{ name xc; {TRANSFORMER} }}", "", "init_transformer_configuration(obj=0;xc): connection type not specified"),
    ("object transformer_configuration { name xc; connect_type WYE_WYE; secondary_voltage 480; power_rating 500; impedance 0.01+0.06j; }", "", "V_primary must be positive"),
    ("object transformer_configuration { name xc; connect_type WYE_WYE; primary_voltage 4160; power_rating 500; impedance 0.01+0.06j; }", "", "V_secondary must be positive"),
    ("object transformer_configuration { name xc; connect_type WYE_WYE; primary_voltage 4160; secondary_voltage 480; impedance 0.01+0.06j; }", "", "kVA_rating(s) must be positive"),
    (f"object transformer_configuration {{ name xc; connect_type WYE_WYE; {TRANSFORMER} powerA_rating 100; powerB_rating 100; powerC_rating 100; }}", "", "kVA rating mismatch across phases exceeds 1%"),
    ("object transformer_configuration { name xc; connect_type WYE_WYE; primary_voltage 4160; secondary_voltage 480; power_rating 500; reactance 0.06; }", "", "resistance must be non-negative"),
    ("object transformer_configuration { name xc; connect_type WYE_WYE; primary_voltage 4160; secondary_voltage 480; power_rating 500; resistance 0.01; }", "", "reactance must be non-negative"),
    (f"object transformer_configuration {{ name xc; connect_type WYE_WYE; {TRANSFORMER} shunt_resistance -1; }}", "", "shunt_resistance must be non-negative"),
    ("object regulator_configuration { name rc; connect_type WYE_WYE; raise_taps 16; lower_taps 16; Control LINE_DROP_COMP; regulation 0.1; }", "", "power_transducer_ratio must be set as a non-zero value when operating in LINE_DROP_COMP mode"),
    ("object regulator_configuration { name rc; connect_type WYE_WYE; raise_taps 16; lower_taps 16; control_level BANK; }", "", "There are too many CT_phases specified for a BANK control_level"),
    ("object regulator_configuration { name rc; connect_type WYE_WYE; raise_taps 16; lower_taps 16; control_level BANK; CT_phase A; }", "", "There are too many PT_phases specified for a BANK control_level"),
    ("object regulator_configuration { name rc; connect_type WYE_WYE; raise_taps 16; }", "", "raise and lower taps must be specified to non-zero numbers"),
    ("object regulator_configuration { name rc; connect_type WYE_WYE; raise_taps 16; lower_taps 16; Control OUTPUT_VOLTAGE; }", "", "regulation must be set to a non-zero number when operating in an automatic controlled mode."),
    ("object regulator_configuration { name rc; connect_type CLOSED_DELTA; raise_taps 16; lower_taps 16; Control OUTPUT_VOLTAGE; regulation 0.1; }", "", "At this time, only WYE_WYE regulators are supported in automatic control modes."),
    ("object regulator_configuration { name rc; connect_type CLOSED_DELTA; raise_taps 16; lower_taps 16; }", "solver_method FBS;", "Only WYE_WYE regulator connections are fully supported in FBS & NR solvers at this time."),
    ("object restoration { name rs; }", "solver_method FD_BX;", "Restoration control is only valid for the Newton-Raphson solver at this time."),
    ("object restoration { name r1; } object restoration { name r2; }", "", "init_restoration(obj=1;r2): Only one restoration object is permitted per model file"),
    ("object restoration { name rs; reconfig_attempts 0; }", "", "Infinite reconfigurations set."),
    ('object node { name n1; phases ABC; nominal_voltage 120; } object restoration { name rs; feeder_power_limit "1e6,2e6"; feeder_vertex_list "n1"; }', "", "restoration: The number of feeder limits and feeder vertices must be the same!"),
    ('object node { name n1; phases ABC; nominal_voltage 120; } object restoration { name rs; feeder_power_limit "1e6"; feeder_vertex_list "n1"; }', "", "restoration: The number of feeder links and feeder vertices must be the same!"),
    ('object node { name n1; phases ABC; nominal_voltage 120; } object restoration { name rs; microgrid_power_limit "1e6+1e5j"; microgrid_vertex_list "n1"; microgrid_power_links "n1"; }', "", "Restoration: failed to find power calculation function for link:n1"),
    ("object restoration { name rs; lower_voltage_limit 1.05; upper_voltage_limit 0.95; }", "", "restoration: the upper and lower voltage limits are either equal, or backwards"),
    ("object pole_configuration { name pc; degradation_rate -1; }", "", "init_pole_configuration(obj=0;pc): pc: degradation_rate must be zero or positive"),
    ("object pole_configuration { name pc; repair_time -1; }", "", "pc: repair time must be positive (or negative to use global pole::repair_time"),
])
def test_init_errors(helpers, glm, module, message):
    r = run(helpers, glm, module)
    assert r.returncode != 0
    assert any(message in x for x in helpers.errors(r)), r.stderr

@pytest.mark.parametrize("glm,message", [
    ("object regulator_configuration { name rc; connect_type WYE_WYE; raise_taps 16; lower_taps 16; Control OUTPUT_VOLTAGE; regulation 0.1; }", "band_width is set to zero in automatic control. May cause oscillations."),
    ("object restoration { name rs; reconfig_iteration_limit 0; }", "Infinite reconfiguration iterations set."),
    (f"object transformer_configuration {{ name xc; connect_type WYE_WYE; {TRANSFORMER} impedance1 0.01+0.01j; }}", "This connection type on transformer:0 (xc) does not support impedance (impedance1 or impedance2) of secondaries at this time."),
    (f"object transformer_configuration {{ name xc; connect_type WYE_WYE; {TRANSFORMER} no_load_loss 0.01; }}", "This connection type on transformer:0 (xc) does not support shunt_impedance at this time."),
])
def test_init_warnings(helpers, glm, message):
    r = run(helpers, glm)
    assert r.returncode == 0, r.stderr
    assert any(message in x for x in helpers.warnings(r)), r.stderr

#
# triplex_line_configuration
#
def test_triplex_line_configuration(helpers):
    """A `triplex_line_configuration` has no parent class but is a
    `line_configuration`: a `line` accepts it and uses its z11 ... z22"""
    m = Model()
    m.read_glm("module powerflow;\n")
    config = Class.find("triplex_line_configuration", module="powerflow")
    assert getattr(config, "parent", None) is None
    assert [p.name for p in config.properties()] == ["conductor_1", "conductor_2", "conductor_N", "insulation_thickness",
        "diameter", "spacing", "z11", "z12", "z21", "z22", "rating.summer.continuous", "rating.summer.emergency",
        "rating.winter.continuous", "rating.winter.emergency"]
    assert config.find_property("rating.winter.emergency").default == "2000 A"
    Class.reset()
    r = helpers.run("""
        object triplex_line_configuration { name tlc; z11 0.5+0.3j; z12 0.1+0.2j; z21 0.1+0.2j; z22 0.5+0.3j; }
        object node { name n0; phases ABN; nominal_voltage 120; bustype SWING; }
        object line { name l1; phases ABN; from n0; to n1; length 100; configuration tlc; }
        object node { name n1; phases ABN; nominal_voltage 120; power_A 500; }
        """, lines=False)
    assert r.returncode == 0, r.stderr
    from powerflow.line import Line # pylint: disable=import-outside-toplevel
    zabc, yabc = Line.line_matrices(r.model, "l1")
    assert zabc[0, 1] == pytest.approx((0.1+0.2j)*100/5280) and zabc[2, 2] == 0 and not yabc.any()
    assert powerflow.get_complex(r.model, "l1", "power_out_A") == pytest.approx(500)

#
# power_metrics
#
def test_power_metrics(helpers):
    """IEEE 1366 indices from the reliability module's calls"""
    from powerflow.power_metrics import PowerMetrics as P # pylint: disable=import-outside-toplevel
    m = helpers.model("object power_metrics { name pm; }", lines=False)
    get = lambda prop_: powerflow.get_double(m, "pm", prop_)
    assert P.calc_metrics(m, "pm", 10, 0, 100, 3600, 0) == 1
    assert (get("SAIFI"), get("SAIDI"), get("CAIDI"), get("MAIFI")) == pytest.approx((0.1, 6.0, 60.0, 0.0))
    assert get("ASAI") == pytest.approx((876000 - 10)/876000)
    assert get("SAIFI_int") == pytest.approx(0.1)
    extra = P.init_reliability(m, "pm", "metrics1")
    extra.value = 2
    P.calc_metrics(m, "pm", 20, 5, 100, 120, 0)
    assert get("SAIFI") == pytest.approx(0.1)
    assert get("MAIFI") == pytest.approx((20 + 2*5)/100)
    assert P.reset_annual_metrics(m, "pm") == 1
    assert (get("SAIFI_int"), get("ASAI_int"), get("SAIFI")) == pytest.approx((0.0, 1.0, 0.1))
    P.calc_metrics(m, "pm", 10, 0, 100, 3600, 0)
    assert get("SAIFI") == pytest.approx(0.2) and get("SAIFI_int") == pytest.approx(0.1)
    P.calc_metrics(m, "pm", 10, 0, 0, 3600, 0)
    assert (get("SAIFI"), get("ASAI"), get("MAIFI")) == (0, 0, 0)
    with pytest.raises(powerflow.PowerflowError, match="power_metrics failed to map fault_check object!"):
        P.reset_interval_metrics(m, "pm")

@pytest.mark.parametrize("base,text", [(60, "1366 metrics based around 1-minute base (outage-minutes)\n\n"),
    (3600, "1366 metrics based around 1-hour base (outage-hours)\n\n"), (900, "1366 metrics uses time base of 900 seconds\n\n")])
def test_power_metrics_logfile(helpers, base, text):
    from powerflow.power_metrics import PowerMetrics # pylint: disable=import-outside-toplevel
    m = helpers.model(f"object power_metrics {{ name pm; base_time_value {base}; }}", lines=False)
    assert PowerMetrics.logfile_extra(m, "pm") == text

#
# restoration
#
def test_restoration_rejects_fbs(helpers):
    r = run(helpers, "object restoration { name rs; }", "solver_method FBS;")
    assert r.returncode != 0
    assert any("init_restoration(obj=0;rs): Restoration control is only valid for the Newton-Raphson solver at this time." in x for x in helpers.errors(r))

def test_restoration_unnamed_link(helpers):
    """An unnamed object in the link lists is reported as `Unnamed`"""
    r = run(helpers, 'object node { phases ABC; nominal_voltage 120; } object restoration { name rs; feeder_power_limit "1e6"; feeder_vertex_list "node:0"; feeder_power_links "node:0"; }')
    assert r.returncode != 0
    assert any("Restoration: failed to find power calculation function for link:Unnamed" in x for x in helpers.errors(r)), r.stderr

def test_perform_restoration_needs_fault_check(helpers):
    """The entry point fault_check calls fails without fault_check, as in
    gridlabd"""
    from powerflow.restoration import Restoration # pylint: disable=import-outside-toplevel
    m = helpers.model("object restoration { name rs; }", lines=False)
    with pytest.raises(powerflow.PowerflowError, match="Restoration: fault_check object not found."):
        Restoration.perform_restoration(m, "rs", -99)
