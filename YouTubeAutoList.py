import os
import json
import logging
import time
import re
from datetime import datetime, timedelta
import requests
from googleapiclient.errors import HttpError
from typing import Dict, List, Optional, Any
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from colorama import init, Fore
import pickle

# Inicialización de colorama para soporte de colores en consola
init()

# Configuración de constantes
SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']
CACHE_FILE = 'YouTubeAutoListCache.pkl'
CONFIG_FILE = 'YouTubeAutoListConfig.json'
LOG_FILE = 'YouTubeAutoList.log'
CACHE_DURATION = 7200  # 2 horas en segundos (configurable)


class QuotaExceededException(Exception):
    """Excepción personalizada para manejar el exceso de cuota de YouTube."""
    pass


class YouTubeCache:
    """Gestiona el sistema de caché para las consultas a la API de YouTube."""

    def __init__(self):
        self.cache = self._load_cache()
        self.last_update = {}

    def _load_cache(self) -> Dict:
        """Carga el caché desde el archivo o crea uno nuevo si no existe."""
        try:
            with open(CACHE_FILE, 'rb') as f:
                return pickle.load(f)
        except FileNotFoundError:
            return {
                'videos': {},
                'channels': {},
                'playlists': {},
                'progress': {}
            }

    def save_cache(self):
        """Guarda el caché actual en el archivo."""
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(self.cache, f)

    def get_cached_data(self, key: str, cache_type: str) -> Optional[Any]:
        """
        Obtiene datos del caché si son válidos según el tiempo configurado.

        Args:
            key: Identificador único del recurso
            cache_type: Tipo de caché ('videos', 'channels', 'playlists', 'progress')
        """
        if (
            key in self.cache[cache_type] and
            key in self.last_update and
            time.time() - self.last_update[key] < CACHE_DURATION
        ):
            return self.cache[cache_type][key]
        return None

    def update_cache(self, key: str, data: Any, cache_type: str):
        """
        Actualiza el caché con nuevos datos.

        Args:
            key: Identificador único del recurso
            data: Datos a almacenar
            cache_type: Tipo de caché ('videos', 'channels', 'playlists', 'progress')
        """
        self.cache[cache_type][key] = data
        self.last_update[key] = time.time()
        self.save_cache()


class YouTubeManager:
    """Gestiona todas las operaciones con la API de YouTube."""

    def __init__(self):
        self.youtube = None
        self.cache = YouTubeCache()
        self._setup_logging()

    def _setup_logging(self):
        """Configura el sistema de logging con colores y formato específico."""
        logging.basicConfig(
            filename=LOG_FILE,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )

    def log_and_print(self, message: str, color: str = Fore.WHITE, level: int = logging.INFO):
        """
        Registra un mensaje en el log y lo muestra en consola con color.

        Args:
            message: Mensaje a registrar
            color: Color para la consola (usando Fore de colorama)
            level: Nivel de logging
        """
        logging.log(level, message)
        print(f"{color}{message}{Fore.RESET}")

    def check_internet_connection(self) -> bool:
        """Verifica la conexión a Internet."""
        self.log_and_print(
            "=== Verificando conexión a Internet ===", Fore.YELLOW)
        try:
            response = requests.get("https://www.google.com", timeout=5)
            if response.status_code == 200:
                self.log_and_print(
                    "Conexión a Internet verificada", Fore.GREEN)
                return True
        except requests.ConnectionError:
            self.log_and_print(
                "No se detectó conexión a Internet", Fore.RED, logging.ERROR)
            return False
        return False

    def authenticate(self):
        """
        Realiza la autenticación OAuth 2.0 con manejo de refresco de token.
        Diseñado para entornos sin interacción humana (contenedores, scripts automáticos).
        """
        self.log_and_print("=== Iniciando autenticación OAuth 2.0 ===", Fore.YELLOW)
        try:
            # Intentar cargar credenciales existentes
            creds = None
            # Verificar si existe un token guardado
            if os.path.exists('YouTubeAutoListToken.json'):
                try:
                    creds = Credentials.from_authorized_user_file(
                        'YouTubeAutoListToken.json',
                        SCOPES
                    )
                except Exception as load_error:
                    self.log_and_print(
                        f"Error al cargar credenciales existentes: {str(load_error)}",
                        Fore.RED
                    )
                    creds = None

            # Verificar si el token necesita ser actualizado
            if creds and creds.expired and creds.refresh_token:
                try:
                    # Intentar refrescar el token
                    creds.refresh(Request())
                except Exception as refresh_error:
                    self.log_and_print(
                        f"Error al refrescar el token: {str(refresh_error)}",
                        Fore.RED
                    )
                    creds = None

            # Si no hay credenciales válidas, usar credenciales de servicio
            if not creds:
                try:
                    # Usar Service Account para autenticación sin interacción
                    creds = service_account.Credentials.from_service_account_file(
                        'youtubeautolist-ff36f334dab3.json',  # Archivo de credenciales de cuenta de servicio
                        scopes=SCOPES
                    )
                except FileNotFoundError:
                    # Generar un nuevo token usando flujo de autorización
                    flow = InstalledAppFlow.from_client_secrets_file(
                        'YouTubeAutoListClientSecret.json',
                        SCOPES
                    )
                    # Usar el flujo de autorización sin interacción (offline access)
                    creds = flow.run_console()

                # Guardar las credenciales actualizadas
                with open('YouTubeAutoListToken.json', 'w') as token:
                    # Serializar las credenciales de manera compatible
                    token_data = {
                        'token': getattr(creds, 'token', None),
                        'refresh_token': getattr(creds, 'refresh_token', None),
                        'token_uri': getattr(creds, 'token_uri', None),
                        'client_id': getattr(creds, 'client_id', None),
                        'client_secret': getattr(creds, 'client_secret', None),
                        'scopes': list(SCOPES)
                    }
                    json.dump({k: v for k, v in token_data.items() if v is not None}, token, indent=4)

            # Crear el cliente de YouTube
            self.youtube = build('youtube', 'v3', credentials=creds)
            self.log_and_print("Autenticación exitosa", Fore.GREEN)

        except Exception as e:
            self.log_and_print(
                f"Error crítico en la autenticación: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            raise

    def get_channel_videos(self, channel_config: Dict) -> List[Dict]:
        """
        Obtiene los videos de un canal que cumplen con los criterios especificados.

        Args:
            channel_config: Configuración del canal incluyendo patrones y límites
        """
        cached_videos = self.cache.get_cached_data(
            channel_config['channel_id'], 'videos')
        if cached_videos:
            self.log_and_print(
                f"Usando caché para videos del canal: {channel_config['channel_name']}",
                Fore.GREEN
            )
            return cached_videos

        try:
            videos = []
            # Calcular la fecha límite basada en hours_limit
            hours_limit = channel_config.get('hours_limit', 4)
            published_after = (
                datetime.utcnow() - timedelta(hours=hours_limit)
            ).isoformat() + 'Z'

            request = self.youtube.search().list(
                part="id,snippet",
                channelId=channel_config['channel_id'],
                maxResults=50,
                order="date",
                type="video",
                publishedAfter=published_after
            )

            while request:
                try:
                    response = request.execute()
                except HttpError as e:
                    # Verificar específicamente el error de cuota
                    error_details = e.error_details[0] if e.error_details else {
                    }
                    if error_details.get('reason') == 'quotaExceeded':
                        self.log_and_print(
                            "Cuota de YouTube excedida. Deteniendo operaciones.",
                            Fore.RED,
                            logging.ERROR
                        )
                        raise QuotaExceededException(
                            "Se ha excedido la cuota diaria de YouTube")
                    else:
                        raise

                for item in response['items']:
                    video_id = item['id']['videoId']
                    video_details = self._get_video_details(video_id)

                    # Aplicar filtros de manera estricta
                    if self._video_matches_criteria(video_details, channel_config):
                        videos.append(video_details)

                request = self.youtube.search().list_next(request, response)

            self.cache.update_cache(
                channel_config['channel_id'], videos, 'videos')
            return videos

        except QuotaExceededException:
            # Propagar la excepción para manejarla en el nivel superior
            raise
        except Exception as e:
            self.log_and_print(
                f"Error al obtener videos del canal {channel_config['channel_name']}: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            return []

    def _get_playlist_items(self, playlist_id: str) -> List[Dict]:
        """
        Obtiene todos los items de una lista de reproducción.

        Args:
            playlist_id: ID de la lista de reproducción
        """
        cached_items = self.cache.get_cached_data(playlist_id, 'playlists')
        if cached_items:
            return cached_items

        try:
            items = []
            request = self.youtube.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=playlist_id,
                maxResults=50
            )

            while request:
                response = request.execute()
                items.extend(response['items'])
                request = self.youtube.playlistItems().list_next(request, response)

            self.cache.update_cache(playlist_id, items, 'playlists')
            return items

        except Exception as e:
            self.log_and_print(
                f"Error al obtener items de la lista {playlist_id}: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            return []

    def _video_matches_criteria(self, video_details: Dict, channel_config: Dict) -> bool:
        """
        Verifica si un video cumple con los criterios especificados de manera más estricta.

        Args:
            video_details: Detalles del video
            channel_config: Configuración del canal con los criterios
        """
        try:
            if not video_details or 'snippet' not in video_details:
                return False

            title = video_details['snippet']['title']

            # Verificación del patrón de título
            title_pattern = channel_config.get('title_pattern')
            if title_pattern:
                title_match = re.search(title_pattern, title)
                if not title_match:
                    return False

            # Verificación de duración
            duration = self._parse_duration(
                video_details['contentDetails']['duration'])
            min_duration = channel_config.get('min_duration', 0)
            max_duration = channel_config.get('max_duration', float('inf'))

            duration_ok = (min_duration <= duration <= max_duration)

            return duration_ok

        except Exception as e:
            self.log_and_print(
                f"Error al verificar criterios del video: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            return False

    def _parse_duration(self, duration_str: str) -> int:
        """
        Convierte la duración de formato ISO 8601 a segundos.

        Args:
            duration_str: Duración en formato ISO 8601 (PT#H#M#S)
        """
        match = re.match(
            r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?',
            duration_str
        )
        if not match:
            return 0

        hours, minutes, seconds = match.groups()
        hours = int(hours) if hours else 0
        minutes = int(minutes) if minutes else 0
        seconds = int(seconds) if seconds else 0

        return hours * 3600 + minutes * 60 + seconds

    def manage_playlist(self, config: Dict):
        """
        Gestiona la lista de reproducción según la configuración proporcionada.

        Args:
            config: Configuración completa incluyendo ID de playlist y canales
        """
        try:
            for channel in config['channels']:
                self.log_and_print(
                    f"Procesando canal: {channel['channel_name']}",
                    Fore.YELLOW
                )

                try:
                    videos = self.get_channel_videos(channel)
                except QuotaExceededException:
                    # Si se excede la cuota, detener completamente el proceso
                    self.log_and_print(
                        "Cuota de YouTube excedida. Deteniendo procesamiento de canales.",
                        Fore.RED,
                        logging.ERROR
                    )
                    break

                current_playlist_items = self._get_playlist_items(
                    config['playlist_id'])

                for video in videos:
                    video_id = video['id']
                    if not self._video_in_playlist(video_id, current_playlist_items):
                        self._add_to_playlist(config['playlist_id'], video_id)

        except Exception as e:
            self.log_and_print(
                f"Error al gestionar la lista de reproducción: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            return []

    def _video_in_playlist(self, video_id: str, playlist_items: List[Dict]) -> bool:
        """
        Verifica si un video ya está en la lista de reproducción.

        Args:
            video_id: ID del video
            playlist_items: Lista de items en la playlist
        """
        return any(
            item['snippet']['resourceId']['videoId'] == video_id
            for item in playlist_items
        )

    def _add_to_playlist(self, playlist_id: str, video_id: str):
        """
        Agrega un video a la lista de reproducción.

        Args:
            playlist_id: ID de la lista de reproducción
            video_id: ID del video a agregar
        """
        try:
            self.youtube.playlistItems().insert(
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

            self.log_and_print(
                f"Video {video_id} agregado a la lista {playlist_id}",
                Fore.GREEN
            )

            # Invalidar caché de la playlist
            self.cache.update_cache(playlist_id, None, 'playlists')

        except Exception as e:
            self.log_and_print(
                f"Error al agregar video {video_id}: {str(e)}",
                Fore.RED,
                logging.ERROR
            )

    def _get_video_details(self, video_id: str) -> Optional[Dict]:
        """
        Obtiene los detalles de un video específico mediante la API de YouTube.

        Args:
            video_id: ID del video.

        Returns:
            Dict con los detalles del video si se encuentran, o None si ocurre un error.
        """
        try:
            # Realiza una solicitud a la API de YouTube para obtener detalles del video
            response = self.youtube.videos().list(
                part="snippet,contentDetails",
                id=video_id
            ).execute()

            # Verifica si se encontró el video y devuelve sus detalles
            if response['items']:
                return response['items'][0]
            else:
                self.log_and_print(
                    f"No se encontraron detalles para el video {video_id}",
                    Fore.YELLOW
                )
                return None
        except Exception as e:
            self.log_and_print(
                f"Error al obtener detalles del video {video_id}: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
        return None

    def load_config(self) -> Dict:
        """
        Carga la configuración desde el archivo o crea uno por defecto si no existe.

        Returns:
            Dict: Configuración cargada
        """
        if not os.path.exists(CONFIG_FILE):
            default_config = {
                "playlist_id": "",
                "channels": []
            }
            with open(CONFIG_FILE, 'w') as f:
                json.dump(default_config, f, indent=4)
            self.log_and_print(
                f"Archivo de configuración creado: {CONFIG_FILE}",
                Fore.YELLOW
            )
            return default_config

        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
            self.log_and_print(
                "Configuración cargada correctamente",
                Fore.GREEN
            )
            return config

        except Exception as e:
            self.log_and_print(
                f"Error al cargar la configuración: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            return {"playlist_id": "", "channels": []}


def main():
    """Función principal que ejecuta el proceso completo."""
    manager = YouTubeManager()

    try:
        # Verificar conexión a Internet
        if not manager.check_internet_connection():
            manager.log_and_print(
                "No se puede continuar sin conexión a Internet",
                Fore.RED,
                logging.ERROR
            )
            return

        # Autenticar
        manager.authenticate()

        # Cargar configuración
        config = manager.load_config()
        if not config['playlist_id'] or not config['channels']:
            manager.log_and_print(
                "Configuración incompleta. Verifica el archivo de configuración.",
                Fore.RED,
                logging.ERROR
            )
            return

        # Gestionar la lista de reproducción
        manager.manage_playlist(config)

        manager.log_and_print(
            "Proceso completado exitosamente",
            Fore.GREEN
        )
    except QuotaExceededException:
        print(Fore.RED + "Se ha excedido la cuota diaria de YouTube." + Fore.RESET)
    except Exception as e:
        manager.log_and_print(
            f"Error en el proceso principal: {str(e)}",
            Fore.RED,
            logging.ERROR
        )


if __name__ == "__main__":
    main()
