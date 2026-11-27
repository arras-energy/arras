# pylint: disable=line-too-long
"""Class `impedance_dump`: XML dump of the link matrices and capacitors

Syntax
------

    object impedance_dump {
        filename "<file>";
        group "<groupid>";          // all objects when empty
        runtime <timestamp>;        // NEVER or 0: the first time step
    }

Output: `runcount`, the number of dumps written.

Description
-----------

An `impedance_dump` writes, once, an XML file of the powerflow links and
capacitors (of group `group`, when it is set), as gridlabd's
`impedance_dump` does, when the time step at `runtime` is committed (its
sync asks for that event; with `runtime` `NEVER` or 0 at the first time
step). The file is

    <?xml version="1.0" encoding="UTF-8" ?>
    <gridlabd>
        <Time>2020-01-01 00:00:00 UTC</Time>
        <fuse>...</fuse>
        ...
    </gridlabd>

with an element for each object of the classes `fuse`, `overhead_line`,
`recloser`, `regulator`, `sectionalizer`, `series_reactor`, `switch`,
`transformer`, `triplex_line`, `underground_line` (exactly those classes,
in that order), then `capacitor`. A link's element holds its `name`, `id`
(`<class>:<id>`), `from_node` and `to_node` (`<class>:<name>`, or
`<class>:<id>` when unnamed), the voltage magnitudes of its nodes on its
first phase (`from_voltage`, `to_voltage`), its `phases` (for the phase
combinations gridlabd lists), the class's extra items (`length` of lines;
`tapA`, `tapB`, `tapC` of regulators; `xfmr_config` (the connection
number), `power_rating` (kVA), `resistance`, and `reactance` (pu) of
transformers), and the matrices `a_matrix` ... `B_matrix` (elements
`a11` ... `B33`, as `+re+imj` with 15 decimals). A capacitor's element
holds its `name`, `id` (`cap:<id>`), `node` (`node:<parent>`), `phases`, and `QA`,
`QB`, `QC` (VAr).

The matrices are gridlabd's forward-backward sweep matrices of the link,
`[V_from; I_from] = [a b; c d] [V_to; I_to]` and `V_to = A V_from - B
I_to` (`A = a^-1`, `B = a^-1 b`), with `I_to` the current out of the link
at its to end: they are derived from the link's admittance blocks (`a =
-Ytf^-1 Ytt`, `b = -Ytf^-1`, `c = Yft - Yff Ytf^-1 Ytt`, `d = -Yff
Ytf^-1`, with pseudo-inverses for the phases the link does not have).

When it initializes, an impedance dump fails without a `filename`. A dump
that finds no links, or cannot write the file, is an error that stops the
run, as in gridlabd.

Caveats
-------

- gridlabd's `relay` class is not ported, so there are no `relay`
  elements.
- The matrices are derived from the admittances used in the solution: they
  are gridlabd's for lines (`a = d = I + Z Y/2`, `b = Z`, `c = Y + Y Z
  Y/4`) and transformers, but a closed switch's (or fuse's) holds its
  small series impedance where gridlabd's sweep matrices hold 0.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The node voltages of a triplex line are its nodes' line 1 voltage
   magnitudes; gridlabd writes 120 for both.
2. A capacitor without a parent is written with its own name as its
   node; gridlabd dereferences the missing parent.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/impedance_dump.cpp`,
  `impedance_dump.h`
"""

from typing import Any

import numpy as np

from ._base import PowerflowClass, prop
from ._common import TS_NEVER, TS_INVALID, PHASE_A, PHASE_B, PHASE_C, ref, object_state, get_int, get_double, get_complex, set_int, gl_error
from .voltdump import runtime_of

CLASSES = ("fuse", "overhead_line", "recloser", "regulator", "sectionalizer", "series_reactor", "switch", "transformer",
    "triplex_line", "underground_line")
"""The link classes dumped, in gridlabd's order (gridlabd's `relay` is not
ported)"""

PHASES = {0x0001: "A", 0x0002: "B", 0x0004: "C", 0x0009: "AN", 0x000a: "BN", 0x000c: "CN", 0x0071: "AS", 0x0072: "BS",
    0x0074: "CS", 0x0003: "AB", 0x0006: "BC", 0x0005: "AC", 0x000b: "ABN", 0x000e: "BCN", 0x000d: "ACN", 0x0007: "ABC",
    0x000f: "ABCN", 0x0107: "ABCD"}
"""The phase combinations gridlabd writes"""

def label(model:Any, name:str) -> str:
    """`<class>:<name>`, or `<class>:<id>` for an unnamed object"""
    obj = model.objects[name]
    cname = obj.oclass.name
    return f"{cname}:{obj.id}" if name == f"{cname}:{obj.id}" else f"{cname}:{name}"

def fmt(value:complex) -> str:
    """gridlabd's `+re+imj` with 15 decimals"""
    re_, im = value.real + 0.0, value.imag + 0.0
    return f"{'+' if re_ >= 0 else '-'}{abs(re_):.15f}{'+' if im >= 0 else '-'}{abs(im):.15f}j"

def sweep_matrices(yff:np.ndarray, yft:np.ndarray, ytf:np.ndarray, ytt:np.ndarray) -> dict[str,np.ndarray]:
    """The forward-backward sweep matrices `a, b, c, d, A, B` of a link
    from its admittance blocks"""
    inv = np.linalg.pinv(ytf)
    a = -inv @ ytt
    b = -inv
    result = {"a": a, "b": b, "c": yft - yff @ inv @ ytt, "d": -yff @ inv}
    big_a = np.linalg.pinv(a)
    result.update(A=big_a, B=big_a @ b)
    for key, matrix in result.items():
        scale = max(np.abs(matrix).max(), 1.0)
        matrix = matrix.copy()
        matrix.real[np.abs(matrix.real) < 1e-12*scale] = 0.0
        matrix.imag[np.abs(matrix.imag) < 1e-12*scale] = 0.0
        result[key] = matrix
    return result

class ImpedanceDump(PowerflowClass):
    """Behavior of class `impedance_dump`"""

    NAME = "impedance_dump"
    TRL = 0 # TRL_UNKNOWN: gridlabd sets none
    PASSCONFIG = "AUTOLOCK"
    EVENTS = ("init", "sync", "commit")
    PROPERTIES = (
        ("group", "char32", prop("the group ID to output data for (all links if empty)")),
        ("filename", "char256", prop("the file to dump the current data into")),
        ("runtime", "timestamp", prop("the time to check voltage data")),
        ("runcount", "int32", prop("the number of times the file has been written to", "0", access="REFERENCE")),
    )

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`impedance_dump::init()`"""
        if not str(model.get_property(name, "filename") or "").strip('"'):
            gl_error("No filename was specified. Unable to open file for righting.")
            return False
        object_state(model, name)["ready"] = True
        return True

    @classmethod
    def sync(cls, model:Any, name:str, t:int) -> int:
        """`sync_impedance_dump()`: an event at `runtime`"""
        runtime = runtime_of(model, name)
        return runtime if runtime > t else TS_NEVER

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int:
        """`impedance_dump::commit()`"""
        runtime = runtime_of(model, name)
        if runtime == 0:
            model.objects[name]["runtime"] = model.globals.timestamp_to_string(t)
            runtime = t
        count = get_int(model, name, "runcount")
        if runtime in (t, TS_NEVER) and count < 1:
            ok = cls.dump(model, name, t)
            set_int(model, name, "runcount", count + 1)
            return TS_NEVER if ok else TS_INVALID
        return runtime if t < runtime else TS_NEVER

    #
    # Dump
    #
    @classmethod
    def first_voltage(cls, model:Any, link:str, node:str) -> float:
        """The voltage magnitude of a node on the link's first phase (line
        1 of a triplex node)"""
        from ._module import behavior # pylint: disable=import-outside-toplevel
        voltages = behavior(model, node).VOLTAGES
        if voltages[0] != "voltage_A":
            return abs(get_complex(model, node, voltages[0]))
        phases = get_int(model, link, "phases")
        for k, bit in enumerate((PHASE_A, PHASE_B, PHASE_C)):
            if phases & bit:
                return abs(get_complex(model, node, voltages[k]))
        return 0.0

    @classmethod
    def link_element(cls, model:Any, cname:str, item:str) -> list[str]: # pylint: disable=too-many-locals
        """The XML lines of a link"""
        from ._module import behavior # pylint: disable=import-outside-toplevel
        obj = model.objects[item]
        fnode, tnode = ref(model, item, "from"), ref(model, item, "to")
        lines = [f"\t<{cname}>", f"\t\t<name>{item}</name>", f"\t\t<id>{cname}:{obj.id}</id>",
            f"\t\t<from_node>{label(model, fnode)}</from_node>", f"\t\t<to_node>{label(model, tnode)}</to_node>",
            f"\t\t<from_voltage>{cls.first_voltage(model, item, fnode):f}</from_voltage>",
            f"\t\t<to_voltage>{cls.first_voltage(model, item, tnode):f}</to_voltage>"]
        if cname == "transformer":
            config = ref(model, item, "configuration")
            lines.append(f"\t\t<xfmr_config>{get_int(model, config, 'connect_type')}</xfmr_config>")
        phases = get_int(model, item, "phases")
        if phases in PHASES:
            lines.append(f"\t\t<phases>{PHASES[phases]}</phases>")
        if cname == "overhead_line":
            lines.append(f"\t\t<length>{get_double(model, item, 'length'):.15f}</length>")
        elif cname in ("triplex_line", "underground_line"):
            lines.append(f"\t\t<length>{get_double(model, item, 'length'):f}</length>")
        elif cname == "regulator":
            lines += [f"\t\t<tap{x}>{get_int(model, item, f'tap_{x}')}</tap{x}>" for x in "ABC"]
        elif cname == "transformer":
            config = ref(model, item, "configuration")
            impedance = get_complex(model, config, "impedance")
            lines += [f"\t\t<power_rating>{get_double(model, config, 'power_rating'):.6f}</power_rating>",
                f"\t\t<resistance>{impedance.real:.6f}</resistance>", f"\t\t<reactance>{impedance.imag:.6f}</reactance>"]
        matrices = sweep_matrices(*behavior(model, item).admittance(model, item))
        for key in ("a", "b", "c", "d", "A", "B"):
            lines.append(f"\t\t<{key}_matrix>")
            for x in range(3):
                for y in range(3):
                    lines.append(f"\t\t\t<{key}{x+1}{y+1}>{fmt(complex(matrices[key][x, y]))}</{key}{x+1}{y+1}>")
            lines.append(f"\t\t</{key}_matrix>")
        lines.append(f"\t</{cname}>")
        return lines

    @classmethod
    def capacitor_element(cls, model:Any, item:str) -> list[str]:
        """The XML lines of a capacitor"""
        obj = model.objects[item]
        parent = ref(model, item, "parent")
        node = parent if parent is not None else item
        nobj = model.objects[node]
        node_text = f"node:{nobj.id}" if node == f"{nobj.oclass.name}:{nobj.id}" else f"node:{node}"
        lines = ["\t<capacitor>", f"\t\t<name>{item}</name>", f"\t\t<id>cap:{obj.id}</id>", f"\t\t<node>{node_text}</node>"]
        phases = get_int(model, item, "phases")
        if phases in PHASES:
            lines.append(f"\t\t<phases>{PHASES[phases]}</phases>")
        lines += [f"\t\t<Q{x}>{get_double(model, item, f'capacitor_{x}'):f}</Q{x}>" for x in "ABC"]
        lines.append("\t</capacitor>")
        return lines

    @classmethod
    def dump(cls, model:Any, name:str, t:int) -> bool:
        """`impedance_dump::dump()`; `False` after an error"""
        group = str(model.get_property(name, "group") or "").strip('"')
        def find(cname:str) -> list[str]:
            return [x for x, obj in model.objects.items() if obj.oclass.name == cname
                and (not group or str(obj.get("groupid") or "").strip('"') == group)]
        links = {cname: find(cname) for cname in CLASSES}
        if not any(links.values()):
            gl_error("No link objects were found.")
            return False
        filename = str(model.get_property(name, "filename") or "").strip('"')
        lines = ['<?xml version="1.0" encoding="UTF-8" ?>', "<gridlabd>", f"\t<Time>{model.globals.timestamp_to_string(t)}</Time>"]
        for cname, items in links.items():
            for item in items:
                lines += cls.link_element(model, cname, item)
        for item in find("capacitor"):
            lines += cls.capacitor_element(model, item)
        try:
            with open(filename, "w", encoding="utf-8") as outfile:
                outfile.write("\n".join(lines) + "\n</gridlabd>")
        except OSError:
            gl_error(f"Unable to open {filename} for writing.")
            return False
        return True

__all__ = ["ImpedanceDump", "sweep_matrices"]
