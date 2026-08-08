import hashlib
import json
import re

from django.core.exceptions import ValidationError


CANONICAL_PROFILE_ID = 'canonical-yaneuraou-csarule24-v1'
CANONICAL_ENGINE_OPTION = 'option.EnteringKingRule=CSARule24'
SHA40 = re.compile(r'^[0-9a-f]{40}$')
SHA64 = re.compile(r'^[0-9a-f]{64}$')


def semantics_sha256(semantics):
    try:
        encoded = json.dumps(
            semantics,
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
            allow_nan=False,
        ).encode('utf-8')
    except (TypeError, ValueError):
        raise ValidationError('rule profile semantics must be canonical JSON') from None
    return hashlib.sha256(encoded).hexdigest()


def validate_rule_profile(profile):
    if not profile.profile_id or len(profile.profile_id) > 128:
        raise ValidationError('rule profile ID is invalid')
    if not SHA40.fullmatch(profile.source_revision or ''):
        raise ValidationError('rule profile source revision is invalid')
    if not SHA64.fullmatch(profile.semantics_sha256 or ''):
        raise ValidationError('rule profile semantics hash is invalid')
    if semantics_sha256(profile.semantics) != profile.semantics_sha256:
        raise ValidationError('rule profile semantics hash does not match')


def options_select_canonical_rule(options):
    if not isinstance(options, str):
        return False
    tokens = options.split()
    entering_king = [
        token for token in tokens
        if token.startswith('option.EnteringKingRule=')
    ]
    return entering_king == [CANONICAL_ENGINE_OPTION]
