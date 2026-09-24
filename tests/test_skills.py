"""R-036: the two shipped skills work as their SKILL.md says.

A skill is instructions plus the scripts it tells an agent to run. The instructions are checked for
what an agent host reads (a name that matches the folder, a description), and the scripts are run:
the SDD guard against a design document whose gates exist and one whose gates do not, and the sweep
runner through a sweep that records, resumes, refuses and stops.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from copela import Ledger, StubProvider
from copela.providers import Pricing

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("skill", ["author-sdd", "run-sweep"])
def test_every_skill_declares_its_name_and_purpose(skill) -> None:
    text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
    front = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert front, "no frontmatter"
    name = re.search(r"^name:\s*(\S+)\s*$", front.group(1), re.M)
    assert name and name.group(1) == skill
    description = front.group(1).split("description:", 1)[1].split("allowed-tools:", 1)[0]
    assert len(" ".join(description.split())) >= 200, "a description too short to choose the skill by"


def test_the_skill_ships_the_same_sdd_guard_as_the_repository() -> None:
    shipped = (SKILLS / "author-sdd" / "scripts" / "check_sdd.py").read_bytes()
    assert shipped.replace(b"\r\n", b"\n") == (ROOT / "scripts" / "check_sdd.py").read_bytes().replace(b"\r\n", b"\n")


def test_the_template_passes_the_guard_when_its_gates_exist_and_fails_when_they_do_not(tmp_path) -> None:
    guard = _load(SKILLS / "author-sdd" / "scripts" / "check_sdd.py", "skill_check_sdd")
    template = (SKILLS / "author-sdd" / "assets" / "SDD-template.md").read_text(encoding="utf-8")
    filled = template.replace("<unit>", "unit").replace("<what_it_checks>", "what_it_checks").replace("<thing>", "thing")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "unit.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "docs" / "design").mkdir(parents=True)
    (tmp_path / "docs" / "design" / "SDD.md").write_text(filled, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check_thing.py").write_text("print('ok')\n", encoding="utf-8")
    test_file = tmp_path / "tests" / "test_unit.py"
    test_file.write_text("def test_what_it_checks():\n    assert True\n", encoding="utf-8")

    assert guard.main(["check_sdd.py", str(tmp_path)]) == 0
    test_file.unlink()
    assert guard.main(["check_sdd.py", str(tmp_path)]) == 1, "a gate that does not exist passed"


def test_the_runner_records_resumes_refuses_and_stops(tmp_path, monkeypatch) -> None:
    runner = _load(SKILLS / "run-sweep" / "scripts" / "run_sweep.py", "skill_run_sweep")
    study = SKILLS / "run-sweep" / "assets" / "example_study.py"
    answer = (SKILLS / "run-sweep" / "assets" / "example_blend.json").read_text(encoding="utf-8")

    def use(provider):
        monkeypatch.setattr(runner, "get", lambda name, **kwargs: provider)

    ledger = tmp_path / "runs.jsonl"
    common = ["--study", str(study), "--provider", "stub", "--model", "stub-small", "--ledger", str(ledger)]

    # A paid model with no budget is refused before the lock.
    use(StubProvider(default=answer, pricing=Pricing(1.0, 5.0)))
    assert runner.main(common) == 2
    assert not ledger.exists() and not ledger.with_suffix(".jsonl.lock").exists()

    # Two repeats of the one case are recorded, each with the document it parsed into.
    assert runner.main([*common, "--budget-usd", "0.05", "--repeats", "2"]) == 0
    records = Ledger(ledger).records()
    assert [r.key.repeat for r in records] == [0, 1]
    # Compared as problems, not as JSON: a document is re-serialised at the installed planteo's
    # schema, and the same problem written at another version is the same problem.
    from planteo import Problem

    assert all(Problem.from_json(r.candidate) == Problem.from_json(json.loads(answer)) for r in records)

    # A resume makes no call: the ledger already holds both.
    before = ledger.read_text(encoding="utf-8")
    assert runner.main([*common, "--budget-usd", "0.05", "--repeats", "2"]) == 0
    assert ledger.read_text(encoding="utf-8") == before

    # The connection drops after the probe: the runner stops with 4, records nothing, unlocks.
    fresh = tmp_path / "fresh.jsonl"
    use(StubProvider(default=answer, pricing=Pricing(1.0, 5.0), unreachable_after=1))
    code = runner.main([*common[:-1], str(fresh), "--budget-usd", "0.05"])
    assert code == 4
    assert not fresh.exists() or fresh.read_text(encoding="utf-8") == ""
    assert not fresh.with_suffix(".jsonl.lock").exists()

    # A probe that fails refuses before anything, as a wrong key does.
    use(StubProvider(default=answer, pricing=Pricing(1.0, 5.0), unreachable_after=0))
    assert runner.main([*common[:-1], str(fresh), "--budget-usd", "0.05"]) == 2
