import unittest

from transcribe import is_quota_error


class TestIsQuotaError(unittest.TestCase):
    """A 429 can mean 'slow down' (retry helps) or 'you have no money' (retry
    never helps, and every future recording dies the same way). Only the second
    one is worth waking the owner for."""

    # Dosłowny tekst, który zatrzymał podsumowania na 9 dni (4–12.09.2026).
    REAL = (
        "Error code: 429 - {'error': {'message': 'You have no credits remaining. "
        "Add credits to continue using the API at "
        "https://platform.openai.com/settings/organization/billing/.', "
        "'type': 'insufficient_quota', 'param': None, "
        "'code': 'credit_balance_exhausted'}}"
    )

    def test_real_production_error_is_quota(self):
        self.assertTrue(is_quota_error(self.REAL))

    def test_each_marker_alone_is_enough(self):
        for raw in (
            "insufficient_quota",
            "credit_balance_exhausted",
            "You have no credits remaining.",
        ):
            self.assertTrue(is_quota_error(raw), raw)

    def test_case_insensitive(self):
        self.assertTrue(is_quota_error("INSUFFICIENT_QUOTA"))

    def test_transient_failures_are_not_quota(self):
        # Te da się przeżyć retry'em — nie wolno na nie wołać ownera.
        for raw in (
            "Error code: 429 - Rate limit reached for whisper-1 in organization org-x",
            "Connection error.",
            "Request timed out.",
            "Error code: 500 - The server had an error while processing your request",
            "Error code: 401 - Incorrect API key provided",
        ):
            self.assertFalse(is_quota_error(raw), raw)

    def test_empty_returns_false(self):
        for raw in ("", "   ", None):
            self.assertFalse(is_quota_error(raw), raw)


if __name__ == "__main__":
    unittest.main()
