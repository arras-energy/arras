Test data
=========

The `test_*.glm` files are the gridlabd autotests of the `assert` module,
from `module/assert/autotest/` in
[arras-energy/gridlabd](https://github.com/arras-energy/gridlabd), copied
from `master` at commit 076e78a (2026-08-16) on 2026-11-24. Files named
`*_err.glm` are expected to fail. They are changed only where `arras` needs
it:

- `module powerflow;`, `module climate;`, and `module residential;` are
  replaced by `#include` of `meter.glm`, `climate.glm`, and `house.glm`,
  which declare the properties that the tests use with the types that
  those modules publish (`node.voltage_A`, `powerflow_object.phases`,
  `climate.temperature`, `climate.interpolate`, `house.compressor_count`),
  because `arras` has no such modules.
- The `PST+8PDT` time zone is replaced by `America/Los_Angeles`, and the
  `PST` suffix is removed from timestamps, because `arras` reads only IANA
  zone names (#41).
- In `test_assert_group.glm`, `test_assert_hold.glm`,
  `test_assert_hold_err.glm`, and `test_assert_start_err.glm`, the
  `randomvar random_value` property is a `double` set by the handler
  `assert_test_random.sync` every `refresh` seconds (the refresh period of
  the original `randomvar`), with uniform(0,1) values from Python's `random`
  module seeded with `randomseed`, because `arras` does not refresh
  `randomvar` values. Runs are repeatable; the draws differ from gridlabd's.
- In `test_assert.glm`, the `object_value` `clock.days` assert checks the
  clock of the object referred to (between 11323 and 11324 days) instead of
  `0`: the original passed only because gridlabd's `object_get_part()` read
  the header from the address of the reference. The gridlabd `assert-fixes`
  branch fixes that function and makes the same change to its autotest
  (DESIGN.md decision 8.4).
- `test_complex_assert_real_err.glm` is unchanged: like the gridlabd file, it
  tests the magnitude, not the real part.

Size: under 10 kB in all.
