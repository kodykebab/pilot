from __future__ import annotations

import json
import secrets
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from pilot.core.site.config import read_site_config
from pilot.exceptions import BenchError
from pilot.internal.atomic_file import exclusive_file_lock, replace_private_text_locked
from pilot.utils import run_command

if TYPE_CHECKING:
    from pilot.core.site import Site


def require_origin(value: str) -> str:
    try:
        url = urlsplit(value)
        valid = (
            url.scheme in ("https", "http")
            and url.hostname
            and url.username is None
            and url.password is None
            and not url.query
            and not url.fragment
            and url.path in ("", "/")
            and not any(ord(character) <= 32 or ord(character) == 127 for character in value)
            and "\\" not in value
        )
        valid = valid and (url.port is None or 0 < url.port < 65536)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise BenchError("Passport requires an absolute HTTP(S) origin without credentials or a path.")
    return value.rstrip("/")


class SiteEnrollment:
    def __init__(self, site: Site) -> None:
        self.site = site
        self.path = site.path / "site_config.json"

    def prepare(self, issuer: str, client_id: str) -> dict:
        issuer = require_origin(issuer)
        if not isinstance(client_id, str) or not client_id or len(client_id) > 140:
            raise BenchError("A Passport client ID of at most 140 characters is required.")
        with exclusive_file_lock(self.path):
            original = read_site_config(self.site.path)
            home = require_origin(original.get("host_name", ""))
            if pending := original.get("passport_enrollment"):
                if (
                    pending["issuer"] != issuer
                    or pending["client_id"] != client_id
                    or pending["home_url"] != home
                ):
                    raise BenchError("Suspend the previous enrollment before changing its destination.")
                return pending
        generated = run_command(
            [str(self.site.bench.python), "-m", "passport_client.enrollment"],
            cwd=self.site.bench.sites_path,
            timeout=15,
        )
        keys = json.loads(generated.stdout)
        request = {
            "issuer": issuer,
            "client_id": client_id,
            "home_url": home,
            "public_jwk": keys["public_jwk"],
        }
        with exclusive_file_lock(self.path):
            current = read_site_config(self.site.path)
            if current != original:
                raise BenchError("Site configuration changed. Prepare enrollment again.")
            current.update(
                passport_disabled=True,
                passport_installation=secrets.token_hex(16),
                passport_issuer=issuer,
                passport_client_id=client_id,
                passport_private_key=keys["private_key"],
                passport_key_id=keys["key_id"],
                passport_enrollment=request,
            )
            replace_private_text_locked(self.path, json.dumps(current, indent=1))
        return request

    def confirm(self, reviewed: dict[str, str], approved: list[str]) -> str:
        with exclusive_file_lock(self.path):
            original = read_site_config(self.site.path)
            if not original.get("passport_enrollment") or not original.get("passport_disabled"):
                raise BenchError("Prepare this site's Passport enrollment first.")
        result = run_command(
            self.site._frappe_call(
                "frappe",
                "--site",
                self.site.config.name,
                "execute",
                "passport_client.enrollment.confirm",
                "--kwargs",
                repr({"reviewed": reviewed, "approved": approved}),
            ),
            cwd=self.site.bench.sites_path,
            timeout=45,
        )
        approval = json.loads(result.stdout)
        with exclusive_file_lock(self.path):
            current = read_site_config(self.site.path)
            if current != original or approval["request"] != current["passport_enrollment"]:
                raise BenchError("Site configuration changed during approval. Passport remains suspended.")
            current.update(passport_installation=approval["installation"], passport_disabled=False)
            current.pop("passport_enrollment")
            replace_private_text_locked(self.path, json.dumps(current, indent=1))
        return approval["installation"]

    def review(self) -> dict:
        result = run_command(
            self.site._frappe_call(
                "frappe", "--site", self.site.config.name, "execute", "passport_client.enrollment.review"
            ),
            cwd=self.site.bench.sites_path,
            timeout=30,
        )
        return json.loads(result.stdout)
