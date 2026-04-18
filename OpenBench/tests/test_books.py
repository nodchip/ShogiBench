import hashlib

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest.mock import patch

from OpenBench import model_utils
from OpenBench.models import Book, Engine, Network, Profile, Test
from django.contrib.auth.models import User


class BookModelTests(TestCase):
    def test_book_string_contains_name_and_engine(self):
        book = Book.objects.create(
            sha256="ABCDEF12",
            name="startpos-large.db",
            engine="tanuki-",
            author="tester",
        )

        self.assertIn("startpos-large.db", str(book))
        self.assertIn("tanuki-", str(book))


class BookModelUtilsTests(TestCase):
    def test_book_to_dict_returns_fields_and_created_as_string(self):
        book = Book.objects.create(
            sha256="ABCDEF12",
            name="startpos-large.db",
            engine="tanuki-",
            author="tester",
        )

        self.assertEqual(
            model_utils.book_to_dict(book),
            {
                "sha256": "ABCDEF12",
                "name": "startpos-large.db",
                "engine": "tanuki-",
                "author": "tester",
                "created": str(book.created),
            },
        )

    def test_book_delete_removes_row_without_deleting_shared_file(self):
        first = Book.objects.create(
            sha256="ABCDEF12",
            name="startpos-large.db",
            engine="tanuki-",
            author="tester",
        )
        Book.objects.create(
            sha256="ABCDEF12",
            name="startpos-small.db",
            engine="tanuki-",
            author="tester",
        )

        with patch("OpenBench.model_utils.FileSystemStorage.delete") as delete_mock:
            message, success = model_utils.book_delete(first)

        self.assertEqual(message, "Deleted startpos-large.db for tanuki-")
        self.assertTrue(success)
        self.assertFalse(Book.objects.filter(pk=first.pk).exists())
        self.assertTrue(Book.objects.filter(sha256="ABCDEF12").exists())
        delete_mock.assert_not_called()

    def test_book_delete_removes_file_when_no_other_rows_share_sha(self):
        book = Book.objects.create(
            sha256="12345678",
            name="startpos-large.db",
            engine="tanuki-",
            author="tester",
        )

        with patch("OpenBench.model_utils.FileSystemStorage.delete") as delete_mock:
            message, success = model_utils.book_delete(book)

        self.assertEqual(message, "Deleted startpos-large.db for tanuki-")
        self.assertTrue(success)
        self.assertFalse(Book.objects.filter(pk=book.pk).exists())
        delete_mock.assert_called_once_with("12345678")

    def test_book_delete_keeps_file_when_network_shares_sha(self):
        book = Book.objects.create(
            sha256="A1B2C3D4",
            name="startpos-large.db",
            engine="tanuki-",
            author="tester",
        )
        Network.objects.create(
            sha256="A1B2C3D4",
            name="shared-network.nnue",
            engine="tanuki-",
            author="tester",
        )

        with patch("OpenBench.model_utils.FileSystemStorage.delete") as delete_mock:
            message, success = model_utils.book_delete(book)

        self.assertEqual(message, "Deleted startpos-large.db for tanuki-")
        self.assertTrue(success)
        self.assertFalse(Book.objects.filter(pk=book.pk).exists())
        delete_mock.assert_not_called()

    def test_network_delete_keeps_file_when_book_shares_sha(self):
        book = Book.objects.create(
            sha256="D4C3B2A1",
            name="startpos-large.db",
            engine="tanuki-",
            author="tester",
        )
        network = Network.objects.create(
            sha256="D4C3B2A1",
            name="shared-network.nnue",
            engine="tanuki-",
            author="tester",
        )

        with patch("OpenBench.model_utils.FileSystemStorage.delete") as delete_mock:
            message, success = model_utils.network_delete(network)

        self.assertEqual(message, "Deleted shared-network.nnue for tanuki-")
        self.assertTrue(success)
        self.assertFalse(Network.objects.filter(pk=network.pk).exists())
        self.assertTrue(Book.objects.filter(pk=book.pk).exists())
        delete_mock.assert_not_called()


class TestBookMetadataTests(TestCase):
    def test_test_stores_dev_and_base_book_metadata(self):
        dev = Engine.objects.create(name="dev", source="src", sha="devsha", bench=1)
        base = Engine.objects.create(name="base", source="src", sha="basesha", bench=2)

        test = Test.objects.create(
            author="tester",
            upload_pgns="FALSE",
            book_name="startpos-only.epd",
            book_index=1,
            dev=dev,
            dev_repo="repo",
            dev_engine="dev",
            dev_options="",
            dev_network="",
            dev_netname="",
            dev_time_control="10+0.1",
            base=base,
            base_repo="repo",
            base_engine="base",
            base_options="",
            base_network="",
            base_netname="",
            base_time_control="10+0.1",
            dev_book_sha="ABCDEF12",
            dev_book_name="dev-book.db",
            base_book_sha="12345678",
            base_book_name="base-book.db",
        )

        test.refresh_from_db()

        self.assertEqual(test.dev_book_sha, "ABCDEF12")
        self.assertEqual(test.dev_book_name, "dev-book.db")
        self.assertEqual(test.base_book_sha, "12345678")
        self.assertEqual(test.base_book_name, "base-book.db")


class BookViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="approver",
            email="approver@example.com",
            password="password",
        )
        Profile.objects.create(user=self.user, enabled=True, approver=True)
        self.client.force_login(self.user)

    def test_book_upload_creates_book_row(self):
        upload = SimpleUploadedFile("startpos-large.db", b"book-bytes")

        response = self.client.post(
            "/books/tanuki-/upload/startpos-large.db/",
            data={"bookfile": upload},
        )

        self.assertEqual(response.status_code, 302)
        book = Book.objects.get(engine="tanuki-", name="startpos-large.db")
        self.assertEqual(book.author, "approver")
        self.assertEqual(book.sha256, hashlib.sha256(b"book-bytes").hexdigest()[:8].upper())

    def test_book_delete_post_removes_book_row(self):
        book = Book.objects.create(
            sha256="ABCDEF12",
            name="startpos-large.db",
            engine="tanuki-",
            author="approver",
        )

        with patch("OpenBench.model_utils.FileSystemStorage.delete") as delete_mock:
            response = self.client.post("/books/tanuki-/DELETE/ABCDEF12/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/books/tanuki-")
        self.assertFalse(Book.objects.filter(pk=book.pk).exists())
        delete_mock.assert_called_once_with("ABCDEF12")

    def test_book_delete_get_does_not_delete_book_row(self):
        book = Book.objects.create(
            sha256="ABCDEF12",
            name="startpos-large.db",
            engine="tanuki-",
            author="approver",
        )

        response = self.client.get("/books/tanuki-/DELETE/ABCDEF12/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/books/tanuki-")
        self.assertTrue(Book.objects.filter(pk=book.pk).exists())

    def test_book_delete_redirects_cleanly_without_profile_row(self):
        user = User.objects.create_user(
            username="ghost",
            email="ghost@example.com",
            password="password",
        )
        self.client.force_login(user)
        Book.objects.create(
            sha256="ABCDEF12",
            name="startpos-large.db",
            engine="tanuki-",
            author="approver",
        )

        response = self.client.post("/books/tanuki-/DELETE/ABCDEF12/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/index/")

    def test_book_download_missing_file_redirects_with_error(self):
        Book.objects.create(
            sha256="ABCDEF12",
            name="startpos-large.db",
            engine="tanuki-",
            author="approver",
        )

        response = self.client.get("/books/tanuki-/DOWNLOAD/ABCDEF12/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/books/tanuki-")
        self.assertEqual(
            self.client.session.get("error_message"),
            "Book file is missing from disk",
        )

    def test_book_page_delete_control_uses_post_form_and_csrf(self):
        Book.objects.create(
            sha256="ABCDEF12",
            name="startpos-large.db",
            engine="tanuki-",
            author="approver",
        )

        response = self.client.get("/books/")
        content = response.content.decode()

        self.assertIn('action="/books/tanuki-/DELETE/ABCDEF12/"', content)
        self.assertIn('method="POST"', content)
        self.assertIn("csrfmiddlewaretoken", content)

    def test_new_book_post_fallback_uploads_book_without_js(self):
        upload = SimpleUploadedFile("startpos-large.db", b"book-bytes")

        response = self.client.post(
            "/newBook/",
            data={
                "name": "startpos-large.db",
                "engine": "tanuki-",
                "bookfile": upload,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/books/tanuki-/")
        self.assertTrue(Book.objects.filter(engine="tanuki-", name="startpos-large.db").exists())

    def test_book_upload_without_file_redirects_with_error(self):
        response = self.client.post(
            "/books/tanuki-/upload/startpos-large.db/",
            data={},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/books/")
        self.assertEqual(
            self.client.session.get("error_message"),
            "Please select a book file to upload",
        )

    def test_book_form_redirects_cleanly_without_profile_row(self):
        user = User.objects.create_user(
            username="ghost",
            email="ghost@example.com",
            password="password",
        )
        self.client.force_login(user)

        response = self.client.get("/newBook/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/index/")

    def test_book_api_download_returns_uploaded_blob(self):
        upload = SimpleUploadedFile("startpos-large.db", b"book-bytes")

        self.client.post(
            "/books/tanuki-/upload/startpos-large.db/",
            data={"bookfile": upload},
        )

        response = self.client.get(
            f"/api/books/tanuki-/{hashlib.sha256(b'book-bytes').hexdigest()[:8].upper()}/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"book-bytes")
