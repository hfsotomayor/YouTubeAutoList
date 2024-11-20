import os
import json
import requests
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta
import logging
import re
from colorama import Fore, Style, init

# Inicializar colorama
init(autoreset=True)


# Definir los alcances necesarios para la API de YouTube
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# Configuración inicial de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filename="youtube_manager.log"
)

HISTORY_FILE = "video_history.json"

def load_history():
    """Carga el historial desde un archivo JSON."""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    return {}

def save_history(history):
    """Guarda el historial en un archivo JSON."""
    with open(HISTORY_FILE, "w", encoding="utf-8") as file:
        json.dump(history, file, indent=4)

def check_internet_connection():
    """
    Verifica si hay conexión a Internet haciendo una solicitud a Google.
    """
    print("=== Verificando conexión a Internet ===")
    try:
        response = requests.get("https://www.google.com", timeout=5)
        if response.status_code == 200:
            print(f"Conexión a Internet {Fore.GREEN}verificada")
            return True
    except requests.ConnectionError:
        print(f"{Fore.RED}No se detectó conexión a Internet")
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
            print(f"El canal {channel_id} {Fore.GREEN}existe")
            return True
        else:
            print(f"El canal {channel_id} {Fore.RED}no existe")
            return False
    except HttpError as e:
        print(f"{Fore.RED}Error al verificar el canal {channel_id}: {e}")
        logging.error(f"Error al verificar el canal {channel_id}: {e}")
        return False

def is_valid_duration(duration, min_duration, max_duration):
    """
    Verifica si la duración del video está dentro de los límites establecidos.
    """
    print(f"=== Verificando duración del video ===")
    match = re.match(r'PT(\d+H)?(\d+M)?(\d+S)?', duration)
    if not match:
        print("Formato de duración {Fore.RED}inválido")
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

def delete_watched_videos(youtube, playlist_id):
    """
    Elimina videos de una playlist si tienen más del 90% de vistas.
    """
    print("=== Eliminando videos con más del 90% vistos ===")
    try:
        playlist_items = youtube.playlistItems().list(
            part="id,snippet,contentDetails",
            playlistId=playlist_id,
            maxResults=50
        ).execute()

        for item in playlist_items.get("items", []):
            video_id = item["contentDetails"]["videoId"]
            watch_response = youtube.videos().list(
                part="statistics",
                id=video_id
            ).execute()

            for video in watch_response.get("items", []):
                view_percentage = float(video["statistics"].get("viewCount", 0)) / 100
                if view_percentage > 90:
                    print(f"Eliminando video {video_id} (visto más del 90%)")
                    youtube.playlistItems().delete(id=item["id"]).execute()

    except HttpError as e:
        print(f"Error al eliminar videos vistos: {e}")
        logging.error(f"Error al eliminar videos vistos: {e}")

def process_channel(youtube, channel_id, playlist_id, title_pattern, min_duration, max_duration, hours_limit, history):
    """
    Procesa un canal de YouTube y agrega videos a una playlist si cumplen los criterios.
    """
    print(f"=== Procesando canal {channel_id} ===")
    try:
        if not check_channel_exists(youtube, channel_id):
            print(f"Canal no existe. {Fore.RED}Saltando...")
            return

        # Fecha límite para la búsqueda
        date_limit = (datetime.utcnow() - timedelta(hours=hours_limit)).isoformat() + "Z"
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
        print(f"Videos encontrados: {Fore.YELLOW}{len(video_ids)}")

        for video_id in video_ids:
            if video_id in history:
                print(f"Video {video_id} ya procesado. {Fore.RED}Saltando...")
                continue

            video_response = youtube.videos().list(
                id=video_id,
                part="contentDetails,snippet"
            ).execute()

            for video in video_response.get("items", []):
                title = video["snippet"]["title"]
                duration = video["contentDetails"]["duration"]

                print(f"Procesando video: {title} (ID: {video_id}, Duración: {duration})")

                if not re.match(title_pattern, title):
                    print(f"Título no coincide con el patrón. {Fore.RED}Saltando...")
                    continue
                if not is_valid_duration(duration, min_duration, max_duration):
                    print(f"Duración no válida. {Fore.RED}Saltando...")
                    continue

                add_video_to_playlist(youtube, playlist_id, video_id)
                history[video_id] = True
                save_history(history)

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
        print(f"Video {video_id} agregado con {Fore.GREEN}éxito")
    except HttpError as e:
        print(f"Error al agregar video {video_id}: {e}")
        logging.error(f"Error al agregar video {video_id}: {e}")

def main():
    """
    Función principal para ejecutar el programa.
    """
    print("=== Iniciando programa ===")

    if not check_internet_connection():
        print("No hay conexión a Internet. Saliendo...")
        return

    youtube = authenticate()
    history = load_history()

    with open("config.json", "r", encoding="utf-8") as config_file:
        channel_configs = json.load(config_file)

    for config in channel_configs["channels"]:
        process_channel(
            youtube,
            config["channel_id"],
            channel_configs["playlist_id"],
            config["title_pattern"],
            config["min_duration"],
            config["max_duration"],
            config["hours_limit"],
            history
        )
        delete_watched_videos(youtube, channel_configs["playlist_id"])

    print("=== Programa finalizado ===")

if __name__ == "__main__":
    main()