from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, ClassVar

from pilot.commands import Arg, Command
from pilot.exceptions import BenchError


@dataclass(kw_only=True)
class PreparePassportCommand(Command):
    name: ClassVar[str] = "passport-prepare"
    help: ClassVar[str] = "Prepare a public Passport enrollment request and suspend Passport login."

    site_name: Annotated[str, Arg(metavar="site", help="Site to enroll.")]
    issuer: Annotated[str, Arg(help="Passport issuer origin.")]
    client_id: Annotated[str, Arg(help="Unique client ID approved by the issuer administrator.")]

    def run(self) -> None:
        request = self.bench.site(self.site_name).prepare_passport_enrollment(self.issuer, self.client_id)
        self.report(json.dumps(request, indent=2))


@dataclass(kw_only=True)
class ReviewPassportCommand(Command):
    name: ClassVar[str] = "passport-review"
    help: ClassVar[str] = "Export identity associations for local admission review."

    site_name: Annotated[str, Arg(metavar="site", help="Site to review.")]

    def run(self) -> None:
        self.report(json.dumps(self.bench.site(self.site_name).review_passport_enrollment(), indent=2))


@dataclass(kw_only=True)
class ConfirmPassportCommand(Command):
    name: ClassVar[str] = "passport-confirm"
    help: ClassVar[str] = "Verify administrator approval and activate reviewed site admission."

    site_name: Annotated[str, Arg(metavar="site", help="Site to activate.")]
    review_file: Annotated[Path, Arg(help="JSON review file containing reviewed and approved associations.")]

    def run(self) -> None:
        try:
            review = json.loads(self.review_file.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise BenchError(
                "Cannot read the admission review. Export and edit a UTF-8 JSON review file."
            ) from error
        if (
            not isinstance(review, dict)
            or not isinstance(review.get("reviewed"), dict)
            or not isinstance(review.get("approved"), list)
        ):
            raise BenchError("The review must contain a reviewed mapping and an approved list.")
        installation = self.bench.site(self.site_name).confirm_passport_enrollment(
            review["reviewed"], review["approved"]
        )
        self.report(f"Passport enrollment active: {installation}")


@dataclass(kw_only=True)
class SuspendPassportCommand(Command):
    name: ClassVar[str] = "passport-suspend"
    help: ClassVar[str] = "Suspend Passport and invalidate any pending enrollment before ownership transfer."

    site_name: Annotated[str, Arg(metavar="site", help="Site to suspend.")]

    def run(self) -> None:
        self.bench.site(self.site_name).suspend_passport()
        self.report("Passport suspended. Prepare and approve a fresh enrollment before enabling it.")
