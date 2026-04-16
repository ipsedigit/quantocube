"""Download all bill PDFs from Gmail to bills/pdfs/."""
from __future__ import annotations

import imaplib
import email as email_lib
import os
from email.message import Message
from pathlib import Path


SENDER = "noreply@a2aenergia.it"
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
DEST_DIR = Path("bills/pdfs")


def load_env(path: str = ".env") -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file. Returns {} if file not found."""
    env: dict[str, str] = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return env


def parse_pdf_attachments(msg: Message) -> list[tuple[str, bytes]]:
    """Return [(filename, bytes)] for every PDF attachment in the message."""
    result = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        if filename and filename.lower().endswith(".pdf"):
            data = part.get_payload(decode=True)
            if data:
                result.append((filename, data))
    return result


def save_pdf(filename: str, data: bytes, dest_dir: Path) -> str:
    """Save PDF bytes to dest_dir/filename. Returns 'saved' or 'skipped'."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / filename
    if path.exists():
        return "skipped"
    path.write_bytes(data)
    return "saved"


def _find_all_mail(imap: imaplib.IMAP4_SSL) -> str:
    """Return the name of the All Mail folder (language-independent)."""
    _, mailboxes = imap.list()
    for mb in mailboxes:
        if mb and b"\\All" in mb:
            # Format: b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"'
            parts = mb.decode().split('"')
            if len(parts) >= 2:
                return parts[-2]
    return "[Gmail]/All Mail"  # safe default


def main() -> None:
    """Download all PDF bill attachments from Gmail to bills/pdfs/.

    Reads GMAIL_USER and GMAIL_APP_PASSWORD from .env (or environment).
    Connects to Gmail via IMAP SSL, searches for emails from noreply@a2aenergia.it,
    and saves each PDF attachment to bills/pdfs/. Skips files already present.
    """
    env = load_env()
    user = env.get("GMAIL_USER") or os.environ.get("GMAIL_USER", "")
    password = env.get("GMAIL_APP_PASSWORD") or os.environ.get("GMAIL_APP_PASSWORD", "")
    if not user or not password:
        print("Error: set GMAIL_USER and GMAIL_APP_PASSWORD in .env")
        return

    print(f"Connecting to {IMAP_HOST}...")
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as imap:
            imap.login(user, password)

            folder = _find_all_mail(imap)
            imap.select(f'"{folder}"', readonly=True)

            _, msg_ids_raw = imap.search(None, 'SUBJECT "Notifica emissione bolletta"')
            ids = [i for i in msg_ids_raw[0].split() if i]
            print(f"Found {len(ids)} emails from {SENDER}")

            saved = skipped = 0
            for msg_id in ids:
                _, msg_data = imap.fetch(msg_id, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue
                msg = email_lib.message_from_bytes(msg_data[0][1])
                for filename, data in parse_pdf_attachments(msg):
                    status = save_pdf(filename, data, DEST_DIR)
                    if status == "saved":
                        saved += 1
                        print(f"  Saved: {filename}")
                    else:
                        skipped += 1

        print(f"\nSaved {saved} PDFs to {DEST_DIR}/")
        if skipped:
            print(f"Skipped {skipped} (already present)")
    except imaplib.IMAP4.error as e:
        print(f"Error: IMAP error — {e}")
    except OSError as e:
        print(f"Error: connection failed — {e}")


if __name__ == "__main__":
    main()
