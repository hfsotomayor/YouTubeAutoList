#!/bin/bash
set -e

# Verifica los archivos de configuración con rutas absolutas
if [ ! -f "/app/YouTubeAutoListConfig.json" ] || [ ! -f "/app/YouTubeAutoListToken.json" ]; then
    echo "Error: Archivos de configuración no encontrados en /app/"
    ls -la /app/
    exit 1
fi

# Verifica permisos
echo "Verificando permisos de archivos..."
ls -la /app/

# Asegura que cron no esté ejecutándose
pkill cron || true
rm -f /var/run/crond.pid

# Configura el cron para ejecutar en los horarios especificados
echo "Configurando cron..."
# Inicia cron en segundo plano
cron -f &
CRON_PID=$!

# Configura trap para manejar señales de detención
trap 'kill $CRON_PID; exit 0' SIGTERM SIGINT

# Muestra los próximos horarios programados
echo "Próximas ejecuciones programadas:"
crontab -l

# Muestra los logs en tiempo real
echo "Iniciando monitoreo de logs..."
touch /var/log/cron.log
tail -f /var/log/cron.log &

# Esperar señales mientras mantiene el contenedor ejecutándose
wait $CRON_PID