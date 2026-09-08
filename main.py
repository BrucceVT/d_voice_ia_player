import asyncio
import logging
import sys
import discord
from discord.ext import commands

from config import config

logger = logging.getLogger("MusicAIBot.Main")


class MusicBot(commands.Bot):
    """Bot de Discord principal con soporte para Slash Commands y Cogs asíncronos."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.voice_states = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self) -> None:
        """Inicialización asíncrona previa al login: Cargar cogs y sincronizar Slash Commands."""
        logger.info("Cargando módulos y cogs...")
        await self.load_extension("cogs.music")
        
        logger.info("Sincronizando Command Tree (Slash Commands) con Discord...")
        synced = await self.tree.sync()
        logger.info(f"¡Sincronización exitosa! {len(synced)} comando(s) registrados globalmente.")

    async def on_ready(self) -> None:
        """Callback ejecutado cuando el bot inicia sesión y está listo."""
        if self.user:
            logger.info(f"Bot autenticado correctamente como '{self.user.name}' (ID: {self.user.id})")
            logger.info("El bot está listo para recibir comandos de música asistidos por Gemini AI 🤖🎵")
            
            # Establecer estado de presencia
            activity = discord.Activity(
                type=discord.ActivityType.listening,
                name="/play | Gemini Music 🤖"
            )
            await self.change_presence(activity=activity)


async def main():
    bot = MusicBot()
    async with bot:
        await bot.start(config.discord_token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot detenido por señal de interrupción del teclado (KeyboardInterrupt). Exiting...")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Error fatal al iniciar el bot: {e}")
        sys.exit(1)
