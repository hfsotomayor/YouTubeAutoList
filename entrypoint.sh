#!/bin/bash
set -e  # Detiene la ejecución si hay algún error

# Verifica los archivos de configuración
if [ ! -f "/app/YouTubeAutoListConfig.json" ] || [ ! -f "/app/YouTubeAutoListToken.json" ]; then
    echo "Error: Archivos de configuración no encontrados"
    exit 1
fi

# Asegura que cron no esté ejecutándose
pkill cron || true
rm -f /var/run/crond.pid

# Inicia cron en primer plano
cron

# Muestra los logs en tiempo real
exec tail -f /var/log/cron.log