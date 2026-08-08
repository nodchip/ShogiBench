import copy
import hashlib
import json
import re

from django.core.exceptions import ValidationError


CANONICAL_PROFILE_ID = 'canonical-yaneuraou-csarule24-v1'
CANONICAL_ENGINE_OPTION = 'option.EnteringKingRule=CSARule24'
CANONICAL_AUTHORITY_KIND = 'canonical-yaneuraou-source'
CANONICAL_SOURCE_REPOSITORY = 'https://github.com/yaneurao/YaneuraOu.git'
CANONICAL_SOURCE_REVISION = '33ccf1f907eb7184889fa23051243f81ab0bf973'
CANONICAL_SEMANTICS = {
    'counted_piece_locations': ['enemy_camp', 'hand'],
    'declaration_points': {'gote': 31, 'sente': 31},
    'declaration_result': 'win',
    'declarer_must_not_be_in_check': True,
    'king_must_be_in_enemy_camp': True,
    'min_non_king_pieces_in_enemy_camp': 10,
    'piece_points': {'bishop': 5, 'other_non_king': 1, 'rook': 5},
}
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


CANONICAL_SEMANTICS_SHA256 = semantics_sha256(CANONICAL_SEMANTICS)


def canonical_profile_fields():
    return {
        'profile_id': CANONICAL_PROFILE_ID,
        'authority_kind': CANONICAL_AUTHORITY_KIND,
        'source_repository': CANONICAL_SOURCE_REPOSITORY,
        'source_revision': CANONICAL_SOURCE_REVISION,
        'semantics_sha256': CANONICAL_SEMANTICS_SHA256,
        'semantics': copy.deepcopy(CANONICAL_SEMANTICS),
    }


def validate_rule_profile(profile):
    if not profile.profile_id or len(profile.profile_id) > 128:
        raise ValidationError('rule profile ID is invalid')
    if not SHA40.fullmatch(profile.source_revision or ''):
        raise ValidationError('rule profile source revision is invalid')
    if not SHA64.fullmatch(profile.semantics_sha256 or ''):
        raise ValidationError('rule profile semantics hash is invalid')
    if semantics_sha256(profile.semantics) != profile.semantics_sha256:
        raise ValidationError('rule profile semantics hash does not match')
    if profile.profile_id == CANONICAL_PROFILE_ID:
        expected = canonical_profile_fields()
        if any(getattr(profile, name) != value for name, value in expected.items()):
            raise ValidationError('canonical rule profile does not match authority')


def options_select_canonical_rule(options):
    if not isinstance(options, str):
        return False
    tokens = options.split()
    entering_king = [
        token for token in tokens
        if token.startswith('option.EnteringKingRule=')
    ]
    return entering_king == [CANONICAL_ENGINE_OPTION]
