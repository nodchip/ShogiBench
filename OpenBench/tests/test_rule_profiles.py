from django.core.exceptions import ValidationError
from django.test import TestCase

from OpenBench.models import RuleProfile
from OpenBench.rule_profiles import canonical_profile_fields


class RuleProfileTests(TestCase):

    def _profile(self):
        return RuleProfile.objects.create(**canonical_profile_fields())

    def test_profile_is_immutable(self):
        profile = self._profile()
        profile.semantics = {'declaration_points': 30}

        with self.assertRaisesMessage(ValidationError, 'rule profiles are immutable'):
            profile.save()

    def test_profile_id_is_immutable(self):
        profile = self._profile()
        profile.profile_id = 'replacement-profile'

        with self.assertRaisesMessage(ValidationError, 'rule profiles are immutable'):
            profile.save()

    def test_semantics_hash_must_match(self):
        with self.assertRaisesMessage(ValidationError, 'semantics hash does not match'):
            fields = canonical_profile_fields()
            fields['semantics_sha256'] = 'a' * 64
            RuleProfile.objects.create(
                **fields,
            )

    def test_canonical_profile_must_match_exact_authority(self):
        fields = canonical_profile_fields()
        fields['source_repository'] = fields['source_repository'].removesuffix('.git')

        with self.assertRaisesMessage(ValidationError, 'does not match authority'):
            RuleProfile.objects.create(**fields)
