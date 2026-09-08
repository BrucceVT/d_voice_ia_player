import logging
from typing import List
from google import genai
from google.genai import types

logger = logging.getLogger("MusicAIBot.Gemini")

class GeminiService:
    """Servicio de inteligencia artificial utilizando el SDK moderno google-genai.
    
    Implementa llamadas totalmente asíncronas vía client.aio.models.generate_content
    con fallbacks automáticos de modelos (gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-flash).
    """

    def __init__(self, api_key: str):
        """Inicializa el cliente de Google GenAI."""
        self.client = genai.Client(api_key=api_key)
        self.candidate_models = ["gemini-3.6-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

    async def interpret_search_prompt(self, user_prompt: str) -> str:
        """Interpreta una solicitud o descripción informal y devuelve un término de búsqueda preciso.
        
        Ejemplo: 'canción melancólica de rock argentino' -> 'Soda Stereo - Té Para Tres'
        """
        system_instruction = (
            "Eres un experto DJ musical con profundo conocimiento universal de canciones. "
            "Tu tarea es recibir una descripción informal, estado de ánimo o género entregado por un usuario "
            "y responder ÚNICAMENTE con el término de búsqueda ideal en formato '[Nombre de Canción] [Nombre de Artista]'. "
            "No incluyas introducciones, ni comentarios, ni comillas, ni explicaciones adicionales. "
            "Si la entrada ya parece un título exacto o enlace, devuélvela limpia."
        )

        prompt = f"Solicitud del usuario: '{user_prompt}'"

        for model_name in self.candidate_models:
            try:
                logger.info(f"Invocando Gemini API ({model_name}) para prompt: '{user_prompt}'")
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.3,
                        max_output_tokens=100,
                    )
                )

                if response and response.text:
                    result = response.text.strip()
                    # Eliminar comillas extras si las hay
                    result = result.replace('"', '').replace("'", "")
                    logger.info(f"Gemini ({model_name}) interpretó exitosamente '{user_prompt}' -> '{result}'")
                    return result
            except Exception as e:
                logger.warning(f"Error al invocar modelo Gemini {model_name}: {e}")

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
            "Responde ÚNICAMENTE con el término de búsqueda en formato '[Nombre de Canción] [Nombre de Artista]'. "
            "No incluyas explicaciones, saluación, viñetas ni comillas."
        )

        prompt = (
            f"Historial reciente de la sesión:\n{history_str}\n\n"
            "¿Cuál debería ser la siguiente canción recomendada?"
        )

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
                    recommendation = response.text.strip().replace('"', '').replace("'", "")
                    logger.info(f"Gemini ({model_name}) generó recomendación -> '{recommendation}'")
                    return recommendation
            except Exception as e:
                logger.warning(f"Error con modelo Gemini {model_name} en recommend: {e}")

        return "Soda Stereo - De Música Ligera"
