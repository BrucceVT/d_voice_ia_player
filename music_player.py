import asyncio
import logging
import unicodedata
from dataclasses import dataclass
from typing import Optional, List
import discord
import yt_dlp

logger = logging.getLogger("MusicAIBot.Player")

# Opciones de yt-dlp optimizadas para extracción completa de audio sin descargas a disco
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'socket_timeout': 8,
    'youtube_include_dash_manifest': False,
    'youtube_include_hls_manifest': False,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'ios']
        }
    },
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    }
}

# Opciones de FFmpeg para reconexión activa de streams y optimización de buffer
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


def is_webpage_url(url: str) -> bool:
    """Comprueba si una URL es una página web de video/playlist en lugar de un stream directo de media."""
    if not url or not isinstance(url, str) or not url.startswith(('http://', 'https://')):
        return True
    if '/watch?' in url or 'youtu.be/' in url or '/playlist?' in url or '/shorts/' in url:
        return True
    return False


def get_direct_stream_from_info(info_dict: dict) -> Optional[str]:
    """Obtiene la URL directa de audio a partir del diccionario de información de yt-dlp."""
    if not info_dict:
        return None

    url = info_dict.get('url')
    if url and not is_webpage_url(url):
        return url

    # Buscar en la lista de formatos
    formats = info_dict.get('formats', [])
    if formats:
        # Filtrar formatos con pista de audio activa (acodec != 'none')
        audio_formats = [f for f in formats if f.get('url') and f.get('acodec') != 'none']
        if not audio_formats:
            # Fallback a cualquier formato con URL
            audio_formats = [f for f in formats if f.get('url')]

        if audio_formats:
            # Ordenar por mejor calidad de audio (abr / tbr)
            audio_formats.sort(key=lambda f: (f.get('abr') or f.get('tbr') or 0), reverse=True)
            candidate = audio_formats[0].get('url')
            if candidate and not is_webpage_url(candidate):
                return candidate

    return None


@dataclass
class Song:
    """Representa una canción cargada y lista para reproducción."""
    title: str
    webpage_url: str
    stream_url: str
    duration: int
    requester: str

    @classmethod
    async def from_query(cls, query: str, requester: str) -> "Song":
        """Busca o procesa la URL con yt-dlp de forma asíncrona usando executor thread pool."""
        loop = asyncio.get_running_loop()
        
        cleaned_query = query.strip()
        is_url = cleaned_query.startswith(("http://", "https://"))
        search_target = cleaned_query if is_url else f"ytsearch1:{cleaned_query}"

        def _extract():
            def _resolve_entry(extractor_instance, target):
                logger.info(f"Extrayendo stream para: {target}")
                data = extractor_instance.extract_info(target, download=False)
                if not data:
                    raise ValueError(f"No se obtuvieron datos de extracción para {target}")

                if 'entries' in data and data['entries']:
                    entry = data['entries'][0]
                else:
                    entry = data

                if not entry:
                    raise ValueError("La búsqueda no devolvió ninguna entrada válida.")

                # Intentar obtener el stream directo inmediatamente del objeto inicial
                stream_url = get_direct_stream_from_info(entry)

                # Si no está presente, resolver metadatos completos usando la URL específica del video
                if not stream_url:
                    vid_url = entry.get('webpage_url') or (f"https://www.youtube.com/watch?v={entry.get('id')}" if entry.get('id') else None)
                    if vid_url:
                        logger.info(f"Resolviendo metadatos completos desde video URL: {vid_url}")
                        full_entry = extractor_instance.extract_info(vid_url, download=False)
                        stream_url = get_direct_stream_from_info(full_entry)
                        if stream_url:
                            entry = full_entry

                if not stream_url:
                    raise ValueError(f"No se pudo resolver un stream directo de media para: {target}")

                entry['direct_stream_url'] = stream_url
                logger.info(f"Stream directo obtenido exitosamente para '{entry.get('title')}': {str(stream_url)[:50]}...")
                return entry

            try:
                # 1. Búsqueda primaria en YouTube (Cliente Android/iOS)
                return _resolve_entry(ytdl, search_target)
            except Exception as first_err:
                logger.warning(f"Búsqueda primaria falló ({first_err}). Reintentando con cliente TVHTML5...")
                # 2. Intentar con cliente de respaldo TVHTML5
                fallback_opts = dict(YTDL_OPTIONS)
                fallback_opts['extractor_args'] = {
                    'youtube': {
                        'player_client': ['tvhtml5', 'web']
                    }
                }
                with yt_dlp.YoutubeDL(fallback_opts) as ytdl_fallback:
                    return _resolve_entry(ytdl_fallback, search_target)

        data = await loop.run_in_executor(None, _extract)

        if not data:
            raise ValueError(f"No se pudo encontrar ninguna canción con la consulta: {query}")

        title = data.get("title", "Canción Desconocida")
        webpage_url = data.get("webpage_url") or (f"https://www.youtube.com/watch?v={data.get('id')}" if data.get('id') else query)
        stream_url = data.get("direct_stream_url") or data.get("url") or ""
        duration = int(data.get("duration", 0))

        if not stream_url or is_webpage_url(stream_url):
            raise ValueError("No se pudo obtener el stream de audio directo.")

        return cls(
            title=title,
            webpage_url=webpage_url,
            stream_url=stream_url,
            duration=duration,
            requester=requester
        )


class GuildMusicManager:
    """Administrador de reproducción de audio, cola de reproducción y temporizador por servidor (Guild)."""

    def __init__(self, guild_id: int, bot: discord.Client):
        self.guild_id = guild_id
        self.bot = bot
        self.queue: asyncio.Queue[Song] = asyncio.Queue()
        self.current_song: Optional[Song] = None
        self.history: List[str] = []
        self.voice_client: Optional[discord.VoiceClient] = None
        self.idle_timer_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def get_queue_list(self) -> List[Song]:
        """Devuelve una lista con los elementos actuales en la cola."""
        return list(self.queue._queue)

    async def add_to_queue(self, song: Song) -> None:
        """Añade una canción a la cola FIFO e inicia reproducción si está inactivo."""
        await self.queue.put(song)
        self.cancel_idle_timer()
        
        if self.voice_client and not self.voice_client.is_playing() and not self.voice_client.is_paused():
            await self.play_next()

    async def play_next(self) -> None:
        """Reproduce la siguiente canción en la cola o activa el temporizador de inactividad."""
        async with self._lock:
            if not self.voice_client or not self.voice_client.is_connected():
                logger.warning(f"Intento de reproducir en guild {self.guild_id} sin conexión de voz.")
                return

            if self.queue.empty():
                self.current_song = None
                logger.info(f"Cola vacía en servidor {self.guild_id}. Iniciando temporizador de auto-desconexión.")
                self.start_idle_timer()
                return

            self.cancel_idle_timer()
            song = await self.queue.get()
            self.current_song = song

            # Registrar en el historial de reproducciones (máximo 10)
            self.history.append(song.title)
            if len(self.history) > 10:
                self.history.pop(0)

            try:
                audio_source = discord.FFmpegPCMAudio(song.stream_url, **FFMPEG_OPTIONS)
                
                loop = asyncio.get_running_loop()
                self.voice_client.play(
                    audio_source,
                    after=lambda error: loop.call_soon_threadsafe(
                        self._handle_song_end, error
                    )
                )
                logger.info(f"Reproduciendo '{song.title}' en servidor {self.guild_id}")
            except Exception as e:
                logger.error(f"Error al reproducir la fuente de audio en guild {self.guild_id}: {e}")
                # Intentar reproducir la siguiente si falla la actual
                await self.play_next()

    def _handle_song_end(self, error: Optional[Exception]) -> None:
        """Callback invocado cuando finaliza una canción."""
        if error:
            logger.error(f"Error durante la reproducción en guild {self.guild_id}: {error}")
        
        # Iniciar la siguiente canción de forma asíncrona
        asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

    async def skip(self) -> bool:
        """Salta la canción actual si hay alguna reproduciéndose."""
        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()
            return True
        return False

    async def pause(self) -> bool:
        """Pausa la reproducción actual."""
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            return True
        return False

    async def resume(self) -> bool:
        """Reanuda la reproducción pausada."""
        if self.voice_client and self.voice_client.is_paused():
            self.resume()
            return True
        return False

    async def stop(self) -> None:
        """Detiene la reproducción, vacía la cola y se desconecta del canal de voz."""
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        
        self.current_song = None
        self.cancel_idle_timer()

        if self.voice_client:
            if self.voice_client.is_playing() or self.voice_client.is_paused():
                self.voice_client.stop()
            await self.voice_client.disconnect()
            self.voice_client = None

    def start_idle_timer(self, timeout_seconds: int = 180) -> None:
        """Inicia el temporizador para desconexión automática tras inactividad (3 minutos)."""
        self.cancel_idle_timer()
        self.idle_timer_task = asyncio.create_task(self._idle_timeout_worker(timeout_seconds))

    def cancel_idle_timer(self) -> None:
        """Cancela el temporizador de inactividad si está en ejecución."""
        if self.idle_timer_task and not self.idle_timer_task.done():
            self.idle_timer_task.cancel()
            self.idle_timer_task = None

    async def _idle_timeout_worker(self, seconds: int) -> None:
        """Tarea asíncrona en segundo plano que espera X segundos y desconecta el bot."""
        try:
            await asyncio.sleep(seconds)
            logger.info(f"Tiempo de inactividad ({seconds}s) alcanzado en servidor {self.guild_id}. Desconectando...")
            await self.stop()
        except asyncio.CancelledError:
            pass
