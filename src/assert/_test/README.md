Testing
-------

From the repository root:

	python3 -m venv .venv
	. .venv/bin/activate
	pip install -e . pytest
	pytest src/assert/_test

The package must be installed (editable or not), because `Model` finds the
module through the `arras.modules` entry point in `pyproject.toml`. The
tests use no network and no credentials, and finish in about two seconds.
`conftest.py` clears `arras.oclass.Class.registry` and
`arras.module.Module.registry` before and after each test, and provides the
`run()` helper, which runs GLM text after a one-step clock and
`module assert;`.

test_autotest.py
----------------

The gridlabd autotests of the `assert` module (`module/assert/autotest/`),
ported to `data/` (see `data/README.md`):

- every autotest is ported (15 files);
- files named `*_err.glm` fail with `RUNERR` and the expected first error
  line; the others succeed with no error or warning lines;
- each of the 53 `assert` objects of `test_assert.glm` fails the run when its
  `status` is set to `FALSE`, so none of them passes without testing;
- `test_assert_hold.glm` passes only because of `hold`, and
  `test_assert_group.glm` selects its 10 objects.

test_assert_module.py
---------------------

The package: the docstring examples (doctest), the entry point, `load()`
(classes, module, `assert::message_flags`, event handlers, `TRL` and pass
configuration, loading into a second model), `modhelp` output, property
types and defaults, the handlers outside a run and on other classes, entry
point errors in `Model.load_module()`, and `Runner.verbose()`.

test_g_assert.py
----------------

The `assert` class: comparisons of every property type (tolerances,
`inside`/`outside`, units, full-width integers, complex values, strings,
`bool` and `object` relations, enumerations, sets, timestamps), every
property part, the failure message, `status`, conversion warnings, global
targets, missing targets, groups (terms, errors, empty groups), `start`,
`stop`, `hold`, the `value`/`lower` alias, enduses, and the `VERBOSE` and
`QUIET` message flags.

test_typed_asserts.py
---------------------

`double_assert`, `int_assert`, `complex_assert`, and `enum_assert`:
tolerance modes, `ASSERT_TRUE`/`ASSERT_FALSE`/`ASSERT_NONE`, messages,
`within` checks at initialization, the `once` logic (a handler changes
`value` during the run), invalid targets, global targets, verbose messages,
complex value forms, and 64-bit `int_assert` arithmetic.

test_helpers.py
---------------

The private helpers: number, complex, flag, and timestamp conversion
(including time zone abbreviations in the hour that repeats when daylight
saving time ends), targets of header properties, operators, and the
remaining property types.

assert_test_random.py
---------------------

Not a test: event handlers used by the ported autotests. `sync()` stands in
for `randomvar` refreshes (see `data/README.md`); `hourly()` asks for an
event every hour.
