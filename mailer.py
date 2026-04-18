"""
Local email module for SCMS.

Provides send_credentials_email() and test_smtp_connection() using Python's
built-in smtplib and email libraries, replacing the broken PyPI `mailer`
package which does not support Python 3.12.
"""

import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.utils import formataddr


def _build_message(email, name, cls, username, password, cfg,
                   qr_path=None, portal_url=None):
    """Construct the MIME email message for student credentials."""
    sender_name = cfg.get("sender_name", "SCMS Pro")
    smtp_user = cfg.get("smtp_user", "")

    msg = MIMEMultipart("related")
    msg["Subject"] = f"Your SCMS Login Credentials – {name}"
    msg["From"] = formataddr((sender_name, smtp_user))
    msg["To"] = email

    portal_link = portal_url or ""
    qr_section = ""
    if qr_path and os.path.exists(qr_path):
        qr_section = (
            '<p style="margin-top:16px;">'
            '<strong>Your QR Code (for quick attendance check-in):</strong><br>'
            '<img src="cid:qrcode" alt="QR Code" '
            'style="margin-top:8px;width:160px;height:160px;border:1px solid #ddd;">'
            "</p>"
        )

    html_body = f"""
    <html>
    <body style="font-family:Arial,sans-serif;color:#333;max-width:560px;margin:auto;">
      <div style="background:#4f46e5;padding:24px 32px;border-radius:8px 8px 0 0;">
        <h1 style="color:#fff;margin:0;font-size:22px;">{sender_name}</h1>
        <p style="color:#c7d2fe;margin:4px 0 0;">Student Credential Notification</p>
      </div>
      <div style="background:#f9fafb;padding:24px 32px;border-radius:0 0 8px 8px;
                  border:1px solid #e5e7eb;border-top:none;">
        <p>Hello <strong>{name}</strong>,</p>
        <p>Your account for <strong>{sender_name}</strong> has been created.
           Here are your login details:</p>
        <table style="border-collapse:collapse;width:100%;margin:16px 0;">
          <tr>
            <td style="padding:10px 14px;background:#ede9fe;border-radius:6px 0 0 0;
                       font-weight:bold;width:35%;">Class</td>
            <td style="padding:10px 14px;background:#f5f3ff;border-radius:0 6px 0 0;">
              {cls}</td>
          </tr>
          <tr>
            <td style="padding:10px 14px;background:#ede9fe;font-weight:bold;">Username</td>
            <td style="padding:10px 14px;background:#f5f3ff;font-family:monospace;">
              {username}</td>
          </tr>
          <tr>
            <td style="padding:10px 14px;background:#ede9fe;border-radius:0 0 0 6px;
                       font-weight:bold;">Password</td>
            <td style="padding:10px 14px;background:#f5f3ff;border-radius:0 0 6px 0;
                       font-family:monospace;">{password}</td>
          </tr>
        </table>
        {qr_section}
        {"<p><a href='" + portal_link + "' style='color:#4f46e5;'>Go to Student Portal →</a></p>" if portal_link else ""}
        <p style="margin-top:24px;font-size:13px;color:#6b7280;">
          Please keep your credentials safe and do not share them with others.
          Contact your teacher or administrator if you have any issues logging in.
        </p>
        <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">
        <p style="font-size:12px;color:#9ca3af;margin:0;">
          This is an automated message from {sender_name}. Please do not reply.
        </p>
      </div>
    </body>
    </html>
    """

    plain_body = (
        f"Hello {name},\n\n"
        f"Your SCMS account has been created.\n\n"
        f"Class:    {cls}\n"
        f"Username: {username}\n"
        f"Password: {password}\n"
        f"{('Portal:   ' + portal_link + chr(10)) if portal_link else ''}"
        f"\nPlease keep your credentials safe.\n\n"
        f"— {sender_name}"
    )

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(plain_body, "plain", "utf-8"))
    alternative.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alternative)

    # Attach QR code as inline image if available
    if qr_path and os.path.exists(qr_path):
        with open(qr_path, "rb") as f:
            img = MIMEImage(f.read(), _subtype="png")
        img.add_header("Content-ID", "<qrcode>")
        img.add_header("Content-Disposition", "inline", filename="qrcode.png")
        msg.attach(img)

    return msg


def send_credentials_email(email, name, cls, username, password, cfg,
                            qr_path=None, portal_url=None):
    """
    Send a credentials email to a student.

    Parameters
    ----------
    email      : str  – recipient email address
    name       : str  – student's full name
    cls        : str  – class / section (e.g. "10A")
    username   : str  – login username
    password   : str  – login password
    cfg        : dict – SMTP config with keys:
                        smtp_host, smtp_port, smtp_user, smtp_pass,
                        sender_name, enabled
    qr_path    : str  – optional path to QR code PNG file
    portal_url : str  – optional URL to the student portal

    Returns
    -------
    (success: bool, message: str)
    """
    if not cfg.get("enabled"):
        return False, "Email sending is disabled in settings."

    smtp_host = cfg.get("smtp_host", "").strip()
    smtp_port = int(cfg.get("smtp_port", 587))
    smtp_user = cfg.get("smtp_user", "").strip()
    smtp_pass = cfg.get("smtp_pass", "")

    if not smtp_host or not smtp_user:
        return False, "SMTP host or user is not configured."

    try:
        msg = _build_message(email, name, cls, username, password, cfg,
                             qr_path=qr_path, portal_url=portal_url)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [email], msg.as_string())

        return True, None

    except smtplib.SMTPAuthenticationError:
        return False, "SMTP authentication failed. Check username and password."
    except smtplib.SMTPConnectError:
        return False, f"Could not connect to SMTP server {smtp_host}:{smtp_port}."
    except smtplib.SMTPRecipientsRefused:
        return False, f"Recipient address '{email}' was refused by the server."
    except smtplib.SMTPException as exc:
        return False, f"SMTP error: {exc}"
    except OSError as exc:
        return False, f"Network error: {exc}"
    except Exception as exc:
        return False, f"Unexpected error: {exc}"


def test_smtp_connection(cfg):
    """
    Test the SMTP connection using the provided configuration.

    Parameters
    ----------
    cfg : dict – SMTP config with keys:
                 smtp_host, smtp_port, smtp_user, smtp_pass,
                 sender_name, enabled

    Returns
    -------
    (success: bool, message: str)
    """
    smtp_host = cfg.get("smtp_host", "").strip()
    smtp_port = int(cfg.get("smtp_port", 587))
    smtp_user = cfg.get("smtp_user", "").strip()
    smtp_pass = cfg.get("smtp_pass", "")

    if not smtp_host:
        return False, "SMTP host is not configured."
    if not smtp_user:
        return False, "SMTP username is not configured."

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)

        return True, f"Successfully connected to {smtp_host}:{smtp_port} as {smtp_user}."

    except smtplib.SMTPAuthenticationError:
        return False, "Authentication failed. Check your SMTP username and password."
    except smtplib.SMTPConnectError:
        return False, f"Could not connect to {smtp_host}:{smtp_port}. Check host and port."
    except smtplib.SMTPException as exc:
        return False, f"SMTP error: {exc}"
    except OSError as exc:
        return False, f"Network error connecting to {smtp_host}:{smtp_port}: {exc}"
    except Exception as exc:
        return False, f"Unexpected error: {exc}"
