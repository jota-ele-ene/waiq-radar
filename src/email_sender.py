"""
Envío de emails por SMTP.
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List

logger = logging.getLogger("waiq-radar.email")


def send_radar_email(
    news: List[dict],
    opinion: dict,
    angles: List[str],
    config: dict,
    date_str: str,
    tool_log: list,
) -> bool:
    """Compone y envía el email principal del radar."""
    subject = f"WAIQ Radar {date_str} - {' / '.join(angles)}"
    body = _compose_main_body(news, opinion, angles, date_str)

    success = _send_smtp(
        to=config["email"]["to"],
        subject=subject,
        body=body,
        config=config,
    )

    tool_log.append({
        "step": len(tool_log) + 1,
        "tool": "send_email (SMTP)",
        "model": "N/A",
        "action": f"Enviar radar a {config['email']['to']}",
        "result": "OK" if success else "ERROR",
    })

    return success


def send_diagnostic_email(
    tool_log: list,
    config: dict,
    date_str: str,
    news_count: int,
    image_stats: dict,
    files_created: int,
) -> bool:
    """Envía el email de diagnóstico con el log completo de ejecución."""
    if not config["email"].get("send_diagnostic", False):
        return True

    subject = f"WAIQ Radar {date_str} - Diagnóstico de ejecución"
    body = _compose_diagnostic_body(
        tool_log, date_str, news_count, image_stats, files_created
    )

    success = _send_smtp(
        to=config["email"]["to"],
        subject=subject,
        body=body,
        config=config,
    )

    return success


def _compose_main_body(
    news: List[dict],
    opinion: dict,
    angles: List[str],
    date_str: str,
) -> str:
    """Compone el body del email principal en texto plano."""
    lines = []
    lines.append(f"WAIQ RADAR TECNOLÓGICO - {date_str}")
    lines.append("=" * 50)
    lines.append("")
    lines.append("NOTICIAS RELEVANTES")
    lines.append("-" * 30)
    lines.append("")

    for i, item in enumerate(news):
        lines.append(f"{i+1}. {item.get('title_es', '')}")
        lines.append(f"   Fuente: {item.get('source', '')}")
        lines.append(f"   Enlace: {item.get('url', '')}")
        lines.append(f"   {item.get('description_es', '')}")
        angles_str = ", ".join(item.get("angles", []))
        lines.append(f"   Ángulo WAIQ: {angles_str}")
        lines.append("")

    lines.append("")
    lines.append("-" * 50)
    lines.append("")
    lines.append("PROPUESTA DE ARTÍCULO DE OPINIÓN")
    lines.append("-" * 40)
    lines.append("")
    lines.append(f"Título: \"{opinion.get('title_es', '')}\"")
    lines.append(f"Ángulo editorial: {' / '.join(angles)}")
    lines.append("")
    lines.append(opinion.get("body_es", ""))
    lines.append("")
    lines.append("-" * 50)
    lines.append("Radar generado automáticamente para waiq.technology")

    return "\n".join(lines)


def _compose_diagnostic_body(
    tool_log: list,
    date_str: str,
    news_count: int,
    image_stats: dict,
    files_created: int,
) -> str:
    """Compone el body del email de diagnóstico."""
    search_calls = sum(1 for t in tool_log if "search" in t["tool"].lower())
    llm_calls = sum(1 for t in tool_log if "llm" in t["tool"].lower())
    email_calls = sum(1 for t in tool_log if "email" in t["tool"].lower())
    errors = [t for t in tool_log if "ERROR" in t.get("result", "")]

    lines = []
    lines.append(f"WAIQ RADAR - DIAGNÓSTICO DE EJECUCIÓN")
    lines.append("=" * 50)
    lines.append(f"Fecha: {date_str}")
    lines.append("")
    lines.append("RESUMEN")
    lines.append("-" * 20)
    lines.append(f"Total de llamadas a herramientas: {len(tool_log)}")
    lines.append(f"  - Búsquedas web: {search_calls}")
    lines.append(f"  - Llamadas LLM: {llm_calls}")
    lines.append(f"  - Emails enviados: {email_calls}")
    lines.append(f"Noticias seleccionadas: {news_count}")
    lines.append(f"Archivos creados en GitHub: {files_created}")
    lines.append(f"Imágenes: {image_stats.get('ok', 0)} descargadas / {image_stats.get('total', 0)} intentadas")
    lines.append("")
    lines.append("DETALLE DE LLAMADAS")
    lines.append("-" * 30)
    lines.append("")

    for entry in tool_log:
        lines.append(f"#{entry['step']} - {entry['tool']}")
        lines.append(f"     Modelo: {entry.get('model', 'N/A')}")
        lines.append(f"     Acción: {entry.get('action', '')}")
        lines.append(f"     Resultado: {entry.get('result', '')}")
        lines.append("")

    lines.append("ERRORES O INCIDENCIAS")
    lines.append("-" * 30)
    if errors:
        for e in errors:
            lines.append(f"  - #{e['step']} {e['tool']}: {e['result']}")
    else:
        lines.append("  Ninguna incidencia.")

    lines.append("")
    lines.append("-" * 50)
    lines.append("Diagnóstico generado automáticamente")

    return "\n".join(lines)


def _send_smtp(to: str, subject: str, body: str, config: dict) -> bool:
    """Envía un email por SMTP."""
    smtp_conf = config["email"]["smtp"]
    from_name = config["email"].get("from_name", "WAIQ Radar")
    from_addr = smtp_conf["username"]

    msg = MIMEMultipart()
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(smtp_conf["host"], smtp_conf["port"]) as server:
            server.starttls()
            server.login(smtp_conf["username"], smtp_conf["password"])
            server.send_message(msg)
        logger.info(f"Email enviado: {subject}")
        return True
    except Exception as e:
        logger.error(f"Error enviando email: {e}")
        return False
