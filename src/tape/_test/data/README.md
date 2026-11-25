Test data
=========

The `test_*.glm` files are the gridlabd autotests of the `tape` module,
from `module/tape/autotest/` in
[arras-energy/gridlabd](https://github.com/arras-energy/gridlabd), copied
from `master` at commit 076e78a (2026-08-16) on 2026-11-24, with their data
files (`exercise_2_1_1.player`, `test_player_buffer.player`,
`test_player_header.csv`, `test_multiplayer.csv`, the schedules
`water_and_setpoint_schedule_v3.glm`) and the outputs that gridlabd wrote
(`test_player_header_output.csv`, `test_multiplayer_record_1.csv`,
`test_multiplayer_record_2.csv`). Files named `*_err.glm` are expected to
fail. The files are changed only where `arras` needs it:

- `module powerflow;` and `module residential;` (and their blocks) are
  replaced by `#include` of `powerflow.glm` and `residential.glm`, which
  declare the classes and properties that the tests set or record with the
  types and units those modules publish, because `arras` has no such
  modules. Their objects have no behavior: values stay as set.
- The `PST+8PDT` and `EST+5EDT` time zones are replaced by
  `America/Los_Angeles` and `America/New_York`, and the `PST` and `EST`
  suffixes are removed from clock times, because `arras` reads only IANA
  zone names (#41).
- The clock's `timestamp` is renamed `starttime` (open question 8).
- `#ifexist`/`#define DIR` blocks and `#on_exit` comparisons are removed
  (`arras` has neither macro): files are named as they are in this folder,
  and the tests compare the outputs.
- `randomvar` properties are `double` properties set by the handler
  `tape_test_random.sync` (in `src/tape/_test/`) every `refresh` seconds,
  with normal(0,1) values from Python's `random` module seeded with
  `randomseed`, because `arras` does not refresh `randomvar` values. Runs
  are repeatable; the draws differ from gridlabd's.
- `test_recorder_multiple_properties.glm`,
  `test_collector_multiple_properties.glm`, and the two
  `test_multi_recorder_multiple_properties*.glm` run for one week instead
  of one year (and in UTC), so the suite stays fast.
- `test_recorder_flush_sync.py` (the commit handler of the
  `test_recorder_flush_*.glm` tests) is rewritten without `pandas` and
  `gldcore`; a failed check returns 0, which stops the run, where gridlabd's
  returned `None`. `#set pythonpath=..:.` is `#set pythonpath=.`.

Not ported: `test_delta_player_first_delta_timestep_err.glm` and
`test_deltamode_player_endtime_err.glm` (with their data files
`data_configurations_delta_123node.glm`, `data_delta_player_load_A*.csv`,
`data_loadchange.csv`) test deltamode players with a powerflow solution,
and `arras` runs neither deltamode nor powerflow. The unused gridlabd outputs
`recorder_flush_test2.csv`, `test_recorder_flush.csv`, and
`test_recorder_flush_300.csv` are not copied.

Files and sizes: `test_player_header.csv` and
`test_player_header_output.csv` (8761 and 8760 lines, about 0.6 MB each),
`water_and_setpoint_schedule_v3.glm` (3609 lines, 0.1 MB); the others are
under 30 kB.
