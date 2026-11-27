Test data
---------

gridlabd autotests of the `generators` module, from
`module/generators/autotest/` in arras-energy/gridlabd at master 076e78a
(2026-08-16), and their reference players.

| File | Source | Checks |
| ---- | ------ | ------ |
| `test_Vout_PV.glm` | autotest | a PWM inverter on a triplex meter with a solar array (Yakima, January morning): array `V_Out` against `solar_Vout.player` within 0.1 V |
| `test_Vout_PV_solar_no_Parent.glm` | autotest | the same array without a parent (static voltages) |
| `test_multipoint_inverter.glm` | autotest | a PWM inverter with the Xantrex multipoint efficiency curve and a fixed array at latitude tilt (Yakima, four June days): inverter `VA_Out` against `MPINV_OUT1.player` within 0.03 |
| `test_4quad_inv_modes_PF_PQ_default_efficiency.glm` | autotest | four-quadrant `CONSTANT_PQ` and `CONSTANT_PF` inverters (single-point efficiency): meter `measured_power` against `constantPQmeterPower_static_efficiency.player` and `constantPFmeterPower_static_efficiency.player` within 0.1, hourly for 25 hours |
| `test_4quad_inv_modes_PF_PQ_multipoint_efficiency.glm` | autotest | the same with the Xantrex multipoint curve and a solar array on the `CONSTANT_PF` inverter (`..._multi_efficiency.player`) |
| `test_solar_climate_default_playerval.glm` | autotest | a year of a flat plate array driven by players of Yakima insolation, temperature, and wind (`Yakima_*.player`): `VA_Out` against `solar_playerval_VA_Out.player` within 0.05; and an array with the static weather: `Insolation` and `VA_Out` against constants |
| `test_solar_parent_err.glm` | autotest | an array whose parent is a transformer fails at init |
| `*.player` (the ten reference and input players) | autotest folder, unchanged | the values the asserts compare |
| `test_4quad_*_pf_sched.player`, `*_output_power.player`, `*_output_var.player` | written by `port_autotests.py` | the hourly values of the autotests' schedules `pf_sched`, `output_power`, and `output_var` |
| `port_autotests.py` | written for these tests | ports the autotests: `python3 port_autotests.py <gridlabd>/module/generators/autotest` |

Changes made by `port_autotests.py`:

- `timezone PST+8PDT` becomes `timezone "America/Los_Angeles"` and
  `timezone PST8` becomes `timezone "Etc/GMT+8"` (`arras` reads IANA zone
  names, decision 3.9);
- the clock's `timestamp` becomes `starttime` (see DESIGN.md, Known
  issues);
- `#set relax_naming_rules=1` is added where missing, since the models
  name nodes `645`;
- `#weather get` lines, `module residential;` (unused), and the unused
  "Misc objects" at the end of `test_multipoint_inverter.glm` (whose names
  contain spaces) are removed;
- player paths lose their `../` prefix;
- the schedule blocks are removed and each property set from a schedule
  (`power_factor pf_sched*1;`, `P_Out output_power*1;`, `Q_Out
  output_var*1;`) is set by a player of the schedule's hourly values
  instead, since `arras` does not read GLM schedules yet;
- in the four-quadrant tests, `const_pq_meter` is connected to node `645`
  by a link (`const_pq_link`) instead of being its child, because `arras`
  meters measure the current through the links of their top node (a child
  meter would measure the whole node, including the triplex branch).

The tests run with `GLPATH` set to `src/climate/_test/data/`, which holds
`WA-Yakima_Air_Terminal.tmy3`.

Not ported: the autotests that need the CA-Chino weather file
(`test_solar_tilt`, `test_solar_orientation`, `test_solar_shading`,
`test_solar_output_efficiency`) or
classes and modes not ported yet (`battery`, `diesel_dg`, `windturb_dg`,
`central_dg_control`, load following, volt-VAr, voltage source).
