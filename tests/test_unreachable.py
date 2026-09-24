"""R-035: a call that never reached the model stops the sweep and is not recorded.

A connection refused, a name that does not resolve, or a key the provider rejects says nothing about
the model. Recording it wrote rows about a key file into an append-only ledger as rows about the
model, and a network that dropped mid-sweep would have done the same for every call until the kill
criterion. An HTTP 500 is different: it is the provider's answer to that call, and stays recorded.
"""

from __future__ import annotations

import http.server
import socket
import threading

import pytest

from copela import (
    Budget,
    Case,
    Ledger,
    ProviderError,
    ProviderUnreachable,
    StubProvider,
    Sweep,
    Target,
)
from copela.providers.base import unreachable
from copela.providers.hosted import DeepSeekProvider


def _cases(n: int) -> list[Case]:
    return [Case(f"c{i}", "optimization", f"narrative {i}") for i in range(n)]


def _sweep(ledger: Ledger, provider: StubProvider) -> Sweep:
    return Sweep(
        ledger=ledger,
        budget=Budget(limit_usd=1.0),
        providers={"stub": provider},
        build_prompt=lambda case: case.narrative,
        parse_response=lambda text, case: None,  # type: ignore[return-value]
        repeats=1,
    )


def test_a_call_that_never_reached_the_provider_stops_the_sweep_and_records_nothing(ledger_path) -> None:
    """The connection drops after two calls: the sweep stops, the two are kept, the third is not
    recorded, and a resume on a working connection completes the rest."""
    ledger = Ledger(ledger_path)
    with pytest.raises(ProviderUnreachable):
        _sweep(ledger, StubProvider(default="x", unreachable_after=2)).run(_cases(4), [Target("stub", "stub-small")])
    assert [r.key.case_id for r in Ledger(ledger_path).records()] == ["c0", "c1"]

    made = _sweep(Ledger(ledger_path), StubProvider(default="x")).run(_cases(4), [Target("stub", "stub-small")])
    assert made == 2
    assert [r.key.case_id for r in Ledger(ledger_path).records()] == ["c0", "c1", "c2", "c3"]
    assert all("call failed" not in r.error for r in Ledger(ledger_path).records())


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_a_refused_connection_is_unreachable() -> None:
    provider = DeepSeekProvider(api_key="not-a-key", base_url=f"http://127.0.0.1:{_free_port()}", timeout_s=5)
    with pytest.raises(ProviderUnreachable):
        provider.complete("hello", model_id="deepseek-v4-pro", max_tokens=8)


@pytest.mark.parametrize(("status", "unreached"), [(401, True), (403, True), (500, False)])
def test_rejected_credentials_are_unreachable_and_a_server_error_is_not(status, unreached) -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802, the stdlib's name
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": {"message": "no"}}')

        def log_message(self, *args) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = DeepSeekProvider(api_key="not-a-key", base_url=f"http://127.0.0.1:{server.server_port}", timeout_s=5)
        with pytest.raises(ProviderError) as raised:
            provider.complete("hello", model_id="deepseek-v4-pro", max_tokens=8)
        assert isinstance(raised.value, ProviderUnreachable) is unreached
    finally:
        server.shutdown()


def test_sdk_errors_are_read_by_name_along_the_mro() -> None:
    """copela does not import the SDKs to ask; a connection error's subclass counts, a rate limit
    does not, because the provider answered it."""

    class APIConnectionError(Exception):
        pass

    class APITimeoutError(APIConnectionError):
        pass

    class RateLimitError(Exception):
        pass

    assert unreachable(APIConnectionError("down"))
    assert unreachable(APITimeoutError("slow to connect"))
    assert not unreachable(RateLimitError("429"))
