import asyncio
import logging
import os
import sys
import urllib.request
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


async def keep_alive_loop() -> None:
    """Mantiene la instancia gratuita de Render activa enviando un ping de salud cada 8 minutos."""
    await asyncio.sleep(15)
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        logger.info("RENDER_EXTERNAL_URL no detectada en variables de entorno; el auto-ping externo está omitido.")
        return

    logger.info(f"Auto-ping configurado para la URL de Render: {render_url}")
    while True:
        try:
            await asyncio.sleep(480)  # 8 minutos (480 segundos)
            logger.info(f"Enviando heartbeat de auto-ping a: {render_url}")
            
            def _ping():
                req = urllib.request.Request(render_url, headers={"User-Agent": "RenderKeepAlive/1.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    return resp.status

            loop = asyncio.get_running_loop()
            status = await loop.run_in_executor(None, _ping)
            logger.info(f"Heartbeat de auto-ping exitoso (Status: {status})")
        except Exception as e:
            logger.warning(f"Advertencia en heartbeat de auto-ping: {e}")


class MusicBot(commands.Bot):
    """Bot de Discord principal con soporte para Slash Commands y Cogs asíncronos."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.voice_states = True
        # Slash Commands (app_commands) no requieren Privileged Intents
        intents.message_content = False

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self) -> None:
        """Inicialización asíncrona previa al login: Cargar cogs e iniciar servidor de salud."""
        logger.info("Cargando módulos y cogs...")
        await self.load_extension("cogs.music")
        
        # Iniciar servidor HTTP de salud y bucle de auto-ping
        asyncio.create_task(start_health_server())
        asyncio.create_task(keep_alive_loop())

    async def on_ready(self) -> None:
        """Callback ejecutado cuando el bot inicia sesión y está listo."""
        if self.user:
            logger.info(f"Bot autenticado correctamente como '{self.user.name}' (ID: {self.user.id})")
            
            # Sincronizar el árbol de Slash Commands al conectar
            try:
                synced = await self.tree.sync()
                logger.info(f"¡Sincronización exitosa! {len(synced)} comando(s) registrados globalmente.")
            except Exception as e:
                logger.error(f"Error al sincronizar command tree: {e}")

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
