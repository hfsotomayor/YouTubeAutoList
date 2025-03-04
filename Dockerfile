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
    && rm -rf /var/lib/apt/lists/*

# Copia todos los archivos necesarios al contenedor
COPY requirements.txt .
COPY YouTubeAutoList.py .
COPY entrypoint.sh .
COPY YouTubeAutoListConfig.json .
COPY YouTubeAutoListToken.json .
COPY YouTubeAutoListClientSecret.json . 

# Instala las dependencias de Python definidas en requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Configura el cron job con redirección de logs
RUN echo "30 4,12,20 * * * /usr/local/bin/python /app/YouTubeAutoList.py >> /var/log/cron.log 2>&1" > /etc/cron.d/youtube-cron && \
    chmod 0644 /etc/cron.d/youtube-cron && \
    crontab /etc/cron.d/youtube-cron

# Crea el archivo de log y establece permisos
RUN touch /var/log/cron.log && \
    chmod 0666 /var/log/cron.log

# Da permisos de ejecución al script de entrada
RUN chmod +x /app/entrypoint.sh

# Define el punto de entrada del contenedor
ENTRYPOINT ["/app/entrypoint.sh"]