"""Classes `overhead_line`, `underground_line`, and `triplex_line`:
registration, initialization, and matrices checked against Kersting's
examples and an independent computation"""
# pylint: disable=missing-function-docstring,line-too-long

import math

import numpy as np
import pytest

from arras.oclass import Class
from arras.model import Model
from powerflow.overhead_line import OverheadLine
from powerflow.underground_line import UndergroundLine
from powerflow.triplex_line import TriplexLine

NODES = """
object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
object node { name n1; phases ABCN; nominal_voltage 2401.7771; power_A 200000+100000j; power_B 120000+60000j; power_C 50000+30000j; }
"""

OVERHEAD = """
object overhead_line_conductor { name olc336; geometric_mean_radius 0.0244 ft; resistance 0.306 Ohm/mile; diameter 0.721 in; }
object overhead_line_conductor { name olc4/0; geometric_mean_radius 0.00814 ft; resistance 0.592 Ohm/mile; diameter 0.563 in; }
object line_spacing { name ls; distance_AB 2.5 ft; distance_BC 4.5 ft; distance_AC 7.0 ft;
    distance_AN 5.656854 ft; distance_BN 4.272002 ft; distance_CN 5.0 ft;
    distance_AE 28 ft; distance_BE 28 ft; distance_CE 28 ft; distance_NE 24 ft; }
object line_configuration { name oc; conductor_A olc336; conductor_B olc336; conductor_C olc336; conductor_N olc4/0; spacing ls; }
"""
"""Kersting example 4.1 (and 5.1): 336,400 26/7 ACSR phases, a 4/0 6/1 ACSR
neutral, phases 28 ft and the neutral 24 ft above ground"""

KERSTING_4_1 = np.array([
    [0.4576+1.0780j, 0.1560+0.5017j, 0.1535+0.3849j],
    [0.1560+0.5017j, 0.4666+1.0482j, 0.1580+0.4236j],
    [0.1535+0.3849j, 0.1580+0.4236j, 0.4615+1.0651j]])
"""Phase impedance matrix of example 4.1 (Ohm/mile)"""

KERSTING_5_1 = 1j*np.array([
    [5.6711, -1.8362, -0.7033],
    [-1.8362, 5.9774, -1.169],
    [-0.7033, -1.169, 5.391]])
"""Shunt admittance matrix of example 5.1 (uS/mile)"""

UNDERGROUND = """
object underground_line_conductor { name ucn; outer_diameter 1.29 in; conductor_gmr 0.0171 ft; conductor_diameter 0.567 in;
    conductor_resistance 0.41 Ohm/mile; neutral_gmr 0.00208 ft; neutral_diameter 0.0641 in; neutral_resistance 14.8722 Ohm/mile;
    neutral_strands 13; insulation_relative_permitivitty 2.3; insulation_R 1; }
object line_spacing { name us; distance_AB 0.5 ft; distance_BC 0.5 ft; distance_AC 1.0 ft; }
object line_configuration { name uc; conductor_A ucn; conductor_B ucn; conductor_C ucn; spacing us; }
"""
"""Kersting example 4.3 (and 5.2): three 250 kcmil AA cables with 13 #14
copper concentric neutral strands, 6 in apart"""

KERSTING_4_3 = np.array([
    [0.7982+0.4463j, 0.3192+0.0328j, 0.2849-0.0143j],
    [0.3192+0.0328j, 0.7891+0.4041j, 0.3192+0.0328j],
    [0.2849-0.0143j, 0.3192+0.0328j, 0.7982+0.4463j]])
"""Phase impedance matrix of example 4.3 (Ohm/mile)"""

TAPE = """
object node { name n0; phases AN; nominal_voltage 2401.7771; bustype SWING; }
object node { name n1; phases AN; nominal_voltage 2401.7771; }
object underground_line_conductor { name uts; outer_diameter 1.06 in; conductor_gmr 0.0111 ft; conductor_diameter 0.368 in;
    conductor_resistance 0.97 Ohm/mile; neutral_gmr 0.01113 ft; neutral_resistance 0.607 Ohm/mile;
    shield_gmr 0.0365 ft; shield_resistance 4.2785 Ohm/mile; shield_diameter 0.88 in; shield_thickness 0.005 in;
    insulation_relative_permitivitty 2.3; insulation_R 1; }
object underground_line_conductor { name un; outer_diameter 0.368 in; conductor_gmr 0.01113 ft; conductor_diameter 0.368 in;
    conductor_resistance 0.607 Ohm/mile; insulation_R 1; }
object line_spacing { name ts; distance_AN 0.25 ft; }
object line_configuration { name tc; conductor_A uts; conductor_N un; spacing ts; }
object underground_line { name u01; phases AN; from n0; to n1; length 5280; configuration tc; }
"""
"""Kersting example 4.4: a 1/0 AA tape-shielded cable and a separate 1/0
copper neutral 3 in away (gridlabd takes the separate neutral's self term
from the phase cable's `neutral_gmr` and `neutral_resistance`)"""

TRIPLEX = """
object node { name n0; phases AS; nominal_voltage 120; }
object node { name n1; phases AS; nominal_voltage 120; }
object triplex_line_conductor { name tlc; resistance 0.97 Ohm/mile; geometric_mean_radius 0.0111 ft; }
object triplex_line_configuration { name tc; conductor_1 tlc; conductor_2 tlc; conductor_N tlc; insulation_thickness 0.08 in; diameter 0.368 in; }
object triplex_line { name t01; phases AS; from n0; to n1; length 100; configuration tc; }
"""
"""Kersting example 11.1: 1/0 AA triplex with 80 mil insulation"""

def carson(gmr_or_d:float, r:float=0.0) -> complex:
    """Modified Carson's equation at 60 Hz, 100 Ohm-m (Kersting 4.41, 4.42,
    with gridlabd's unrounded coefficients)"""
    return complex(r + 0.00158836*60, 0.00202237*60*(math.log(1/gmr_or_d) + math.log(100/60)/2 + 7.6786))

def test_registration():
    Model().read_glm("module powerflow;\n")
    for name in ("overhead_line", "underground_line", "triplex_line"):
        assert Class.find(name, module="powerflow").parent.name == "line"
    overhead = Class.find("overhead_line", module="powerflow")
    assert overhead.find_property("ice_thickness").unit == "in" and overhead.find_property("is_covered").ptype == "bool"
    assert Class.find("underground_line", module="powerflow").find_property("ductbank").ptype == "object"

def test_overhead_kersting(helpers):
    """`Zabc` and `Yabc` of example 4.1 and 5.1"""
    m = helpers.model(OVERHEAD + NODES + "object overhead_line { name o01; phases ABCN; from n0; to n1; length 5280; configuration oc; }",
        module="line_capacitance true;", lines=False)
    zabc, yabc = OverheadLine.line_matrices(m, "o01")
    assert np.max(np.abs(zabc - KERSTING_4_1)) < 2e-4
    assert np.max(np.abs(yabc*1e6 - KERSTING_5_1)) < 1e-2  # Kersting rounds the potential coefficients

def test_overhead_independent(helpers):
    """`Zabc` of a two-phase line, scaled by its length, from the primitive
    matrix Kron-reduced"""
    m = helpers.model(OVERHEAD + NODES + "object overhead_line { name o01; phases BCN; from n0; to n1; length 1000; configuration oc; }", lines=False)
    zabc, yabc = OverheadLine.line_matrices(m, "o01")
    zp = np.array([[carson(0.0244, 0.306), carson(4.5), carson(4.272002)],
        [carson(4.5), carson(0.0244, 0.306), carson(5.0)],
        [carson(4.272002), carson(5.0), carson(0.00814, 0.592)]])
    expected = (zp[:2, :2] - np.outer(zp[:2, 2], zp[2, :2])/zp[2, 2])*1000/5280
    assert np.max(np.abs(zabc[1:, 1:] - expected)) < 1e-9
    assert not zabc[0].any() and not zabc[:, 0].any() and not yabc.any()

def test_overhead_matrix_form(helpers):
    """An overhead line with a matrix configuration uses the `line` model"""
    m = helpers.model(NODES + """
        object line_configuration { name mc; z11 0.3+1j; z22 0.3+1j; z33 0.3+1j; c11 10; }
        object overhead_line { name o01; phases ABCN; from n0; to n1; length 5280; configuration mc; }
        """, lines=False)
    zabc, _ = OverheadLine.line_matrices(m, "o01")
    assert np.allclose(zabc, np.diag([0.3+1j]*3))

def test_overhead_solves_as_line(helpers):
    """A feeder of an overhead line gives the solution of a `line` with its
    impedance in matrix form"""
    m = helpers.model(OVERHEAD + NODES + "object overhead_line { name o01; phases ABCN; from n0; to n1; length 2000; configuration oc; }", lines=False)
    zabc, _ = OverheadLine.line_matrices(m, "o01")
    terms = " ".join(f"z{i+1}{j+1} {zabc[i, j]*5280/2000:.12g};".replace("(", "").replace(")", "") for i in range(3) for j in range(3))
    r1 = helpers.run(OVERHEAD + NODES + "object overhead_line { name o01; phases ABCN; from n0; to n1; length 2000; configuration oc; }", lines=False)
    r2 = helpers.run(NODES + f"object line_configuration {{ name mc; {terms} }} object line {{ name o01; phases ABCN; from n0; to n1; length 2000; configuration mc; }}", lines=False)
    assert r1.returncode == 0 and r2.returncode == 0, r1.stderr + r2.stderr
    assert np.max(np.abs(helpers.voltages(r1.model, "n1") - helpers.voltages(r2.model, "n1"))) < 1e-6
    assert abs(helpers.voltages(r1.model, "n1")[0]) < 2401.7771

def test_overhead_missing_heights(helpers):
    """Without heights, no capacitance, with a warning"""
    glm = OVERHEAD.replace("distance_AE 28 ft;", "") + NODES + "object overhead_line { name o01; phases ABCN; from n0; to n1; length 1000; configuration oc; }"
    r = helpers.run(glm, module="line_capacitance true;", lines=False)
    assert r.returncode == 0, r.stderr
    assert any("Shunt capacitance of overhead line:o01 not calculated - invalid values" in x for x in helpers.warnings(r))
    assert not OverheadLine.line_matrices(r.model, "o01")[1].any()

@pytest.mark.parametrize("glm,message", [
    ("object overhead_line { name o01; phases ABCN; from n0; to n1; length 100; }", "init_overhead_line(obj=6;o01): no overhead line configuration specified."),
    ("object overhead_line { name o01; phases ABCN; from n0; to n1; length 100; configuration ls; }", "invalid line configuration for overhead line"),
    ("object line_configuration { name bad; conductor_A olc336; conductor_C olc336; conductor_N olc4/0; spacing ls; } object overhead_line { name o01; phases ABCN; from n0; to n1; length 100; configuration bad; }",
     "missing conductor for phase B of overhead line o01"),
    ("object line_configuration { name bad; conductor_A ls; conductor_B olc336; conductor_C olc336; conductor_N olc4/0; spacing ls; } object overhead_line { name o01; phases ABCN; from n0; to n1; length 100; configuration bad; }",
     "invalid conductor for phase A of overhead line o01"),
    ("object line_configuration { name bad; conductor_A olc336; conductor_B olc336; conductor_C olc336; conductor_N olc4/0; } object overhead_line { name o01; phases ABCN; from n0; to n1; length 100; configuration bad; }",
     "invalid or missing line spacing on overhead line"),
])
def test_overhead_init_errors(helpers, glm, message):
    r = helpers.run(OVERHEAD + NODES + glm, lines=False)
    assert r.returncode != 0
    assert any(message in x for x in helpers.errors(r)), r.stderr

def test_overhead_change(helpers):
    """Changing a conductor changes the admittance key and the matrices"""
    m = helpers.model(OVERHEAD + NODES + "object overhead_line { name o01; phases ABCN; from n0; to n1; length 5280; configuration oc; }", lines=False)
    zabc, _ = OverheadLine.line_matrices(m, "o01")
    m.set_property("olc336", "resistance", "0.5")
    assert OverheadLine.line_matrices(m, "o01")[0][0, 0].real > zabc[0, 0].real + 0.1

def test_underground_concentric_kersting(helpers):
    """`Zabc` and `Yabc` of examples 4.3 and 5.2"""
    m = helpers.model(UNDERGROUND + NODES + "object underground_line { name u01; phases ABC; from n0; to n1; length 5280; configuration uc; }",
        module="line_capacitance true;", lines=False)
    zabc, yabc = UndergroundLine.line_matrices(m, "u01")
    assert np.max(np.abs(zabc - KERSTING_4_3)) < 3e-4
    assert np.allclose(np.diag(yabc)*1e6, 96.5569j, atol=0.1) and not (yabc - np.diag(np.diag(yabc))).any()

def test_underground_tape_kersting(helpers):
    """`zaa` of example 4.4"""
    r = helpers.run(TAPE, lines=False)
    assert r.returncode == 0, r.stderr
    zabc, _ = UndergroundLine.line_matrices(r.model, "u01")
    assert abs(zabc[0, 0] - (1.3218+0.6744j)) < 3e-4
    assert np.count_nonzero(zabc) == 1

def test_underground_messages(helpers):
    r = helpers.run(UNDERGROUND + NODES + "object line_configuration { name bad; conductor_A ucn; conductor_C ucn; spacing us; } object underground_line { name u01; phases ABC; from n0; to n1; length 100; configuration bad; }", lines=False)
    assert any("missing conductor for phase B of underground line u01" in x for x in helpers.errors(r)), r.stderr

def test_triplex_geometric(helpers):
    """`b_mat` and `tn` of the geometric triplex model"""
    m = helpers.model(TRIPLEX, lines=False)
    b_mat, tn = TriplexLine.triplex_matrices(m, "t01")
    zp11 = carson(0.0111, 0.97)
    zp12 = carson((0.368 + 0.16)/12)
    zp13 = carson((0.368 + 0.08)/12)
    miles = 100/5280
    assert b_mat[0, 0] == pytest.approx((zp11 - zp13**2/zp11)*miles, rel=1e-4)
    assert b_mat[0, 1] == pytest.approx((zp12 - zp13**2/zp11)*miles, rel=1e-4)
    assert b_mat[1, 0] == pytest.approx(-b_mat[0, 1]) and b_mat[1, 1] == pytest.approx(-b_mat[0, 0])
    assert tn[0] == pytest.approx(-zp13/zp11, rel=1e-4) and tn[2] == 0

@pytest.mark.parametrize("glm,method,message", [
    (TRIPLEX.replace("phases AS; from", "phases A; from"), "NR", "is triplex but doesn't have phases S set"),
    (TRIPLEX.replace("insulation_thickness 0.08 in; diameter 0.368 in;", ""), "NR", "diameter and/or insulation_thickness are incorrectly set"),
    (TRIPLEX.replace("conductor_2 tlc;", ""), "NR", "configuration doesn't have a valid phase conductor!"),
])
def test_triplex_messages(helpers, glm, method, message):
    r = helpers.run(glm, module=f"solver_method {method};", lines=False)
    assert any(message in x for x in helpers.errors(r) + helpers.warnings(r)), r.stderr
