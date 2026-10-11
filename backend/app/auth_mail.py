"""Server-side transactional email transport; never prints tokens or passwords."""
from __future__ import annotations
import os
import smtplib
import ssl
from email.message import EmailMessage
from fastapi import HTTPException

class SMTPMailer:
    def send(self, recipient: str, subject: str, text: str) -> None:
        host = os.getenv('AUTH_SMTP_HOST','')
        sender = os.getenv('AUTH_SMTP_FROM','')
        if not host or not sender:
            raise HTTPException(503,'Email service not configured')
        port = int(os.getenv('AUTH_SMTP_PORT','587'))
        if port != 587 and port != 465:
            raise HTTPException(503,'Email service requires TLS')
        message = EmailMessage()
        message['From'] = sender
        message['To'] = recipient
        message['Subject'] = subject
        message.set_content(text)
        try:
            if port == 465:
                with smtplib.SMTP_SSL(host,port,timeout=10,context=ssl.create_default_context()) as smtp:
                    self._login(smtp)
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(host,port,timeout=10) as smtp:
                    smtp.ehlo()
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                    self._login(smtp)
                    smtp.send_message(message)
        except (OSError,smtplib.SMTPException) as exc:
            raise HTTPException(503,'Email service temporarily unavailable') from exc

    @staticmethod
    def _login(smtp):
        user = os.getenv('AUTH_SMTP_USER','')
        password = os.getenv('AUTH_SMTP_PASSWORD','')
        if bool(user) != bool(password):
            raise HTTPException(503,'Email service authentication is incomplete')
        if user:
            smtp.login(user,password)

def email_sender():
    return SMTPMailer()
