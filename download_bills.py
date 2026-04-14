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
