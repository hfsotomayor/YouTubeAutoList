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

# Prueba la ejecución del script antes de iniciar cron
echo "Probando script..."
cd /app && /usr/local/bin/python /app/YouTubeAutoList.py

# Si la prueba es exitosa, inicia cron
if [ $? -eq 0 ]; then
    echo "Prueba exitosa, iniciando cron..."
    # Inicia cron en primer plano
    cron -f &
else
    echo "Error en la prueba inicial del script"
    exit 1
fi

# Muestra los logs en tiempo real
exec tail -f /var/log/cron.log