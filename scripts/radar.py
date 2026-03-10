"""
WAIQ Radar — Pipeline principal

Modos de ejecución (variable RADAR_MODE):
  full          — busca + genera artículo + publica en GitHub + email  [default]
  fetch-only    — busca + genera artículo + email + guarda JSON  (sin GitHub)
  publish-only  — lee JSON (RADAR_JSON_PATH) + publica en GitHub + email
"""

import os, re, sys, json, time, smtplib, urllib.request
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic
from github import Github, GithubException

# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO        = os.environ.get("GITHUB_REPO", "jota-ele-ene/waiq-multi")
HUGO_BASE_URL      = os.environ.get("HUGO_BASE_URL", "https://waiq.technology")
GMAIL_USER         = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_RECIPIENTS   = os.environ.get("EMAIL_RECIPIENTS", "")

RADAR_MODE      = os.environ.get("RADAR_MODE", "full").lower()   # full | fetch-only | publish-only
RADAR_JSON_PATH = os.environ.get("RADAR_JSON_PATH", "")           # solo para publish-only
OUTPUT_DIR      = os.environ.get("OUTPUT_DIR", ".")               # carpeta para el JSON

MODEL = "claude-sonnet-4-6"

REPO_PATH_EN  = "content/en/article"
REPO_PATH_ES  = "content/es/article"
REPO_PATH_IMG = "static/images/upload/articles"
OPINION_AUTHOR = "WAIQ Radar"

AREAS_VALIDAS = [
    "regulation", "ethical", "legal", "business", "innovation",
    "governance", "social", "technology", "sovereignty", "democracy",
    "use-cases", "research"
]

WAIQ_MANIFESTO = """
WAIQ (Web3, AI, Quantum) es un foro nacido en Harvard Law School en 2023 que analiza
la convergencia de tecnologías disruptivas desde perspectivas NO técnicas:
gobernanza, regulación, ética, impacto social, modelos de negocio, democracia,
soberanía tecnológica, propiedad intelectual y competitividad.

Busca contenidos que:
- Analicen regulación/gobernanza de IA, Web3 o Quantum (EU AI Act, MiCA, PQC...)
- Aborden impacto social, ético o legal de estas tecnologías
- Traten modelos de negocio innovadores o soberanía digital
- Provengan de fuentes de calidad: think tanks, medios especializados, organismos oficiales
- Tengan perspectiva europea o global, NO meramente técnica
"""

# ─────────────────────────────────────────────────────────────
# 1. BÚSQUEDA
# ─────────────────────────────────────────────────────────────

def buscar_noticias(client):
    print("📡 Buscando noticias relevantes para WAIQ...")
    desde = (datetime.now(timezone.utc) - timedelta(days=4)).strftime("%Y-%m-%d")

    prompt = f"""Eres el editor del radar WAIQ. Contexto:
{WAIQ_MANIFESTO}

Busca noticias desde {desde} sobre regulación/gobernanza IA, aspectos legales/éticos/sociales
de AI·Web3·Quantum, soberanía tecnológica, brecha digital, convergencia WAIQ, modelos de
negocio innovadores y democracia+tecnología. NO noticias técnicas puras.

Por cada noticia devuelve:
- title_en, title_es
- description_en, description_es  (2-3 frases, tono WAIQ)
- url, source, source_domain
- topic: "ai"|"web3"|"quantum"
- extra_topics: [] o lista de otros
- areas: lista de [{", ".join(AREAS_VALIDAS)}]
- image_url: thumbnail o null
- date: YYYY-MM-DD

Devuelve SOLO JSON sin backticks:
{{"noticias":[{{...}},...]}}

Selecciona 8-12 noticias de calidad para juristas, innovadores y directivos."""

    resp = client.messages.create(
        model=MODEL, max_tokens=5000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}]
    )
    text  = "".join(b.text for b in resp.content if hasattr(b, "text"))
    text  = re.sub(r"```json|```", "", text).strip()
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        raise ValueError("JSON no encontrado en respuesta de búsqueda")
    noticias = json.loads(match.group()).get("noticias", [])
    print(f"   ✓ {len(noticias)} noticias")
    return noticias


# ─────────────────────────────────────────────────────────────
# 2. ARTÍCULO DE OPINIÓN
# ─────────────────────────────────────────────────────────────

def generar_articulo(client, noticias):
    print("✍️  Generando artículo de opinión bilingüe...")
    refs = "\n\n".join(
        f"[{n.get('topic','').upper()}] {n['title_en']} ({n['source']})\n"
        f"EN: {n['description_en']}\nES: {n['description_es']}\nURL: {n['url']}"
        for n in noticias
    )
    prompt = f"""Eres el articulista de WAIQ. Contexto:
{WAIQ_MANIFESTO}

Noticias del radar:
{refs}

Escribe artículo de opinión (700-900 palabras por idioma), tono analítico/crítico/propositivo,
perspectiva europea, para juristas y directivos. Usa subtítulos y cita fuentes naturalmente.

Devuelve SOLO JSON sin backticks:
{{"title_en":"...","title_es":"...","slug":"...","description_en":"...","description_es":"...",
"tags_en":[],"tags_es":[],"areas":[],"topics":[],"body_en":"...","body_es":"..."}}"""

    resp = client.messages.create(
        model=MODEL, max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    text  = re.sub(r"```json|```", "", resp.content[0].text).strip()
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        raise ValueError("JSON no encontrado en artículo de opinión")
    art = json.loads(match.group())
    print(f"   ✓ «{art['title_en']}»")
    return art


# ─────────────────────────────────────────────────────────────
# 3. JSON INTERMEDIO
# ─────────────────────────────────────────────────────────────

def guardar_json(noticias, articulo, fecha):
    payload = {
        "fecha": fecha,
        "generado": datetime.now(timezone.utc).isoformat(),
        "noticias": noticias,
        "articulo": articulo
    }
    p = Path(OUTPUT_DIR) / f"radar_{fecha}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   ✓ JSON: {p}")
    return str(p)


def cargar_json(path):
    print(f"📂 Cargando {path}...")
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    print(f"   ✓ {len(d['noticias'])} noticias · «{d['articulo']['title_en']}»")
    return d["noticias"], d["articulo"], d.get("fecha", datetime.now(timezone.utc).strftime("%Y-%m-%d"))


# ─────────────────────────────────────────────────────────────
# 4. IMÁGENES
# ─────────────────────────────────────────────────────────────

def descargar_imagen(url, slug):
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
            ct   = r.headers.get("Content-Type", "image/jpeg")
            ext  = "png" if "png" in ct else "webp" if "webp" in ct else "jpg"
            return f"{slug}.{ext}", data
    except Exception as e:
        print(f"   ⚠ Imagen no descargable: {e}")
        return None


def svg_fallback(title, topic):
    c = {"ai": "#6366f1", "web3": "#10b981", "quantum": "#f59e0b"}.get(topic, "#6366f1")
    w = title.split()
    l1, l2 = " ".join(w[:6]), " ".join(w[6:12])
    l2_tag = f'<text x="400" y="310" font-family="system-ui" font-size="26" font-weight="600" fill="white" text-anchor="middle">{l2}</text>' if l2 else ""
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450" viewBox="0 0 800 450">
  <rect width="800" height="450" fill="{c}"/>
  <rect x="0" y="380" width="800" height="70" fill="rgba(0,0,0,0.3)"/>
  <text x="400" y="180" font-family="system-ui" font-size="72" font-weight="bold" fill="white" text-anchor="middle" opacity="0.25">#{topic.upper()}</text>
  <text x="400" y="270" font-family="system-ui" font-size="26" font-weight="600" fill="white" text-anchor="middle">{l1}</text>
  {l2_tag}
  <text x="400" y="420" font-family="system-ui" font-size="18" fill="rgba(255,255,255,0.8)" text-anchor="middle">waiq.technology</text>
</svg>"""
    return "svg", svg.encode("utf-8")


def preparar_imagen(noticia, slug):
    r = descargar_imagen(noticia.get("image_url"), slug)
    if r:
        fname, data = r
    else:
        ext, data = svg_fallback(noticia["title_en"], noticia.get("topic", "ai"))
        fname = f"{slug}.{ext}"
    return fname, data, f"{REPO_PATH_IMG}/{fname}"


# ─────────────────────────────────────────────────────────────
# 5. MARKDOWN
# ─────────────────────────────────────────────────────────────

def slugify(t):
    t = t.lower()
    for a, b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n"),
                 ("à","a"),("è","e"),("ì","i"),("ò","o"),("ù","u"),("ü","u")]:
        t = t.replace(a, b)
    return re.sub(r"\s+", "-", re.sub(r"[^a-z0-9\s-]", "", t)).strip("-")[:70]


def yml_list(items):
    return "\n".join(f'  - "{i}"' for i in items)


def md_noticia(n, fecha, img_path, lang):
    title  = n["title_en"]       if lang == "en" else n["title_es"]
    desc   = n["description_en"] if lang == "en" else n["description_es"]
    btn    = f"Read in {n['source']}" if lang == "en" else f"Leer en {n['source']}"
    topic  = n.get("topic", "ai").lower()
    topics = list(dict.fromkeys([topic] + [t.lower() for t in n.get("extra_topics", []) if t.lower() in ["ai","web3","quantum"]]))
    slug   = slugify(n["title_en"])
    base   = REPO_PATH_EN if lang == "en" else REPO_PATH_ES
    img    = f"/{img_path.replace('static/','')}" if img_path else ""
    body = f"""---
title: "{title.replace('"',"'")}"
date: {fecha}T00:00:00Z
draft: false
description: "{desc[:200].replace('"',"'")}"
topics:
{yml_list(topics)}
areas:
{yml_list(n.get('areas', ['technology']))}
categories:
  - "Radar"
source: "{n.get('source','')}"
url_original: "{n.get('url','')}"
button_label: "{btn}"
{"image: \"" + img + "\"" if img else "# image: \"\""}
---

{desc}

**{btn}:** [{n.get('source','')}]({n.get('url','')})
"""
    return f"{base}/{fecha}-{slug}.md", body


def md_articulo(art, fecha, img_path, lang):
    title  = art["title_en"]       if lang == "en" else art["title_es"]
    desc   = art["description_en"] if lang == "en" else art["description_es"]
    body   = art["body_en"]        if lang == "en" else art["body_es"]
    topics = [t.lower() for t in art.get("topics", ["ai"]) if t.lower() in ["ai","web3","quantum"]]
    areas  = art.get("areas", ["regulation"])
    base   = REPO_PATH_EN if lang == "en" else REPO_PATH_ES
    img    = f"/{img_path.replace('static/','')}" if img_path else ""
    content = f"""---
title: "{title.replace('"',"'")}"
date: {fecha}T00:00:00Z
draft: false
description: "{desc[:200].replace('"',"'")}"
topics:
{yml_list(topics)}
areas:
{yml_list(areas)}
categories:
  - "Radar"
  - "Opinion"
author: "{OPINION_AUTHOR}"
{"image: \"" + img + "\"" if img else "# image: \"\""}
---

{body}
"""
    return f"{base}/{fecha}-{art['slug']}.md", content


# ─────────────────────────────────────────────────────────────
# 6. CONSTRUIR FICHEROS
# ─────────────────────────────────────────────────────────────

def construir_ficheros(noticias, articulo, fecha):
    txt, bin_ = [], []
    print("📄 Generando ficheros...")

    # Artículo — imagen SVG
    ext, art_data = svg_fallback(articulo["title_en"], "ai")
    art_img = f"{REPO_PATH_IMG}/{fecha}-opinion-{articulo['slug']}.{ext}"
    bin_.append((art_img, art_data))
    for lang in ["en", "es"]:
        p, c = md_articulo(articulo, fecha, art_img, lang)
        txt.append((p, c))
        print(f"   ✓ Artículo [{lang.upper()}]")

    # Noticias
    for n in noticias:
        slug = slugify(n["title_en"])
        fname, data, img_path = preparar_imagen(n, f"{fecha}-{slug}")
        bin_.append((img_path, data))
        for lang in ["en", "es"]:
            txt.append(md_noticia(n, fecha, img_path, lang))
        print(f"   ✓ {slug[:55]}")

    print(f"   Total: {len(txt)} .md + {len(bin_)} imágenes")
    return txt, bin_


# ─────────────────────────────────────────────────────────────
# 7. GITHUB
# ─────────────────────────────────────────────────────────────

def push_github(txt, bin_, fecha):
    print("🐙 Publicando en GitHub...")
    repo = Github(GITHUB_TOKEN).get_repo(GITHUB_REPO)
    msg  = f"Radar {fecha}"
    for path, content in txt + [(p, d) for p, d in bin_]:
        try:
            ex = repo.get_contents(path)
            repo.update_file(path, msg, content, ex.sha)
            print(f"   ↻ {path}")
        except GithubException:
            repo.create_file(path, msg, content)
            print(f"   + {path}")
        time.sleep(0.3)
    print(f"   ✓ Commit: «{msg}»")


# ─────────────────────────────────────────────────────────────
# 8. EMAIL
# ─────────────────────────────────────────────────────────────

def enviar_email(noticias, articulo, fecha, publicado):
    if not (GMAIL_USER and GMAIL_APP_PASSWORD and EMAIL_RECIPIENTS):
        print("   ⚠ Email no configurado — omitido")
        return
    print("📧 Enviando email...")
    colors = {"ai": "#6366f1", "web3": "#10b981", "quantum": "#f59e0b"}
    rows = ""
    for n in noticias:
        c = colors.get(n.get("topic", "ai"), "#6366f1")
        rows += f"""<div style="border-left:3px solid {c};padding:12px 16px;margin:10px 0;background:#fafafa;border-radius:0 8px 8px 0;">
          <div style="font-size:11px;color:{c};font-weight:700;letter-spacing:1px;">#{n.get('topic','').upper()} · {n.get('source','')}</div>
          <a href="{n['url']}" style="font-size:15px;font-weight:700;color:#1a1a2e;text-decoration:none;">{n['title_en']}</a>
          <p style="font-size:13px;color:#555;margin:5px 0 7px;">{n['description_en']}</p>
          <a href="{n['url']}" style="font-size:12px;color:{c};">Read →</a></div>"""

    art_url = f"{HUGO_BASE_URL}/article/{fecha}-{articulo['slug']}/"
    preview = re.sub(r"#{1,6}\s|[*_]", "", articulo["body_en"])[:280] + "..."
    badge   = ('<span style="background:#10b981;color:white;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;">✓ Published</span>'
               if publicado else
               '<span style="background:#f59e0b;color:white;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;">⏳ Preview — pending publication</span>')
    art_btn = (f'<a href="{art_url}" style="display:inline-block;background:#6366f1;color:white;padding:9px 20px;border-radius:6px;font-size:13px;font-weight:600;text-decoration:none;">Read full article →</a>'
               if publicado else
               '<em style="font-size:13px;color:#888;">Pending GitHub upload</em>')

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:660px;margin:0 auto;padding:20px;color:#1a1a2e;">
  <div style="background:linear-gradient(135deg,#1a1a2e,#6366f1);padding:28px;border-radius:12px;color:white;margin-bottom:24px;">
    <div style="font-size:11px;letter-spacing:2px;opacity:0.7;">WAIQ RADAR · {fecha}</div>
    <h1 style="margin:8px 0 4px;font-size:24px;">#WAIQ News Radar</h1>
    <p style="margin:0 0 10px;opacity:0.8;font-size:14px;">{len(noticias)} curated references · Web3 · AI · Quantum</p>
    {badge}
  </div>
  <h2 style="font-size:17px;border-bottom:2px solid #f0f0f0;padding-bottom:8px;">📰 Highlights</h2>
  {rows}
  <div style="background:#f0f0ff;border-radius:12px;padding:22px;margin:24px 0;">
    <div style="font-size:11px;color:#6366f1;font-weight:700;letter-spacing:1px;margin-bottom:8px;">✍️ WAIQ OPINION</div>
    <h3 style="margin:0 0 10px;font-size:17px;">{articulo['title_en']}</h3>
    <p style="font-size:13px;color:#555;margin:0 0 14px;line-height:1.6;">{preview}</p>
    {art_btn}
  </div>
  <p style="font-size:11px;color:#bbb;text-align:center;">WAIQ Radar · <a href="{HUGO_BASE_URL}" style="color:#bbb;">waiq.technology</a></p>
</body></html>"""

    status = "✓ Published" if publicado else "⏳ Preview"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"#WAIQ Radar {fecha} [{status}] — {articulo['title_en'][:50]}"
    msg["From"] = GMAIL_USER
    msg["To"]   = EMAIL_RECIPIENTS
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.sendmail(GMAIL_USER, [r.strip() for r in EMAIL_RECIPIENTS.split(",")], msg.as_string())
    print(f"   ✓ Email enviado")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    print(f"\n🚀 WAIQ Radar [{RADAR_MODE.upper()}]")
    print("=" * 50)
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if RADAR_MODE == "fetch-only":
        if not ANTHROPIC_API_KEY: sys.exit("❌ ANTHROPIC_API_KEY requerida")
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        noticias = buscar_noticias(client)
        if not noticias: sys.exit("⚠️  Sin noticias")
        articulo  = generar_articulo(client, noticias)
        json_path = guardar_json(noticias, articulo, fecha)
        enviar_email(noticias, articulo, fecha, publicado=False)
        print(f"\n✅ fetch-only OK · JSON: {json_path}")

    elif RADAR_MODE == "publish-only":
        if not GITHUB_TOKEN:    sys.exit("❌ GITHUB_TOKEN requerido")
        if not RADAR_JSON_PATH: sys.exit("❌ RADAR_JSON_PATH requerido")
        noticias, articulo, fecha = cargar_json(RADAR_JSON_PATH)
        txt, bin_ = construir_ficheros(noticias, articulo, fecha)
        push_github(txt, bin_, fecha)
        enviar_email(noticias, articulo, fecha, publicado=True)
        print(f"\n✅ publish-only OK · commit «Radar {fecha}»")

    else:  # full
        if not ANTHROPIC_API_KEY: sys.exit("❌ ANTHROPIC_API_KEY requerida")
        if not GITHUB_TOKEN:      sys.exit("❌ GITHUB_TOKEN requerido")
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        noticias = buscar_noticias(client)
        if not noticias: sys.exit("⚠️  Sin noticias")
        articulo  = generar_articulo(client, noticias)
        guardar_json(noticias, articulo, fecha)
        txt, bin_ = construir_ficheros(noticias, articulo, fecha)
        push_github(txt, bin_, fecha)
        enviar_email(noticias, articulo, fecha, publicado=True)
        print(f"\n✅ Pipeline completo · {len(noticias)} noticias · commit «Radar {fecha}»")


if __name__ == "__main__":
    main()