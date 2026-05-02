"""
Servicio de email transaccional.
Soporta Resend API (default) y SMTP fallback.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx
from loguru import logger

from config.settings import settings


def send_email(to: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """
    Envía un email. Retorna True si tuvo éxito.
    Usa Resend si está configurado, sino intenta SMTP.
    """
    if not settings.email_from:
        logger.warning("[EMAIL] email_from no configurado. No se envio el email.")
        return False

    if settings.email_provider == "resend" and settings.resend_api_key:
        return _send_via_resend(to, subject, html_body, text_body)

    if settings.smtp_host:
        return _send_via_smtp(to, subject, html_body, text_body)

    logger.warning("[EMAIL] Ningun proveedor de email configurado.")
    return False


def _send_via_resend(to: str, subject: str, html_body: str, text_body: str) -> bool:
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": f"{settings.email_from_name} <{settings.email_from}>",
                "to": [to],
                "subject": subject,
                "html": html_body,
                "text": text_body or "",
            },
            timeout=15,
        )
        resp.raise_for_status()
        logger.info(f"[EMAIL] Enviado a {to} via Resend")
        return True
    except Exception as exc:
        logger.error(f"[EMAIL] Error Resend: {exc}")
        return False


def _send_via_smtp(to: str, subject: str, html_body: str, text_body: str) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.email_from_name} <{settings.email_from}>"
        msg["To"] = to

        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            if settings.smtp_tls:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.email_from, to, msg.as_string())

        logger.info(f"[EMAIL] Enviado a {to} via SMTP")
        return True
    except Exception as exc:
        logger.error(f"[EMAIL] Error SMTP: {exc}")
        return False


def send_password_reset_email(to: str, reset_url: str) -> bool:
    subject = "Restablecer contrasena - Trading Bot Platform"
    html = f"""
    <h2>Restablecer contrasena</h2>
    <p>Haz clic en el siguiente enlace para restablecer tu contrasena:</p>
    <p><a href="{reset_url}" style="padding:10px 20px;background:#3b82f6;color:#fff;text-decoration:none;border-radius:5px;">Restablecer contrasena</a></p>
    <p>Si no solicitaste esto, ignora este email.</p>
    <p>El enlace expira en 30 minutos.</p>
    """
    text = f"Restablecer contrasena: {reset_url}\nEl enlace expira en 30 minutos."
    return send_email(to, subject, html, text)


def send_verification_email(to: str, verify_url: str) -> bool:
    subject = "Verifica tu email - Trading Bot Platform"
    html = f"""
    <h2>Bienvenido a Trading Bot Platform</h2>
    <p>Haz clic en el siguiente enlace para verificar tu email:</p>
    <p><a href="{verify_url}" style="padding:10px 20px;background:#22c55e;color:#fff;text-decoration:none;border-radius:5px;">Verificar email</a></p>
    <p>Si no creaste esta cuenta, ignora este email.</p>
    <p>El enlace expira en 24 horas.</p>
    """
    text = f"Verifica tu email: {verify_url}\nEl enlace expira en 24 horas."
    return send_email(to, subject, html, text)
