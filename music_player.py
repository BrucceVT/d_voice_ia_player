import asyncio
import json
import logging
import ssl
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional, List
import discord
import yt_dlp

logger = logging.getLogger("MusicAIBot.Player")

# Opciones de yt-dlp optimizadas para extracción completa de audio sin descargas a disco
YTDL_OPTIONS = {
    'format': 'ba/ba*/bestaudio/best',
    'extractaudio': True,
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'socket_timeout': 10,
    'extractor_args': {
        'youtube': {
            'player_client': ['android_vr', 'android', 'web', 'tvhtml5']
        }
    }
}

# Opciones de FFmpeg para reconexión activa de streams y reproducción de audio puro sin alteraciones
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
ssl_ctx = ssl._create_unverified_context()


def sanitize_query(query: str) -> str:
    """Normaliza texto eliminando acentos, tildes y guiones huérfanos al final para evitar búsquedas incompletas."""
    if query.startswith(("http://", "https://")):
        return query
    normalized = unicodedata.normalize('NFKD', query)
    ascii_str = ''.join([c for c in normalized if not unicodedata.combining(c)])
    cleaned = ascii_str.strip().rstrip(" -:\t\n")
    if "-" in cleaned:
        parts = cleaned.split("-", 1)
        if not parts[1].strip():
            cleaned = parts[0].strip()
    return cleaned


def is_webpage_url(url: str) -> bool:
    """Comprueba si una URL es una página web de video/playlist en lugar de un stream directo de media."""
    if not url or not isinstance(url, str) or not url.startswith(('http://', 'https://')):
        return True
    if '/watch?' in url or 'youtu.be/' in url or '/playlist?' in url or '/shorts/' in url:
        return True
    return False


async def resolve_youtube_oembed_title(url: str) -> Optional[str]:
    """Obtiene el título oficial de un video de YouTube sin autenticación ni bloqueos de IP mediante el endpoint público de oEmbed."""
    if not any(domain in url for domain in ("youtube.com", "youtu.be")):
        return None

    oembed_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(url)}&format=json"
    req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    loop = asyncio.get_running_loop()

    def _fetch():
        try:
            with urllib.request.urlopen(req, timeout=5, context=ssl_ctx) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    return data.get("title")
        except Exception as e:
            logger.warning(f"Error resolviendo oEmbed para YouTube URL '{url}': {e}")
        return None

    return await loop.run_in_executor(None, _fetch)


def extract_sc_entry(sc_target: str) -> Optional[dict]:
    """Extrae la mejor entrada de audio completa desde SoundCloud dado un término scsearch."""
    opts = dict(YTDL_OPTIONS)
    with yt_dlp.YoutubeDL(opts) as ytdl_sc:
        info = ytdl_sc.extract_info(sc_target, download=False)
        if info and 'entries' in info and info['entries']:
            full_tracks = [e for e in info['entries'] if e and e.get('duration', 0) > 45]
            selected_entry = full_tracks[0] if full_tracks else info['entries'][0]
            stream_url = get_direct_stream_from_info(selected_entry) or selected_entry.get('url')
            if stream_url and not is_webpage_url(stream_url):
                selected_entry['direct_stream_url'] = stream_url
                return selected_entry
    return None


async def resolve_via_itunes_api(query: str) -> Optional[dict]:
    """Resuelve metadatos y título oficial de la canción a través de iTunes Search API."""
    cleaned_q = sanitize_query(query)
    if cleaned_q.startswith(("http://", "https://")):
        return None

    url = f"https://itunes.apple.com/search?term={urllib.parse.quote(cleaned_q)}&entity=song&limit=1"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    loop = asyncio.get_running_loop()

    def _fetch():
        try:
            with urllib.request.urlopen(req, timeout=4, context=ssl_ctx) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                results = data.get('results', [])
                if results:
                    item = results[0]
                    artist = item.get('artistName', '')
                    track = item.get('trackName', '')
                    preview = item.get('previewUrl')
                    title = f"{artist} - {track}" if artist and track else (track or artist or cleaned_q)
                    webpage_url = item.get('trackViewUrl') or item.get('collectionViewUrl') or f"https://music.apple.com"
                    duration = int(item.get('trackTimeMillis', 30000) / 1000)
                    return {
                        "title": title,
                        "webpage_url": webpage_url,
                        "stream_url": preview,
                        "duration": duration
                    }
        except Exception as e:
            logger.warning(f"Error en iTunes Search API: {e}")
        return None

    return await loop.run_in_executor(None, _fetch)


def get_direct_stream_from_info(info_dict: dict) -> Optional[str]:
    """Obtiene la URL directa de audio a partir del diccionario de información de yt-dlp."""
    if not info_dict:
        return None

    url = info_dict.get('url')
    if url and not is_webpage_url(url):
        return url

    formats = info_dict.get('formats', [])
    if formats:
        audio_formats = [f for f in formats if f.get('url') and f.get('acodec') != 'none']
        if not audio_formats:
            audio_formats = [f for f in formats if f.get('url')]

        if audio_formats:
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
        """Busca o procesa la URL de forma asíncrona resolviendo el título exacto y el stream completo."""
        loop = asyncio.get_running_loop()
        cleaned_query = sanitize_query(query)
        is_url = cleaned_query.startswith(("http://", "https://"))
        target_search_term = cleaned_query

        # 1. Si la consulta no es una URL y parece ambigua o corta, resolver el título oficial con iTunes
        if not is_url and ("-" not in cleaned_query or len(cleaned_query.split()) < 2):
            logger.info(f"Búsqueda ambigua '{cleaned_query}'. Resolviendo título oficial con iTunes...")
            itunes_meta = await resolve_via_itunes_api(cleaned_query)
            if itunes_meta and itunes_meta.get("title"):
                target_search_term = itunes_meta["title"]
                logger.info(f"iTunes resolvió el tema oficial: '{target_search_term}'")

        # 2. Extracción de stream completo vía SoundCloud (100% libre de bloqueos de IP en la nube)
        if not is_url:
            sc_target = f"scsearch5:{target_search_term}"
            try:
                sc_data = await loop.run_in_executor(None, extract_sc_entry, sc_target)
                if sc_data and sc_data.get("direct_stream_url"):
                    title = sc_data.get("title", target_search_term)
                    webpage_url = sc_data.get("webpage_url") or query
                    stream_url = sc_data.get("direct_stream_url")
                    duration = int(sc_data.get("duration", 0))
                    logger.info(f"Extracción COMPLETA exitosa vía SoundCloud para '{title}' ({duration}s)")
                    return cls(
                        title=title,
                        webpage_url=webpage_url,
                        stream_url=stream_url,
                        duration=duration,
                        requester=requester
                    )
            except Exception as sc_err:
                logger.warning(f"Extracción SoundCloud falló para '{target_search_term}': {sc_err}")

        # 3. Extracción de stream completo vía YouTube yt-dlp
        search_target = target_search_term if is_url else f"ytsearch1:{target_search_term}"

        def _extract():
            def _resolve_entry(extractor_instance, target):
                logger.info(f"Extrayendo stream de audio completo con yt-dlp para: {target}")
                info = extractor_instance.extract_info(target, download=False)
                if not info:
                    raise ValueError(f"No se obtuvieron datos de extracción para {target}")

                if 'entries' in info and info['entries']:
                    entry = info['entries'][0]
                else:
                    entry = info

                if not entry:
                    raise ValueError("La búsqueda no devolvió ninguna entrada válida.")

                stream_url = get_direct_stream_from_info(entry)

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
                logger.info(f"Stream de audio completo ({entry.get('duration')}s) obtenido para '{entry.get('title')}': {str(stream_url)[:50]}...")
                return entry

            try:
                return _resolve_entry(ytdl, search_target)
            except Exception as first_err:
                logger.warning(f"Búsqueda primaria YouTube falló ({first_err}). Reintentando con cliente TVHTML5...")
                fallback_opts = dict(YTDL_OPTIONS)
                fallback_opts['extractor_args'] = {
                    'youtube': {
                        'player_client': ['tvhtml5', 'web']
                    }
                }
                with yt_dlp.YoutubeDL(fallback_opts) as ytdl_fallback:
                    return _resolve_entry(ytdl_fallback, search_target)

        data = None
        try:
            data = await loop.run_in_executor(None, _extract)
        except Exception as yt_err:
            logger.warning(f"yt-dlp falló para '{target_search_term}': {yt_err}")

        if data and data.get("direct_stream_url"):
            title = data.get("title", "Canción Desconocida")
            webpage_url = data.get("webpage_url") or (f"https://www.youtube.com/watch?v={data.get('id')}" if data.get('id') else query)
            stream_url = data.get("direct_stream_url") or data.get("url") or ""
            duration = int(data.get("duration", 0))

            if stream_url and not is_webpage_url(stream_url):
                return cls(
                    title=title,
                    webpage_url=webpage_url,
                    stream_url=stream_url,
                    duration=duration,
                    requester=requester
                )

        # 4. Fallback de resolución inteligente para URLs de YouTube cuando la IP del servidor es bloqueada ("Sign in to confirm you're not a bot")
        if is_url and any(domain in cleaned_query for domain in ("youtube.com", "youtu.be")):
            logger.info(f"YouTube bloqueó la extracción directa para la URL '{cleaned_query}'. Obteniendo título del video vía oEmbed...")
            yt_title = await resolve_youtube_oembed_title(cleaned_query)
            if yt_title:
                clean_title = sanitize_query(yt_title)
                logger.info(f"Título resuelto vía oEmbed: '{yt_title}'. Buscando pista alternativa en SoundCloud...")
                sc_fallback_target = f"scsearch5:{clean_title}"
                try:
                    sc_data = await loop.run_in_executor(None, extract_sc_entry, sc_fallback_target)
                    if sc_data and sc_data.get("direct_stream_url"):
                        title = sc_data.get("title") or yt_title
                        webpage_url = sc_data.get("webpage_url") or cleaned_query
                        stream_url = sc_data.get("direct_stream_url")
                        duration = int(sc_data.get("duration", 0))
                        logger.info(f"Éxito: Audio resuelto vía SoundCloud para '{title}' ({duration}s)")
                        return cls(
                            title=title,
                            webpage_url=webpage_url,
                            stream_url=stream_url,
                            duration=duration,
                            requester=requester
                        )
                except Exception as sc_url_err:
                    logger.warning(f"Fallback SoundCloud para URL de YouTube falló: {sc_url_err}")

        # 4. Fallback de emergencia a vista previa de iTunes si la extracción de YouTube y SoundCloud fallaran por completo
        logger.warning(f"Iniciando vista previa de iTunes como último recurso para: '{target_search_term}'")
        itunes_fallback = await resolve_via_itunes_api(target_search_term)
        if itunes_fallback and itunes_fallback.get("stream_url"):
            return cls(
                title=itunes_fallback["title"],
                webpage_url=itunes_fallback["webpage_url"],
                stream_url=itunes_fallback["stream_url"],
                duration=itunes_fallback["duration"],
                requester=requester
            )

        raise ValueError(f"No se pudo resolver el stream de audio para: '{query}'")


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
