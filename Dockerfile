# Usa Python 3.11 versión slim (imagen base más ligera)
FROM python:3.11-slim

# Define el directorio de trabajo dentro del contenedor
WORKDIR /app

# Configura la zona horaria
ENV TZ=Europe/Madrid
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Instala cron y otras utilidades necesarias
RUN apt-get update && apt-get install -y \
    cron \
    tzdata \
    procps \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copiar archivos con permisos explícitos
COPY  requirements.txt .
COPY  YouTubeAutoList.py .
COPY  database_manager.py .
COPY  entrypoint.sh .
COPY  YouTubeAutoListConfig.json .
COPY  YouTubeAutoListClientSecret.json .
COPY YouTubeAutoListNotification_config.json .

# El token debe ser copiado después de generarlo fuera del contenedor
COPY YouTubeAutoListToken.json . 

# Cambio de permisos.
RUN chmod 644 requirements.txt && \
    chmod 644 YouTubeAutoList.py && \
    chmod 644 database_manager.py && \
    chmod 755 entrypoint.sh && \
    chmod 644 YouTubeAutoListConfig.json && \
    chmod 644 YouTubeAutoListClientSecret.json && \
    chmod 600 YouTubeAutoListToken.json && \
    chmod 600 YouTubeAutoListNotification_config.json

# Asegurar permisos para BD y logs
RUN mkdir -p /app/db /app/logs && \
    chmod 755 /app/db /app/logs && \
    touch /app/db/.keep /app/logs/.keep && \
    chmod 644 /app/db/.keep /app/logs/.keep

# Instala las dependencias de Python definidas en requirements.txt
RUN pip install --no-cache-dir -r requirements.txt --index-url https://pypi.org/simple

# Configura el cron job con redirección de logs y ruta absoluta
RUN echo "30 4,12,20 * * * cd /app && /usr/local/bin/python /app/YouTubeAutoList.py >> /app/logs/cron.log 2>&1" > /etc/cron.d/youtube-cron && \
    chmod 0644 /etc/cron.d/youtube-cron && \
    crontab /etc/cron.d/youtube-cron

# Asegurar que todos los archivos tengan los permisos correctos y el usuario correcto
RUN chown -R root:root /app && \
    chmod -R 644 /app/* && \
    chmod 755 /app && \
    chmod 755 /app/entrypoint.sh && \
    chmod 600 /app/YouTubeAutoListToken.json

# Crea el archivo de log y establece permisos
RUN touch /var/log/cron.log && \
    chmod 0666 /var/log/cron.log

# Define el punto de entrada del contenedor
ENTRYPOINT ["/app/entrypoint.sh"]