import hashlib
import json

from django.core.exceptions import ValidationError
from django.test import TestCase

from OpenBench.models import RuleProfile


class RuleProfileTests(TestCase):

    def _profile(self):
        semantics = {'declaration_points': 31}
        digest = hashlib.sha256(json.dumps(
            semantics, sort_keys=True, separators=(',', ':'),
        ).encode()).hexdigest()
        return RuleProfile.objects.create(
            profile_id='canonical-yaneuraou-csarule24-v1',
            authority_kind='canonical-yaneuraou-source',
            source_repository='https://github.com/yaneurao/YaneuraOu',
            source_revision='33ccf1f907eb7184889fa23051243f81ab0bf973',
            semantics_sha256=digest,
            semantics=semantics,
        )

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
            RuleProfile.objects.create(
                profile_id='canonical-yaneuraou-csarule24-v1',
                authority_kind='canonical-yaneuraou-source',
                source_repository='https://github.com/yaneurao/YaneuraOu',
                source_revision='33ccf1f907eb7184889fa23051243f81ab0bf973',
                semantics_sha256='a' * 64,
                semantics={'declaration_points': 31},
            )
