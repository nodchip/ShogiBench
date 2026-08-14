from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from OpenBench.config import OPENBENCH_CONFIG
from OpenBench.models import Book, Engine, Machine, Profile, Result, RuleProfile, Test
from OpenBench.rule_profiles import canonical_profile_fields
from OpenBench.workloads.get_workload import workload_to_dictionary


class WorkloadPayloadBookTests(TestCase):
    def test_workload_payload_includes_dev_and_base_book_metadata(self):
        user = User.objects.create_user(username="tester", password="secret")
        Profile.objects.create(user=user, enabled=True, approver=True, repos={})

        dev = Engine.objects.create(
            name="dev",
            source="https://github.com/example/dev/archive/dev.zip",
            sha="a" * 40,
            bench=111,
        )
        base = Engine.objects.create(
            name="base",
            source="https://github.com/example/base/archive/base.zip",
            sha="b" * 40,
            bench=222,
        )

        Book.objects.create(sha256="ABCDEF12", name="dev-book.db", engine="tanuki-", author="tester")
        Book.objects.create(sha256="12345678", name="base-book.db", engine="tanuki-", author="tester")

        opening_book = next(iter(OPENBENCH_CONFIG["books"].keys()))
        rule_profile = RuleProfile.objects.create(**canonical_profile_fields())
        test = Test.objects.create(
            author="tester",
            book_name=opening_book,
            upload_pgns="FALSE",
            rule_profile=rule_profile,
            dev=dev,
            dev_repo="https://github.com/example/dev",
            dev_engine="tanuki-",
            dev_options="Threads=1 Hash=16",
            dev_network="ABCDEF12",
            dev_time_control="8.0+0.08",
            dev_book_sha="ABCDEF12",
            dev_book_name="dev-book.db",
            base=base,
            base_repo="https://github.com/example/base",
            base_engine="tanuki-",
            base_options="Threads=1 Hash=16",
            base_network="12345678",
            base_time_control="8.0+0.08",
            base_book_sha="12345678",
            base_book_name="base-book.db",
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
        machine = Machine.objects.create(
            user=user,
            info={
                "concurrency": 1,
                "physical_cores": 1,
                "sockets": 1,
            },
        )
        result = Result.objects.create(test=test, machine=machine)

        workload = workload_to_dictionary(test, result, machine)

        self.assertEqual(workload["test"]["dev"]["book"], "ABCDEF12")
        self.assertEqual(workload["test"]["dev"]["book_name"], "dev-book.db")
        self.assertEqual(workload["test"]["base"]["book"], "12345678")
        self.assertEqual(workload["test"]["base"]["book_name"], "base-book.db")
        self.assertEqual(workload["test"]["dev"]["bench"], 0)
        self.assertEqual(workload["test"]["base"]["bench"], 0)
        self.assertEqual(
            workload["test"]["rule_profile_id"],
            "canonical-yaneuraou-csarule24-v1",
        )
        self.assertEqual(
            workload["test"]["rule_profile_semantics_sha256"],
            "be4a1cff6b5bf416f89f9ed17bc70676f9272bf32fd27dd373b8fb4d8d997a93",
        )

        test.workload_size = 1
        test.max_games = 2
        test.save(update_fields=("workload_size", "max_games"))
        machine.info = {"concurrency": 64, "physical_cores": 64, "sockets": 1}
        machine.save(update_fields=("info",))
        acceptance = workload_to_dictionary(test, result, machine)
        self.assertEqual(acceptance["distribution"], {
            "runner-count": 1,
            "concurrency-per": 1,
            "games-per-runner": 2,
        })

        test.test_mode = "SPRT"
        test.workload_size = 32
        test.max_games = 131072
        test.games = 131040
        test.save(update_fields=("test_mode", "workload_size", "max_games", "games"))
        capped = workload_to_dictionary(test, result, machine)
        self.assertEqual(capped["distribution"], {
            "runner-count": 1,
            "concurrency-per": 16,
            "games-per-runner": 32,
        })
