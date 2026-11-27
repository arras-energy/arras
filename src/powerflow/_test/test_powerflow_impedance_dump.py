"""Class `impedance_dump`: registration, timing, format, matrices, groups,
and errors"""
# pylint: disable=missing-function-docstring,line-too-long

import re
import xml.etree.ElementTree as ET

import numpy as np
import pytest

import powerflow
from powerflow.impedance_dump import sweep_matrices, fmt
from powerflow.overhead_line import OverheadLine
from arras.oclass import Class
from arras.model import Model

VNOM = 2401.7771
FEEDER = f"""
object overhead_line_conductor {{ name olc336; geometric_mean_radius 0.0244 ft; resistance 0.306 Ohm/mile; diameter 0.721 in; }}
object overhead_line_conductor {{ name olc4/0; geometric_mean_radius 0.00814 ft; resistance 0.592 Ohm/mile; diameter 0.563 in; }}
object line_spacing {{ name ls; distance_AB 2.5 ft; distance_BC 4.5 ft; distance_AC 7.0 ft;
    distance_AN 5.656854 ft; distance_BN 4.272002 ft; distance_CN 5.0 ft;
    distance_AE 28 ft; distance_BE 28 ft; distance_CE 28 ft; distance_NE 24 ft; }}
object line_configuration {{ name oc; conductor_A olc336; conductor_B olc336; conductor_C olc336; conductor_N olc4/0; spacing ls; }}
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object overhead_line {{ name o01; groupid feeder; phases ABCN; from n0; to n1; length 2000; configuration oc; }}
object node {{ name n1; phases ABCN; nominal_voltage {VNOM}; }}
object switch {{ name sw; phases ABCN; from n1; to n2; status CLOSED; }}
object node {{ name n2; phases ABCN; nominal_voltage {VNOM}; power_A 100000+50000j; power_B 100000; power_C 100000; }}
object capacitor {{ name cap; parent n2; phases ABCN; capacitor_A 50 kVAr; capacitor_B 50 kVAr; capacitor_C 50 kVAr; nominal_voltage {VNOM}; }}
"""

@pytest.fixture(name="here", autouse=True)
def fixture_here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path

def matrix(element, key:str) -> np.ndarray:
    result = np.zeros((3, 3), dtype=complex)
    for x in range(3):
        for y in range(3):
            text = element.find(f"{key}_matrix/{key}{x+1}{y+1}").text
            re_, im = re.fullmatch(r"([+-][0-9.]+)([+-][0-9.]+)j", text).groups()
            result[x, y] = complex(float(re_), float(im))
    return result

def test_registration():
    Model().read_glm("module powerflow;\n")
    oclass = Class.find("impedance_dump", module="powerflow")
    assert oclass.trl == 0 and oclass.parent is None
    assert oclass.find_property("runcount").default == "0"
    assert [x.name for x in powerflow.classes()].index("impedance_dump") == [x.name for x in powerflow.classes()].index("triplex_zipload") + 1

def test_fmt():
    assert fmt(complex(1.5, -0.25)) == "+1.500000000000000-0.250000000000000j"
    assert fmt(complex(-0.0, 0.0)) == "+0.000000000000000+0.000000000000000j"

def test_dump(helpers): # pylint: disable=too-many-locals
    r = helpers.run(FEEDER + 'object impedance_dump { name zd; filename "z.xml"; }\n', stop="2020-01-01 01:00:00", lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    with open("z.xml", encoding="utf-8") as fh:
        text = fh.read()
    assert text.startswith('<?xml version="1.0" encoding="UTF-8" ?>\n<gridlabd>\n\t<Time>2020-01-01 00:00:00 UTC</Time>\n\t<overhead_line>')
    assert text.endswith("\t</capacitor>\n</gridlabd>")
    root = ET.fromstring(text.split("\n", 1)[1])
    assert [x.tag for x in root][1:] == ["overhead_line", "switch", "capacitor"]
    ohl = root.find("overhead_line")
    assert ohl.find("name").text == "o01" and ohl.find("from_node").text == "node:n0" and ohl.find("to_node").text == "node:n1"
    assert ohl.find("phases").text == "ABCN" and float(ohl.find("length").text) == 2000
    assert float(ohl.find("to_voltage").text) == pytest.approx(abs(powerflow.get_complex(m, "n1", "voltage_A")), abs=1e-6)
    # line: a = d = I + ZY/2, b = Z, c = Y + YZY/4, A = inv(a), B = inv(a) b
    z = OverheadLine.series_impedance(m, "o01")
    yf, yt = OverheadLine.shunt_admittance(m, "o01")
    y = yf + yt
    a, b, c, d = (matrix(ohl, x) for x in "abcd")
    assert np.allclose(a, np.eye(3) + z @ y/2, atol=1e-12) and np.allclose(d, a, atol=1e-12)
    assert np.allclose(b, z, atol=1e-9) and np.allclose(c, y + y @ z @ y/4, atol=1e-12)
    assert np.allclose(matrix(ohl, "A"), np.linalg.inv(a), atol=1e-12) and np.allclose(matrix(ohl, "B"), np.linalg.inv(a) @ b, atol=1e-9)
    cap = root.find("capacitor")
    assert cap.find("id").text.startswith("cap:") and cap.find("node").text == "node:n2" and cap.find("phases").text == "ABCN" and float(cap.find("QA").text) == 50000
    assert m.get_property("zd", "runcount") == "1"

def test_sweep_matrices_partial_phases():
    z = np.diag([1+2j, 0, 0])
    y = np.zeros((3, 3), dtype=complex)
    y[0, 0] = 1/z[0, 0]
    result = sweep_matrices(y, -y, -y, y)
    assert np.allclose(result["a"], np.diag([1, 0, 0])) and np.allclose(result["b"], z)
    assert np.allclose(result["c"], 0) and np.allclose(result["A"], np.diag([1, 0, 0]))

def test_runtime_and_group(helpers):
    r = helpers.run(FEEDER + 'object impedance_dump { name zd; filename "z.xml"; group feeder; runtime "2020-01-01 00:30:00"; }\n',
        stop="2020-01-01 01:00:00", lines=False)
    assert r.returncode == 0, r.stderr
    with open("z.xml", encoding="utf-8") as fh:
        root = ET.fromstring(fh.read().split("\n", 1)[1])
    assert root.find("Time").text == "2020-01-01 00:30:00 UTC"
    assert [x.tag for x in root][1:] == ["overhead_line"]

def test_errors(helpers):
    r = helpers.run(FEEDER + "object impedance_dump { name zd; }\n", lines=False)
    assert r.returncode != 0 and any("No filename was specified" in x for x in helpers.errors(r))
    r = helpers.run(FEEDER + 'object impedance_dump { name zd; filename "z.xml"; group none; }\n', lines=False)
    assert r.returncode != 0 and any("No link objects were found." in x for x in helpers.errors(r))

def test_transformer_triplex(helpers):
    """Transformer items, and the line 1 voltages of a triplex line's
    nodes (gridlabd writes 120)"""
    glm = """
object transformer_configuration { name tc; connect_type SINGLE_PHASE_CENTER_TAPPED; install_type POLETOP; primary_voltage 7200; secondary_voltage 120;
    power_rating 50; powerA_rating 50; impedance 0.006+0.0136j; }
object node { name n1; phases ABCN; nominal_voltage 7200; bustype SWING; }
object transformer { name t12; phases AS; from n1; to m2; configuration tc; }
object triplex_meter { name m2; phases AS; nominal_voltage 120; }
object triplex_line_conductor { name tlc; resistance 0.97; geometric_mean_radius 0.0111; }
object triplex_line_configuration { name tlcfg; conductor_1 tlc; conductor_2 tlc; conductor_N tlc; insulation_thickness 0.08; diameter 0.368; }
object triplex_line { name tl; phases AS; from m2; to l3; length 100; configuration tlcfg; }
object triplex_load { name l3; phases AS; nominal_voltage 120; constant_power_1 1000+500j; constant_power_2 1000; }
object impedance_dump { name zd; filename "z.xml"; }
"""
    r = helpers.run(glm, lines=False)
    assert r.returncode == 0, r.stderr
    with open("z.xml", encoding="utf-8") as fh:
        root = ET.fromstring(fh.read().split("\n", 1)[1])
    xfmr, tpl = root.find("transformer"), root.find("triplex_line")
    assert xfmr.find("xfmr_config").text == "5" and xfmr.find("phases").text == "AS"
    assert xfmr.find("power_rating").text == "50.000000" and xfmr.find("resistance").text == "0.006000" and xfmr.find("reactance").text == "0.013600"
    assert float(xfmr.find("from_voltage").text) == pytest.approx(abs(powerflow.get_complex(r.model, "n1", "voltage_A")), abs=1e-6)
    assert float(tpl.find("to_voltage").text) == pytest.approx(abs(powerflow.get_complex(r.model, "l3", "voltage_1")), abs=1e-6)
    assert [x.tag for x in root][1:] == ["transformer", "triplex_line"]
