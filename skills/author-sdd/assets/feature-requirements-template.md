# <Feature>, requirements

Part of `docs/design/SDD.md`. Design in `design.md`, tasks in `tasks.md`.

```
R-101  WHEN <trigger>, THE <component> SHALL <response>.
       Gate: tests/test_<feature>.py::test_<what_it_checks>

R-102  WHILE <state>, THE <component> SHALL <response>.
       Gate: tests/test_<feature>.py::test_<what_it_checks>

R-103  IF <unwanted condition>, THEN THE <component> SHALL <response>, and SHALL NOT <what it must
       never do>.
       Gate: tests/test_<feature>.py::test_<what_it_checks>
```

Why each exists: <the incident, measurement or decision behind it>.

Mutation check, per gate: <what was broken to watch the gate fail, and that it failed>.
