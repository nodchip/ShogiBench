import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from OpenBench.models import (
    Book, Engine, LogEvent, Machine, Network, PGN, Profile, Result,
    RuleProfile, Test,
)
from OpenBench.rule_profiles import (
    CANONICAL_PROFILE_ID, CANONICAL_SEMANTICS_SHA256,
)


class Command(BaseCommand):
    help = "Audit the typed fresh-server state without emitting identities or secrets."

    def add_arguments(self, parser):
        parser.add_argument("phase", choices=("zero", "bootstrap", "acceptance"))

    def handle(self, *args, **options):
        phase = options["phase"]
        counts = {
            "users": User.objects.count(),
            "profiles": Profile.objects.count(),
            "tests": Test.objects.count(),
            "results": Result.objects.count(),
            "machines": Machine.objects.count(),
            "engines": Engine.objects.count(),
            "networks": Network.objects.count(),
            "books": Book.objects.count(),
            "pgn_records": PGN.objects.count(),
            "log_events": LogEvent.objects.count(),
            "rule_profiles": RuleProfile.objects.count(),
        }
        media_root = Path(settings.MEDIA_ROOT)
        media_file_count = 0
        if media_root.exists():
            if media_root.is_symlink() or not media_root.is_dir():
                return self._reject(phase, "media_root_invalid", counts, 0)
            media_file_count = sum(
                1 for path in media_root.rglob("*") if path.is_file() or path.is_symlink()
            )

        error = self._validate(phase, counts, media_file_count)
        if error:
            return self._reject(phase, error, counts, media_file_count)
        return json.dumps({
            "schema_version": 1,
            "profile_id": "shogibench-fresh-audit-v1",
            "phase": phase,
            "counts": counts,
            "media_file_count": media_file_count,
            "canonical_profile_exact": phase == "zero" or self._canonical_exact(),
            "autotune_identity_bounded": phase == "zero" or self._autotune_bounded(),
            "private_engine_count": 0,
            "confidential_values_emitted": False,
            "status": "passed",
        }, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _canonical_exact():
        try:
            profile = RuleProfile.objects.get(pk=CANONICAL_PROFILE_ID)
        except RuleProfile.DoesNotExist:
            return False
        return profile.semantics_sha256 == CANONICAL_SEMANTICS_SHA256

    @staticmethod
    def _autotune_bounded():
        username = getattr(settings, "AUTOTUNE_USERNAME", "")
        try:
            profile = Profile.objects.select_related("user").get(user__username=username)
        except Profile.DoesNotExist:
            return False
        return not profile.approver and not profile.user.has_usable_password()

    def _validate(self, phase, counts, media_file_count):
        if phase == "zero":
            if any(counts.values()) or media_file_count:
                return "legacy_or_existing_state_present"
            return None
        required = {
            "users": 3,
            "profiles": 3,
            "engines": 1,
            "networks": 1,
            "rule_profiles": 1,
        }
        if any(counts[name] != value for name, value in required.items()):
            return "minimal_seed_count_mismatch"
        if counts["books"] < 1 or media_file_count < counts["books"] + counts["networks"]:
            return "seed_material_count_mismatch"
        if not self._canonical_exact():
            return "canonical_profile_mismatch"
        if not self._autotune_bounded():
            return "autotune_identity_unbounded"
        if phase == "bootstrap":
            for name in ("tests", "results", "machines", "pgn_records", "log_events"):
                if counts[name] != 0:
                    return "post_bootstrap_runtime_state_present"
        return None

    def _reject(self, phase, error, counts, media_file_count):
        self.stdout.write(json.dumps({
            "schema_version": 1,
            "profile_id": "shogibench-fresh-audit-v1",
            "phase": phase,
            "counts": counts,
            "media_file_count": media_file_count,
            "confidential_values_emitted": False,
            "status": "rejected",
            "error": error,
        }, sort_keys=True, separators=(",", ":")))
        raise CommandError("fresh server audit rejected")
