Test data
=========

case14.json
-----------

- Source: `tools/autotest/case14.json` in
  [arras-energy/gridlabd](https://github.com/arras-energy/gridlabd), copied
  from `master` at commit 076e78a (2026-08-16) on 2026-11-23, unchanged.
- Written by gridlabd 4.3.11 (`gridlabd -C case14.glm -o case14.json`): the
  IEEE 14-bus case for the `pypower` module.
- Contents: gridlabd's JSON format (`source/json.cpp`) with the sections
  `application`, `version`, `modules` (`pypower`), `types`, `header`,
  `classes` (12 `pypower` classes), `globals`, `schedules` (none), and
  `objects` (44: 14 `bus`, 20 `branch`, 5 `gen`, 5 `gencost`).
- Used by `test_model.py` to check that `arras.model.Model` reads JSON that
  gridlabd wrote, registers its classes, and writes it back as JSON and GLM.
- Size: 87 kB.
