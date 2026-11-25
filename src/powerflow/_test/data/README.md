Test data
---------

`unbalanced_feeder.glm`: a 4.16 kV (2401.7771 V line-to-neutral) feeder of
two three-phase line sections, 2000 ft and 2500 ft, of IEEE 13-node feeder
line configuration 601, written for these tests (not a gridlabd autotest):

| node | loads |
| ---- | ----- |
| `n0` | swing node |
| `n1` | wye constant power: A 200+100j kVA, B 120+60j kVA, C 50+30j kVA |
| `n2` | delta constant power AB 100+40j kVA; wye constant current C 15+5j A; wye admittance B 0.002+0.0005j S |

The lines are `test_line` objects, the stand-in line class that
`conftest.py` registers (`StandInLine`), so the file runs only after
`register_test_line()`. `test_feeder_file` compares its node voltages with
the independent solution of `conftest.reference()`.

gridlabd's powerflow autotests (`module/powerflow/autotest/`) all use line,
transformer, load, or meter classes, which are not ported yet; they are to
be added here with those classes.
