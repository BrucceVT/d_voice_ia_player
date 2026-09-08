# ==========================================
# Multi-stage / Slim Dockerfile para Bot Discord de Música + IA
# Base: Python 3.12 Slim (Debian Bookworm)
# ==========================================

FROM python:3.12-slim-bookworm

# Evitar la generación de archivos .pyc y forzar salida stdout sin buffer
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# Definir directorio de trabajo
WORKDIR /app

# Instalación de dependencias del sistema requeridas por FFmpeg y PyNaCl/discord.py
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    libffi-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copiar archivo de requerimientos e instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente completo de la aplicación
COPY . .

# Crear un usuario sin privilegios root por razones de seguridad
RUN useradd -m -u 10001 appuser && \
    chown -R appuser:appuser /app

USER appuser

# Comando de ejecución persistente para el bot
CMD ["python", "main.py"]
