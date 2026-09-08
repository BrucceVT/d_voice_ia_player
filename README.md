# 🎵 AI-Powered Discord Music Bot (Python 3.12 + Gemini AI + Docker)

Bot de Discord de Música de última generación asistido por Inteligencia Artificial (**Google Gemini AI** con el SDK moderno `google-genai`), diseñado para ejecutarse 24/7 en la nube dentro de un contenedor Docker sin depender de tu máquina local.

---

## 🌟 Características Principales

- 🤖 **Interpretación Inteligente de Prompts (`/play`):** Si pasas una descripción informal (ej. *"canción melancólica de rock argentino"*), Gemini deduce la intención y obtiene el término de búsqueda exacto.
- ✨ **Recomendaciones Inteligentes (`/recommend`):** Analiza las últimas 3 canciones escuchadas y encola la recomendación ideal.
- 🎶 **Streaming de Audio Directo:** Extracción ultra-rápida con `yt-dlp` canalizada vía `FFmpeg` sin descargar archivos pesados al disco.
- ⏹️ **Control Total de Reproducción:** `/play`, `/skip`, `/pause`, `/resume`, `/stop`, `/queue`.
- 🔋 **Auto-Desconexión Inteligente:** Se desconecta automáticamente tras 3 minutos de inactividad o si se queda solo en el canal de voz.
- 🐳 **Dockerizado 24/7:** Optimizado en `python:3.12-slim-bookworm` con usuario no-root.

---

## 📂 Estructura del Repositorio

```text
d_voice_ia_player/
├── cogs/
│   └── music.py           # Cog con Slash Commands y eventos de voz
├── config.py              # Validación de variables de entorno y logger
├── gemini_service.py      # Integración asíncrona con el SDK google-genai
├── music_player.py        # Gestor de audio, yt-dlp, FFmpeg y cola FIFO
├── main.py                # Entrada principal y sincronización del Command Tree
├── Dockerfile             # Imagen Docker multi-stage 24/7 sin root
├── docker-compose.yml     # Configuración para pruebas locales en Docker
├── .env.example           # Plantilla de variables de entorno
├── .gitignore             # Filtro de archivos sensibles y temporales
├── requirements.txt       # Dependencias exactas del proyecto
└── README.md              # Guía completa de despliegue
```

---

## 🔑 Obtención de Credenciales y Claves

### 1. Bot Token de Discord
1. Ve al [Discord Developer Portal](https://discord.com/developers/applications).
2. Haz clic en **New Application**, dale un nombre y créala.
3. Ve a la sección **Bot** -> Haz clic en **Reset Token** para obtener tu `DISCORD_TOKEN`.
4. En **Privileged Gateway Intents**, activa:
   - **MESSAGE CONTENT INTENT**
   - **SERVER MEMBERS INTENT** (opcional pero recomendado)
5. Ve a **OAuth2** -> **URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Connect`, `Speak`, `Send Messages`, `Use Slash Commands`, `Embed Links`.
   - Copia la URL generada e invita al bot a tu servidor de Discord.

### 2. API Key de Google Gemini
1. Ve a [Google AI Studio](https://aistudio.google.com/).
2. Haz clic en **Get API key** -> **Create API key**.
3. Copia tu clave `GEMINI_API_KEY`.

---

## 🚀 Despliegue Paso a Paso en la Nube (24/7 Gratis/Económico)

### Paso 1: Subir el Proyecto a GitHub

1. Inicializa el repositorio Git e ingresa tus cambios:
   ```bash
   git init
   git add .
   git commit -m "Initial commit: Discord AI Music Bot"
   ```
2. Crea un nuevo repositorio **privado o público** en [GitHub](https://github.com/new).
3. Conecta tu repositorio local y sube los cambios:
   ```bash
   git branch -M main
   git remote add origin https://github.com/tu-usuario/tu-repositorio.git
   git push -u origin main
   ```

---

### Paso 2A: Despliegue en Render (Recomendado para Docker)

Render permite desplegar contenedores Docker de forma muy sencilla.

1. Inicia sesión o regístrate en [Render.com](https://render.com/).
2. Haz clic en **New +** y selecciona **Background Worker** (o **Web Service**).
3. Conecta tu cuenta de GitHub y selecciona el repositorio de tu bot.
4. Configura los datos del servicio:
   - **Name:** `discord-ai-music-bot`
   - **Region:** Selecciona la más cercana.
   - **Environment:** `Docker` (Render detectará automáticamente el `Dockerfile`).
   - **Branch:** `main`
5. En la sección **Environment Variables**, añade las dos claves requeridas:
   - Key: `DISCORD_TOKEN` | Value: `tu_token_de_discord`
   - Key: `GEMINI_API_KEY` | Value: `tu_api_key_de_gemini`
6. Haz clic en **Create Background Worker**. Render construirá la imagen Docker e iniciará tu bot 24/7.

---

### Paso 2B: Despliegue en Fly.io

1. Instala la herramienta de línea de comandos `flyctl` en tu máquina:
   - Windows (PowerShell): `iwr https://fly.io/install.ps1 -useb | iex`
   - Linux/macOS: `curl -L https://fly.io/install.sh | sh`
2. Autentícate en Fly.io:
   ```bash
   fly auth login
   ```
3. Inicializa la aplicación en la carpeta del proyecto:
   ```bash
   fly launch --no-deploy
   ```
4. Configura las variables de entorno secretas:
   ```bash
   fly secrets set DISCORD_TOKEN="tu_token_de_discord" GEMINI_API_KEY="tu_api_key_de_gemini"
   ```
5. Despliega la aplicación en los servidores de Fly.io:
   ```bash
   fly deploy
   ```

---

## 🛠️ Ejecución Local con Docker Compose (Opcional)

Si deseas probar el bot localmente antes de desplegarlo:

1. Crea un archivo `.env` basado en `.env.example`:
   ```bash
   cp .env.example .env
   ```
2. Rellena tus claves `DISCORD_TOKEN` y `GEMINI_API_KEY` en `.env`.
3. Levanta el contenedor con Docker Compose:
   ```bash
   docker compose up --build
   ```

---

## 📄 Licencia

Este proyecto está distribuido bajo la licencia MIT.
