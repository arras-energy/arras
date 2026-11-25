Test data
=========

The `test_*.glm` files and `case.glm` are the gridlabd autotests of the
`pypower` module, from `module/pypower/autotest/` in
[arras-energy/gridlabd](https://github.com/arras-energy/gridlabd), copied
from `master` at commit 076e78a (2026-08-16) on 2026-11-24, with their
data files: the PYPOWER cases (`case*.py`), `controllers.py`,
`check_case.py`, `verify.py`, the weather, geodata, and player files
(`test_case14_weather.csv`, `test_case14_sensitivity.csv`,
`test_case14_geodata_P.csv`, `test_derating_weather.csv`,
`test_case14_powerplant_pp_bus_2.csv`), and the recordings that gridlabd
wrote (`*_record.csv`, `test_case14_ts.csv`,
`test_derating_powerplant_capacity.csv`). Files named `*_err.glm` are
expected to fail; files named `*_opt.glm` may fail.

Generated: `make_cases.py` (in this folder; run it here to regenerate)
converts each case `caseNAME.py` to `caseNAME.glm`, as gridlabd's
`#input "caseNAME.py" -t pypower` (`converters/py2glm.py`) does, and
writes `caseNAME_verify.glm`, the asserts that the autotests' `#begin
python` blocks write with `verify.py`.

The autotests are changed only where `arras` needs it:

- `#input "case${CASE}.py" -t pypower` is `#include "case${CASE}.glm"`,
  and the `#begin python ... #end` blocks that write the verify files are
  removed (the verify files are generated). `make_cases.py` writes `apf`
  without the unit `pu`, because `apf` has no unit and `arras` refuses a
  unit on a unitless property (`arras.model` difference 1), and the DC
  line `status` as an integer (gridlabd's converter writes `1.0`, which
  `arras` does not read as a keyword value).
- The `#on_exit` commands (`check_case.py` and `diff` of recordings) and
  `#gridlabd -C ...` are removed; the tests make the same checks after the
  run (see `../README.md`). `case.glm`'s `#for OBJ in ${FIND class=shunt}`
  loop is removed: the cases have no shunts.
- `#ifexist ...`/`#define DIR=..` blocks, `${DIR:-.}/` prefixes,
  `controllers_path "${DIR}"`, `#setenv PYTHONPATH`, and `#system cp`
  are removed (`arras` has no `#if` macros; the files are in the working
  folder, where the controllers module is found).
- The `PST+8PDT` time zone is `America/Los_Angeles`, `GMT0` is `UTC`, and
  the `PST`/`PDT` suffixes of clock times are removed, because `arras`
  reads only IANA zone names (#41).
- Global values with units that differ from the global's are converted:
  `maximum_timestep 1h` and `opf_update_interval 1h` are `3600`,
  `autosize_angle 60 deg` is `1.0471975511965976` (rad), because
  `arras.globals` accepts only the declared unit (open question 2, #12).
- `voltage_high 1.05 pu` and `voltage_low 0.95 pu` of
  `test_shunt_capacitor.glm` are `1.05` and `0.95` (unitless
  properties); `baseKV (${BASEKV}/2)` of `test_autosize.glm` is
  `34.5 kV` (`arras` reads no expressions).
- `#define NO_ONEXIT TRUE` is `#define NO_ONEXIT=TRUE`.
- The `#for` loops of `test_case14_ts.glm` and
  `test_case14_opf_dispatch_opt.glm` are expanded.
- `${modelname/.glm/_record.csv}` and `${modelname/.glm/.json}` are the
  file names they give, because `arras` does not set `modelname`.

Data files trimmed to the times the autotests run (the runs read the same
rows):

- `test_case14_weather.csv` and `test_case14_sensitivity.csv` (identical
  files of 5-minute weather, 2018 to 2022, 525,888 lines and 33 MB each)
  keep the header and the rows from 2020-07-31 00:00 to 2020-09-02 00:00
  (-07:00), 9,506 lines and 0.6 MB each.
- `test_case14_powerplant_pp_bus_2.csv` (hourly, 2019 to 2021, 23,706
  lines) keeps the header and the rows from 2020-04-30 to 2020-05-03.

Not copied: `test_derating_powerplant_capacity` (an older recording of
`test_derating.glm` in Pacific time that the autotest does not use).

Sizes: `case118.glm` is 121 kB, the two weather files 0.6 MB each; the
others are under 60 kB.
