#!/usr/bin/env python3
"""
WAIQ Technology Radar — Script principal con pipeline por fases.

Cada fase genera un archivo JSON intermedio en data/{fecha}/ que sirve
como entrada para la siguiente fase. Esto permite:
  - Ejecutar fases por separado (ahorro en APIs)
  - Reintentar una fase sin repetir las anteriores
  - Inspeccionar/editar datos intermedios manualmente
  - Desacoplar consumo de modelos de publicación y envío

Uso:
  python run.py                          # Pipeline completo
  python run.py --dry-run                # Todo excepto email + GitHub push
  python run.py --phase search           # Solo búsqueda web
  python run.py --phase filter           # Solo filtrado (lee búsqueda previa)
  python run.py --phase search,filter    # Varias fases separadas por coma
  python run.py --phase compose-publish  # Rango: desde compose hasta publish
  python run.py --phase publish          # Solo publicar (con datos ya generados)
  python run.py --data-dir data/2026-03-13  # Usar directorio de datos específico
  python run.py --date 2026-03-13        # Fuerza una fecha (y su directorio)
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from src.config_loader import load_config
from src.search import search_all, SearchResult
from src.llm import LLMClient
from src.filter_and_compose import (
    filter_news,
    verify_news_urls,
    choose_editorial_angle,
    compose_opinion_article,
)
from src.email_sender import send_radar_email, send_diagnostic_email
from src.publisher import publish_to_github

# ─── Definición de fases (en orden) ──────────────────────────────────────────

PHASES_ORDER = ["search", "filter", "verify", "compose", "email", "publish", "diagnostic"]

PHASE_FILES = {
    "search":  "1_search_results.json",
    "filter":  "2_filtered_news.json",
    "verify":  "3_verified_news.json",
    "compose": "4_composed.json",
}

PHASE_DESCRIPTIONS = {
    "search":     "Búsqueda web (Tavily/Serper/DDG)",
    "filter":     "Filtrado y selección con LLM",
    "verify":     "Verificación de URLs",
    "compose":    "Ángulo editorial + artículo de opinión (LLM)",
    "email":      "Envío email del radar",
    "publish":    "Publicación en GitHub (Hugo)",
    "diagnostic": "Envío email de diagnóstico",
}


# ─── Utilidades de datos intermedios ─────────────────────────────────────────

def get_data_dir(date_iso: str, custom_dir: str = None) -> Path:
    """Devuelve el directorio de datos intermedios para la fecha dada."""
    if custom_dir:
        p = Path(custom_dir)
    else:
        p = Path("data") / date_iso
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_phase_data(data_dir: Path, phase: str, data) -> Path:
    """Guarda los datos de una fase como JSON."""
    filename = PHASE_FILES.get(phase)
    if not filename:
        return None
    filepath = data_dir / filename
    filepath.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return filepath


def load_phase_data(data_dir: Path, phase: str) -> any:
    """Carga los datos de una fase previa desde JSON."""
    filename = PHASE_FILES.get(phase)
    if not filename:
        return None
    filepath = data_dir / filename
    if not filepath.exists():
        return None
    return json.loads(filepath.read_text(encoding="utf-8"))


def resolve_phases(phase_arg: str) -> list:
    """
    Parsea el argumento --phase y devuelve la lista ordenada de fases.

    Formatos soportados:
      "search"                → ["search"]
      "search,filter"         → ["search", "filter"]
      "compose-publish"       → ["compose", "email", "publish"]
      "filter-diagnostic"     → ["filter", "verify", "compose", "email", "publish", "diagnostic"]
    """
    if not phase_arg:
        return list(PHASES_ORDER)

    # Rango con guión
    if "-" in phase_arg and "," not in phase_arg:
        parts = phase_arg.split("-", 1)
        start = parts[0].strip()
        end = parts[1].strip()
        if start not in PHASES_ORDER or end not in PHASES_ORDER:
            print(f"Error: fases no válidas en rango '{phase_arg}'")
            print(f"Fases disponibles: {', '.join(PHASES_ORDER)}")
            sys.exit(1)
        i_start = PHASES_ORDER.index(start)
        i_end = PHASES_ORDER.index(end)
        if i_start > i_end:
            print(f"Error: '{start}' va después de '{end}' en el pipeline")
            sys.exit(1)
        return PHASES_ORDER[i_start:i_end + 1]

    # Lista separada por comas
    phases = [p.strip() for p in phase_arg.split(",")]
    for p in phases:
        if p not in PHASES_ORDER:
            print(f"Error: fase '{p}' no reconocida")
            print(f"Fases disponibles: {', '.join(PHASES_ORDER)}")
            sys.exit(1)
    return phases


# ─── Setup ───────────────────────────────────────────────────────────────────

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


# ─── Pipeline ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="WAIQ Technology Radar — pipeline por fases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Fases disponibles (en orden):
  search      Búsqueda web (Tavily/Serper/DuckDuckGo)
  filter      Filtrado y selección con LLM
  verify      Verificación de URLs (fetch + LLM)
  compose     Ángulo editorial + artículo de opinión (LLM)
  email       Envío del email del radar
  publish     Publicación en GitHub (Hugo .md + imágenes)
  diagnostic  Envío del email de diagnóstico

Ejemplos:
  python run.py                            # Pipeline completo
  python run.py --phase search             # Solo búsqueda
  python run.py --phase filter             # Solo filtrado (lee datos previos)
  python run.py --phase search,filter      # Búsqueda + filtrado
  python run.py --phase compose-publish    # Desde compose hasta publish
  python run.py --phase publish            # Solo publicar
  python run.py --phase email,diagnostic   # Solo reenviar emails
  python run.py --dry-run --phase search,filter,compose  # Generar datos sin enviar nada

Datos intermedios:
  Cada fase guarda su resultado en data/{fecha}/ como JSON.
  Las fases posteriores leen automáticamente de ahí.
  Puedes editar manualmente los JSON antes de ejecutar la siguiente fase.
""",
    )
    parser.add_argument("--config", default="config.yaml",
                        help="Ruta al archivo de configuración")
    parser.add_argument("--dry-run", action="store_true",
                        help="No enviar email ni pushear a GitHub")
    parser.add_argument("--date", default=None,
                        help="Fecha forzada (YYYY-MM-DD)")
    parser.add_argument("--phase", default=None,
                        help="Fase(s) a ejecutar: search, filter, verify, compose, email, publish, diagnostic. "
                             "Separar con coma (search,filter) o rango con guión (compose-publish)")
    parser.add_argument("--data-dir", default=None,
                        help="Directorio de datos intermedios (por defecto: data/{fecha})")
    args = parser.parse_args()

    # ── Configuración ─────────────────────────────────────────────────────────
    config = load_config(args.config)

    if args.date:
        now = datetime.strptime(args.date, "%Y-%m-%d")
    else:
        now = datetime.now()

    date_iso = now.strftime("%Y-%m-%d")
    date_str = now.strftime(config["date_format"])

    data_dir = get_data_dir(date_iso, args.data_dir)
    phases = resolve_phases(args.phase)

    log_file = setup_logging(config, date_iso)
    logger = logging.getLogger("waiq-radar")
    logger.info("=" * 60)
    logger.info(f"WAIQ RADAR — {date_str}")
    logger.info(f"Fases:  {' → '.join(phases)}")
    logger.info(f"Datos:  {data_dir}")
    logger.info(f"LLM:    {config['llm']['provider']}/{config['llm']['model']}")
    logger.info(f"Search: {config['search']['provider']}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("=" * 60)

    # Tool log (persiste entre ejecuciones parciales)
    tool_log_path = data_dir / "tool_log.json"
    if tool_log_path.exists():
        tool_log = json.loads(tool_log_path.read_text(encoding="utf-8"))
    else:
        tool_log = []

    # Variables que se van llenando según la fase
    search_results = None    # List[dict] de búsqueda bruta
    news = None              # List[dict] noticias filtradas
    angles = None            # List[str]
    opinion = None           # dict
    image_stats = {"ok": 0, "total": 0}
    files_created = 0

    llm = None  # Se inicializa solo si es necesario

    def get_llm():
        nonlocal llm
        if llm is None:
            llm = LLMClient(config, tool_log)
        return llm

    # ── FASE: search ──────────────────────────────────────────────────────────
    if "search" in phases:
        logger.info("▶ FASE: search — Búsqueda web...")
        raw_results = search_all(config, tool_log)
        search_results = [r.to_dict() for r in raw_results]
        logger.info(f"  Resultados brutos: {len(search_results)}")

        save_phase_data(data_dir, "search", search_results)
        logger.info(f"  → Guardado: {data_dir / PHASE_FILES['search']}")

        if len(search_results) == 0:
            logger.error("  No se obtuvieron resultados. Abortando.")
            _save_tool_log(tool_log, tool_log_path)
            sys.exit(1)

    # ── FASE: filter ──────────────────────────────────────────────────────────
    if "filter" in phases:
        logger.info("▶ FASE: filter — Filtrado con LLM...")

        # Cargar datos de búsqueda si no están en memoria
        if search_results is None:
            search_results = load_phase_data(data_dir, "search")
            if search_results is None:
                logger.error(f"  No hay datos de búsqueda. Ejecuta primero: --phase search")
                logger.error(f"  Buscando en: {data_dir / PHASE_FILES['search']}")
                _save_tool_log(tool_log, tool_log_path)
                sys.exit(1)
            logger.info(f"  Cargados {len(search_results)} resultados de {data_dir / PHASE_FILES['search']}")

        # Convertir dicts a SearchResult para la función
        results_as_objects = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("snippet", ""),
                date=r.get("date", ""),
            )
            for r in search_results
        ]

        news = filter_news(results_as_objects, config, get_llm())
        logger.info(f"  Noticias seleccionadas: {len(news)}")

        save_phase_data(data_dir, "filter", news)
        logger.info(f"  → Guardado: {data_dir / PHASE_FILES['filter']}")

        if len(news) == 0:
            logger.error("  No se seleccionaron noticias. Abortando.")
            _save_tool_log(tool_log, tool_log_path)
            sys.exit(1)

    # ── FASE: verify ──────────────────────────────────────────────────────────
    if "verify" in phases:
        logger.info("▶ FASE: verify — Verificación de URLs...")

        if news is None:
            news = load_phase_data(data_dir, "filter")
            if news is None:
                logger.error(f"  No hay datos filtrados. Ejecuta primero: --phase filter")
                _save_tool_log(tool_log, tool_log_path)
                sys.exit(1)
            logger.info(f"  Cargadas {len(news)} noticias de {data_dir / PHASE_FILES['filter']}")

        if config.get("verify_urls", False):
            news = verify_news_urls(news, config, get_llm(), tool_log)
            logger.info(f"  Verificadas {len(news)} noticias")
        else:
            logger.info("  Verificación desactivada en config (verify_urls: false)")

        save_phase_data(data_dir, "verify", news)
        logger.info(f"  → Guardado: {data_dir / PHASE_FILES['verify']}")

    # ── FASE: compose ─────────────────────────────────────────────────────────
    if "compose" in phases:
        logger.info("▶ FASE: compose — Ángulo editorial + artículo de opinión...")

        if news is None:
            # Intentar cargar verified primero, luego filtered
            news = load_phase_data(data_dir, "verify")
            if news is None:
                news = load_phase_data(data_dir, "filter")
            if news is None:
                logger.error("  No hay noticias. Ejecuta primero: --phase filter")
                _save_tool_log(tool_log, tool_log_path)
                sys.exit(1)
            source = "verify" if (data_dir / PHASE_FILES["verify"]).exists() else "filter"
            logger.info(f"  Cargadas {len(news)} noticias de {data_dir / PHASE_FILES[source]}")

        angles = choose_editorial_angle(news, config, get_llm())
        logger.info(f"  Ángulos: {angles}")

        opinion = compose_opinion_article(news, angles, config, get_llm(), date_str)
        logger.info(f"  Artículo: {opinion.get('title_es', '?')}")

        composed = {
            "date": date_str,
            "date_iso": date_iso,
            "angles": angles,
            "news": news,
            "opinion": opinion,
        }
        save_phase_data(data_dir, "compose", composed)
        logger.info(f"  → Guardado: {data_dir / PHASE_FILES['compose']}")

    # ── FASE: email ───────────────────────────────────────────────────────────
    if "email" in phases:
        logger.info("▶ FASE: email — Envío del radar...")

        composed = _load_composed(data_dir, news, angles, opinion, logger, tool_log)
        if composed is None:
            _save_tool_log(tool_log, tool_log_path)
            sys.exit(1)
        news, angles, opinion = composed

        if args.dry_run:
            logger.info("  Email OMITIDO (dry-run)")
            # Guardar preview del email
            from src.email_sender import _compose_main_body
            preview_path = data_dir / "email_preview.txt"
            preview_path.write_text(
                _compose_main_body(news, opinion, angles, date_str),
                encoding="utf-8",
            )
            logger.info(f"  → Preview guardado: {preview_path}")
        elif config["email"]["enabled"]:
            send_radar_email(news, opinion, angles, config, date_str, tool_log)
        else:
            logger.info("  Email desactivado en config")

    # ── FASE: publish ─────────────────────────────────────────────────────────
    if "publish" in phases:
        logger.info("▶ FASE: publish — Publicación en GitHub...")

        composed = _load_composed(data_dir, news, angles, opinion, logger, tool_log)
        if composed is None:
            _save_tool_log(tool_log, tool_log_path)
            sys.exit(1)
        news, angles, opinion = composed

        if args.dry_run:
            logger.info("  GitHub OMITIDO (dry-run)")
        elif config["github"]["enabled"]:
            stats = publish_to_github(news, opinion, config, date_str, date_iso, tool_log)
            files_created = stats["files_created"]
            image_stats = {"ok": stats["images_ok"], "total": stats["images_total"]}
            logger.info(f"  Publicados: {files_created} archivos, {image_stats['ok']}/{image_stats['total']} imágenes")
        else:
            logger.info("  GitHub desactivado en config")

    # ── FASE: diagnostic ──────────────────────────────────────────────────────
    if "diagnostic" in phases:
        logger.info("▶ FASE: diagnostic — Email de diagnóstico...")

        news_count = len(news) if news else 0
        if news_count == 0:
            composed_data = load_phase_data(data_dir, "compose")
            if composed_data:
                news_count = len(composed_data.get("news", []))

        if args.dry_run:
            logger.info("  Diagnóstico OMITIDO (dry-run)")
        elif config["email"]["enabled"] and config["email"].get("send_diagnostic", False):
            send_diagnostic_email(tool_log, config, date_str, news_count, image_stats, files_created)
        else:
            logger.info("  Diagnóstico desactivado en config")

    # ── Guardar tool_log acumulado ────────────────────────────────────────────
    _save_tool_log(tool_log, tool_log_path)

    # También en logs/ para compatibilidad
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    (log_dir / f"tool_log_{date_iso}.json").write_text(
        json.dumps(tool_log, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("=" * 60)
    logger.info(f"COMPLETADO — Fases: {' → '.join(phases)}")
    logger.info(f"Datos intermedios: {data_dir}/")
    logger.info(f"Tool log: {tool_log_path}")
    logger.info("=" * 60)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _load_composed(data_dir, news, angles, opinion, logger, tool_log):
    """Carga datos compuestos (news + angles + opinion) si no están en memoria."""
    if news is not None and angles is not None and opinion is not None:
        return (news, angles, opinion)

    composed = load_phase_data(data_dir, "compose")
    if composed is None:
        logger.error(f"  No hay datos compuestos. Ejecuta primero: --phase compose")
        logger.error(f"  Buscando en: {data_dir / PHASE_FILES['compose']}")
        return None

    news = composed.get("news", [])
    angles = composed.get("angles", [])
    opinion = composed.get("opinion", {})
    logger.info(f"  Cargados de {data_dir / PHASE_FILES['compose']}: "
                f"{len(news)} noticias, ángulos: {angles}")
    return (news, angles, opinion)


def _save_tool_log(tool_log, path):
    """Guarda el tool_log acumulado."""
    path.write_text(
        json.dumps(tool_log, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
