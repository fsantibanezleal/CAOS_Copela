"""The run ledger: append-only JSONL, one record per call.

Two properties, both enforced rather than intended.

**Append-only.** A record that has been written is never modified. A ledger that can be rewritten is
not evidence, and the whole value of this file is that a number in a report can be traced back to
the call that produced it.

**Every call pins its provenance.** Model id, model version, temperature, seed, provider
fingerprint, repeat index and prompt digest, on every record. Without those a rate is a number with
no subject, and six months later nobody can say which model produced it.

The ledger is also the resume mechanism: a sweep reads it, sees which (case, model, repeat) triples
are already done, and skips them. A long sweep that lost its work to an interruption is a cost this
account has already paid once.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

#: 1.1 adds `harness` and `max_tokens`; 1.2 adds `candidate`. An older record still loads, with
#: what it lacks empty.
LEDGER_SCHEMA = "copela-ledger/1.2"


class LedgerError(RuntimeError):
    """Raised when an operation would violate the append-only contract."""


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class CallKey:
    """What makes a call unique, and therefore what resume matches on."""

    case_id: str
    provider: str
    model_id: str
    repeat: int

    def as_tuple(self) -> tuple[str, str, str, int]:
        return (self.case_id, self.provider, self.model_id, self.repeat)


@dataclass(frozen=True, slots=True)
class Record:
    """One call. Every field below is required; that is the point of R-003."""

    key: CallKey
    family: str
    model_version: str
    temperature: float
    seed: int | None
    provider_fingerprint: str
    prompt_digest: str
    response_digest: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    verdicts: list[dict[str, object]] = field(default_factory=list)
    error: str = ""
    #: A bounded excerpt of the raw response, kept ONLY when the call failed.
    #:
    #: A digest proves a response existed and says nothing about what was wrong with it. Diagnosing
    #: a failure from a digest is impossible, and re-running to reproduce does not work either:
    #: hosted inference is not deterministic, so the failure may not come back. The excerpt is
    #: bounded because a ledger is evidence, not a transcript archive, and it is kept only on
    #: failure because a successful run is already described by its verdicts.
    response_excerpt: str = ""
    recorded_at: str = ""
    #: The copela version that scored the call, and the output cap it ran at (R-033).
    #:
    #: Both were missing, and both turned out to matter. One ledger held records scored by three
    #: copela versions, which judge an unbounded candidate differently, with nothing in a record
    #: to tell them apart; and a report had to assume the cap, because a record could not say it.
    #: Records written before schema 1.1 load with both empty: unknown, not guessed.
    harness: str = ""
    max_tokens: int = 0
    #: The candidate the response parsed into, as its document, whole (R-034). None when the
    #: response did not parse, or the record predates schema 1.2.
    #:
    #: The verdicts say what the layers concluded and nothing about what they concluded it of. A
    #: stronger check written later could not be applied to a recorded candidate, because the ledger
    #: kept a digest of every response and an excerpt of the failed ones only; so most of a
    #: published faithfulness rate rested on the one layer that had run, with no way to re-examine
    #: it. And two refutations that turned out to be a reading the statement allowed, whole numbers
    #: against a continuous reference, could be established only from excerpts that happened to
    #: keep the declarations. It is kept whole because a truncated document cannot be re-checked.
    candidate: dict[str, object] | None = None

    def to_json(self) -> dict[str, object]:
        data = {
            "schema": LEDGER_SCHEMA,
            "case_id": self.key.case_id,
            "provider": self.key.provider,
            "model_id": self.key.model_id,
            "repeat": self.key.repeat,
            "family": self.family,
            "model_version": self.model_version,
            "temperature": self.temperature,
            "seed": self.seed,
            "provider_fingerprint": self.provider_fingerprint,
            "prompt_digest": self.prompt_digest,
            "response_digest": self.response_digest,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "verdicts": self.verdicts,
            "error": self.error,
            "response_excerpt": self.response_excerpt,
            "recorded_at": self.recorded_at
            or datetime.now(UTC).isoformat(timespec="seconds"),
            "harness": self.harness,
            "max_tokens": self.max_tokens,
            "candidate": self.candidate,
        }
        return data

    @classmethod
    def from_json(cls, data: dict[str, object]) -> Record:
        return cls(
            key=CallKey(
                case_id=str(data["case_id"]),
                provider=str(data["provider"]),
                model_id=str(data["model_id"]),
                repeat=int(data["repeat"]),  # type: ignore[arg-type]
            ),
            family=str(data.get("family", "")),
            model_version=str(data.get("model_version", "")),
            temperature=float(data.get("temperature", 0.0)),  # type: ignore[arg-type]
            seed=None if data.get("seed") is None else int(data["seed"]),  # type: ignore[arg-type]
            provider_fingerprint=str(data.get("provider_fingerprint", "")),
            prompt_digest=str(data.get("prompt_digest", "")),
            response_digest=str(data.get("response_digest", "")),
            latency_ms=float(data.get("latency_ms", 0.0)),  # type: ignore[arg-type]
            input_tokens=int(data.get("input_tokens", 0)),  # type: ignore[arg-type]
            output_tokens=int(data.get("output_tokens", 0)),  # type: ignore[arg-type]
            cost_usd=float(data.get("cost_usd", 0.0)),  # type: ignore[arg-type]
            verdicts=list(data.get("verdicts", [])),  # type: ignore[arg-type]
            error=str(data.get("error", "")),
            response_excerpt=str(data.get("response_excerpt", "")),
            recorded_at=str(data.get("recorded_at", "")),
            harness=str(data.get("harness", "")),
            max_tokens=int(data.get("max_tokens", 0)),  # type: ignore[arg-type]
            candidate=data.get("candidate"),  # type: ignore[arg-type]
        )


#: Fields whose absence makes a record useless as evidence. R-003.
REQUIRED_PROVENANCE = (
    "model_id",
    "model_version",
    "temperature",
    "provider_fingerprint",
    "prompt_digest",
    "repeat",
)


class LedgerBusy(LedgerError):
    """Another process holds this ledger."""


class Ledger:
    """An append-only JSONL file of call records.

    ``exclusive=True`` takes a lock for the lifetime of the object, so two sweeps cannot write one
    ledger. That is not hypothetical: a sweep was started while an earlier one was still alive, both
    appended to the same file, and the result interleaved records from two different versions of the
    code. Append-only does not help there, because the two processes write different keys, so
    nothing collides and nothing complains. The file simply stops meaning one thing.
    """

    def __init__(self, path: str | os.PathLike[str], exclusive: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._holds_lock = False
        if exclusive:
            self._acquire()

    def _acquire(self) -> None:
        try:
            # O_EXCL is the whole mechanism: creating the file IS the lock, atomically.
            descriptor = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            holder = ""
            try:
                holder = self._lock_path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
            raise LedgerBusy(
                f"{self.path} is locked by {holder or 'another process'}. Two sweeps writing one "
                f"ledger interleave their records and the file stops meaning one thing. "
                f"Stop the other run, or delete {self._lock_path.name} if it is stale"
            ) from None
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(
                f"pid {os.getpid()} since "
                f"{datetime.now(UTC).isoformat(timespec='seconds')}\n"
            )
        self._holds_lock = True

    def release(self) -> None:
        if self._holds_lock:
            self._lock_path.unlink(missing_ok=True)
            self._holds_lock = False

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *_: object) -> None:
        self.release()

    # -- writing ---------------------------------------------------------------------

    def append(self, record: Record) -> None:
        """Append one record. Refuses a duplicate key, because that would be a rewrite."""
        payload = record.to_json()
        missing = [
            name
            for name in REQUIRED_PROVENANCE
            if payload.get(name) in (None, "")
        ]
        if missing:
            raise LedgerError(
                f"refusing to record a call missing its provenance: {', '.join(missing)}. "
                "A rate over records that cannot say which model produced them is not evidence"
            )
        if self.has(record.key):
            raise LedgerError(
                f"{record.key.as_tuple()} is already in the ledger. The ledger is append-only; "
                "a run is never edited, because a ledger that can be rewritten is not evidence"
            )
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    # -- reading ---------------------------------------------------------------------

    def __iter__(self) -> Iterator[Record]:
        if not self.path.exists():
            return iter(())
        return self._read()

    def _read(self) -> Iterator[Record]:
        with self.path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield Record.from_json(json.loads(line))
                except (json.JSONDecodeError, KeyError) as error:
                    raise LedgerError(
                        f"{self.path}:{number} is not a readable record: {error}"
                    ) from error

    def records(self) -> list[Record]:
        return list(self)

    def keys(self) -> set[tuple[str, str, str, int]]:
        return {record.key.as_tuple() for record in self}

    def has(self, key: CallKey) -> bool:
        return key.as_tuple() in self.keys()

    def completed(self) -> set[tuple[str, str, str, int]]:
        """Keys already done, so a resumed sweep can skip them. R-012."""
        return self.keys()

    @property
    def total_cost_usd(self) -> float:
        return sum(record.cost_usd for record in self)
