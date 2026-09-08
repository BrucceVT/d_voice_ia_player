import asyncio
import logging
import os
import sys
import discord
from discord.ext import commands

from config import config

logger = logging.getLogger("MusicAIBot.Main")


async def handle_health_check(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Responde 200 OK a las peticiones HTTP de Render (Health Check)."""
    try:
        await reader.read(1024)
        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/plain\r\n"
            "Content-Length: 17\r\n"
            "Connection: close\r\n\r\n"
            "Bot status: OK 🤖"
        )
        writer.write(response.encode("utf-8"))
        await writer.drain()
    except Exception as e:
        logger.debug(f"Error en health check request: {e}")
    finally:
        writer.close()
        await writer.wait_closed()


async def start_health_server() -> None:
    """Inicia un servidor HTTP ligero para satisfacer el Health Check de Render Web Service."""
    port = int(os.getenv("PORT", "8080"))
    server = await asyncio.start_server(handle_health_check, "0.0.0.0", port)
    logger.info(f"Servidor HTTP de Health Check escuchando en 0.0.0.0:{port}")


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
        
        # Iniciar servidor de Health Check para Render
        asyncio.create_task(start_health_server())

    async def on_ready(self) -> None:
        """Callback ejecutado cuando el bot inicia sesión y está listo."""
        if self.user:
            logger.info(f"Bot autenticado correctamente como '{self.user.name}' (ID: {self.user.id})")
            logger.info("El bot está listo para recibir comandos de música asistidos por Gemini AI 🤖🎵")
            
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
