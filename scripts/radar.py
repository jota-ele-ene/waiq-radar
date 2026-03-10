"""
WAIQ Radar — Pipeline principal
Busca noticias sobre WAIQ (Web3, AI, Quantum) desde perspectivas no técnicas,
genera .md en ES/EN, descarga imágenes, crea artículo de opinión bilingüe
y prepara un commit Git para el repositorio waiq-multi.
"""

import os
import re
import json
import time
import base64
import smtplib
import hashlib
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic
from github import Github, GithubException

# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN (variables de entorno)
# ─────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GITHUB_TOKEN       = os.environ["GITHUB_TOKEN"]
GITHUB_REPO        = os.environ.get("GITHUB_REPO", "jota-ele-ene/waiq-multi")
HUGO_BASE_URL      = os.environ.get("HUGO_BASE_URL", "https://waiq.technology")
GMAIL_USER         = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
EMAIL_RECIPIENTS   = os.environ["EMAIL_RECIPIENTS"]

MODEL = "claude-sonnet-4-6"

# Rutas en el repo waiq-multi
REPO_PATH_EN_ARTICLES = "content/en/article"
REPO_PATH_ES_ARTICLES = "content/es/article"
REPO_PATH_IMAGES      = "static/images/upload/articles"

# Nombre del autor del artículo de opinión
OPINION_AUTHOR = "WAIQ Radar"

# ─────────────────────────────────────────────────────────────
# MANIFESTO WAIQ (contexto para Claude)
# ─────────────────────────────────────────────────────────────

WAIQ_MANIFESTO = """
WAIQ (Web3, AI, Quantum) es un foro nacido en Harvard Law School en 2023 que analiza
la convergencia de tecnologías disruptivas desde perspectivas NO técnicas:
gobernanza, regulación, ética, impacto social, modelos de negocio, democracia,
soberanía tecnológica, propiedad intelectual y competitividad.

El foro defiende que Europa y España deben liderar esta revolución con valentía,
combinando excelencia tecnológica con marcos éticos sólidos y regulación inteligente.

Busca contenidos que:
- Analicen regulación/gobernanza de IA, Web3 o Quantum (EU AI Act, MiCA, PQC standards...)
- Aborden el impacto social, ético o legal de estas tecnologías
- Traten modelos de negocio innovadores en estos campos
- Discutan soberanía digital, brecha tecnológica o competitividad
- Analicen la convergencia entre las tres tecnologías WAIQ
- Provengan de fuentes de calidad: think tanks, medios especializados, organismos oficiales
- Tengan perspectiva europea o global, pero no meramente técnica
"""

# Áreas temáticas válidas del sitio
AREAS_VALIDAS = [
    "regulation", "ethical", "legal", "business", "innovation",
    "governance", "social", "technology", "sovereignty", "democracy",
    "use-cases", "research"
]

# ─────────────────────────────────────────────────────────────
# PASO 1: BÚSQUEDA DE NOTICIAS CON WEB SEARCH
# ─────────────────────────────────────────────────────────────

def buscar_noticias(client: anthropic.Anthropic) -> list[dict]:
    print("📡 Buscando noticias relevantes para WAIQ...")

    fecha_limite = (datetime.now(timezone.utc) - timedelta(days=4)).strftime("%Y-%m-%d")

    prompt = f"""Eres el editor del radar de noticias de WAIQ, un foro que analiza Web3, AI y Quantum
desde perspectivas NO técnicas. Lee este contexto:

{WAIQ_MANIFESTO}

Busca noticias publicadas desde {fecha_limite} sobre:
- Regulación y gobernanza de IA (EU AI Act, políticas nacionales, supervisión...)
- Aspectos legales, éticos o sociales de la inteligencia artificial
- Web3: regulación cripto (MiCA), DAOs, identidad digital, propiedad intelectual
- Quantum: transición post-cuántica, impacto en ciberseguridad, regulación, inversión pública
- Soberanía tecnológica europea, brecha digital, competitividad
- Convergencia de tecnologías WAIQ y su impacto en sociedad o economía
- Modelos de negocio innovadores basados en estas tecnologías
- Democracia, derechos fundamentales y nuevas tecnologías

NO incluyas noticias puramente técnicas (benchmarks, nuevos modelos, hardware...).
SÍ incluye análisis, informes de think tanks, decisiones regulatorias, debates políticos,
casos de uso con impacto social, y noticias de medios de referencia.

Para cada noticia relevante encontrada, devuelve:
- title_en: titular en inglés
- title_es: titular en español
- description_en: entradilla en inglés (2-3 frases, tono WAIQ)
- description_es: entradilla en español (2-3 frases, tono WAIQ)
- url: enlace original
- source: nombre del medio
- source_domain: dominio del medio (ej: "reuters.com")
- topic: "ai", "web3" o "quantum" (el principal)
- extra_topics: otros topics WAIQ aplicables (lista, puede estar vacía)
- areas: lista de áreas de entre: {", ".join(AREAS_VALIDAS)}
- image_url: URL de thumbnail/imagen destacada del artículo (o null si no hay)
- date: fecha de publicación (YYYY-MM-DD)

Devuelve ÚNICAMENTE JSON válido sin backticks:
{{
  "noticias": [ {{ ...campos... }}, ... ]
}}

Selecciona 8-12 noticias. Prioriza calidad y relevancia para la audiencia WAIQ
(juristas, innovadores, académicos, directivos) sobre cantidad."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=5000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}]
    )

    text = "".join(b.text for b in response.content if hasattr(b, "text"))
    text = re.sub(r"```json|```", "", text).strip()

    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        raise ValueError("No se encontró JSON en la respuesta de búsqueda")

    data = json.loads(match.group())
    noticias = data.get("noticias", [])
    print(f"   ✓ {len(noticias)} noticias encontradas")
    return noticias


# ─────────────────────────────────────────────────────────────
# PASO 2: ARTÍCULO DE OPINIÓN BILINGÜE
# ─────────────────────────────────────────────────────────────

def generar_articulo_opinion(client: anthropic.Anthropic, noticias: list[dict]) -> dict:
    print("✍️  Generando artículo de opinión bilingüe...")

    noticias_str = "\n\n".join(
        f"[{n.get('topic','').upper()}] {n['title_en']} ({n['source']})\n"
        f"EN: {n['description_en']}\nES: {n['description_es']}\nURL: {n['url']}"
        for n in noticias
    )
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    prompt = f"""Eres el articulista de WAIQ. Contexto del foro:

{WAIQ_MANIFESTO}

Basándote en estas noticias del radar de esta semana:

{noticias_str}

Escribe un artículo de comentario/opinión con estas características:
- Tono: analítico, crítico y propositivo, con perspectiva europea
- No técnico: orientado a juristas, directivos e innovadores
- Conecta las noticias con los temas centrales de WAIQ (convergencia, regulación, ética, soberanía)
- Extensión: 700-900 palabras por idioma
- Usa secciones con subtítulos
- Cita fuentes de las noticias de forma natural

Devuelve ÚNICAMENTE JSON válido sin backticks:
{{
  "title_en": "English article title",
  "title_es": "Título en español",
  "slug": "slug-en-kebab-case-compartido",
  "description_en": "SEO description in English (max 160 chars)",
  "description_es": "Descripción SEO en español (máx 160 chars)",
  "tags_en": ["tag1", "tag2"],
  "tags_es": ["etiqueta1", "etiqueta2"],
  "areas": ["regulation", "ethical"],
  "topics": ["ai", "quantum"],
  "body_en": "Full article in English in markdown (no frontmatter)",
  "body_es": "Artículo completo en español en markdown (sin frontmatter)"
}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text
    text = re.sub(r"```json|```", "", text).strip()
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        raise ValueError("No se encontró JSON en el artículo de opinión")

    articulo = json.loads(match.group())
    print(f"   ✓ Artículo: «{articulo['title_en']}»")
    return articulo


# ─────────────────────────────────────────────────────────────
# PASO 3: IMÁGENES
# ─────────────────────────────────────────────────────────────

def descargar_imagen(url: str, filename: str) -> tuple | None:
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            content_type = resp.headers.get("Content-Type", "image/jpeg")
            ext = "jpg"
            if "png" in content_type:
                ext = "png"
            elif "webp" in content_type:
                ext = "webp"
            fname = filename + "." + ext
            return fname, data
    except Exception as e:
        print(f"   ⚠ No se pudo descargar imagen {url}: {e}")
        return None


def generar_imagen_svg(title: str, topic: str, filename: str) -> tuple:
    colors = {"ai": "#6366f1", "web3": "#10b981", "quantum": "#f59e0b"}
    color = colors.get(topic.lower(), "#6366f1")
    words = title.split()
    line1 = " ".join(words[:6])
    line2 = " ".join(words[6:12]) if len(words) > 6 else ""
    line2_tag = f'<text x="400" y="310" font-family="system-ui,sans-serif" font-size="26" font-weight="600" fill="white" text-anchor="middle">{line2}</text>' if line2 else ""

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450" viewBox="0 0 800 450">
  <rect width="800" height="450" fill="{color}"/>
  <rect x="0" y="380" width="800" height="70" fill="rgba(0,0,0,0.3)"/>
  <text x="400" y="180" font-family="system-ui,sans-serif" font-size="72" font-weight="bold"
        fill="white" text-anchor="middle" opacity="0.3">#{topic.upper()}</text>
  <text x="400" y="270" font-family="system-ui,sans-serif" font-size="26" font-weight="600"
        fill="white" text-anchor="middle">{line1}</text>
  {line2_tag}
  <text x="400" y="420" font-family="system-ui,sans-serif" font-size="18"
        fill="rgba(255,255,255,0.8)" text-anchor="middle">waiq.technology</text>
</svg>"""
    return filename + ".svg", svg.encode("utf-8")


def preparar_imagen(noticia: dict, slug: str) -> tuple:
    filename = slug
    resultado = descargar_imagen(noticia.get("image_url"), filename)
    if resultado:
        fname, data = resultado
    else:
        fname, data = generar_imagen_svg(noticia["title_en"], noticia.get("topic", "ai"), filename)
    repo_image_path = f"{REPO_PATH_IMAGES}/{fname}"
    return fname, data, repo_image_path


# ─────────────────────────────────────────────────────────────
# PASO 4: GENERAR FRONTMATTER HUGO
# ─────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    text = text.lower().strip()
    for src, dst in [("á","a"),("à","a"),("ä","a"),("â","a"),("é","e"),("è","e"),
                     ("ë","e"),("ê","e"),("í","i"),("ì","i"),("ï","i"),("î","i"),
                     ("ó","o"),("ò","o"),("ö","o"),("ô","o"),("ú","u"),("ù","u"),
                     ("ü","u"),("û","u"),("ñ","n")]:
        text = text.replace(src, dst)
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text[:70].strip("-")


def lista_yaml(items: list) -> str:
    return "\n".join(f'  - "{i}"' for i in items)


def generar_md_noticia(noticia: dict, fecha: str, image_path: str, lang: str) -> tuple:
    title  = noticia["title_en"]       if lang == "en" else noticia["title_es"]
    desc   = noticia["description_en"] if lang == "en" else noticia["description_es"]
    button = f"Read in {noticia['source']}" if lang == "en" else f"Leer en {noticia['source']}"

    topic = noticia.get("topic", "ai").lower()
    extra = [t.lower() for t in noticia.get("extra_topics", []) if t.lower() in ["ai","web3","quantum"]]
    all_topics = list(dict.fromkeys([topic] + extra))
    areas = noticia.get("areas", ["technology"])
    source_url = noticia.get("url", "")

    slug = slugify(noticia["title_en"])
    filename = f"{fecha}-{slug}.md"
    image_ref = f"/{image_path.replace('static/', '')}" if image_path else ""
    repo_path = f"{REPO_PATH_EN_ARTICLES if lang == 'en' else REPO_PATH_ES_ARTICLES}/{filename}"

    content = f"""---
title: "{title.replace('"', "'")}"
date: {fecha}T00:00:00Z
draft: false
description: "{desc[:200].replace('"', "'")}"
topics:
{lista_yaml(all_topics)}
areas:
{lista_yaml(areas)}
categories:
  - "Radar"
source: "{noticia.get('source', '')}"
url_original: "{source_url}"
button_label: "{button}"
{"image: \\"" + image_ref + "\\"" if image_ref else "# image: \\"\\""}
---

{desc}

**{button}:** [{noticia.get('source', '')}]({source_url})
"""
    return repo_path, content


def generar_md_articulo(articulo: dict, fecha: str, image_path: str, lang: str) -> tuple:
    title  = articulo["title_en"]       if lang == "en" else articulo["title_es"]
    desc   = articulo["description_en"] if lang == "en" else articulo["description_es"]
    body   = articulo["body_en"]        if lang == "en" else articulo["body_es"]
    topics = [t.lower() for t in articulo.get("topics", ["ai"]) if t.lower() in ["ai","web3","quantum"]]
    areas  = articulo.get("areas", ["regulation"])

    filename  = f"{fecha}-{articulo['slug']}.md"
    repo_path = f"{REPO_PATH_EN_ARTICLES if lang == 'en' else REPO_PATH_ES_ARTICLES}/{filename}"
    image_ref = f"/{image_path.replace('static/', '')}" if image_path else ""

    content = f"""---
title: "{title.replace('"', "'")}"
date: {fecha}T00:00:00Z
draft: false
description: "{desc[:200].replace('"', "'")}"
topics:
{lista_yaml(topics)}
areas:
{lista_yaml(areas)}
categories:
  - "Radar"
  - "Opinion"
author: "{OPINION_AUTHOR}"
{"image: \\"" + image_ref + "\\"" if image_ref else "# image: \\"\\""}
---

{body}
"""
    return repo_path, content


# ─────────────────────────────────────────────────────────────
# PASO 5: PUSH A GITHUB
# ─────────────────────────────────────────────────────────────

def push_a_github(ficheros_texto: list, ficheros_binarios: list, fecha: str):
    print("🐙 Subiendo ficheros a GitHub...")
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(GITHUB_REPO)
    commit_msg = f"Radar {fecha}"
    total = 0

    for path, content in ficheros_texto:
        try:
            existing = repo.get_contents(path)
            repo.update_file(path, commit_msg, content, existing.sha)
            print(f"   ↻ {path}")
        except GithubException:
            repo.create_file(path, commit_msg, content)
            print(f"   ✓ {path}")
        total += 1
        time.sleep(0.3)

    for path, data in ficheros_binarios:
        try:
            existing = repo.get_contents(path)
            repo.update_file(path, commit_msg, data, existing.sha)
            print(f"   ↻ {path}")
        except GithubException:
            repo.create_file(path, commit_msg, data)
            print(f"   ✓ {path}")
        total += 1
        time.sleep(0.3)

    print(f"   ✓ {total} ficheros — commit: «{commit_msg}»")


# ─────────────────────────────────────────────────────────────
# PASO 6: EMAIL
# ─────────────────────────────────────────────────────────────

def construir_email_html(noticias: list, articulo: dict, fecha: str) -> str:
    topic_colors = {"ai": "#6366f1", "web3": "#10b981", "quantum": "#f59e0b"}
    noticias_html = ""
    for n in noticias:
        color = topic_colors.get(n.get("topic","ai"), "#6366f1")
        noticias_html += f"""
        <div style="border-left:3px solid {color};padding:12px 16px;margin:12px 0;background:#fafafa;border-radius:0 8px 8px 0;">
          <div style="font-size:11px;color:{color};font-weight:700;letter-spacing:1px;margin-bottom:4px;">
            #{n.get('topic','').upper()} · {n.get('source','')}
          </div>
          <a href="{n['url']}" style="font-size:15px;font-weight:700;color:#1a1a2e;text-decoration:none;">{n['title_en']}</a>
          <p style="font-size:13px;color:#555;margin:6px 0 8px;line-height:1.5;">{n['description_en']}</p>
          <a href="{n['url']}" style="font-size:12px;color:{color};">Read article →</a>
        </div>"""

    article_url = f"{HUGO_BASE_URL}/article/{fecha}-{articulo['slug']}/"
    preview = re.sub(r"#{1,6}\s|[*_]", "", articulo["body_en"])[:280].strip() + "..."

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:660px;margin:0 auto;padding:20px;color:#1a1a2e;">
  <div style="background:linear-gradient(135deg,#1a1a2e,#6366f1);padding:28px;border-radius:12px;color:white;margin-bottom:28px;">
    <div style="font-size:11px;letter-spacing:2px;opacity:0.7;margin-bottom:6px;">WAIQ RADAR · {fecha}</div>
    <h1 style="margin:0;font-size:24px;">#WAIQ News Radar</h1>
    <p style="margin:8px 0 0;opacity:0.8;font-size:14px;">{len(noticias)} curated references · Web3 · AI · Quantum</p>
  </div>
  <h2 style="font-size:17px;border-bottom:2px solid #f0f0f0;padding-bottom:8px;">📰 This radar's highlights</h2>
  {noticias_html}
  <div style="background:#f0f0ff;border-radius:12px;padding:22px;margin:28px 0;">
    <div style="font-size:11px;color:#6366f1;font-weight:700;letter-spacing:1px;margin-bottom:8px;">✍️ WAIQ OPINION</div>
    <h3 style="margin:0 0 10px;font-size:17px;">{articulo['title_en']}</h3>
    <p style="font-size:13px;color:#555;margin:0 0 14px;line-height:1.6;">{preview}</p>
    <a href="{article_url}" style="display:inline-block;background:#6366f1;color:white;padding:9px 20px;border-radius:6px;font-size:13px;font-weight:600;text-decoration:none;">Read full article →</a>
  </div>
  <p style="font-size:11px;color:#bbb;text-align:center;margin-top:32px;">
    WAIQ Radar · <a href="{HUGO_BASE_URL}" style="color:#bbb;">waiq.technology</a>
  </p>
</body></html>"""


def enviar_email(noticias: list, articulo: dict, fecha: str):
    print("📧 Enviando email...")
    html = construir_email_html(noticias, articulo, fecha)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"#WAIQ Radar {fecha} — {len(noticias)} references · {articulo['title_en'][:50]}"
    msg["From"]    = GMAIL_USER
    msg["To"]      = EMAIL_RECIPIENTS
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, [r.strip() for r in EMAIL_RECIPIENTS.split(",")], msg.as_string())
    print(f"   ✓ Email enviado a: {EMAIL_RECIPIENTS}")


# ─────────────────────────────────────────────────────────────
# PIPELINE PRINCIPAL
# ─────────────────────────────────────────────────────────────

def main():
    print("\n🚀 WAIQ Radar — Iniciando pipeline")
    print("=" * 50)

    fecha  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # 1. Buscar noticias
    noticias = buscar_noticias(client)
    if not noticias:
        print("⚠️  No se encontraron noticias. Abortando.")
        return

    # 2. Artículo de opinión bilingüe
    articulo = generar_articulo_opinion(client, noticias)

    # 3. Preparar ficheros
    ficheros_texto    = []
    ficheros_binarios = []

    print("📄 Generando ficheros .md e imágenes...")

    # Imagen del artículo de opinión
    art_slug = f"{fecha}-opinion-{articulo['slug']}"
    art_img_fname, art_img_data = generar_imagen_svg(articulo["title_en"], "ai", art_slug)
    art_img_repo_path = f"{REPO_PATH_IMAGES}/{art_img_fname}"
    ficheros_binarios.append((art_img_repo_path, art_img_data))

    # .md del artículo EN y ES
    for lang in ["en", "es"]:
        path, content = generar_md_articulo(articulo, fecha, art_img_repo_path, lang)
        ficheros_texto.append((path, content))
        print(f"   ✓ Artículo [{lang.upper()}]: {path}")

    # Noticias individuales
    for noticia in noticias:
        slug = slugify(noticia["title_en"])
        img_fname, img_data, img_repo_path = preparar_imagen(noticia, f"{fecha}-{slug}")
        ficheros_binarios.append((img_repo_path, img_data))
        for lang in ["en", "es"]:
            path, content = generar_md_noticia(noticia, fecha, img_repo_path, lang)
            ficheros_texto.append((path, content))
        print(f"   ✓ {slug[:55]}")

    print(f"\n   Total: {len(ficheros_texto)} .md + {len(ficheros_binarios)} imágenes")

    # 4. Push a GitHub
    push_a_github(ficheros_texto, ficheros_binarios, fecha)

    # 5. Email
    enviar_email(noticias, articulo, fecha)

    print(f"\n✅ WAIQ Radar completado — {fecha}")
    print(f"   Noticias: {len(noticias)} | Ficheros: {len(ficheros_texto) + len(ficheros_binarios)}")
    print(f"   Commit: «Radar {fecha}»")


if __name__ == "__main__":
    main()