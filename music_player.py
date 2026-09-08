import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, List
import discord
import yt_dlp

logger = logging.getLogger("MusicAIBot.Player")

# Opciones de yt-dlp optimizadas con spoofing de cliente móvil (iOS/mweb) para bypass en la nube
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
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'extractor_args': {
        'youtube': {
            'player_client': ['ios', 'mweb', 'android'],
            'skip': ['webpage']
        }
    },
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
    }
}

# Opciones de FFmpeg para reconexión activa de streams y optimización de buffer
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


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
        
        # Si no es una URL directa, utilizar búsqueda de YouTube
        search_target = query if query.startswith(("http://", "https://")) else f"ytsearch:{query}"

        def _extract():
            try:
                data = ytdl.extract_info(search_target, download=False)
                if 'entries' in data and data['entries']:
                    return data['entries'][0]
                return data
            except Exception as first_err:
                logger.warning(f"Extracción primaria falló ({first_err}). Reintentando con cliente TVHTML5/iOS...")
                fallback_opts = dict(YTDL_OPTIONS)
                fallback_opts['extractor_args'] = {
                    'youtube': {
                        'player_client': ['tvhtml5', 'ios', 'android_vr']
                    }
                }
                with yt_dlp.YoutubeDL(fallback_opts) as ytdl_fallback:
                    data = ytdl_fallback.extract_info(search_target, download=False)
                    if 'entries' in data and data['entries']:
                        return data['entries'][0]
                    return data

        data = await loop.run_in_executor(None, _extract)

        if not data:
            raise ValueError(f"No se pudo encontrar ninguna canción con la consulta: {query}")

        title = data.get("title", "Canción Desconocida")
        webpage_url = data.get("webpage_url", query)
        stream_url = data.get("url", "")
        duration = int(data.get("duration", 0))

        if not stream_url:
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
            self.voice_client.resume()
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
