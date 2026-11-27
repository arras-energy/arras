# pylint: disable=line-too-long
"""Class `fault_check`: topology check that takes unsupported phases out of the powerflow

Syntax
------

    object fault_check {
        check_mode {SINGLE,ONCHANGE,ALL,SINGLE_DEBUG};
        output_filename "<file>";
        reliability_mode {TRUE,FALSE};
        strictly_radial {TRUE,FALSE};       // default TRUE
        full_output_file {TRUE,FALSE};
        grid_association {TRUE,FALSE};
        eventgen_object <eventgen>;
    }

Description
-----------

A `fault_check` checks which phases of the network's buses are supported
(connected to a source), as gridlabd's `fault_check` does in its sync
pass; here the module's solver makes the check in each sync pass, after
the objects and the links' and nodes' updates (switch states, fuses),
just before the network is built:

- with `SINGLE` (the default) at the first sync pass, with `ONCHANGE` at
  each pass where the network's topology (a link's status, phases, or
  connected phases) changed since the last check, with `ALL` at every
  pass, and with `SINGLE_DEBUG` once, after which the run stops with the
  error `fault_check:ID NAME -- Special debug mode utilized, simulation
  terminating`;
- the supported phases are those connected through closed links (the
  phases their admittances connect) to the first `SWING` node, or, with
  `grid_association`, to any `SWING` or `SWING_PQ` node or source (a node
  a source link such as `vfd` drives), each source starting an island;
- when a phase is unsupported, the list is appended to `output_filename`
  (`Unsupported at timestamp T - YYYY-MM-DD HH:MM:SS =`, then `Phase A on
  node N`, `Phases A and B on node N`, ... for each node); without
  `reliability_mode` or `grid_association` the run fails (`Unsupported
  phase on node N` when `strictly_radial`, `Unsupported phase on a
  possibly meshed node` otherwise); otherwise it warns, and the
  unsupported phases are taken out of the powerflow (their voltages are
  0) until a later check finds them supported again;
- with `full_output_file`, the file also lists the supported phases
  (`Supported Nodes`, with each node's island and the island count with
  `grid_association`), also at the first check when nothing is
  unsupported and the check is not strictly radial.

When it initializes, a fault check fails unless `powerflow::solver_method`
is `NR`, when there is another `fault_check`, when `eventgen_object` is
not an `eventgen` object (with an `eventgen`, `reliability_mode` is
set), and when `powerflow::NR_island_failure_handled` is set without
`grid_association`; it empties `output_filename`, and `grid_association`
turns `strictly_radial` off, with a warning.

With a `restoration` object, each check calls its reconfiguration, which
is not ported, so the run fails there; gridlabd requires meshed checking
for it and turns `strictly_radial` off, with a warning.

Caveats
-------

- The reliability functions (`reliability_alterations`,
  `handle_sectionalizer`, `island_removal_function`, `rescan_topology`)
  have no callers here: the reliability module (`eventgen`), faults on
  links, and per-island solver failures are not ported.
- The nodes are listed in creation order (gridlabd: its solver's bus
  order).

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. In strictly radial mode with `reliability_mode`, the unsupported
   phases are taken out of the powerflow at each check, as in meshed
   mode; gridlabd takes them out only when a reliability event calls its
   alterations, so its solver then fails on the unsupported phases.
2. `ONCHANGE` checks when the links' status or phases changed; gridlabd
   checks when its solver's admittance-change flag is set.
3. The first check does not force another pass at the same time.
4. The check runs in the solver, after the switches have applied their
   status; gridlabd ranks the object to sync just before the solver.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/fault_check.cpp`,
  `fault_check.h`, `docs/Module/Powerflow/Fault_check.md`
"""

from typing import Any

from ._base import PowerflowClass, prop, keywords
from ._common import (PHASE_A, PHASE_B, PHASE_C, SWING, SWING_PQ, SM_NR, g, ref, msg, isa, objects_of,
    object_state, get_int, gl_error, PowerflowError)

SINGLE, ONCHANGE, ALL, SINGLE_DEBUG = range(4)
"""`check_mode` values"""

TRL_DEMONSTRATED = 6
"""Technology readiness level `TRL_DEMONSTRATED`"""

PHASE_BITS = (PHASE_A, PHASE_B, PHASE_C)

PHASE_TEXT = {0b001: "Phase A", 0b010: "Phase B", 0b100: "Phase C", 0b011: "Phases A and B", 0b101: "Phases A and C",
    0b110: "Phases B and C", 0b111: "Phases A, B, and C"}
"""Phase lists of the output file, by phase bits (A = 1)"""

def checker(model:Any) -> str|None:
    """The model's initialized `fault_check` object, or `None`"""
    for name in objects_of(model, "fault_check"):
        if object_state(model, name).get("ready"):
            return name
    return None

def slot_bits(model:Any, node:str) -> dict[int,int]:
    """Phase bit of each bus slot of a top node (both lines of a
    split-phase node are its phase)"""
    from ._module import behavior # pylint: disable=import-outside-toplevel
    cls = behavior(model, node)
    phases = get_int(model, node, "phases") & 0x07
    split = cls.split(model, node)
    return {slot: phases if split else PHASE_BITS[slot] for slot, *_ in cls.bus_slots(model, node)}

def topology(model:Any) -> tuple[list[str],dict[tuple[str,int],set[tuple[str,int]]]]:
    """The top nodes, and the bus slots each bus slot connects to through
    closed links (the slots their admittance blocks connect)"""
    # pylint: disable=too-many-locals
    from ._module import behavior, top_node # pylint: disable=import-outside-toplevel
    tops = [x for x in objects_of(model, "node") if top_node(model, x) == x]
    graph: dict[tuple[str,int],set[tuple[str,int]]] = {}
    for top in tops:
        for slot in slot_bits(model, top):
            graph[(top, slot)] = set()
    for name in objects_of(model, "link"):
        cls = behavior(model, name)
        if cls.SOURCE or not cls.closed(model, name):
            continue
        fnode, tnode = top_node(model, ref(model, name, "from")), top_node(model, ref(model, name, "to"))
        _, yft, ytf, _ = cls.admittance(model, name)
        fslots, tslots = cls.bus_slots(model, name)
        for i, fslot in enumerate(fslots):
            for j, tslot in enumerate(tslots):
                if fslot < 0 or tslot < 0 or (abs(yft[i, j]) == 0 and abs(ytf[j, i]) == 0):
                    continue
                a, b = (fnode, fslot), (tnode, tslot)
                if a in graph and b in graph:
                    graph[a].add(b)
                    graph[b].add(a)
    return tops, graph

def sources(model:Any, tops:list[str], grid:bool) -> list[str]:
    """The source nodes, in search order: the first `SWING` node, or with
    `grid` every `SWING`, then `SWING_PQ` node, then the nodes source links
    drive"""
    from ._module import sourced # pylint: disable=import-outside-toplevel
    swings = [x for x in tops if get_int(model, x, "bustype") == SWING]
    if not grid:
        return swings[:1]
    driven = sourced(model)
    return swings + [x for x in tops if get_int(model, x, "bustype") == SWING_PQ] + [x for x in tops if x in driven and x not in swings]

def support(model:Any, grid:bool) -> tuple[list[str],set[tuple[str,int]],dict[str,int]]:
    """The top nodes, the supported bus slots, and the island of each
    supported node"""
    tops, graph = topology(model)
    supported: set[tuple[str,int]] = set()
    islands: dict[str,int] = {}
    count = 0
    for source in sources(model, tops, grid):
        start = [(source, slot) for slot in slot_bits(model, source)]
        if not start or all(x in supported for x in start):
            continue
        stack = [x for x in start if x not in supported]
        while stack:
            bus = stack.pop()
            if bus in supported:
                continue
            supported.add(bus)
            islands.setdefault(bus[0], count)
            stack.extend(x for x in graph[bus] if x not in supported)
        count += 1
    return tops, supported, islands

def signature(model:Any) -> tuple:
    """The links' status and phases (for `ONCHANGE`)"""
    from ._module import behavior # pylint: disable=import-outside-toplevel
    result = []
    for name in objects_of(model, "link"):
        cls = behavior(model, name)
        connected = cls.connected_phases(model, name) if hasattr(cls, "connected_phases") else None
        result.append((name, cls.closed(model, name), get_int(model, name, "phases"), connected))
    return tuple(result)

class FaultCheck(PowerflowClass):
    """Behavior of class `fault_check`"""

    NAME = "fault_check"
    TRL = TRL_DEMONSTRATED
    PASSCONFIG = "BOTTOMUP|AUTOLOCK"
    EVENTS = ("init",)
    PROPERTIES = (
        ("check_mode", "enumeration", prop("Frequency of fault checks", "SINGLE", keywords=keywords(("SINGLE", SINGLE), ("ONCHANGE", ONCHANGE),
            ("ALL", ALL), ("SINGLE_DEBUG", SINGLE_DEBUG)))),
        ("output_filename", "char1024", prop("Output filename for list of unsupported nodes")),
        ("reliability_mode", "bool", prop("General flag indicating if fault_check is operating under faulting or restoration mode -- reliability set this", "FALSE")),
        ("strictly_radial", "bool", prop("Flag to indicate if a system is known to be strictly radial -- uses radial assumptions for reliability alterations", "TRUE")),
        ("full_output_file", "bool", prop("Flag to indicate if the output_filename report contains both supported and unsupported nodes -- if false, just does unsupported", "FALSE")),
        ("grid_association", "bool", prop("Flag to indicate if multiple, distinct grids are allowed in a GLM, or if anything not attached to the master swing is removed", "FALSE")),
        ("eventgen_object", "object", prop("Link to generic eventgen object to handle unexpected faults")),
    )

    @classmethod
    def removed(cls, model:Any, name:str) -> set[tuple[str,int]]:
        """The bus slots `(top node, slot)` the check took out of the
        powerflow"""
        return set(object_state(model, name).get("removed", ()))

    @classmethod
    def flag(cls, model:Any, name:str, prop_:str) -> bool:
        """A `bool` property"""
        return bool(get_int(model, name, prop_))

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`fault_check::init()`"""
        from .node import init_failed # pylint: disable=import-outside-toplevel
        obj = model.objects[name]
        label = name if name != f"{obj.oclass.name}:{obj.id}" else "Unnamed"
        try:
            if g(model, "solver_method") != SM_NR:
                raise PowerflowError("Fault checking object is only valid for the Newton-Raphson solver at this time.")
            if checker(model) is not None:
                raise PowerflowError("Only one fault_check object is supported at this time")
        except PowerflowError as err:
            init_failed(model, name, err)
            return False
        eventgen = ref(model, name, "eventgen_object")
        if eventgen is not None:
            if not isa(model, eventgen, "eventgen"):
                gl_error(f"fault_check:{label} {eventgen} is not an eventgen object. Please specify the name of an eventgen object.")
                return False
            model.objects[name]["reliability_mode"] = "TRUE"
        filename = str(model.get_property(name, "output_filename") or "").strip('"')
        if filename:
            with open(filename, "wt", encoding="utf-8"):
                pass
        if cls.flag(model, name, "grid_association") and cls.flag(model, name, "strictly_radial"):
            msg(model, name).warning(f"fault_check:{label} was forced into meshed search mode due to multiple grids being desired")
            model.objects[name]["strictly_radial"] = "FALSE"
        if g(model, "NR_island_failure_handled") and not cls.flag(model, name, "grid_association"):
            gl_error(f"fault_check:{label} - powerflow::NR_island_failure_handled is set, but grid_association is not!")
            return False
        object_state(model, name).update(ready=True, first=True, removed=set(), signature=None)
        return True

    @classmethod
    def due(cls, model:Any, name:str) -> bool:
        """Whether this sync pass checks the topology"""
        state = object_state(model, name)
        mode = get_int(model, name, "check_mode")
        if mode in (SINGLE, SINGLE_DEBUG):
            return state["first"]
        if mode == ALL:
            return True
        return signature(model) != state["signature"]

    @classmethod
    def solver_check(cls, model:Any, name:str, t:int) -> bool:
        """`fault_check::sync()`, called by the module's solver after the
        objects' sync passes and the links' and nodes' updates, before the
        network is built (gridlabd ranks the object just below the swing
        node so that it runs just before the solver); `False` stops the
        run"""
        state = object_state(model, name)
        if not state.get("ready"):
            return True
        mode = get_int(model, name, "check_mode")
        obj = model.objects[name]
        if cls.due(model, name):
            try:
                cls.check(model, name, t, mode == SINGLE_DEBUG)
            except PowerflowError as err:
                gl_error(f"sync_fault_check(obj={obj.id};{name if name != f'fault_check:{obj.id}' else 'unnamed'}): {err}")
                return False
        state["first"] = False
        if mode == SINGLE_DEBUG:
            gl_error(f"fault_check:{obj.id} {name if name != f'fault_check:{obj.id}' else 'Unnamed'} -- Special debug mode utilized, simulation terminating")
            return False
        return True

    @classmethod
    def check(cls, model:Any, name:str, t:int, debug:bool=False) -> None:
        """One topology check; raises `PowerflowError` when it fails"""
        # pylint: disable=too-many-locals
        from .node import init_voltages # pylint: disable=import-outside-toplevel
        state = object_state(model, name)
        radial = cls.flag(model, name, "strictly_radial")
        restorations = objects_of(model, "restoration")
        if restorations and not debug:
            if radial:
                msg(model, name).warning("fault_check interaction with restoration requires meshed checking mode - enabling this now")
                model.objects[name]["strictly_radial"] = "FALSE"
                radial = False
            from .restoration import Restoration # pylint: disable=import-outside-toplevel
            try:
                Restoration.perform_restoration(model, restorations[0], -99)
            except PowerflowError as err:
                raise PowerflowError(f"Restoration failed to execute properly ({err})") from err
        grid = cls.flag(model, name, "grid_association")
        tops, supported, islands = support(model, grid)
        state["signature"] = signature(model)
        before = state["removed"]
        unsupported = {(top, slot) for top in tops for slot in slot_bits(model, top) if (top, slot) not in supported}
        outs = {}
        for top in tops:
            bits = 0
            for slot, bit in slot_bits(model, top).items():
                if (top, slot) not in supported:
                    bits |= bit
            if bits:
                outs[top] = bits
        filename = str(model.get_property(name, "output_filename") or "").strip('"')
        full = cls.flag(model, name, "full_output_file")
        tolerant = cls.flag(model, name, "reliability_mode") or grid or debug
        if outs or debug or (full and state["first"] and not radial):
            if filename:
                cls.write_output(model, name, filename, t, tops, outs, supported, islands, debug)
        if outs and not debug:
            message = f"Unsupported phase on node {next(iter(outs))}" if radial else "Unsupported phase on a possibly meshed node"
            if not tolerant:
                raise PowerflowError(message)
            msg(model, name).warning(message)
        state["removed"] = unsupported
        for top in {x[0] for x in before - unsupported}:
            init_voltages(model, top)

    @classmethod
    def write_output(cls, model:Any, name:str, filename:str, t:int, tops:list[str], outs:dict[str,int], # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
            supported:set[tuple[str,int]], islands:dict[str,int], debug:bool) -> None:
        """`fault_check::write_output_file()`"""
        from .scheduled_load import local_time # pylint: disable=import-outside-toplevel
        grid = cls.flag(model, name, "grid_association")
        count = len(set(islands.values()))
        when = local_time(model, t)
        stamp = f"timestamp {t} - {when.year:04d}-{when.month:02d}-{when.day:02d} {when.hour:02d}:{when.minute:02d}:{when.second:02d} ="
        lines = []
        if outs:
            lines.append("Special debug topology check -- phase checks bypassed -- Unsupported nodes list\n" if debug else f"Unsupported at {stamp}\n")
            lines += [f"{PHASE_TEXT[bits]} on node {top}" for top, bits in outs.items()]
        elif debug:
            lines.append("Special debug topology check -- phase checks bypassed -- No unsupported nodes found\n")
        if cls.flag(model, name, "full_output_file"):
            header = bool(lines)
            first = True
            for top in tops:
                bits = 0
                for slot, bit in slot_bits(model, top).items():
                    if (top, slot) in supported:
                        bits |= bit
                if not bits:
                    continue
                if first:
                    first = False
                    if not header:
                        if debug:
                            lines.append(f"Special debug topology check -- phase checks bypassed -- Supported nodes list{f' -- {count} Islands detected' if grid else ''}\n")
                        else:
                            lines.append(f"Supported at {stamp}" + (f"\nNumber detected islands = {count}\n" if grid else "\n"))
                    else:
                        lines.append(f"\nSupported Nodes{f' -- {count} Islands detected' if grid else ''}")
                lines.append(f"{PHASE_TEXT[bits]} on node {top}" + (f" - Island {islands[top] + 1}" if grid else ""))
        with open(filename, "at", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n\n" if lines else "\n")

__all__ = ["FaultCheck", "checker", "support"]
