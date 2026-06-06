from django.contrib.auth.models import User
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings

from OpenBench.config import OPENBENCH_CONFIG
from OpenBench.models import Engine, Machine, Profile, Result, Test
from OpenBench.utils import update_test


class CompletionEmailProfileTests(TestCase):
    def test_profile_page_shows_disabled_completion_email_setting_by_default(self):
        user = User.objects.create_user(username="tester", password="secret")
        Profile.objects.create(user=user, enabled=True, approver=True, repos={})
        self.client.force_login(user)

        response = self.client.get("/profile/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="completion-emails"')
        self.assertNotContains(response, 'name="completion-emails" checked')

    def test_profile_config_updates_completion_email_setting(self):
        user = User.objects.create_user(username="tester", password="secret")
        profile = Profile.objects.create(user=user, enabled=True, approver=True, repos={})
        self.client.force_login(user)

        response = self.client.post(
            "/profileConfig/",
            {
                "deleted-repos": "[]",
                "new-engine-name": "None",
                "new-engine-repo": "",
                "completion-emails": "on",
            },
        )

        self.assertRedirects(response, "/profile/")
        profile.refresh_from_db()
        self.assertTrue(profile.completion_emails)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CompletionEmailNotificationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.author = User.objects.create_user(
            username="author",
            email="author@example.com",
            password="secret",
        )
        Profile.objects.create(
            user=self.author,
            enabled=True,
            approver=True,
            repos={},
            completion_emails=True,
        )
        self.worker = User.objects.create_user(username="worker", password="secret")
        Profile.objects.create(user=self.worker, enabled=True, approver=True, repos={})
        self.dev = Engine.objects.create(
            name="dev",
            source="https://github.com/example/dev/archive/dev.zip",
            sha="a" * 40,
            bench=111,
        )
        self.base = Engine.objects.create(
            name="base",
            source="https://github.com/example/base/archive/base.zip",
            sha="b" * 40,
            bench=222,
        )
        self.machine = Machine.objects.create(
            user=self.worker,
            info={
                "concurrency": 1,
                "physical_cores": 1,
                "sockets": 1,
            },
        )
        self.test = Test.objects.create(
            author=self.author.username,
            book_name=next(iter(OPENBENCH_CONFIG["books"].keys())),
            upload_pgns="FALSE",
            dev=self.dev,
            dev_repo="https://github.com/example/dev",
            dev_engine="tanuki-",
            dev_options="Threads=1 Hash=16",
            dev_network="",
            dev_time_control="8.0+0.08",
            base=self.base,
            base_repo="https://github.com/example/base",
            base_engine="tanuki-",
            base_options="Threads=1 Hash=16",
            base_network="",
            base_time_control="8.0+0.08",
            workload_size=2,
            priority=0,
            throughput=1000,
            scale_method=Test.ScaleMethod.BASE,
            scale_nps=1000,
            syzygy_wdl="DISABLED",
            syzygy_adj="DISABLED",
            win_adj="None",
            draw_adj="None",
            test_mode="GAMES",
            max_games=2,
        )
        self.result = Result.objects.create(test=self.test, machine=self.machine)

    def post_update(self, trinomial):
        request = self.factory.post(
            "/clientSubmitResults/",
            {
                "crashes": "0",
                "timelosses": "0",
                "illegals": "0",
                "machine_id": str(self.machine.id),
                "result_id": str(self.result.id),
                "test_id": str(self.test.id),
                "trinomial": trinomial,
                "pentanomial": "0 0 0 0 0",
            },
        )
        return update_test(request, self.machine)

    def test_update_test_emails_author_when_test_completes(self):
        response = self.post_update("0 0 2")

        self.assertEqual(response, {"stop": True})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["author@example.com"])
        self.assertIn(f"Workload #{self.test.id}", mail.outbox[0].subject)

    def test_update_test_does_not_email_author_when_setting_is_disabled(self):
        Profile.objects.filter(user=self.author).update(completion_emails=False)

        self.post_update("0 0 2")

        self.assertEqual(mail.outbox, [])
