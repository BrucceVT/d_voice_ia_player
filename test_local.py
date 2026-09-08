import asyncio
import os
import sys
import logging
from dotenv import load_dotenv

# Cargar variables de entorno si existen en .env
load_dotenv()

# Configurar logging para ver detalles de prueba
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from gemini_service import GeminiService
from music_player import Song, sanitize_query

async def main():
    print("=" * 60)
    print("INICIANDO PRUEBAS LOCALES DE INTERPRETACION Y EXTRACCION DE AUDIO")
    print("=" * 60)

    # 1. Probar Gemini AI si hay clave API
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        print("No se encontro GEMINI_API_KEY en .env. (Si tienes una clave API, agrégala en .env para probar Gemini).")
    else:
        print("\n1. Probando Gemini AI (interpretacion de prompts):")
        serv = GeminiService(api_key=gemini_key)
        
        test_prompts = [
            "cancion run rabbit",
            "cancion melancolica de rock argentino",
            "musica alegre para trabajar",
            "Soda Stereo"
        ]

        for p in test_prompts:
            try:
                res = await serv.interpret_search_prompt(p)
                print(f"  Prompt: '{p}' -> Interpretado: '{res}'")
            except Exception as e:
                print(f"  Error con prompt '{p}': {e}")

    # 2. Probar Extraccion de Streams Completos de Audio
    print("\n2. Probando Extraccion de Streams de Audio (music_player.py):")
    
    test_queries = [
        "Eminem - Rabbit Run",
        "Soda Stereo - Te Para Tres",
        "Soda Stereo - De Musica Ligera",
        "cancion run rabbit",
        "https://youtu.be/zC7Mn1_sDlk?si=MYEgU77T_4QqC2Ke"
    ]

    for q in test_queries:
        print(f"\nProcesando consulta: '{q}'...")
        try:
            song = await Song.from_query(q, requester="TesterLocal")
            mins, secs = divmod(song.duration, 60)
            safe_title = song.title.encode('ascii', 'ignore').decode('ascii')
            print(f"  EXITO:")
            print(f"     - Titulo: {safe_title}")
            print(f"     - Duracion: {mins}m {secs:02d}s ({song.duration} segundos)")
            print(f"     - Webpage URL: {song.webpage_url}")
            print(f"     - Stream URL: {song.stream_url[:75]}...")
            
            if song.duration < 60:
                print(f"  ADVERTENCIA: La cancion dura menos de 1 minuto ({song.duration}s).")
            else:
                print(f"  CANCION COMPLETA VALIDADA ({mins}m {secs:02d}s >= 1 min).")
        except Exception as e:
            print(f"  ERROR al procesar '{q}': {e}")

    print("\n" + "=" * 60)
    print("PRUEBAS LOCALES FINALIZADAS CON EXITO")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
