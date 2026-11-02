from __future__ import annotations

import json
from pathlib import Path

import pytest

from pilot.config import SiteConfig
from pilot.core.site import Site
from tests.pilot.commands.test_commands import make_bench


def test_failed_restore_leaves_passport_suspended_and_retries_keep_fence(tmp_path, monkeypatch):
    bench = make_bench(tmp_path)
    bench.config.db_type = "sqlite"
    site = Site(SiteConfig(name="test.local", apps=[]), bench)
    site.path.mkdir(parents=True)
    path = site.path / "site_config.json"
    path.write_text(
        json.dumps(
            {"db_type": "sqlite", "db_name": "fixture", "passport_client_id": "fixture", "unrelated": 42}
        )
    )

    def fail_restore(*args, **kwargs):
        state = json.loads(path.read_text())
        assert state["passport_disabled"] is True
        assert state["passport_installation"]
        raise RuntimeError("fixture restore failed")

    monkeypatch.setattr("pilot.core.site.commands.run_command", fail_restore)
    with pytest.raises(RuntimeError, match="fixture restore failed"):
        site.restore("backup.sql.gz")
    first = json.loads(path.read_text())
    with pytest.raises(RuntimeError, match="fixture restore failed"):
        site.restore("backup.sql.gz")
    assert json.loads(path.read_text()) == first
    assert first["unrelated"] == 42
    assert first["passport_client_id"] == "fixture"


def test_restore_recreates_runtime_directories_and_keeps_existing_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench = make_bench(tmp_path)
    bench.config.db_type = "sqlite"
    site = Site(SiteConfig(name="restored.localhost", apps=[]), bench)
    site.path.mkdir(parents=True)
    config = '{"db_type": "sqlite", "db_name": "restored"}'
    (site.path / "site_config.json").write_text(config)

    def restore_command(cmd: list[str], **kwargs) -> None:
        assert cmd[cmd.index("restore") + 1] == "backup.sql.gz"
        with (site.path / "logs" / "database.log").open("a") as log:
            log.write("restored\n")
        (site.path / "locks" / "restore.lock").touch()

    monkeypatch.setattr("pilot.core.site.commands.run_command", restore_command)
    site.restore("backup.sql.gz")
    site.restore("backup.sql.gz")

    assert (site.path / "logs" / "database.log").read_text() == "restored\nrestored\n"
    assert (site.path / "locks" / "restore.lock").is_file()
    assert (site.path / "site_config.json").read_text() == config
