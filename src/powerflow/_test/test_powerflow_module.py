"""The `powerflow` package: docstrings, registration, globals, published
properties, and initialization"""
# pylint: disable=missing-function-docstring,line-too-long

import doctest
import importlib

import pytest

import powerflow
from arras.oclass import Class
from arras.module import Module
from arras.model import Model

MODULES = ["powerflow", "powerflow.solver", "powerflow.powerflow_object", "powerflow.powerflow_library",
    "powerflow.node", "powerflow.link", "powerflow.fuse", "powerflow.line", "powerflow.line_spacing",
    "powerflow.overhead_line", "powerflow.underground_line", "powerflow.triplex_line",
    "powerflow.transformer", "powerflow.regulator",
    "powerflow.switch", "powerflow.recloser", "powerflow.sectionalizer",
    "powerflow.overhead_line_conductor", "powerflow.underground_line_conductor", "powerflow.line_configuration",
    "powerflow.transformer_configuration", "powerflow.regulator_configuration", "powerflow.triplex_line_configuration", "powerflow.triplex_line_conductor",
    "powerflow.restoration", "powerflow.power_metrics", "powerflow.pole_configuration"]

@pytest.mark.parametrize("name", MODULES)
def test_doctests(name):
    """The docstring examples give the output shown"""
    result = doctest.testmod(importlib.import_module(name), optionflags=doctest.ELLIPSIS)
    assert result.failed == 0

def test_load():
    """GLM `module powerflow;` registers the module with its solvers, its
    classes in gridlabd's order with their parents, and its globals"""
    m = Model()
    m.read_glm("module powerflow;\n")
    assert [x.name for x in powerflow.classes()] == ["powerflow_object", "powerflow_library", "node", "link", "fuse", "line", "line_spacing",
        "overhead_line", "underground_line", "overhead_line_conductor", "underground_line_conductor", "line_configuration",
        "transformer_configuration", "transformer", "regulator_configuration", "regulator", "triplex_line", "triplex_line_configuration", "triplex_line_conductor", "switch", "restoration", "power_metrics", "recloser",
        "sectionalizer", "pole_configuration"]
    assert {"init", "sync"} <= set(Module.find("powerflow").solvers)
    assert Class.find("node", module="powerflow").parent.name == "powerflow_object"
    assert Class.find("link", module="powerflow").parent.name == "powerflow_object"
    globs = m.globals
    assert globs.get("powerflow::solver_method") == "NR"
    assert globs.get("powerflow::NR_iteration_limit") == "500"
    assert globs.get("powerflow::convergence_error_handling") == "FATAL"
    assert globs.get("powerflow::default_resistance") == "+0.0001 Ohm"
    assert globs.get("powerflow::default_continuous_rating") == "+1000 A"
    assert globs.get("powerflow::violation_watchset") == "ALL"
    assert globs.get("powerflow::fault_impedance") == "+1e-06+0j Ohm"

def test_load_twice_and_globals_alias():
    """Loading again keeps the globals; `default_maximum_voltage_error` is
    another name of `maximum_voltage_error`, as in gridlabd"""
    m = Model()
    m.read_glm("module powerflow { default_maximum_voltage_error 1e-9; }\nmodule powerflow;\n")
    assert m.globals.get("powerflow::maximum_voltage_error") == "+1e-09 V"
    m.globals.set("powerflow::maximum_voltage_error", 1e-7)
    assert m.globals.get("powerflow::default_maximum_voltage_error") == "+1e-07 V"

def test_solver_method_keywords():
    m = Model()
    m.read_glm("module powerflow { solver_method FD_XB; }\n")
    assert m.globals.get("powerflow::solver_method") == "FD_XB"
    for method in ("FBS", "GS", "NR", "FD_BX", "DC"):
        m.globals.set("powerflow::solver_method", method)
        assert m.globals.get("powerflow::solver_method") == method

def test_published_properties():
    """Selected properties as gridlabd publishes them"""
    Model().read_glm("module powerflow;\n")
    base = Class.find("powerflow_object", module="powerflow")
    phases = base.find_property("phases")
    assert phases.ptype == "set" and list(phases.keywords) == ["A", "B", "C", "D", "N", "S", "G"]
    assert phases.keywords["S"] == 0x70 and phases.flags & 0x0008
    node = Class.find("node", module="powerflow")
    assert node.find_property("nominal_voltage").oclass is base
    assert node.find_property("voltage_A").unit == "V"
    assert node.find_property("power_A").access == "HIDDEN"
    assert list(node.find_property("bustype").keywords) == ["SWING_PQ", "SWING", "PV", "PQ"]
    assert node.find_property("bustype").default == "PQ"
    assert node.find_property("shunt_AB").unit == "S" and node.find_property("power_AB").unit == "VA"
    link = Class.find("link", module="powerflow")
    assert link.find_property("status").default == "CLOSED"
    assert link.find_property("from").ptype == "object"
    assert link.find_property("power_out_real").unit == "W"
    assert link.find_property("fault_voltage_A").unit == "A"
    assert list(link.find_property("flow_direction").keywords)[:3] == ["CN", "CR", "CF"]
    assert sum(1 for p in node.properties()) == 75

def test_abstract_class():
    Model().read_glm("module powerflow;\n")
    assert Class.find("powerflow_object", module="powerflow").passconfig & 0x0100

def test_handlers_need_a_run():
    with pytest.raises(powerflow.PowerflowError, match="only during"):
        powerflow.init("n1", 0)

#
# Initialization
#
@pytest.mark.parametrize("glm,message", [
    ("object node { name n1; nominal_voltage 120; }", "init_node(obj=0;n1): phases not specified"),
    ("object node { name n1; phases ABS; nominal_voltage 120; }", "split connection is connected to two phases simultaneously"),
    ("object node { name n1; phases S; nominal_voltage 120; }", "split connection is missing A,B, or C phase connection"),
    ("object node { name n1; phases ASD; nominal_voltage 120; }", "split and delta connection cannot occur simultaneously"),
    ("object node { name n1; phases ABC; }", "nominal_voltage is not set"),
    ("object node { name n1; phases ABC; nominal_voltage 120; maximum_voltage_error -1; }", "negative maximum_voltage_error is invalid"),
    ("object node { name n1; phases ABC; nominal_voltage 120; } object link { name l1; phases ABC; from n1; }", "link to node is not specified"),
    ("object node { name n1; phases ABC; nominal_voltage 120; } object link { name l1; phases ABC; to n1; }", "link from node is not specified"),
    ("object node { name n1; phases ABC; nominal_voltage 120; } object link { name l1; phases ABC; from n1; to n1; }", "FROM and TO objects are the same object!"),
    ("object node { name n1; phases ABC; nominal_voltage 120; } object node { name n2; phases AB; nominal_voltage 120; } object link { name l1; phases ABC; from n1; to n2; }", "has a phase mismatch at one or both ends"),
    ("object node { name n1; phases ABC; nominal_voltage 120; } object node { name n2; phases ABC; nominal_voltage 120; } object link { name l1; phases ABC; from n1; to n2; violation_rating -1; }", "negative violation_rating is not valid"),
    ("object node { name n1; phases AN; nominal_voltage 120; } object node { name n2; phases ABN; nominal_voltage 120; parent n1; }", "Parent and child node phases for nodes n1 and n2 do not match!"),
])
def test_init_errors(helpers, glm, message):
    r = helpers.run(glm, lines=False)
    assert r.returncode != 0
    assert any(message in x for x in helpers.errors(r)), r.stderr

def test_gs_removed(helpers):
    r = helpers.run("object node { name n1; phases ABC; nominal_voltage 120; bustype SWING; }", module="solver_method GS;", lines=False)
    assert r.returncode != 0
    assert any("Gauss_Seidel is a deprecated solver and has been removed" in x for x in helpers.errors(r))

def test_init_defaults(helpers):
    """Voltages at nominal on the phases a node has, 0 elsewhere; the
    maximum voltage error from the global; the link's nominal voltage from
    its from node; split-phase neutral dropped"""
    m = helpers.model("""
        object node { name n1; phases ABN; nominal_voltage 1000; bustype SWING; }
        object node { name n2; phases ABN; nominal_voltage 1000; }
        object link { name l1; phases AB; from n1; to n2; mean_repair_time -1; }
        object node { name n3; phases ASN; nominal_voltage 120; bustype SWING; }
        """, lines=False)
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    r = Runner(model=m)
    assert powerflow.get_double(m, "n1", "maximum_voltage_error") == pytest.approx(0.001)
    assert powerflow.get_complex(m, "n1", "voltage_C") == 0
    assert abs(powerflow.get_complex(m, "n1", "voltage_B") - 1000*complex(-0.5, -0.75**0.5)) < 1e-9
    assert abs(abs(powerflow.get_complex(m, "n1", "voltage_AB")) - 1000*3**0.5) < 1e-9
    assert powerflow.get_double(m, "l1", "nominal_voltage") == 1000
    assert powerflow.get_double(m, "l1", "mean_repair_time") == 0
    assert m.get_property("n3", "phases") == "AS"
    assert any("neutral phase ignored on split connection." in x for x in helpers.warnings(r))
    assert any("negative mean_repair_time" in x for x in helpers.warnings(r))
    assert any("split-phase nodes are not supported yet" in x for x in helpers.errors(r))

def test_phases_from_parent(helpers):
    m = helpers.model("""
        object node { name n1; phases ABCN; nominal_voltage 1000; bustype SWING; }
        object node { name n2; parent n1; nominal_voltage 1000; }
        """, lines=False)
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    assert Runner(model=m).returncode == 0
    assert m.get_property("n2", "phases") == "ABCN"

def test_child_nodes(helpers):
    """Children are folded into their parent's buses; their loads add to
    the parent's and their voltages are the parent's; a grandchild moves to
    the top node; a different nominal voltage is replaced"""
    r = helpers.run("""
        object node { name src; phases ABCN; nominal_voltage 1000; bustype SWING; }
        object link { name l1; phases ABCN; from src; to n1; }
        object node { name n1; phases ABCN; nominal_voltage 1000; }
        object node { name c1; phases AN; nominal_voltage 999; parent n1; power_A 10000; }
        object node { name c2; phases AN; nominal_voltage 1000; parent c1; power_A 5000; }
        """, lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert powerflow.get_double(m, "c1", "nominal_voltage") == 1000
    assert m.get_property("c2", "parent") == "n1"
    assert powerflow.get_complex(m, "c1", "voltage_A") == powerflow.get_complex(m, "n1", "voltage_A")
    assert powerflow.get_complex(m, "c2", "voltage_A") == powerflow.get_complex(m, "n1", "voltage_A")
    assert abs(powerflow.get_complex(m, "l1", "power_out_A") - 15000) < 1e-3
    assert any("grandchildren objects are not supported, changing parent to node:2 (n1)" in x for x in helpers.warnings(r))
    assert any("does not have the same nominal voltage as its parent" in x for x in helpers.warnings(r))

def test_link_deferred_until_child_nodes_init(helpers):
    """A link to a child node created before it waits for the node"""
    r = helpers.run("""
        object node { name src; phases ABCN; nominal_voltage 1000; bustype SWING; }
        object link { name l1; phases ABCN; from src; to c1; }
        object node { name n1; phases ABCN; nominal_voltage 1000; }
        object node { name c1; phases ABCN; nominal_voltage 1000; parent n1; power_B 1000; }
        """, lines=False)
    assert r.returncode == 0, r.stderr
    assert abs(powerflow.get_complex(r.model, "l1", "power_out_B") - 1000) < 1e-3
