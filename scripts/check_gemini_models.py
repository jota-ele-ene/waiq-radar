import os
from dotenv import load_dotenv
from google import genai

env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
load_dotenv(dotenv_path=env_path)

def discover_models():
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    
    try:
        print("📡 Listando modelos disponibles...")
        models = list(client.models.list())
        if not models:
            print("No se encontraron modelos vinculados a esta API Key.")
            return

        for m in models:
            # Imprimimos el ID y todos los atributos disponibles para no fallar
            attrs = [a for a in dir(m) if not a.startswith('_')]
            print(f"-> ID: {m.name}")
            # print(f"   Atributos disponibles: {attrs}")
            
    except Exception as e:
        print(f"❌ Error crítico: {e}")

if __name__ == "__main__":
    discover_models()