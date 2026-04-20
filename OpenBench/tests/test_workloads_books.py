from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from OpenBench.config import OPENBENCH_CONFIG
from OpenBench.models import Book, Engine, Profile, Test
from OpenBench.workloads.create_workload import create_new_test
from OpenBench.workloads.verify_workload import verify_test_creation


class WorkloadBookFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="secret")
        Profile.objects.create(user=self.user, enabled=True, approver=True, repos={})
        self.client.force_login(self.user)
        Book.objects.create(sha256="ABCDEF12", name="dev-book.db", engine="tanuki-", author="tester")
        Book.objects.create(sha256="12345678", name="base-book.db", engine="tanuki-", author="tester")

    def test_create_test_page_shows_dev_and_base_book_selectors(self):
        response = self.client.get("/test/new/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="dev_book"')
        self.assertContains(response, 'id="base_book"')
        self.assertContains(response, "dev-book.db")
        self.assertContains(response, "base-book.db")


class WorkloadBookValidationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        Book.objects.create(sha256="ABCDEF12", name="dev-book.db", engine="tanuki-", author="tester")
        self.opening_book = next(iter(OPENBENCH_CONFIG["books"].keys()))

    def test_verify_test_creation_rejects_unknown_dev_book(self):
        request = self.factory.post(
            "/test/new/",
            {
                "dev_engine": "tanuki-",
                "dev_repo": "https://github.com/example/dev",
                "dev_network": "",
                "dev_options": "Threads=1 Hash=16",
                "dev_time_control": "8.0+0.08",
                "dev_book": "DEADBEEF",
                "base_engine": "tanuki-",
                "base_repo": "https://github.com/example/base",
                "base_network": "",
                "base_options": "Threads=1 Hash=16",
                "base_time_control": "8.0+0.08",
                "base_book": "",
                "book_name": self.opening_book,
                "upload_pgns": "FALSE",
                "test_mode": "GAMES",
                "test_bounds": "[0.00, 1.00]",
                "test_confidence": "[0.10, 0.05]",
                "test_max_games": "2",
                "priority": "0",
                "throughput": "1",
                "syzygy_wdl": "DISABLED",
                "workload_size": "1",
                "scale_method": "BASE",
                "scale_nps": "1",
                "syzygy_adj": "DISABLED",
                "win_adj": "None",
                "draw_adj": "None",
            },
        )

        errors = []
        verify_test_creation(errors, request)

        self.assertIn("Unknown Book Provided for Dev Book", errors)


class WorkloadBookPersistenceTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="tester", password="secret")
        Profile.objects.create(user=self.user, enabled=True, approver=True, repos={})
        self.dev_book = Book.objects.create(sha256="ABCDEF12", name="dev-book.db", engine="tanuki-", author="tester")
        self.base_book = Book.objects.create(sha256="12345678", name="base-book.db", engine="tanuki-", author="tester")
        self.opening_book = next(iter(OPENBENCH_CONFIG["books"].keys()))

    def test_create_new_test_persists_dev_and_base_book_metadata(self):
        request = self.factory.post(
            "/test/new/",
            {
                "book_name": self.opening_book,
                "upload_pgns": "FALSE",
                "dev_repo": "https://github.com/example/dev",
                "dev_engine": "tanuki-",
                "dev_options": "Threads=1 Hash=16",
                "dev_network": "",
                "dev_time_control": "8.0+0.08",
                "dev_book": self.dev_book.sha256,
                "base_repo": "https://github.com/example/base",
                "base_engine": "tanuki-",
                "base_options": "Threads=1 Hash=16",
                "base_network": "",
                "base_time_control": "8.0+0.08",
                "base_book": self.base_book.sha256,
                "workload_size": "2",
                "priority": "0",
                "throughput": "1000",
                "syzygy_wdl": "DISABLED",
                "syzygy_adj": "DISABLED",
                "win_adj": "None",
                "draw_adj": "None",
                "scale_method": "BASE",
                "scale_nps": "1000",
                "test_mode": "GAMES",
                "test_max_games": "2",
                "test_bounds": "[0.00, 1.00]",
                "test_confidence": "[0.10, 0.05]",
            },
        )
        request.user = self.user

        dev_info = ("https://github.com/example/dev/archive/dev.zip", "dev", "a" * 40, 111)
        base_info = ("https://github.com/example/base/archive/base.zip", "base", "b" * 40, 222)

        with patch("OpenBench.workloads.create_workload.verify_workload", return_value=([], ((dev_info, True), (base_info, True)))):
            test, errors = create_new_test(request)

        self.assertIsNone(errors)
        self.assertIsInstance(test, Test)
        self.assertEqual(test.dev_book_sha, self.dev_book.sha256)
        self.assertEqual(test.dev_book_name, self.dev_book.name)
        self.assertEqual(test.base_book_sha, self.base_book.sha256)
        self.assertEqual(test.base_book_name, self.base_book.name)


class WorkloadBookPresentationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="secret")
        Profile.objects.create(user=self.user, enabled=True, approver=True, repos={})
        self.client.force_login(self.user)
        self.dev_engine = Engine.objects.create(
            name="dev",
            source="https://github.com/example/dev/archive/dev.zip",
            sha="a" * 40,
            bench=111,
        )
        self.base_engine = Engine.objects.create(
            name="base",
            source="https://github.com/example/base/archive/base.zip",
            sha="b" * 40,
            bench=222,
        )

    def create_workload(self, test_mode):
        return Test.objects.create(
            author="tester",
            upload_pgns="FALSE",
            book_name=next(iter(OPENBENCH_CONFIG["books"].keys())),
            dev=self.dev_engine,
            dev_repo="https://github.com/example/dev",
            dev_engine="tanuki-",
            dev_options="Threads=1 Hash=16",
            dev_network="",
            dev_time_control="8.0+0.08",
            dev_book_sha="ABCDEF12",
            dev_book_name="dev-book.db",
            base=self.base_engine,
            base_repo="https://github.com/example/base",
            base_engine="tanuki-",
            base_options="Threads=1 Hash=16",
            base_network="",
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
            test_mode=test_mode,
            max_games=2,
        )

    def test_test_detail_page_shows_dev_and_base_books(self):
        test = self.create_workload("GAMES")

        response = self.client.get(f"/test/{test.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dev Book")
        self.assertContains(response, "dev-book.db")
        self.assertContains(response, "Base Book")
        self.assertContains(response, "base-book.db")

    def test_datagen_detail_page_shows_dev_and_base_books(self):
        test = self.create_workload("DATAGEN")

        response = self.client.get(f"/datagen/{test.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dev Book")
        self.assertContains(response, "dev-book.db")
        self.assertContains(response, "Base Book")
        self.assertContains(response, "base-book.db")

    def test_test_detail_page_shows_none_when_books_are_unset(self):
        test = self.create_workload("GAMES")
        test.dev_book_sha = ""
        test.dev_book_name = ""
        test.base_book_sha = ""
        test.base_book_name = ""
        test.save(update_fields=["dev_book_sha", "dev_book_name", "base_book_sha", "base_book_name"])

        response = self.client.get(f"/test/{test.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<tr><td class=\"td-label\">Dev Book</td><td>None</td></tr>", html=True)
        self.assertContains(response, "<tr><td class=\"td-label\">Base Book</td><td>None</td></tr>", html=True)
