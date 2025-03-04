# YouTubeAutoList

Automatización para crear y mantener listas de reproducción de YouTube basadas en canales específicos y criterios configurables.

## Características

- Autenticación OAuth 2.0 con YouTube API
- Sistema de caché para optimizar las consultas a la API
- Filtrado de videos por duración y patrones en títulos
- Detección y exclusión automática de Shorts
- Limpieza automática de videos antiguos
- Soporte para múltiples canales y listas de reproducción
- Sistema de logging con colores
- Contenedorización con Docker

## Requisitos

- Python 3.11+
- Credenciales de YouTube API
- Docker (opcional)

## Estructura

```
YouTubeAutoList/
├── YouTubeAutoList.py     # Script principal
├── config/                # Directorio de configuración
│   ├── YouTubeAutoListConfig.json
│   └── YouTubeAutoListToken.json
├── data/                  # Directorio de datos
├── logs/                  # Directorio de logs
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
└── requirements.txt
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

1. Construir imagen:
```bash
docker compose build
```

2. Ejecutar:
```bash
docker compose up -d
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

## Licencia

MIT