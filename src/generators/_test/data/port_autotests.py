"""Port the gridlabd generators autotests that use the Yakima weather file

Run from this folder with the path of gridlabd's `module/generators/autotest`
folder: `python3 port_autotests.py <autotest folder>`. The changes are
listed in `README.md`.
"""

import os
import re
import sys
import shutil

TESTS = ["test_Vout_PV.glm", "test_Vout_PV_solar_no_Parent.glm", "test_multipoint_inverter.glm",
    "test_4quad_inv_modes_PF_PQ_default_efficiency.glm", "test_4quad_inv_modes_PF_PQ_multipoint_efficiency.glm",
    "test_solar_parent_err.glm", "test_solar_climate_default_playerval.glm"]
"""Autotests ported"""

PLAYERS = ["solar_Vout.player", "MPINV_OUT1.player",
    "constantPQmeterPower_static_efficiency.player", "constantPFmeterPower_static_efficiency.player",
    "constantPQmeterPower_multi_efficiency.player", "constantPFmeterPower_multi_efficiency.player",
    "Yakima_Insolation.player", "Yakima_ambient_temperature.player", "Yakima_wind_speed.player",
    "solar_playerval_VA_Out.player"]
"""Reference players copied unchanged"""

SCHEDULES = {"pf_sched": "power_factor", "output_power": "P_Out", "output_var": "Q_Out"}
"""Schedules of the four-quadrant autotests and the property each sets"""

def schedules(text:str) -> dict[str,dict[int,str]]:
    """Hourly values of each schedule block (`* HOUR * * * VALUE;`, with
    `20-0` meaning hours 20 to 23 and 0)"""
    result = {}
    for name, body in re.findall(r"schedule\s+(\w+)\s*\{(.*?)\}", text, re.S):
        hours = {}
        for hour, value in re.findall(r"\*\s+([\d-]+)\s+\*\s+\*\s+\*\s+([-\d.]+?)\.?;", body):
            if "-" in hour:
                first, last = (int(x) for x in hour.split("-"))
                span = list(range(first, 24)) + list(range(0, last+1)) if last < first else list(range(first, last+1))
            else:
                span = [int(hour)]
            for h in span:
                hours[h] = value
        result[name] = hours
    return result

def player(hours:dict[int,str]) -> str:
    """Player rows for 2010-06-01 00:00 to 2010-06-02 01:00 PDT"""
    rows = [f"2010-06-01 {h:02d}:00:00 PDT,{hours[h]}" for h in range(24)]
    rows += [f"2010-06-02 {h:02d}:00:00 PDT,{hours[h]}" for h in range(2)]
    return "\n".join(rows) + "\n"

def port(source:str, file:str) -> None:
    """Port one autotest"""
    with open(os.path.join(source, file), encoding="utf-8") as fh:
        text = fh.read()
    text = text.replace("timezone PST+8PDT;", 'timezone "America/Los_Angeles";')
    text = re.sub(r"\n(\s*)timezone PST8;", r'\n\1timezone "Etc/GMT+8";', text)
    text = re.sub(r"^#weather get .*\n", "", text, flags=re.M)
    text = re.sub(r"(\s)timestamp '", r"\1starttime '", text)
    text = re.sub(r"//Misc objects - prevent rank issue.*", "", text, flags=re.S)
    if "#set relax_naming_rules=1" not in text:
        text = "#set relax_naming_rules=1\n" + text
    text = re.sub(r"^module residential;\n", "", text, flags=re.M)
    text = text.replace('"../', '"').replace(" ../", " ")
    found = schedules(text)
    text = re.sub(r"schedule\s+\w+\s*\{.*?\}\n", "", text, flags=re.S)
    for name, prop in SCHEDULES.items():
        if name not in found:
            continue
        stem = os.path.splitext(file)[0]
        target = f"{stem}_{name}.player"
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(player(found[name]))
        text = re.sub(rf"(\n(\s*){prop} {name}\*1;)", f"\n\\2object player {{ property {prop}; file \"{target}\"; }};", text)
    if file.startswith("test_4quad"):
        text = separate_meter(text)
    with open(file, "w", encoding="utf-8") as fh:
        fh.write(text)

def separate_meter(text:str) -> str:
    """Connect `const_pq_meter` to node 645 with a link instead of making
    it a child of the node, so that its `measured_power` is its own load
    (`arras` meters measure the current through the links of their top
    node)"""
    head, sep, tail = text.partition("\tobject meter {\n\t\tname const_pq_meter;")
    assert sep, "const_pq_meter not found"
    head = head.rstrip() + "\n}\n\nobject link {\n\tname const_pq_link;\n\tfrom 645;\n\tto const_pq_meter;\n\tphases ABCN;\n}\n\n"
    tail, sep, rest = tail.partition("\nobject transformer {\n\tname CTTF_B_645;")
    assert sep, "CTTF_B_645 not found"
    tail = tail.rstrip()
    assert tail.endswith("}"), "end of node 645 not found"
    tail = tail[:-1].rstrip() + "\n"
    return head + "object meter {\n\t\tname const_pq_meter;" + tail + "\n" + sep + rest

def main(source:str) -> None:
    """Port the autotests and copy their players"""
    for file in TESTS:
        port(source, file)
    for file in PLAYERS:
        shutil.copy(os.path.join(source, file), file)

if __name__ == "__main__":
    main(sys.argv[1])
