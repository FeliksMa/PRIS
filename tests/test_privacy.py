import io
import unittest
import urllib.error
from unittest.mock import patch

from pris.cloud import cloud_request
from pris.http import HttpError, _NoCredentialRedirect, _safe_url, request
from pris.privacy import public_paper_url, research_export


class PrivacyTests(unittest.TestCase):
    def test_export_blocks_credentials_without_echoing_them(self):
        with self.assertRaises(ValueError) as err:
            research_export({"content": "accidental test-private-key"}, ["test-private-key"])
        self.assertNotIn("test-private-key", str(err.exception))

    def test_export_blocks_secret_fields_but_preserves_usage_and_keywords(self):
        with self.assertRaises(ValueError):
            research_export({"DEEPSEEK_API_KEY": "value"}, [])
        value = {"input_tokens": 50, "keywords": ["uncertainty"]}
        self.assertEqual(research_export(value, []), value)

    def test_export_hides_local_paths_without_editing_original(self):
        value = {"content": "[PDF](file:///D:/Research/private.pdf)\n本地: C:\\Users\\Name\\paper.pdf"}
        result = research_export(value, [])
        self.assertNotIn("private.pdf", result["content"])
        self.assertNotIn("C:\\Users", result["content"])
        self.assertIn("private.pdf", value["content"])

    def test_only_public_paper_links_are_exported(self):
        for url in ["file:///D:/private.pdf", "https://user:password@example.com/paper", "https://example.com/?api_key=test"]:
            self.assertEqual(public_paper_url(url), "")
        self.assertEqual(public_paper_url("https://doi.org/10.1000/example"), "https://doi.org/10.1000/example")

    def test_safe_url_hides_account_and_query_credentials(self):
        url = _safe_url("https://user:pass@example.com/paper?password=private&signature=secret")
        self.assertNotIn("user:pass", url)
        self.assertNotIn("private", url)
        self.assertNotIn("secret", url)

    def test_authentication_requires_tls_and_cannot_redirect(self):
        with self.assertRaises(HttpError):
            request("http://example.com", headers={"Authorization": "Bearer test"})
        self.assertIsNone(_NoCredentialRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))

    def test_http_error_does_not_echo_response_body(self):
        err = urllib.error.HTTPError("https://example.com", 403, "", {}, io.BytesIO(b"echoed-secret private research"))
        with patch("urllib.request.OpenerDirector.open", side_effect=err):
            with self.assertRaises(HttpError) as caught:
                request("https://example.com", headers={"Authorization": "Bearer test"})
        self.assertNotIn("echoed-secret", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_cloud_credentials_cannot_be_sent_to_other_site(self):
        with patch.dict("os.environ", {"PRIS_CLOUD_URL": "https://other.chatgpt.site", "PRIS_SITE_ACCESS_TOKEN": "test", "PRIS_RUNNER_TOKEN": "test"}):
            with patch("pris.cloud.request") as send:
                with self.assertRaises(ValueError):
                    cloud_request()
                send.assert_not_called()
