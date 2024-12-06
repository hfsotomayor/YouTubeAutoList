# YouTubeAutoList

## Genera una lista automáticamente

### Diagrama de flujo

```mermaid
flowchart TD
    A[Inicio] --> B{Verificar Internet}
    B -->|No| End[Fin]
    B -->|Sí| C[Autenticar OAuth]

    C --> D[Cargar JSONs y Cache]
    D --> E[Cargar Configuración]

    E --> F[Procesar Canales]
    F --> G[Verificar Validez Cache]

    G -->|Caducado| H[Actualizar Timestamp]
    G -->|Válido| I[Obtener Videos Recientes]

    I --> J{Por cada video}

    J --> K{¿En Historial?}
    K -->|Sí| J
    K -->|No| L[Obtener Progreso]

    L --> M{Verificar Criterios}
    M --> N{Progreso > Umbral}
    N -->|Sí| J
    N -->|No| O{Verificar Duración}

    O -->|Inválida| J
    O -->|Válida| P{Verificar Título}

    P -->|No Coincide| J
    P -->|Coincide| Q[Agregar a Playlist]

    Q --> R[Actualizar Historial]
    R --> J

    J --> S{¿Más Canales?}
    S -->|Sí| F
    S -->|No| End

```

### Archivo de configuracion

'''json
{
"playlist*id": "ID Lista",
"channels": [
{
"channel_id": "ID Canal",
"channel_name": "Nombre Canal",
"title_pattern": "([a-zA-Z0-9*-]+)",
"min*duration": 120,
"max_duration": 900,
"hours_limit": 6
},
{
"channel_id": "ID Canal",
"channel_name": "Nombre Canal",
"title_pattern": "([a-zA-Z0-9*-]+)",
"min*duration": 120,
"max_duration": 900,
"hours_limit": 6
},
{
"channel_id": "UCuCeID Canal",
"channel_name": "Nombre Canal",
"title_pattern": "([a-zA-Z0-9*-]+)",
"min_duration": 120,
"max_duration": 900,
"hours_limit": 6
},
]
}
'''