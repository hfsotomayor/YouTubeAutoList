#!/bin/bash

# Colores para los mensajes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Función para mostrar mensajes
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Solicitar versión
read -p "Ingrese la versión de la imagen (ejemplo: 0.4.202503): " VERSION

if [ -z "$VERSION" ]; then
    log_error "La versión es requerida"
    exit 1
fi

IMAGE_NAME="hfs/youtubeautolist:$VERSION"
CONTAINER_NAME="youtubeautolist$VERSION"

# Definir directorios de persistencia
DATA_DIR="./persistent_data"
DB_DIR="$DATA_DIR/db"
LOGS_DIR="$DATA_DIR/logs"
DB_FILE="$DB_DIR/YouTubeAutoList.db"

# Crear directorios si no existen
mkdir -p $DB_DIR $LOGS_DIR
log_info "Directorios de persistencia creados en $DATA_DIR"

# Verificar y copiar datos del contenedor existente
if docker ps -a | grep -q $CONTAINER_NAME; then
    log_info "Contenedor existente encontrado, respaldando datos..."
    
    # Verificar integridad de la base de datos antes de copiar
    docker exec $CONTAINER_NAME sqlite3 /app/db/YouTubeAutoList.db ".tables" > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        # Respaldo de base de datos con verificación
        if docker cp "$CONTAINER_NAME:/app/db/YouTubeAutoList.db" "$DB_FILE"; then
            log_info "Base de datos respaldada exitosamente"
            
            # Verificar y actualizar estructura si es necesario
            sqlite3 "$DB_FILE" "CREATE TABLE IF NOT EXISTS removed_videos (video_id TEXT PRIMARY KEY, channel_name TEXT, removal_date DATETIME DEFAULT CURRENT_TIMESTAMP);" 2>/dev/null
            if [ $? -eq 0 ]; then
                log_info "Estructura de base de datos actualizada"
            else
                log_warning "No se pudo actualizar la estructura de la base de datos"
            fi
        else
            log_warning "No se pudo respaldar la base de datos"
        fi
    else
        log_warning "Base de datos en contenedor existente no accesible o corrupta"
    fi
    
    # Respaldar logs
    if docker cp "$CONTAINER_NAME:/app/logs/." "$LOGS_DIR/" 2>/dev/null; then
        log_info "Logs respaldados exitosamente"
    else
        log_warning "No hay logs para respaldar"
    fi

    # Detener y eliminar contenedor antiguo
    log_warning "Deteniendo contenedor existente..."
    docker stop $CONTAINER_NAME
    docker rm $CONTAINER_NAME
else
    log_info "Primera ejecución detectada - Creando estructura inicial de base de datos"
    # Crear estructura inicial de base de datos si es primera vez
    sqlite3 "$DB_FILE" "CREATE TABLE IF NOT EXISTS removed_videos (video_id TEXT PRIMARY KEY, channel_name TEXT, removal_date DATETIME DEFAULT CURRENT_TIMESTAMP);" 2>/dev/null
fi

# Construir nueva imagen
log_info "Construyendo nueva imagen..."
BUILD_LOG_FILE="$LOGS_DIR/LogsBuild$(date '+%Y%m%d-%H%M%S').txt"
if ! docker build -t $IMAGE_NAME . > $BUILD_LOG_FILE 2>&1; then
    log_error "Error al construir la imagen. Revise el log en $BUILD_LOG_FILE"
    exit 1
fi
log_info "Imagen construida exitosamente. Log guardado en $BUILD_LOG_FILE"

# Ejecutar nuevo contenedor
log_info "Iniciando nuevo contenedor..."
if ! CONTAINER_ID=$(docker run -d --name $CONTAINER_NAME --restart unless-stopped $IMAGE_NAME .); then
    log_error "Error al iniciar el contenedor"
    exit 1
fi

# Copiar archivos de persistencia al nuevo contenedor
log_info "Copiando datos persistentes al nuevo contenedor..."
if [ -f "$DB_FILE" ]; then
    docker cp "$DB_FILE" "$CONTAINER_NAME:/app/db/"
    log_info "Base de datos restaurada"
fi

if [ -d "$LOGS_DIR" ] && [ "$(ls -A $LOGS_DIR)" ]; then
    docker cp "$LOGS_DIR/." "$CONTAINER_NAME:/app/logs/"
    log_info "Logs restaurados"
fi

# Verificar permisos de base de datos después de restauración
if [ -f "$DB_FILE" ]; then
    chmod 644 "$DB_FILE"
    log_info "Permisos de base de datos actualizados"
fi

# Verificar que el contenedor está corriendo
if docker ps | grep -q $CONTAINER_NAME; then
    log_info "Contenedor iniciado exitosamente"
    log_info "ID del contenedor: $CONTAINER_ID"
    log_info "Nombre del contenedor: $CONTAINER_NAME"
else
    log_error "El contenedor no está corriendo"
    exit 1
fi
