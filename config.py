import os
import logging
from dataclasses import dataclass
from dotenv import load_dotenv

# Cargar variables de entorno desde archivo .env si existe
load_dotenv()

# Configurar sistema de logs centralizado
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger("MusicAIBot")

@dataclass(frozen=True)
class Config:
    """Configuración inmutable de la aplicación cargada desde el entorno."""
    discord_token: str
    gemini_api_key: str
    log_level: str = "INFO"

    @classmethod
    def load(cls) -> "Config":
        token = os.getenv("DISCORD_TOKEN", "").strip()
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        log_level = os.getenv("LOG_LEVEL", "INFO").strip()

        missing = []
        if not token:
            missing.append("DISCORD_TOKEN")
        if not gemini_key:
            missing.append("GEMINI_API_KEY")

        if missing:
            raise ValueError(
                f"Faltan las siguientes variables de entorno requeridas: {', '.join(missing)}. "
                "Asegúrate de configurarlas en el archivo .env o en las variables de tu proveedor Cloud."
            )

        return cls(
            discord_token=token,
            gemini_api_key=gemini_key,
            log_level=log_level
        )

# Instancia global de configuración
config = Config.load()
