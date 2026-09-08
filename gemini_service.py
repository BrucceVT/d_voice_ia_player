import logging
from typing import List
from google import genai
from google.genai import types

logger = logging.getLogger("MusicAIBot.Gemini")

class GeminiService:
    """Servicio de inteligencia artificial utilizando el SDK moderno google-genai.
    
    Implementa llamadas totalmente asíncronas vía client.aio.models.generate_content
    para no bloquear el bucle de eventos de asyncio.
    """

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash"):
        """Inicializa el cliente de Google GenAI."""
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

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

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.3,
                    max_output_tokens=100,
                )
            )

            result = response.text.strip() if response.text else user_prompt
            logger.info(f"Gemini interpretó prompt '{user_prompt}' -> '{result}'")
            return result
        except Exception as e:
            logger.error(f"Error al invocar a Gemini en interpret_search_prompt: {e}")
            # Fallback en caso de error de la API
            return user_prompt

    async def recommend_next_song(self, history: List[str]) -> str:
        """Analiza el historial reciente de reproducciones y recomienda la siguiente canción más coherente.
        
        Args:
            history: Lista con los títulos de las últimas canciones reproducidas.
            
        Returns:
            Término de búsqueda recomendado en formato '[Título] [Artista]'.
        """
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

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,
                    max_output_tokens=100,
                )
            )

            recommendation = response.text.strip() if response.text else "Queen - Bohemian Rhapsody"
            logger.info(f"Gemini generó recomendación basada en historial -> '{recommendation}'")
            return recommendation
        except Exception as e:
            logger.error(f"Error al invocar a Gemini en recommend_next_song: {e}")
            return "Soda Stereo - De Música Ligera"
