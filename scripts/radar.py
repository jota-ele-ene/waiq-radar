import os
import sys
import json
import argparse
import requests
import subprocess
from datetime import datetime, timedelta
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from google import genai

# 1. Rutas y Entorno
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(BASE_DIR)
load_dotenv(dotenv_path=os.path.join(BASE_DIR, '.env'))

from config import radar_config as cfg

class WaiqRadar:
    def __init__(self, output_dir=None):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.repo_url = os.getenv("REPO_URL") # Asegúrate de añadir esto a tu .env
        self.model_id = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
        
        # Cliente v1beta (más flexible para el modo JSON en este SDK)
        self.client = genai.Client(api_key=self.api_key, http_options={'api_version': 'v1beta'})
        
        self.output_base = output_dir or os.path.join(BASE_DIR, "output")
        self.logs_dir = os.path.join(BASE_DIR, "logs")
        
        for sub in ['es', 'en', 'static/images/upload']:
            os.makedirs(os.path.join(self.output_base, sub), exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)

    def sync_repo(self):
        """Asegura que tenemos lo último del repo antes de calcular fechas."""
        print("🔄 Sincronizando repositorio local con remoto...")
        try:
            if os.path.exists(os.path.join(BASE_DIR, ".git")):
                subprocess.run(["git", "pull"], cwd=BASE_DIR, check=True)
            else:
                print("⚠️ No se detectó repo Git. Saltando sincronización.")
        except Exception as e:
            print(f"⚠️ Error al sincronizar: {e}")

    def get_smart_date_and_history(self):
        """Calcula fecha (último editorial - 2 días) y lista archivos existentes."""
        es_path = os.path.join(self.output_base, "es")
        existing_files = [f.replace('.md', '') for f in os.listdir(es_path) if f.endswith('.md')]
        
        # Buscar el último editorial: YYYY-MM-DD-editorial-waiq.md
        editorials = sorted([f for f in existing_files if "editorial" in f], reverse=True)
        
        if editorials:
            try:
                last_date_str = "-".join(editorials[0].split('-')[:3])
                last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
                target_date = last_date - timedelta(days=2)
                return target_date.strftime("%Y-%m-%d"), existing_files
            except:
                pass
        
        return (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"), existing_files

    def fetch_and_generate(self, forced_since=None):
        self.sync_repo()
        smart_since, history = self.get_smart_date_and_history()
        since = forced_since or smart_since
        
        print(f"🔎 Investigando desde: {since}")
        print(f"🚫 Omitiendo {len(history)} noticias ya publicadas.")

        # Inyectamos la lista de archivos existentes en el prompt para que no los repita
        history_context = f"DO NOT include any of the following stories (already published): {', '.join(history[:50])}"
        full_prompt = f"{cfg.WAIQ_PROMPT}\n\nDate: {datetime.now().strftime('%Y-%m-%d')}\nSince: {since}\n{history_context}"

        try:
            # Eliminamos response_mime_type de config para evitar el error 400 anterior
            # y lo forzamos en el prompt de radar_config.py
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=full_prompt,
                config={'temperature': 0.2} 
            )
            
            # Limpiamos posible basura de markdown del texto
            json_text = response.text.replace('```json', '').replace('```', '').strip()
            data = json.loads(json_text)

            for art in data.get('articles', []):
                # Verificación extra por si la IA ignora el prompt
                if art['filename'] in history:
                    print(f"⏭️ Saltando duplicado: {art['filename']}")
                    continue
                
                print(f"📄 Generando: {art['filename']}")
                # Aquí iría tu lógica de download_image y guardado de archivos...
                self.save_article(art)

        except Exception as e:
            print(f"❌ Error: {e}")

    def save_article(self, art):
        # Lógica de guardado ya funcional que tenías antes
        pass

    def publish(self):
        print("🚀 Publicando...")
        subprocess.run(["git", "add", "."], cwd=BASE_DIR)
        subprocess.run(["git", "commit", "-m", f"Radar Update {datetime.now().isoformat()}"], cwd=BASE_DIR)
        subprocess.run(["git", "push"], cwd=BASE_DIR)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["full", "only-fetch", "only-publish"])
    parser.add_argument("--since", help="Forzar fecha YYYY-MM-DD")
    args = parser.parse_args()

    radar = WaiqRadar()
    if args.mode in ["full", "only-fetch"]:
        radar.fetch_and_generate(forced_since=args.since)
    if args.mode in ["full", "only-publish"]:
        radar.publish()

if __name__ == "__main__":
    main()