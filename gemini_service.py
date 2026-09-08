import asyncio
import logging
from typing import List
from google import genai
from google.genai import types

logger = logging.getLogger("MusicAIBot.Gemini")

def _clean_gemini_output(raw_text: str) -> str:
    """Limpia y valida el resultado generado por Gemini, asegurando el formato 'Artista - Canción'."""
    if not raw_text:
        return ""
    result = raw_text.strip().replace('"', '').replace("'", "")
    if result.lower().startswith("topic:"):
        result = result[6:].strip()
    result = result.rstrip(" -:\t\n")
    
    # Validar que tenga el formato Artista - Canción completo
    if "-" in result:
        parts = result.split("-", 1)
        artist = parts[0].strip()
        song = parts[1].strip()
        if artist and song and len(song) >= 2 and len(artist) >= 2:
            return f"{artist} - {song}"
        return ""  # Incompleto (ej: 'Soda -'), descartar para usar fallback
        
    # Si no tiene guion, verificar que sea al menos de 2 palabras (ej: 'Soda Stereo Té Para Tres')
    words = result.split()
    if len(words) >= 2 and len(result) >= 5:
        return result
        
    return ""


class GeminiService:
    """Servicio de inteligencia artificial utilizando el SDK moderno google-genai.
    
    Implementa llamadas totalmente asíncronas vía client.aio.models.generate_content
    con reintentos y rotación de modelos para alta disponibilidad.
    """

    def __init__(self, api_key: str):
        """Inicializa el cliente de Google GenAI."""
        self.client = genai.Client(api_key=api_key)
        self.candidate_models = ["gemini-3.6-flash", "gemini-2.0-flash-exp", "gemini-1.5-flash-latest"]

    async def interpret_search_prompt(self, user_prompt: str) -> str:
        """Interpreta una solicitud o descripción informal y devuelve un término de búsqueda preciso."""
        system_instruction = (
            "Eres un DJ experto en música universal. Tu función es interpretar la solicitud o descripción informal del usuario "
            "y responder ÚNICAMENTE con el nombre del artista y el título exacto de la canción en formato 'Artista - Canción'. "
            "Ejemplo 1: Si recibes 'cancion run rabbit', responde 'Eminem - Rabbit Run'. "
            "Ejemplo 2: Si recibes 'rock argentino melancolico', responde 'Soda Stereo - Té Para Tres'. "
            "OBLIGATORIO: Debes incluir SIEMPRE tanto el Artista COMO el nombre exacto de la Canción en el formato 'Artista - Canción'. "
            "Jamás respondas con nombres de álbumes, bandas sonoras solas ('From 8'), géneros ni comillas. "
            "Responde únicamente con 'Artista - Canción'."
        )

        prompt = f"Solicitud del usuario: '{user_prompt}'"

        for attempt in range(2):  # Reintento en caso de pico 503
            for model_name in self.candidate_models:
                try:
                    logger.info(f"Invocando Gemini API ({model_name}) para prompt: '{user_prompt}'")
                    response = await self.client.aio.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            temperature=0.2,
                            max_output_tokens=100,
                        )
                    )

                    if response and response.text:
                        result = _clean_gemini_output(response.text)
                        if result and len(result) > 2:
                            logger.info(f"Gemini ({model_name}) interpretó exitosamente '{user_prompt}' -> '{result}'")
                            return result
                except Exception as e:
                    logger.warning(f"Error con modelo Gemini {model_name}: {e}")
            
            if attempt == 0:
                await asyncio.sleep(1.0)

        logger.error(f"No se pudo interpretar prompt con Gemini AI. Usando entrada directa: '{user_prompt}'")
        return user_prompt

    async def recommend_next_song(self, history: List[str]) -> str:
        """Analiza el historial reciente de reproducciones y recomienda la siguiente canción más coherente."""
        if not history:
            history_str = "Variado / Éxitos populares"
        else:
            history_str = "\n".join([f"- {song}" for song in history[-3:]])

        system_instruction = (
            "Eres un DJ inteligente de radio. Analiza las últimas canciones reproducidas en la sesión "
            "y recomienda la SIGUIENTE canción que mantenga la coherencia temática, energía o género. "
            "Responde ÚNICAMENTE con el término de búsqueda en formato 'Artista - Canción'. "
            "No incluyas explicaciones, saluación, viñetas ni comillas."
        )

        prompt = (
            f"Historial reciente de la sesión:\n{history_str}\n\n"
            "¿Cuál debería ser la siguiente canción recomendada?"
        )

        for attempt in range(2):
            for model_name in self.candidate_models:
                try:
                    response = await self.client.aio.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            temperature=0.7,
                            max_output_tokens=100,
                        )
                    )

                    if response and response.text:
                        recommendation = _clean_gemini_output(response.text)
                        if recommendation and len(recommendation) > 2:
                            logger.info(f"Gemini ({model_name}) generó recomendación -> '{recommendation}'")
                            return recommendation
                except Exception as e:
                    logger.warning(f"Error con modelo Gemini {model_name} en recommend: {e}")
            
            if attempt == 0:
                await asyncio.sleep(1.0)

        return "Soda Stereo - De Música Ligera"
