import os
import json
import requests
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta
import logging
import re

# Definir los alcances necesarios para la API de YouTube
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# Configuración inicial de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filename="youtube_manager.log"
)

def check_internet_connection():
    """
    Verifica si hay conexión a Internet haciendo una solicitud a Google.
    """
    print("=== Verificando conexión a Internet ===")
    try:
        response = requests.get("https://www.google.com", timeout=5)
        if response.status_code == 200:
            print("Conexión a Internet verificada")
            return True
    except requests.ConnectionError:
        print("No se detectó conexión a Internet")
        return False
    return False

def authenticate():
    """
    Realiza la autenticación mediante OAuth 2.0.
    Devuelve un cliente autenticado de la API de YouTube.
    """
    print("=== Autenticando mediante OAuth 2.0 ===")
    creds_path = "client_secret_119875361364-9uanll7390o4lvqho48mm3j5b2fcovg8.apps.googleusercontent.com.json"  # Reemplázalo con la ruta a tus credenciales

    if not os.path.exists(creds_path):
        raise FileNotFoundError(f"No se encontró el archivo de credenciales: {creds_path}")
    
    # Iniciar el flujo de autorización
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=8080)

    # Crear el cliente autenticado de la API de YouTube
    return build("youtube", "v3", credentials=creds)

def check_channel_exists(youtube, channel_id):
    """
    Verifica si un canal de YouTube existe.
    """
    print(f"=== Verificando existencia del canal: {channel_id} ===")
    try:
        response = youtube.channels().list(
            part="id",
            id=channel_id
        ).execute()
        if response.get("items"):
            print(f"El canal {channel_id} existe")
            return True
        else:
            print(f"El canal {channel_id} no existe")
            return False
    except HttpError as e:
        print(f"Error al verificar el canal {channel_id}: {e}")
        logging.error(f"Error al verificar el canal {channel_id}: {e}")
        return False

def is_valid_duration(duration, min_duration, max_duration):
    """
    Verifica si la duración del video está dentro de los límites establecidos.
    """
    print(f"=== Verificando duración del video ===")
    match = re.match(r'PT(\d+H)?(\d+M)?(\d+S)?', duration)
    if not match:
        print("Formato de duración inválido")
        return False

    # Convertir duración a segundos
    hours = int(match.group(1)[:-1]) if match.group(1) else 0
    minutes = int(match.group(2)[:-1]) if match.group(2) else 0
    seconds = int(match.group(3)[:-1]) if match.group(3) else 0

    total_seconds = hours * 3600 + minutes * 60 + seconds
    is_valid = min_duration <= total_seconds <= max_duration
    print(f"Duración total en segundos: {total_seconds}")
    print(f"¿Duración válida? {is_valid}")
    return is_valid

def process_channel(youtube, channel_id, playlist_id, title_pattern, min_duration, max_duration, days_limit=7):
    """
    Procesa un canal de YouTube y agrega videos a una playlist si cumplen los criterios.
    """
    print(f"=== Procesando canal {channel_id} ===")
    try:
        # Verificar existencia del canal
        if not check_channel_exists(youtube, channel_id):
            print("\033 Canal {channel_id} no existe. Saltando...")
            return

        # Fecha límite para la búsqueda
        date_limit = (datetime.utcnow() - timedelta(days=days_limit)).isoformat() + "Z"
        print(f"Buscando videos publicados después de: {date_limit}")

        # Buscar videos en el canal
        search_response = youtube.search().list(
            channelId=channel_id,
            publishedAfter=date_limit,
            order="date",
            part="id,snippet",
            maxResults=50,
            type="video"
        ).execute()

        video_ids = [item["id"]["videoId"] for item in search_response.get("items", [])]
        print(f"Videos encontrados: {len(video_ids)}")

        if not video_ids:
            print("No se encontraron videos nuevos")
            return

        # Obtener detalles de los videos
        video_response = youtube.videos().list(
            id=",".join(video_ids),
            part="contentDetails,snippet"
        ).execute()

        # Procesar cada video
        for video in video_response.get("items", []):
            video_id = video["id"]
            title = video["snippet"]["title"]
            duration = video["contentDetails"]["duration"]

            print(f"Procesando video: {title} (ID: {video_id}, Duración: {duration})")

            # Verificar título y duración
            if not re.match(title_pattern, title):
                print("\033 Título no coincide con el patrón. Saltando...")
                continue
            if not is_valid_duration(duration, min_duration, max_duration):
                print("\033 Duración no válida. Saltando...")
                continue

            # Agregar video a la playlist
            add_video_to_playlist(youtube, playlist_id, video_id)

    except HttpError as e:
        print(f"Error al procesar el canal {channel_id}: {e}")
        logging.error(f"Error al procesar el canal {channel_id}: {e}")

def add_video_to_playlist(youtube, playlist_id, video_id):
    """
    Agrega un video a la playlist especificada.
    """
    print(f"Agregando video {video_id} a la playlist {playlist_id}...")
    try:
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id
                    }
                }
            }
        ).execute()
        print(f"\033 Video {video_id} agregado con éxito")
    except HttpError as e:
        print(f"Error al agregar video {video_id}: {e}")
        logging.error(f"Error al agregar video {video_id}: {e}")

def main():
    """
    Función principal para ejecutar el programa.
    """
    print("=== Iniciando programa ===")

    # Verificar conexión a Internet
    if not check_internet_connection():
        print("No hay conexión a Internet. Saliendo...")
        return

    # Autenticación mediante OAuth 2.0
    youtube = authenticate()

    # Configuración de canales
    channel_configs = [
        {
            "channel_id": "UC7QZIf0dta-XPXsp9Hv4dTw",  # RTVE Noticias
            "title_pattern": r'Las noticias del (\w+) (\d{1,2}) de (\w+) en 10 minutos | RTVE Noticias',
            "min_duration": 500,
            "max_duration": 660,
            "days_limit": 1
        }
    ]

    # Playlist de destino
    playlist_id = "PLwFfNCxuxPv1S0Laim0gk3WOXJvLesNi0"

    # Procesar cada canal
    for config in channel_configs:
        process_channel(
            youtube,
            config["channel_id"],
            playlist_id,
            config["title_pattern"],
            config["min_duration"],
            config["max_duration"],
            config["hours_limit"]
        )

    print("=== Programa finalizado ===")

if __name__ == "__main__":
    main()