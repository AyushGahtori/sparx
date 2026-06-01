from app.utils.email import is_valid_email, normalize_spoken_email


def test_normalize_spoken_email_with_words():
    assert normalize_spoken_email("ayush gahtori 24 at gmail dot com") == "ayushgahtori24@gmail.com"


def test_normalize_spelled_email():
    assert normalize_spoken_email("a y u s h 24 @ gmail.com") == "ayush24@gmail.com"


def test_invalid_email_is_rejected():
    assert not is_valid_email(normalize_spoken_email("not a real email"))
