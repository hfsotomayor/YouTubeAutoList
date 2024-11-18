from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import re
from datetime import datetime, timedelta
import json
import os

import logging

# Configurar logging al inicio del script
logging.basicConfig(
    level=logging.DEBUG,  # Muestra todos los mensajes de debug
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# logs
logging.debug("Mensaje de depuración")
logging.info("Información importante")
logging.warning("Advertencia")
logging.error("Error")


def print_debug(message):
    print(f"DEBUG: {message}")

# Cargar las variables de entorno
load_dotenv("/Users/hfsot/Library/CloudStorage/OneDrive-Personal/Proyectos/Developer/YouTubeAutoList/terces.env")
api_key: str = os.getenv("YTtercesAPI")
target_playlist_id: str = os.getenv("AutoList")

print(f"API Key: {api_key}")
print(f"Target Playlist ID: {target_playlist_id}")

# logs
logging.debug("Mensaje de depuración")
logging.info("Información importante")
logging.warning("Advertencia")
logging.error("Error")

class YouTubePlaylistManager:
    def __init__(self, api_key, target_playlist_id):
        print("Inicializando el gestor de playlists de YouTube...")
        self.youtube = build('youtube', 'v3', developerKey=api_key)
        self.target_playlist_id = target_playlist_id
        self.quota_usage = 0
        self.already_added_videos = set()
        self.load_video_history()
        # logs
        logging.debug("Mensaje de depuración")
        logging.info("Información importante")
        logging.warning("Advertencia")
        logging.error("Error")

    def load_video_history(self):
        print("Cargando el historial de videos agregados...")
        try:
            with open('video_history.json', 'r') as f:
                self.already_added_videos = set(json.load(f))
            print(f"Se cargaron {len(self.already_added_videos)} videos del historial.")
        except FileNotFoundError:
            self.already_added_videos = set()
            print("No se encontró el historial de videos. Empezando con un historial vacío.")
            logging.debug("Mensaje de depuración")
            logging.info("Información importante")
            logging.warning("Advertencia")
            logging.error("Error")

    def save_video_history(self):
        print("Guardando el historial de videos agregados...")
        with open('video_history.json', 'w') as f:
            json.dump(list(self.already_added_videos), f)
        print("Historial guardado exitosamente.")

    def check_quota(self, units):
        print(f"Verificando cuota para {units} unidades...")
        if self.quota_usage + units > 10000:
            print("No hay suficiente cuota disponible.")
            return False
        self.quota_usage += units
        print(f"Cuota actualizada. Uso de cuota: {self.quota_usage} unidades.")
        return True

    def matches_title_pattern(self, title, patterns):
        print(f"Verificando si el título '{title}' coincide con los patrones...")
        return any(re.match(pattern, title) for pattern in patterns)

    def is_valid_duration(self, duration, min_duration, max_duration):
        print(f"Verificando la duración del video: {duration}...")
        # Convierte la duración ISO 8601 a segundos
        match = re.match(r'PT(\d+H)?(\d+M)?(\d+S)?', duration)
        if not match:
            print("Duración inválida. No se cumple con el formato ISO 8601.")
            return False
        
        hours = int(match.group(1)[:-1]) if match.group(1) else 0
        minutes = int(match.group(2)[:-1]) if match.group(2) else 0
        seconds = int(match.group(3)[:-1]) if match.group(3) else 0
        
        total_seconds = hours * 3600 + minutes * 60 + seconds
        if min_duration <= total_seconds <= max_duration:
            print(f"Duración válida: {total_seconds} segundos.")
            return True
        else:
            print(f"Duración no válida. Debería estar entre {min_duration} y {max_duration} segundos.")
            return False

    def process_channel(self, channel_id, title_patterns, min_duration, max_duration, days_limit=7):
        print(f"Procesando canal {channel_id}...")
        if not self.check_quota(100):  # Estimación de cuota para búsqueda de videos
            print(f"No hay suficiente cuota para procesar el canal {channel_id}")
            return

        try:
            # Obtiene los videos más recientes del canal
            print(f"Obteniendo videos del canal {channel_id}...")
            search_response = self.youtube.search().list(
                channelId=channel_id,
                publishedAfter=(datetime.utcnow() - timedelta(days=days_limit)).isoformat() + 'Z',
                order='date',
                part='id,snippet',
                maxResults=50
            ).execute()

            video_ids = [item['id']['videoId'] for item in search_response.get('items', [])
                        if item['id']['kind'] == 'youtube#video']

            # Obtiene detalles de los videos
            if video_ids:
                print(f"Se encontraron {len(video_ids)} videos.")
                video_response = self.youtube.videos().list(
                    id=','.join(video_ids),
                    part='contentDetails,snippet'
                ).execute()

                for video in video_response.get('items', []):
                    video_id = video['id']
                    
                    # Verifica si el video ya ha sido agregado
                    if video_id in self.already_added_videos:
                        print(f"El video '{video['snippet']['title']}' ya ha sido agregado anteriormente.")
                        continue

                    title = video['snippet']['title']
                    duration = video['contentDetails']['duration']

                    # Verifica criterios
                    if (self.matches_title_pattern(title, title_patterns) and
                            self.is_valid_duration(duration, min_duration, max_duration)):
                        
                        # Agrega el video a la playlist
                        if self.check_quota(50):  # Cuota para insertar en playlist
                            print(f"Agregando el video '{title}' a la playlist...")
                            self.youtube.playlistItems().insert(
                                part='snippet',
                                body={
                                    'snippet': {
                                        'playlistId': self.target_playlist_id,
                                        'resourceId': {
                                            'kind': 'youtube#video',
                                            'videoId': video_id
                                        }
                                    }
                                }
                            ).execute()
                            
                            self.already_added_videos.add(video_id)
                            print(f"Video agregado: {title}")

        except HttpError as e:
            print(f"Error al procesar el canal {channel_id}: {str(e)}")

    def process_channels(self, channel_configs):
        print("Iniciando el procesamiento de canales...")
        for config in channel_configs:
            print(f"Procesando configuración para el canal {config['rtvenoticias']}...")
            self.process_channel(
                channel_id=config['rtvenoticias'],
                title_patterns=config[r'Las noticias del (\w+) (\d{1,2}) de (\w+) en 10 minutos'],
                min_duration=config['400'],
                max_duration=config['600'],
                days_limit=config.get('1', 7)
            )
        
        self.save_video_history()
        print("Procesamiento de canales completado.")