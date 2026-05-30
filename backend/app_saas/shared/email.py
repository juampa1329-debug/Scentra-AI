from __future__ import annotations

import html
import smtplib
from email.message import EmailMessage

from app_saas.config import settings

SCENTRA_LOGO_URL = "https://scentra-ai.online/logo-blanco.png"
SCENTRA_FAVICON_URL = "https://scentra-ai.online/favicon.png"


def smtp_is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from_email)


def _html_to_text(value: str) -> str:
    text = str(value or "")
    for tag in ("</p>", "</div>", "</h1>", "</h2>", "</h3>", "<br>", "<br/>", "<br />"):
        text = text.replace(tag, "\n")
    text = text.replace("<li>", "- ")
    clean = []
    in_tag = False
    for char in text:
        if char == "<":
            in_tag = True
            continue
        if char == ">":
            in_tag = False
            continue
        if not in_tag:
            clean.append(char)
    return html.unescape("".join(clean)).strip()


def _render_shell(*, title: str, preheader: str, body_html: str, cta_label: str = "", cta_url: str = "", footer_note: str = "", severity: str = "info") -> str:
    title = html.escape(str(title or "Scentra +AI"))
    preheader = html.escape(str(preheader or "Notificación de Scentra +AI"))
    footer_note = html.escape(str(footer_note or "Este correo fue enviado por Scentra +AI."))
    cta = ""
    if cta_label and cta_url:
        cta = (
            f'<a href="{html.escape(cta_url)}" '
            'style="display:inline-block;margin:18px 0 4px;padding:13px 18px;border-radius:14px;'
            'background:linear-gradient(135deg,#34d399,#14b8a6);color:#04231d;text-decoration:none;'
            'font-weight:900;">'
            f"{html.escape(cta_label)}</a>"
        )
    accent = {"critical": "#fb7185", "warning": "#fbbf24", "success": "#34d399"}.get(str(severity or "").lower(), "#14b8a6")
    return f"""<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="icon" href="{SCENTRA_FAVICON_URL}">
    <title>{title}</title>
  </head>
  <body style="margin:0;background:#071113;color:#eefcf8;font-family:Arial,Helvetica,sans-serif;">
    <div style="display:none;max-height:0;overflow:hidden;color:transparent;">{preheader}</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:linear-gradient(135deg,#071113,#0d1b20);padding:28px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;border:1px solid rgba(183,231,224,.18);border-radius:28px;overflow:hidden;background:#102027;box-shadow:0 24px 80px rgba(0,0,0,.34);">
            <tr>
              <td style="padding:24px 26px;background:linear-gradient(135deg,rgba(20,184,166,.24),rgba(96,165,250,.14));border-bottom:1px solid rgba(183,231,224,.16);">
                <img src="{SCENTRA_LOGO_URL}" alt="Scentra +AI" width="168" style="display:block;max-width:168px;height:auto;margin-bottom:16px;">
                <div style="width:54px;height:4px;border-radius:999px;background:{accent};margin-bottom:14px;"></div>
                <h1 style="margin:0;color:#eefcf8;font-size:28px;line-height:1.15;letter-spacing:-.02em;">{title}</h1>
                <p style="margin:8px 0 0;color:#b7d4d6;font-size:14px;line-height:1.5;">{preheader}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:28px 26px;color:#dff8f4;font-size:15px;line-height:1.65;">
                {body_html}
                {cta}
              </td>
            </tr>
            <tr>
              <td style="padding:18px 26px;background:#0b181d;border-top:1px solid rgba(183,231,224,.14);color:#8eabb1;font-size:12px;line-height:1.5;">
                <img src="{SCENTRA_FAVICON_URL}" alt="" width="22" height="22" style="vertical-align:middle;border-radius:7px;margin-right:8px;">
                {footer_note}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def send_plain_email(to_email: str, subject: str, body: str) -> bool:
    if not smtp_is_configured():
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = str(to_email or "").strip()
    message["Subject"] = str(subject or "").strip()
    message.set_content(str(body or ""))

    with smtplib.SMTP(settings.smtp_host, int(settings.smtp_port or 587), timeout=12) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)
    return True


def send_html_email(*, to_email: str, subject: str, body_text: str, body_html: str) -> bool:
    if not smtp_is_configured():
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = str(to_email or "").strip()
    message["Subject"] = str(subject or "").strip()
    message.set_content(str(body_text or "").strip() or _html_to_text(body_html))
    message.add_alternative(str(body_html or ""), subtype="html")

    with smtplib.SMTP(settings.smtp_host, int(settings.smtp_port or 587), timeout=12) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)
    return True


def send_scentra_notification_email(
    *,
    to_email: str,
    subject: str,
    title: str,
    body: str,
    cta_label: str = "",
    cta_url: str = "",
    preheader: str = "",
    footer_note: str = "",
    severity: str = "info",
) -> bool:
    paragraphs = "".join(f"<p style='margin:0 0 13px;'>{html.escape(part).replace(chr(10), '<br>')}</p>" for part in str(body or "").split("\n\n") if part.strip())
    shell = _render_shell(
        title=title,
        preheader=preheader or subject,
        body_html=paragraphs,
        cta_label=cta_label,
        cta_url=cta_url,
        footer_note=footer_note,
        severity=severity,
    )
    return send_html_email(to_email=to_email, subject=subject, body_text=body, body_html=shell)


def send_welcome_email(*, to_email: str, full_name: str = "", tenant_name: str = "", role_label: str = "", login_url: str = "", temporary_password: str = "") -> bool:
    greeting = f"Hola {full_name}," if full_name else "Hola,"
    body = (
        f"{greeting}\n\n"
        f"Tu acceso a Scentra +AI fue habilitado{f' para {tenant_name}' if tenant_name else ''}.\n\n"
        f"Rol: {role_label or 'usuario'}\n"
        f"Correo: {to_email}\n"
        f"{'Clave temporal: ' + temporary_password + chr(10) if temporary_password else ''}\n"
        "Por seguridad, cambia tu clave después del primer ingreso si recibiste una clave temporal."
    )
    return send_scentra_notification_email(
        to_email=to_email,
        subject="Bienvenido a Scentra +AI",
        title="Bienvenido a Scentra +AI",
        body=body,
        cta_label="Ingresar a Scentra",
        cta_url=login_url or str(settings.scentra_app_public_url or "").rstrip("/"),
        preheader="Tu acceso fue creado correctamente.",
        footer_note="Si no reconoces este acceso, informa al administrador de tu empresa.",
        severity="success",
    )


def send_password_reset_email(*, to_email: str, reset_url: str, expires_label: str) -> bool:
    body = (
        "Recibimos una solicitud para recuperar tu cuenta de Scentra +AI.\n\n"
        f"Fecha de vencimiento del enlace: {expires_label}.\n\n"
        "Si no solicitaste este cambio, ignora este mensaje. Tu clave actual seguirá funcionando mientras no uses el enlace."
    )
    return send_scentra_notification_email(
        to_email=to_email,
        subject="Recupera tu cuenta de Scentra +AI",
        title="Recuperar clave",
        body=body,
        cta_label="Crear nueva clave",
        cta_url=reset_url,
        preheader=f"El enlace vence el {expires_label}.",
        footer_note="Por seguridad, este enlace es de un solo uso y tiene vencimiento.",
        severity="warning",
    )


def send_alert_email(*, to_email: str, subject: str, body: str, severity: str = "warning", cta_url: str = "") -> bool:
    return send_scentra_notification_email(
        to_email=to_email,
        subject=subject,
        title=subject,
        body=body,
        cta_label="Abrir Scentra" if cta_url else "",
        cta_url=cta_url,
        preheader="Alerta transaccional de Scentra +AI.",
        footer_note="Recibes este correo porque tu cuenta, rol o acceso fue afectado por un cambio administrativo.",
        severity=severity,
    )
