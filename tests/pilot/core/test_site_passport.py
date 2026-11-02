import json
from types import SimpleNamespace

import pytest

from pilot.config import SiteConfig
from pilot.core.site import Site
from pilot.core.site.config import read_public_config, read_site_config, update_public_config
from pilot.core.site.passport import require_origin
from pilot.exceptions import BenchError
from tests.pilot.commands.test_commands import make_bench


@pytest.mark.parametrize(
    "origin",
    [
        "https://@site.invalid",
        "https://user:@site.invalid",
        "https://site.invalid:bad",
        "https://site.invalid/path",
        "https://site.invalid/?secret=x",
    ],
)
def test_enrollment_origin_rejects_credentials_and_non_origins(origin):
    with pytest.raises(BenchError):
        require_origin(origin)


@pytest.fixture
def site(tmp_path):
    site = Site(SiteConfig(name="test.local", apps=[]), make_bench(tmp_path))
    site.path.mkdir(parents=True)
    (site.path / "site_config.json").write_text(
        json.dumps({"host_name": "https://site.example.invalid", "unrelated": 42})
    )
    return site


@pytest.fixture
def generated(monkeypatch):
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "private_key": "fixture-private",
                    "key_id": "fixture-kid",
                    "public_jwk": {"x": "fixture-public"},
                }
            ).encode()
        )

    monkeypatch.setattr("pilot.core.site.passport.run_command", run)
    return calls


def test_preparation_is_private_suspended_and_idempotent(site, generated):
    request = site.prepare_passport_enrollment("https://id.example.invalid", "client")
    assert "private" not in json.dumps(request)
    assert site.prepare_passport_enrollment("https://id.example.invalid", "client") == request
    assert len(generated) == 1
    state = read_site_config(site.path)
    assert state["passport_disabled"] is True
    assert state["passport_private_key"] == "fixture-private"
    assert state["unrelated"] == 42
    assert (site.path / "site_config.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(BenchError):
        site.prepare_passport_enrollment("https://other.example.invalid", "client")


def test_restore_invalidates_pending_approval(site, generated):
    site.prepare_passport_enrollment("https://id.example.invalid", "client")
    before = read_site_config(site.path)
    site.suspend_passport()
    after = read_site_config(site.path)
    assert after["passport_installation"] != before["passport_installation"]
    assert "passport_enrollment" not in after
    with pytest.raises(BenchError):
        site.confirm_passport_enrollment({}, [])


def test_confirmation_only_enables_unchanged_preparation(site, generated, monkeypatch):
    request = site.prepare_passport_enrollment("https://id.example.invalid", "client")
    monkeypatch.setattr(
        "pilot.core.site.passport.run_command",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=json.dumps({"request": request, "installation": "approved-revision"}).encode()
        ),
    )
    assert site.confirm_passport_enrollment({}, []) == "approved-revision"
    state = read_site_config(site.path)
    assert state["passport_disabled"] is False
    assert state["passport_installation"] == "approved-revision"
    assert "passport_enrollment" not in state


def test_restore_during_confirmation_cannot_enable_site(site, generated, monkeypatch):
    request = site.prepare_passport_enrollment("https://id.example.invalid", "client")

    def confirm(*args, **kwargs):
        site.suspend_passport()
        return SimpleNamespace(
            stdout=json.dumps({"request": request, "installation": "approved-revision"}).encode()
        )

    monkeypatch.setattr("pilot.core.site.passport.run_command", confirm)
    with pytest.raises(BenchError, match="configuration changed"):
        site.confirm_passport_enrollment({}, [])
    assert read_site_config(site.path)["passport_disabled"] is True


def test_failed_generation_preserves_configuration(site, monkeypatch):
    before = read_site_config(site.path)

    def fail(*args, **kwargs):
        raise BenchError("fixture generation failed")

    monkeypatch.setattr("pilot.core.site.passport.run_command", fail)
    with pytest.raises(BenchError):
        site.prepare_passport_enrollment("https://id.example.invalid", "client")
    assert read_site_config(site.path) == before


@pytest.mark.parametrize("key", ["passport_disabled", "passport_enrollment", "passport_installation"])
def test_public_configuration_cannot_bypass_enrollment(site, generated, key):
    site.prepare_passport_enrollment("https://id.example.invalid", "client")
    before = read_site_config(site.path)
    assert key not in read_public_config(site.path)
    for value in (None, False, "previous-installation"):
        with pytest.raises(BenchError):
            update_public_config(site.path, {key: value})
        assert read_site_config(site.path) == before
