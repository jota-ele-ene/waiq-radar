#!/usr/bin/env python3
"""
WAIQ Technology Radar — Script principal.

Uso:
  python run.py                     # Ejecuta el radar completo
  python run.py --dry-run           # Ejecuta sin enviar email ni pushear a GitHub
  python run.py --config otra.yaml  # Usa archivo de configuración alternativo
  python run.py --date 2026-03-13   # Fuerza una fecha específica (para testing)
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from src.config_loader import load_config
from src.search import search_all
from src.llm import LLMClient
from src.filter_and_compose import (
    filter_news,
    verify_news_urls,
    choose_editorial_angle,
    compose_opinion_article,
)
from src.email_sender import send_radar_email, send_diagnostic_email
from src.publisher import publish_to_github


def setup_logging(config: dict, date_iso: str):
    """Configura logging a archivo y consola."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = str(log_dir / f"radar_{date_iso}.log")

    level = getattr(logging, config["log"]["level"].upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_file


def main():
    parser = argparse.ArgumentParser(description="WAIQ Technology Radar")
    parser.add_argument("--config", default="config.yaml", help="Ruta al archivo de configuración")
    parser.add_argument("--dry-run", action="store_true", help="No enviar email ni pushear a GitHub")
    parser.add_argument("--date", default=None, help="Fecha forzada (YYYY-MM-DD)")
    args = parser.parse_args()

    # ── Configuración ─────────────────────────────────────────────────────────
    config = load_config(args.config)

    if args.date:
        now = datetime.strptime(args.date, "%Y-%m-%d")
    else:
        now = datetime.now()

    date_iso = now.strftime("%Y-%m-%d")
    date_str = now.strftime(config["date_format"])

    log_file = setup_logging(config, date_iso)
    logger = logging.getLogger("waiq-radar")
    logger.info(f"{'='*60}")
    logger.info(f"WAIQ RADAR — {date_str}")
    logger.info(f"LLM: {config['llm']['provider']}/{config['llm']['model']}")
    logger.info(f"Search: {config['search']['provider']}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"{'='*60}")

    # Log de herramientas (se va llenando durante la ejecución)
    tool_log = []

    # ── Paso 1: Búsqueda ─────────────────────────────────────────────────────
    logger.info("PASO 1: Búsqueda web...")
    results = search_all(config, tool_log)
    logger.info(f"Resultados brutos: {len(results)}")

    if config["log"].get("save_raw_results", False):
        raw_path = Path("logs") / f"raw_results_{date_iso}.json"
        raw_path.write_text(
            json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"Resultados brutos guardados en {raw_path}")

    if len(results) == 0:
        logger.error("No se obtuvieron resultados de búsqueda. Abortando.")
        sys.exit(1)

    # ── Paso 2: Filtrado con LLM ─────────────────────────────────────────────
    logger.info("PASO 2: Filtrado y selección con LLM...")
    llm = LLMClient(config, tool_log)
    news = filter_news(results, config, llm)
    logger.info(f"Noticias seleccionadas: {len(news)}")

    if len(news) == 0:
        logger.error("No se seleccionaron noticias. Abortando.")
        sys.exit(1)

    # ── Paso 2b: Verificación de URLs ────────────────────────────────────────
    if config.get("verify_urls", False):
        logger.info("PASO 2b: Verificación de URLs...")
        news = verify_news_urls(news, config, llm, tool_log)

    # ── Paso 3: Ángulo editorial ─────────────────────────────────────────────
    logger.info("PASO 3: Elegir ángulo editorial...")
    angles = choose_editorial_angle(news, config, llm)

    # ── Paso 4: Artículo de opinión ──────────────────────────────────────────
    logger.info("PASO 4: Generar artículo de opinión...")
    opinion = compose_opinion_article(news, angles, config, llm, date_str)

    # ── Guardar resultados intermedios ────────────────────────────────────────
    findings_path = Path("logs") / f"findings_{date_iso}.json"
    findings_path.write_text(
        json.dumps({
            "date": date_str,
            "angles": angles,
            "news": news,
            "opinion": {k: v for k, v in opinion.items() if k != "body_es" and k != "body_en"},
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"Hallazgos guardados en {findings_path}")

    # ── Paso 5: Enviar email ─────────────────────────────────────────────────
    if not args.dry_run and config["email"]["enabled"]:
        logger.info("PASO 5: Enviando email del radar...")
        send_radar_email(news, opinion, angles, config, date_str, tool_log)
    else:
        logger.info("PASO 5: Email OMITIDO (dry-run o desactivado)")

    # ── Paso 6: Publicar en GitHub ───────────────────────────────────────────
    image_stats = {"ok": 0, "total": 0}
    files_created = 0

    if not args.dry_run and config["github"]["enabled"]:
        logger.info("PASO 6: Publicando en GitHub...")
        stats = publish_to_github(news, opinion, config, date_str, date_iso, tool_log)
        files_created = stats["files_created"]
        image_stats = {"ok": stats["images_ok"], "total": stats["images_total"]}
    else:
        logger.info("PASO 6: GitHub OMITIDO (dry-run o desactivado)")

    # ── Paso 7: Email de diagnóstico ─────────────────────────────────────────
    if not args.dry_run and config["email"]["enabled"] and config["email"].get("send_diagnostic", False):
        logger.info("PASO 7: Enviando email de diagnóstico...")
        send_diagnostic_email(tool_log, config, date_str, len(news), image_stats, files_created)
    else:
        logger.info("PASO 7: Diagnóstico OMITIDO")

    # ── Guardar log de herramientas ──────────────────────────────────────────
    log_path = Path("logs") / f"tool_log_{date_iso}.json"
    log_path.write_text(
        json.dumps(tool_log, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info(f"{'='*60}")
    logger.info(f"RADAR COMPLETADO — {len(news)} noticias, {len(tool_log)} llamadas")
    logger.info(f"Log: {log_file}")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
