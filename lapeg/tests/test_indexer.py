from typing import Any

import pytest

from lapeg.chain import indexer


class FakeEth:
    """get_logs that rejects ranges wider than `cap` and fails transiently every `flaky`-th call."""

    def __init__(self, cap: int, flaky: int = 0) -> None:
        self.cap, self.flaky, self.calls = cap, flaky, 0
        self.ranges: list[tuple[int, int]] = []

    def get_logs(self, flt: dict[str, Any]) -> list[dict[str, int]]:
        self.calls += 1
        if self.flaky and self.calls % self.flaky == 0:
            raise ConnectionError("429 Too Many Requests")
        lo, hi = flt["fromBlock"], flt["toBlock"]
        if hi - lo + 1 > self.cap:
            raise ValueError("ranges over 10000 blocks are not supported on free plan")
        self.ranges.append((lo, hi))
        return [{"blockNumber": b} for b in range(lo, hi + 1) if b % 97 == 0]


class FakeW3:
    def __init__(self, eth: FakeEth) -> None:
        self.eth = eth


ADDR = "0x0000000000000000000000000000000000000001"


@pytest.mark.parametrize("cap", [10_000, 100, 37])
def test_covers_range_exactly_once(cap: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(indexer.time, "sleep", lambda s: None)
    eth = FakeEth(cap)
    logs = indexer.fetch_logs(FakeW3(eth), ADDR, [], 1_000, 25_000, chunk=10_000, min_chunk=10)  # type: ignore[arg-type]
    covered = [b for lo, hi in eth.ranges for b in range(lo, hi + 1)]
    assert covered == list(range(1_000, 25_001))                     # contiguous, no gaps, no overlap
    assert [x["blockNumber"] for x in logs] == [b for b in range(1_000, 25_001) if b % 97 == 0]
    assert max(hi - lo + 1 for lo, hi in eth.ranges) <= cap


def test_transient_errors_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(indexer.time, "sleep", lambda s: None)
    eth = FakeEth(cap=1_000, flaky=3)
    logs = indexer.fetch_logs(FakeW3(eth), ADDR, [], 0, 5_000, chunk=1_000)  # type: ignore[arg-type]
    assert len(logs) == len([b for b in range(0, 5_001) if b % 97 == 0])


def test_range_error_classification() -> None:
    assert indexer.is_range_error(ValueError("ranges over 10000 blocks are not supported on free plan"))
    assert not indexer.is_range_error(ConnectionError("429 Too Many Requests"))
