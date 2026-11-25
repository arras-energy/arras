Testing
-------

From the repository root:

	python3 -m venv .venv
	. .venv/bin/activate
	pip install -e . pytest
	pytest src/tape/_test

The package must be installed (editable or not), because `Model` finds the
module through the `arras.modules` entry point in `pyproject.toml`. The
tests use no network and no credentials, and finish in about 12 seconds
(4 of them for the year of hourly samples of `test_player_header.glm`).
`conftest.py` runs each test in an empty temporary folder with empty
`arras.oclass.Class.registry` and `arras.module.Module.registry`, ignores
the `data` folder when collecting tests, and provides helpers (the
`helpers` fixture): `model()` and `run()` (GLM text after a clock and
`module tape { csv_header_type NAME; }`), `copy_data()` (the test data into
the working folder), `lines()`, and `write()`.

`tape_test_random.py` holds the event handler that stands in for the
`randomvar` refreshes of the ported autotests (see `data/README.md`).

test_tape_autotest.py
---------------------

Runs each ported gridlabd autotest (`data/test_*.glm`) in its own folder:
the `_err` files must fail with `RUNERR` and the expected first error, the
others must succeed with no error or warning lines. Then checks what the
autotests leave to their `#on_exit` comparisons or do not check:

- `test_player_header`: the 8760 recorded rows are those gridlabd wrote
  (`data/test_player_header_output.csv`), line for line.
- `test_multiplayer`: both recordings are those gridlabd wrote.
- the histograms: the counts of each bin at each row, checked by hand
  against the node voltages, enumerations, and sets of the models.
- `test_recorder_epoch`, `test_recorder_strftime_format`,
  `test_tape_whitespace`: timestamps as seconds and as `strftime`
  formats, every output format (`%a`, `%e`, `%f`, `%g`, the complex forms),
  and property lists with spaces.
- the player, recorder, collector, and multi-recorder exercises, the
  global recorders, and the flush tests: rows and values.

The two deltamode autotests are not ported (see `data/README.md`).

test_tape_module.py
-------------------

The docstring examples of every module; registration of the module, its
11 classes in gridlabd's order, and its globals (including the shared
`csv_data_only`/`csv_header_type` value); published properties, defaults,
keywords, and readiness levels; `method` properties given twice in GLM;
handlers outside a run and on objects of other classes; unsupported tape
modes; file `-`; the three CSV header types and `csv_keep_clean`; and the
helpers (C `%a` formats, value conversions, local times, date formats,
shape fields, jsoncpp `StyledWriter` text).

test_tape_players.py
--------------------

Players (absolute, relative, epoch, and US dates, zone abbreviations,
loops, units, complex parts, CSV headers, fractions of a second, players
without a parent, default file names, and each error and warning),
shapers (direct shapes, queue events, file and target errors), and
multiplayers (`on_error` cases, initialization errors, globals, complex
values with units).

test_tape_recorders.py
----------------------

Recorders (intervals, value types, units, `header_units`, `line_units`,
output formats, triggers, limits, timestamp formats, `minimum_timestep`,
flushing, multi-run files, and errors), multi-recorders, collectors
(every aggregator, parts, units, absolute values, and each aggregate
error), histograms (auto-sized bins, parents, complex parts, errors), and
group recorders (intervals, units, limits, strict and non-strict errors).

test_tape_powerflow.py
----------------------

Violation recorders (each of the 8 checks on a small network of GLM
stand-in classes, the log rows, the summary, continuous and dynamic checks
over time, limits, delays, default files, and errors), metrics collectors
for each kind of parent, `findOutLimit()`, and metrics collector writers
(the six JSON files, their metadata, and the `StyledWriter` layout).
