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
            'player_client': ['mweb', 'ios', 'android']
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


async def resolve_via_invidious_api(query: str) -> Optional[dict]:
    """Resuelve la búsqueda y la URL directa de audio utilizando instancias públicas de Invidious/Piped."""
    cleaned_q = sanitize_query(query)
    is_url = cleaned_q.startswith(("http://", "https://"))

    video_id = None
    if is_url:
        if 'v=' in cleaned_q:
            video_id = cleaned_q.split('v=')[1].split('&')[0]
        elif 'youtu.be/' in cleaned_q:
            video_id = cleaned_q.split('youtu.be/')[1].split('?')[0]

    invidious_instances = [
        "https://invidious.flokinet.to",
        "https://inv.hostux.net",
        "https://invidious.drgns.space",
        "https://invidious.nerdvpn.de",
        "https://yewtu.be",
        "https://invidious.privacyredirect.com"
    ]

    loop = asyncio.get_running_loop()

    # Paso 1: Si no tenemos video_id, buscar en la API de Invidious
    if not video_id:
        encoded_q = urllib.parse.quote(cleaned_q)
        for base_url in invidious_instances:
            try:
                search_url = f"{base_url}/api/v1/search?q={encoded_q}&type=video"
                req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                
                def _do_search(s_url=search_url, request_obj=req):
                    with urllib.request.urlopen(request_obj, timeout=2.5, context=ssl_ctx) as resp:
                        return json.loads(resp.read().decode('utf-8'))

                results = await loop.run_in_executor(None, _do_search)
                if isinstance(results, list) and len(results) > 0:
                    first = results[0]
                    video_id = first.get("videoId")
                    if video_id:
                        title = first.get("title", cleaned_q)
                        logger.info(f"Invidious Search ({base_url}) encontró video ID '{video_id}' para '{cleaned_q}'")
                        break
            except Exception as e:
                logger.debug(f"Search API {base_url} falló: {e}")

    if not video_id:
        return None

    # Paso 2: Obtener las URLs de audio directo desde la API de detalles de video de Invidious
    for base_url in invidious_instances:
        try:
            details_url = f"{base_url}/api/v1/videos/{video_id}"
            req = urllib.request.Request(details_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

            def _do_details(d_url=details_url, request_obj=req):
                with urllib.request.urlopen(request_obj, timeout=2.5, context=ssl_ctx) as resp:
                    return json.loads(resp.read().decode('utf-8'))

            details = await loop.run_in_executor(None, _do_details)
            title = details.get("title", "Canción Desconocida")
            duration = int(details.get("lengthSeconds", 0))
            webpage_url = f"https://www.youtube.com/watch?v={video_id}"

            adaptive_formats = details.get("adaptiveFormats", [])
            audio_streams = [
                f for f in adaptive_formats 
                if f.get("type", "").startswith("audio/") and f.get("url")
            ]

            if audio_streams:
                # Ordenar por bitrate (bitrate o max (container))
                audio_streams.sort(key=lambda f: int(f.get("bitrate", 0)), reverse=True)
                direct_audio_url = audio_streams[0]["url"]
                logger.info(f"Invidious Video API ({base_url}) obtuvo stream directo de audio para '{title}'")
                return {
                    "title": title,
                    "webpage_url": webpage_url,
                    "stream_url": direct_audio_url,
                    "duration": duration
                }
        except Exception as e:
            logger.debug(f"Details API {base_url} falló: {e}")

    return None


async def resolve_via_itunes_api(query: str) -> Optional[dict]:
    """Resuelve la búsqueda y la URL directa de audio a través de iTunes Search API (100% libre de bloqueos de IP)."""
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
                    if preview:
                        logger.info(f"iTunes Search API resolvió con éxito '{title}' (stream directo AAC)")
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
        """Busca o procesa la URL con yt-dlp de forma asíncrona usando executor thread pool."""
        loop = asyncio.get_running_loop()
        cleaned_query = sanitize_query(query)

        # 1. Intentar obtener el stream directo a través de la API pública de Invidious
        invidious_data = await resolve_via_invidious_api(cleaned_query)
        if invidious_data and invidious_data.get("stream_url"):
            logger.info(f"Extracción exitosa mediante Invidious API para '{invidious_data['title']}'")
            return cls(
                title=invidious_data["title"],
                webpage_url=invidious_data["webpage_url"],
                stream_url=invidious_data["stream_url"],
                duration=invidious_data["duration"],
                requester=requester
            )

        # 2. Intentar yt-dlp con YouTube
        is_url = cleaned_query.startswith(("http://", "https://"))
        search_target = cleaned_query if is_url else f"ytsearch1:{cleaned_query}"

        data = None
        try:
            def _extract():
                def _resolve_entry(extractor_instance, target):
                    logger.info(f"Extrayendo stream con yt-dlp para: {target}")
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
                    logger.info(f"Stream directo obtenido exitosamente para '{entry.get('title')}': {str(stream_url)[:50]}...")
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

            data = await loop.run_in_executor(None, _extract)
        except Exception as yt_err:
            logger.warning(f"yt-dlp falló para '{cleaned_query}': {yt_err}")

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

        # 3. Tier 3: Fallback a iTunes Search API (100% Libre de bloqueos de IP de datacenter)
        logger.info(f"Iniciando Tier 3 iTunes Search API fallback para: '{cleaned_query}'")
        itunes_data = await resolve_via_itunes_api(cleaned_query)
        if itunes_data and itunes_data.get("stream_url"):
            return cls(
                title=itunes_data["title"],
                webpage_url=itunes_data["webpage_url"],
                stream_url=itunes_data["stream_url"],
                duration=itunes_data["duration"],
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
