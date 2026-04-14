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


from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from email.message import Message


def _make_email(attachments: list[tuple[str, bytes]]) -> Message:
    """Build a synthetic email.message.Message with the given PDF attachments."""
    msg = MIMEMultipart()
    msg["From"] = "sender@example.com"
    msg["To"] = "me@example.com"
    msg["Subject"] = "Bolletta"
    msg.attach(MIMEText("body text"))
    for filename, data in attachments:
        part = MIMEBase("application", "pdf")
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)
    return msg


def test_parse_pdf_attachments_returns_pdf_data():
    msg = _make_email([("bolletta.pdf", b"%PDF-1.4 fake")])
    result = download_bills.parse_pdf_attachments(msg)
    assert len(result) == 1
    assert result[0][0] == "bolletta.pdf"
    assert result[0][1] == b"%PDF-1.4 fake"


def test_parse_pdf_attachments_ignores_non_pdf():
    msg = _make_email([])
    # add a non-PDF attachment manually
    part = MIMEBase("application", "octet-stream")
    part.set_payload(b"data")
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="readme.txt")
    msg.attach(part)
    result = download_bills.parse_pdf_attachments(msg)
    assert result == []


def test_parse_pdf_attachments_multiple():
    msg = _make_email([
        ("jan.pdf", b"%PDF jan"),
        ("feb.pdf", b"%PDF feb"),
    ])
    result = download_bills.parse_pdf_attachments(msg)
    assert len(result) == 2
    filenames = [r[0] for r in result]
    assert "jan.pdf" in filenames
    assert "feb.pdf" in filenames


def test_save_pdf_writes_file(tmp_path):
    status = download_bills.save_pdf("bill.pdf", b"%PDF data", tmp_path)
    assert status == "saved"
    assert (tmp_path / "bill.pdf").read_bytes() == b"%PDF data"


def test_save_pdf_skips_existing(tmp_path):
    (tmp_path / "bill.pdf").write_bytes(b"original")
    status = download_bills.save_pdf("bill.pdf", b"new data", tmp_path)
    assert status == "skipped"
    assert (tmp_path / "bill.pdf").read_bytes() == b"original"


def test_save_pdf_creates_dest_dir(tmp_path):
    dest = tmp_path / "nested" / "pdfs"
    download_bills.save_pdf("bill.pdf", b"%PDF", dest)
    assert (dest / "bill.pdf").exists()
