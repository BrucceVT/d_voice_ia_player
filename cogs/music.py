import discord
from discord import app_commands
from discord.ext import commands
import logging
from typing import Dict, Optional

from music_player import GuildMusicManager, Song
from gemini_service import GeminiService

logger = logging.getLogger("MusicAIBot.Cog")


class MusicCog(commands.Cog):
    """Cog principal que registra los comandos de música e interactúa con Gemini y discord.py."""

    def __init__(self, bot: commands.Bot, gemini_service: GeminiService):
        self.bot = bot
        self.gemini = gemini_service
        self.managers: Dict[int, GuildMusicManager] = {}

    def get_manager(self, guild_id: int) -> GuildMusicManager:
        """Obtiene o crea un GuildMusicManager único para el servidor especificado."""
        if guild_id not in self.managers:
            self.managers[guild_id] = GuildMusicManager(guild_id, self.bot)
        return self.managers[guild_id]

    async def _ensure_voice_connection(self, interaction: discord.Interaction) -> Optional[discord.VoiceClient]:
        """Asegura que el usuario esté en un canal de voz y conecta al bot si es necesario."""
        if not interaction.user or not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("⚠️ Este comando solo se puede usar dentro de un servidor.")
            return None

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send("❌ Debes estar conectado a un canal de voz para reproducir música.")
            return None

        voice_channel = interaction.user.voice.channel
        guild = interaction.guild

        if not guild:
            return None

        manager = self.get_manager(guild.id)

        if not manager.voice_client or not manager.voice_client.is_connected():
            manager.voice_client = await voice_channel.connect()
            logger.info(f"Bot conectado al canal de voz '{voice_channel.name}' en guild {guild.id}")
        elif manager.voice_client.channel != voice_channel:
            await manager.voice_client.move_to(voice_channel)
            logger.info(f"Bot movido al canal de voz '{voice_channel.name}' en guild {guild.id}")

        return manager.voice_client

    @app_commands.command(
        name="play",
        description="Reproduce una canción vía URL, búsqueda o prompt descriptivo procesado por IA."
    )
    @app_commands.describe(
        cancion_o_prompt="Enlace directos, título o descripción informal (ej: 'rock argentino melancólico')"
    )
    async def play(self, interaction: discord.Interaction, cancion_o_prompt: str):
        """Comando /play con soporte para Gemini AI e intenciones complejas."""
        # Prevenir timeouts deferiendo la respuesta inmediatamente
        await interaction.response.defer()

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ Este comando debe ejecutarse en un servidor.")
            return

        voice_client = await self._ensure_voice_connection(interaction)
        if not voice_client:
            return

        manager = self.get_manager(guild.id)
        search_query = cancion_o_prompt.strip()

        # Si el usuario no proporcionó una URL directa, consultar a Gemini para entender la intención
        is_url = search_query.startswith(("http://", "https://"))
        if not is_url:
            ai_status_msg = await interaction.followup.send("🤖 *Analizando tu solicitud con Gemini AI...*", wait=True)
            search_query = await self.gemini.interpret_search_prompt(cancion_o_prompt)

        try:
            song = await Song.from_query(search_query, interaction.user.display_name)
            await manager.add_to_queue(song)

            embed = discord.Embed(
                title="🎵 Canción Añadida a la Cola",
                description=f"[{song.title}]({song.webpage_url})",
                color=discord.Color.brand_green()
            )
            embed.add_field(name="Solicitado por", value=song.requester, inline=True)
            
            if song.duration > 0:
                mins, secs = divmod(song.duration, 60)
                embed.add_field(name="Duración", value=f"{mins}:{secs:02d}", inline=True)
            
            if not is_url and search_query != cancion_o_prompt:
                embed.set_footer(text=f"💡 Prompt original: '{cancion_o_prompt}' -> Gemini Búsqueda: '{search_query}'")

            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Error procesando comando /play para '{cancion_o_prompt}': {e}")
            await interaction.followup.send(f"❌ Error al procesar la canción: `{str(e)}`")

    @app_commands.command(name="skip", description="Salta la canción actualmente en reproducción.")
    async def skip(self, interaction: discord.Interaction):
        """Comando /skip para avanzar a la siguiente canción."""
        await interaction.response.defer()
        guild = interaction.guild
        if not guild:
            return

        manager = self.get_manager(guild.id)
        skipped = await manager.skip()

        if skipped:
            await interaction.followup.send("⏭️ Canción saltada con éxito.")
        else:
            await interaction.followup.send("⚠️ No hay ninguna canción en reproducción para saltar.")

    @app_commands.command(name="pause", description="Pausa la reproducción actual.")
    async def pause(self, interaction: discord.Interaction):
        """Comando /pause para pausar el reproductor."""
        guild = interaction.guild
        if not guild:
            return

        manager = self.get_manager(guild.id)
        paused = await manager.pause()

        if paused:
            await interaction.response.send_message("⏸️ Reproducción pausada.")
        else:
            await interaction.response.send_message("⚠️ No hay reproducción activa para pausar.")

    @app_commands.command(name="resume", description="Reanuda la reproducción pausada.")
    async def resume(self, interaction: discord.Interaction):
        """Comando /resume para reanudar el audio."""
        guild = interaction.guild
        if not guild:
            return

        manager = self.get_manager(guild.id)
        resumed = await manager.resume()

        if resumed:
            await interaction.response.send_message("▶️ Reproducción reanudada.")
        else:
            await interaction.response.send_message("⚠️ La reproducción no está pausada.")

    @app_commands.command(name="stop", description="Detiene la música, vacía la cola y desconecta el bot.")
    async def stop(self, interaction: discord.Interaction):
        """Comando /stop para terminar la sesión de audio."""
        guild = interaction.guild
        if not guild:
            return

        manager = self.get_manager(guild.id)
        await manager.stop()
        await interaction.response.send_message("🛑 Reproducción detenida y cola vaciada. ¡Hasta luego!")

    @app_commands.command(name="queue", description="Muestra la canción actual y la lista de reproducción pendiente.")
    async def queue_list(self, interaction: discord.Interaction):
        """Comando /queue para listar el estado actual de la cola."""
        guild = interaction.guild
        if not guild:
            return

        manager = self.get_manager(guild.id)
        songs = manager.get_queue_list()
        current = manager.current_song

        if not current and not songs:
            await interaction.response.send_message("🎶 La cola de reproducción está vacía.")
            return

        embed = discord.Embed(
            title="📜 Cola de Reproducción Actual",
            color=discord.Color.blue()
        )

        if current:
            embed.add_field(
                name="🔊 En Reproducción Ahora",
                value=f"[{current.title}]({current.webpage_url}) | Pedida por: {current.requester}",
                inline=False
            )

        if songs:
            queue_description = ""
            for idx, song in enumerate(songs[:10], start=1):
                queue_description += f"`{idx}.` [{song.title}]({song.webpage_url}) | *{song.requester}*\n"
            
            if len(songs) > 10:
                queue_description += f"\n*... y {len(songs) - 10} canciones más.*"

            embed.add_field(name="⏳ Próximas Canciones", value=queue_description, inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="recommend",
        description="Gemini AI analiza las últimas 3 canciones y añade automáticamente una recomendación."
    )
    async def recommend(self, interaction: discord.Interaction):
        """Comando /recommend asistido por la IA de Gemini."""
        await interaction.response.defer()

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ Este comando debe ejecutarse en un servidor.")
            return

        voice_client = await self._ensure_voice_connection(interaction)
        if not voice_client:
            return

        manager = self.get_manager(guild.id)

        # Solicitar recomendación inteligente a Gemini basado en el historial
        recommended_search = await self.gemini.recommend_next_song(manager.history)

        try:
            song = await Song.from_query(recommended_search, "Gemini AI 🤖")
            await manager.add_to_queue(song)

            embed = discord.Embed(
                title="✨ Recomendación de Gemini AI Encolada",
                description=f"[{song.title}]({song.webpage_url})",
                color=discord.Color.purple()
            )
            if manager.history:
                embed.add_field(
                    name="Basado en tu historial reciente",
                    value="\n".join([f"• {title}" for title in manager.history[-3:]]),
                    inline=False
                )
            embed.set_footer(text="¡Generado automáticamente con el modelo Gemini 2.5 Flash!")

            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Error procesando recomendación de Gemini: {e}")
            await interaction.followup.send(f"❌ No se pudo cargar la recomendación de la IA: `{str(e)}`")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Evento para monitorear el canal de voz y desconectar si el bot se queda solo."""
        if member.bot:
            return

        # Si un usuario abandona un canal donde está el bot
        if before.channel and before.channel.guild:
            guild = before.channel.guild
            manager = self.managers.get(guild.id)

            if manager and manager.voice_client and manager.voice_client.channel == before.channel:
                # Contar miembros reales (no bots) en el canal
                non_bot_members = [m for m in before.channel.members if not m.bot]
                
                if len(non_bot_members) == 0:
                    logger.info(f"El bot se ha quedado solo en el canal de voz de guild {guild.id}. Iniciando temporizador de auto-desconexión.")
                    manager.start_idle_timer(timeout_seconds=180)


async def setup(bot: commands.Bot):
    """Función de registro del Cog para discord.py."""
    # Instanciar servicio Gemini desde la configuración global
    from config import config
    gemini_service = GeminiService(api_key=config.gemini_api_key)
    await bot.add_cog(MusicCog(bot, gemini_service))
