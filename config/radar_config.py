# radar_config.py

# Diccionario para asegurar que los temas y áreas sigan el esquema de Hugo
TOPICS_MAP = {
    "AI": "ai",
    "Web3": "web3",
    "Quantum": "quantum"
}

AREAS_MAP = ["business", "legal", "regulation", "innovation", "technology", "ethical", "ip"]

WAIQ_PROMPT = """
Actúa como el agente autónomo WAIQ Technology Radar.
Tu objetivo es investigar noticias de las últimas 24-48 horas sobre la convergencia de IA, Web3 y Ciencias Cuánticas.

CRITERIOS DE SELECCIÓN:
1. Relevancia en gobernanza, ética o impacto socioeconómico.
2. Casos de uso en España o Europa.
3. Convergencia tecnológica (Framework 3C: Combinación, Convergencia, Composición).

FORMATO DE SALIDA (OBLIGATORIO):
Debes responder EXCLUSIVAMENTE con un objeto JSON válido. No incluyas explicaciones fuera del JSON.

Estructura del JSON:
{
  "email_body": "Contenido del email en texto plano, siguiendo la estructura: WAIQ RADAR [Fecha] / NOTICIAS RELEVANTES / PROPUESTA DE ARTÍCULO DE OPINIÓN.",
  "articles": [
    {
      "filename": "yyyy-mm-dd-slug-en-ingles",
      "button_url": "URL original de la noticia para extraer imagen",
      "frontmatter_es": "--- (YAML con title, date, description, featured: true, image: 'IMAGE_PLACEHOLDER', areas, topics, button_label: 'Leer más', button_url: 'URL') ---",
      "frontmatter_en": "--- (Igual que ES pero en inglés, con button_label: 'Read more') ---",
      "body_es": "Resumen extendido de la noticia en español.",
      "body_en": "Extended summary of the news in english."
    }
  ],
  "opinion_article": {
    "title_es": "Título del artículo",
    "content_es": "3-4 párrafos sustantivos",
    "title_en": "Title in english",
    "content_en": "3-4 paragraphs in english"
  }
}

INSTRUCCIONES TÉCNICAS:
- En 'frontmatter', mantén el campo image como 'IMAGE_PLACEHOLDER'. El script lo reemplazará con la ruta local.
- Los 'topics' permitidos son: ai, web3, quantum.
- Las 'areas' permitidas son: business, legal, regulation, innovation, technology, ethical, ip.
- El 'filename' debe ser la fecha seguida de un slug corto en inglés (ej: 2026-03-11-quantum-spain-nodes).
"""

def get_hugo_template(lang, title, date, description, image, area, topic, body, url=None):
    # Genera el contenido final para Hugo
    btn_label = "Leer más" if lang == "es" else "Read more"
    return f"""---
title: "{title}"
date: {date}
description: "{description}"
featured: "true"
image: "{image}"
areas: ["{area}"]
topics: ["{topic}"]
button_label: "{btn_label}"
button_url: "{url}"
---
{body}
"""