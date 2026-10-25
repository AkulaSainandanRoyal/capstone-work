"""Anvil fork lifecycle and state manipulation.

One AnvilFork = one anvil process forked from an upstream RPC at a fixed block.

Snapshot semantics (anvil): evm_revert(id) restores the state AND consumes snapshot `id` and every later
one. Take a new snapshot after each revert if you need to return again; `branch()` does this for you.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from web3 import Web3


class AnvilError(RuntimeError):
    pass


class SnapshotError(AnvilError):
    pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _word(x: int) -> str:
    """uint256 -> 0x-prefixed 32-byte hex."""
    if not 0 <= x < 2**256:
        raise ValueError("value out of uint256 range")
    return "0x" + x.to_bytes(32, "big").hex()


class AnvilFork:
    def __init__(
        self,
        fork_url: str,
        block: int,
        *,
        port: int | None = None,
        anvil_bin: str = "anvil",
        extra_args: list[str] | None = None,
        startup_timeout_s: float = 90.0,
        log_path: str | Path | None = None,
    ) -> None:
        self.fork_url = fork_url
        self.block = block
        self.port = port
        self.anvil_bin = anvil_bin
        self.extra_args = list(extra_args or [])
        self.startup_timeout_s = startup_timeout_s
        self.log_path = Path(log_path) if log_path else None
        self._proc: subprocess.Popen[bytes] | None = None
        self._log_file: Any = None
        self.w3: Web3 | None = None

    # ---------- lifecycle ----------
    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> AnvilFork:
        if self.running:
            return self
        exe = shutil.which(self.anvil_bin)
        if exe is None:
            raise AnvilError(f"'{self.anvil_bin}' not found on PATH (install Foundry)")
        if self.port is None:
            self.port = _free_port()
        if self.log_path is None:
            fd, name = tempfile.mkstemp(prefix="anvil_", suffix=".log")
            os.close(fd)
            self.log_path = Path(name)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = open(self.log_path, "wb")
        cmd = [exe, "--fork-url", self.fork_url, "--fork-block-number", str(self.block),
               "--host", "127.0.0.1", "--port", str(self.port), *self.extra_args]
        self._proc = subprocess.Popen(cmd, stdout=self._log_file, stderr=subprocess.STDOUT)
        self.w3 = Web3(Web3.HTTPProvider(self.url, request_kwargs={"timeout": 120}))
        self._wait_ready()
        return self

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + self.startup_timeout_s
        while time.monotonic() < deadline:
            if not self.running:
                raise AnvilError(f"anvil exited during startup:\n{self.log_tail()}")
            try:
                if self.rpc("eth_blockNumber") is not None:
                    return
            except Exception:
                time.sleep(0.25)
        self.stop()
        raise AnvilError(f"anvil not ready after {self.startup_timeout_s}s:\n{self.log_tail()}")

    def stop(self) -> None:
        if self._proc is not None:
            if self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait(timeout=10)
            self._proc = None
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def log_tail(self, n: int = 30) -> str:
        if self.log_path is None or not self.log_path.exists():
            return ""
        lines = self.log_path.read_text(errors="replace").splitlines()
        return "\n".join(lines[-n:])

    def __enter__(self) -> AnvilFork:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # ---------- raw RPC ----------
    def rpc(self, method: str, params: list[Any] | None = None) -> Any:
        if self.w3 is None:
            raise AnvilError("fork not started")
        resp = self.w3.provider.make_request(method, params or [])  # type: ignore[arg-type]
        if "error" in resp:
            raise AnvilError(f"{method} failed: {resp['error']}")
        return resp["result"]

    def block_number(self) -> int:
        return int(self.rpc("eth_blockNumber"), 16)

    # ---------- snapshots ----------
    def snapshot(self) -> str:
        return str(self.rpc("evm_snapshot"))

    def revert(self, snapshot_id: str) -> None:
        """Restore the state saved by `snapshot_id`. The snapshot is consumed."""
        if not self.rpc("evm_revert", [snapshot_id]):
            raise SnapshotError(f"snapshot {snapshot_id} not found (already reverted to?)")

    @contextmanager
    def branch(self) -> Iterator[None]:
        """Run the block on a throwaway branch: everything inside is undone on exit."""
        snap = self.snapshot()
        try:
            yield
        finally:
            self.revert(snap)

    # ---------- accounts and state ----------
    def impersonate(self, address: str) -> None:
        self.rpc("anvil_impersonateAccount", [Web3.to_checksum_address(address)])

    def stop_impersonating(self, address: str) -> None:
        self.rpc("anvil_stopImpersonatingAccount", [Web3.to_checksum_address(address)])

    @contextmanager
    def impersonated(self, address: str) -> Iterator[str]:
        addr = Web3.to_checksum_address(address)
        self.impersonate(addr)
        try:
            yield addr
        finally:
            self.stop_impersonating(addr)

    def set_eth_balance(self, address: str, wei: int) -> None:
        self.rpc("anvil_setBalance", [Web3.to_checksum_address(address), hex(wei)])

    def get_storage(self, address: str, slot: int) -> int:
        word = self.rpc("eth_getStorageAt", [Web3.to_checksum_address(address), _word(slot), "latest"])
        return int(word, 16)

    def set_storage(self, address: str, slot: int, value: int) -> None:
        """Overwrite one storage word (the RPC equivalent of forge's vm.store)."""
        self.rpc("anvil_setStorageAt", [Web3.to_checksum_address(address), _word(slot), _word(value)])

    # ---------- time and blocks ----------
    def increase_time(self, seconds: int) -> None:
        self.rpc("evm_increaseTime", [seconds])

    def mine(self, blocks: int = 1) -> None:
        self.rpc("anvil_mine", [hex(blocks)])
