from src.observability.pii_redaction import (
    PIIType,
    detect_pii,
)


class TestDetectPII:
    def test_detect_nric(self):
        text = "Customer: John Doe, NRIC: S1234567A"
        matches = detect_pii(text)
        nric_matches = [m for m in matches if m.pii_type == PIIType.NRIC]
        assert len(nric_matches) == 1
        assert nric_matches[0].original == "S1234567A"

    def test_detect_multiple_nric_formats(self):
        text = "S1234567A G9876543Z T0123456B F7654321X M1111111A"
        matches = detect_pii(text)
        nric_matches = [m for m in matches if m.pii_type == PIIType.NRIC]
        assert len(nric_matches) == 5

    def test_detect_email(self):
        text = "Contact: user@example.com for support"
        matches = detect_pii(text)
        email_matches = [m for m in matches if m.pii_type == PIIType.EMAIL]
        assert len(email_matches) == 1
        assert email_matches[0].original == "user@example.com"

    def test_detect_phone_with_country_code(self):
        text = "Call +65 91234567 or 65 81234567"
        matches = detect_pii(text)
        phone_matches = [m for m in matches if m.pii_type == PIIType.PHONE]
        assert len(phone_matches) >= 1

    def test_detect_phone_local(self):
        text = "Mobile: 91234567"
        matches = detect_pii(text)
        phone_matches = [m for m in matches if m.pii_type == PIIType.PHONE]
        assert len(phone_matches) == 1

    def test_detect_postal_code(self):
        text = "Address: 123 Main St, Singapore 518000"
        matches = detect_pii(text)
        postal_matches = [m for m in matches if m.pii_type == PIIType.POSTAL_CODE]
        assert len(postal_matches) == 1
        assert postal_matches[0].original == "518000"

    def test_detect_bank_account(self):
        text = "Account: 1234567890"
        matches = detect_pii(text)
        account_matches = [m for m in matches if m.pii_type == PIIType.BANK_ACCOUNT]
        assert len(account_matches) == 1

    def test_skip_date_like_numbers(self):
        text = "Date: 20250115"
        matches = detect_pii(text)
        account_matches = [m for m in matches if m.pii_type == PIIType.BANK_ACCOUNT]
        assert len(account_matches) == 0

    def test_no_pii_in_clean_text(self):
        text = "Transaction: SALARY DEPOSIT 5000.00 SGD"
        matches = detect_pii(text)
        sensitive_matches = [m for m in matches if m.pii_type in (PIIType.NRIC, PIIType.EMAIL)]
        assert len(sensitive_matches) == 0

    def test_empty_text_has_no_pii(self):
        assert detect_pii("") == []
