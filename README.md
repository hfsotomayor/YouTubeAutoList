# YouTubeAutoList

Sistema automatizado para gestionar listas de reproducción de YouTube basado en criterios configurables.

## Requisitos Previos

1. Python 3.11 o superior
2. Docker (opcional)
3. Cuenta de Google y proyecto en Google Cloud Platform

## Configuración de Google Cloud Platform

1. Crear un nuevo proyecto en [Google Cloud Console](https://console.cloud.google.com/)
2. Habilitar YouTube Data API v3:
   - Ir a "APIs & Services" > "Library"
   - Buscar "YouTube Data API v3"
   - Clic en "Enable"

3. Configurar credenciales OAuth:
   - Ir a "APIs & Services" > "Credentials"
   - Clic en "Create Credentials" > "OAuth client ID"
   - Seleccionar "Desktop Application"
   - Configurar pantalla de consentimiento:
     * Tipo de usuario: Externo
     * Información de la aplicación
     * Permisos: `.../auth/youtube.force-ssl`
   - Descargar el archivo JSON de credenciales y renombrarlo a `YouTubeAutoListClientSecret.json`

## Características

- Autenticación OAuth 2.0 con YouTube API
- Sistema de caché para optimizar las consultas a la API
- Filtrado de videos por duración y patrones en títulos
- Detección y exclusión automática de Shorts
- Limpieza automática de videos antiguos
- Soporte para múltiples canales y listas de reproducción
- Contenedorización con Docker

## Requisitos

- Python 3.11+
- Credenciales de YouTube API
- Docker (opcional)

## Estructura

```
YouTubeAutoList/
├── YouTubeAutoList.py       # Script principal
├── auth_setup.py           # Script de autenticación inicial
├── entrypoint.sh          # Punto de entrada para Docker
├── Dockerfile             # Configuración de Docker
├── requirements.txt       # Dependencias Python
├── YouTubeAutoListConfig.json    # Configuración de canales
├── YouTubeAutoListToken.json     # Token de autenticación
└── YouTubeAutoListClientSecret.json  # Credenciales de Google Cloud
```

## Diagrama de Flujo

```mermaid
graph TD
    A[main] --> B[YouTubeManager.__init__]
    B --> C[check_internet_connection]
    C --> D[authenticate]
    D --> E[load_config]
    E --> F[manage_playlist]
    F --> G[get_channel_videos]
    G --> H[_video_matches_criteria]
    H --> I[_parse_duration]
    F --> J[_get_playlist_items]
    F --> K[_video_in_playlist]
    F --> L[_add_to_playlist]
    A --> M[cleanup_playlists]
    M --> N[_get_playlist_items]
    
    subgraph "Caché"
        O[YouTubeCache.__init__]
        P[_load_cache]
        Q[save_cache]
        R[get_cached_data]
        S[update_cache]
        T[is_cache_valid]
    end

    subgraph "Autenticación"
        D --> U[Verificar token existente]
        U --> V[Cargar credenciales]
        V --> W[Refrescar token si es necesario]
    end
```

## Configuración

### Archivo YouTubeAutoListConfig.json

```json
{
    "channels": [
        {
            "channel_id": "ID_CANAL",
            "channel_name": "Nombre Canal",
            "playlist_id": "ID_PLAYLIST",
            "playlist_name": "Nombre Playlist",
            "title_pattern": "regex_pattern",
            "min_duration": 120,
            "max_duration": 900,
            "hours_limit": 8
        }
    ]
}
```

### Variables de Entorno Docker

```yaml
environment:
  - TZ=Europe/Madrid
  - CONFIG_DIR=/app/config
  - LOG_DIR=/app/logs
  - DATA_DIR=/app/data
```

## Uso

### Local

1. Instalar dependencias:
```bash
pip install -r requirements.txt
```

2. Ejecutar:
```bash
python YouTubeAutoList.py
```

### Docker 

# Falta aclar contexto de por que no se usa volumnes y docker compose 

1. Construir imagen:
```bash
docker build -t owner/youtubeautolist:tag . >> LogsBuild$(date "+%Y%m%d-%H%M%S").txt
```

2. Ejecutar:
```bash
docker run -d --name youtubeautolisttag --restart unless-stopped owner/youtubeautolist:tag .
```

## Logging

Los logs se guardan en:
- `logs/YouTubeAutoList.log`: Logs de la aplicación
- `logs/cron.log`: Logs de las ejecuciones programadas

## Contribuir

1. Fork del repositorio
2. Crear rama feature (`git checkout -b feature/NuevaCaracteristica`)
3. Commit cambios (`git commit -am 'Añadir nueva característica'`)
4. Push a la rama (`git push origin feature/NuevaCaracteristica`)
5. Crear Pull Request
