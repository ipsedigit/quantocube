from pathlib import Path
import download_bills


def test_load_env_reads_key_value_pairs(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GMAIL_USER=me@gmail.com\nGMAIL_APP_PASSWORD=abcd efgh\n")
    result = download_bills.load_env(str(env_file))
    assert result["GMAIL_USER"] == "me@gmail.com"
    assert result["GMAIL_APP_PASSWORD"] == "abcd efgh"


def test_load_env_ignores_comments_and_blanks(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\n\nGMAIL_USER=x@y.com\n")
    result = download_bills.load_env(str(env_file))
    assert result == {"GMAIL_USER": "x@y.com"}


def test_load_env_missing_file_returns_empty():
    result = download_bills.load_env("/nonexistent/.env")
    assert result == {}
