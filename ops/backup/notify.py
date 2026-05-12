#!/usr/bin/env python3
"""Send an alert email via the same SMTP relay used by the application.

Reads SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / MAIL_FROM from the
environment (sourced by the calling shell script from config.env). Uses
stdlib smtplib so no external dependency is required.

Usage:
    notify.py --to user@example.com --subject "..." --body "..."
"""
import argparse
import os
import smtplib
import socket
import ssl
import sys
from email.message import EmailMessage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body", required=True)
    args = parser.parse_args()

    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    sender = os.environ.get("MAIL_FROM", user)

    if not host or not user or not password:
        print("notify.py: SMTP_HOST / SMTP_USER / SMTP_PASSWORD missing in env", file=sys.stderr)
        return 2

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = args.to
    msg["Subject"] = args.subject
    msg.set_content(
        f"Host: {socket.gethostname()}\n"
        f"\n"
        f"{args.body}\n"
    )

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(user, password)
            smtp.send_message(msg)
    except Exception as exc:
        print(f"notify.py: failed to send mail: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
