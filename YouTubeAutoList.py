import os
import json
import logging
import time
import re
from datetime import datetime, timedelta, timezone
import requests
from googleapiclient.errors import HttpError
from typing import Dict, List, Optional, Any
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from colorama import init, Fore
import pickle
from dateutil import parser
from dateutil.relativedelta import relativedelta
import pytz

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
        self.cache_duration = {
            'videos': 3600,  # 1 hora para videos
            'playlists': 7200  # 2 horas para playlists
        }

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

    def is_cache_valid(self, key: str, cache_type: str) -> bool:
        """Verifica si el caché aún es válido"""
        if key not in self.last_update:
            return False

        elapsed = time.time() - self.last_update[key]
        return elapsed < self.cache_duration[cache_type]


class YouTubeManager:
    """Gestiona todas las operaciones con la API de YouTube."""

    def __init__(self):
        self.youtube = None
        self.cache = YouTubeCache()
        self.video_cache = {}  # Cache para almacenar información de videos
        self.playlist_cache = {}  # Cache para almacenar información de playlists
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
        """Autenticación usando archivo de token o flujo interactivo"""
        self.log_and_print(
            "=== Iniciando autenticación OAuth 2.0 ===", Fore.YELLOW)
        try:
            # Intentar cargar token existente
            if os.path.exists('YouTubeAutoListToken.json'):
                creds = Credentials.from_authorized_user_file(
                    'YouTubeAutoListToken.json', SCOPES)
                if not creds.expired:
                    self.youtube = build('youtube', 'v3', credentials=creds)
                    self.log_and_print(
                        "Autenticación exitosa usando token existente", Fore.GREEN)
                    return
                if creds.refresh_token:
                    creds.refresh(Request())
                    self.youtube = build('youtube', 'v3', credentials=creds)
                    # Guardar token actualizado
                    with open('YouTubeAutoListToken.json', 'w') as token:
                        token.write(creds.to_json())
                    self.log_and_print(
                        "Token refrescado exitosamente", Fore.GREEN)
                    return

            # Si no hay token, hacer autenticación interactiva una vez
            flow = InstalledAppFlow.from_client_secrets_file(
                'YouTubeAutoListClientSecret.json', SCOPES)
            creds = flow.run_local_server(port=8080)

            # Guardar token para futuras ejecuciones
            with open('YouTubeAutoListToken.json', 'w') as token:
                token.write(creds.to_json())

            self.youtube = build('youtube', 'v3', credentials=creds)
            self.log_and_print("Nueva autenticación exitosa", Fore.GREEN)

            return True
        except Exception as e:
            self.log_and_print(
                f"Error en autenticación: {str(e)}", Fore.RED, logging.ERROR)
            raise

    def get_channel_videos(self, channel_config: Dict) -> List[Dict]:
        """Obtiene videos con optimización de cuota"""
        channel_id = channel_config['channel_id']

        # Usar caché si es válido
        if self.cache.is_cache_valid(channel_id, 'videos'):
            cached_videos = self.cache.get_cached_data(channel_id, 'videos')
            if cached_videos:
                return cached_videos

        # Limitar resultados máximos
        max_results = min(channel_config.get('max_results', 10), 50)

        try:
            videos = []
            request = self.youtube.search().list(
                part="id",  # Solicitar solo IDs primero
                channelId=channel_id,
                maxResults=max_results,
                order="date",
                type="video",
                publishedAfter=(datetime.utcnow() -
                                timedelta(hours=channel_config.get(
                                    'hours_limit', 8))
                                ).isoformat() + 'Z'
            )

            # Obtener IDs primero
            video_ids = []
            response = request.execute()
            for item in response['items']:
                video_ids.append(item['id']['videoId'])

            # Obtener detalles en una sola llamada
            if video_ids:
                details = self.youtube.videos().list(
                    part="snippet,contentDetails",
                    id=','.join(video_ids)
                ).execute()

                for video in details['items']:
                    if self._video_matches_criteria(video, channel_config):
                        videos.append(video)

            self.cache.update_cache(channel_id, videos, 'videos')
            return videos

        except Exception as e:
            self.log_and_print(
                f"Error al obtener videos: {str(e)}",
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
        Verifica si un video cumple con los criterios especificados.
        """
        try:
            if not video_details or 'snippet' not in video_details:
                return False

            title = video_details['snippet']['title']

            # Verificar el patrón del título si está configurado
            title_pattern = channel_config.get('title_pattern')
            if title_pattern:
                match = re.search(title_pattern, title, re.IGNORECASE)
                if not match:
                    self.log_and_print(
                        f"Video descartado: '{title}' no coincide con el patrón configurado: {title_pattern}",
                        Fore.YELLOW
                    )
                    return False
                else:
                    self.log_and_print(
                        f"Coincidencia encontrada en título: '{title}' con patrón: {title_pattern}\n"
                        f"Grupo coincidente: {match.group(0)}",
                        Fore.CYAN
                    )

            if 'id' in video_details:
                video_id = video_details['id']
                try:
                    # Obtener detalles completos del video
                    response = self.youtube.videos().list(
                        part="snippet,contentDetails,status",
                        id=video_id
                    ).execute()

                    if not response['items']:
                        return False

                    video_info = response['items'][0]
                    
                    # 1. Detectar Shorts por múltiples indicadores
                    is_short = False
                    
                    # Verificar en la descripción
                    description = str(video_info['snippet'].get('description', '')).lower()
                    if '#shorts' in description or '/shorts/' in description:
                        is_short = True
                    
                    # Verificar en el título
                    if '#shorts' in title.lower():
                        is_short = True
                    
                    # Verificar duración (los Shorts suelen ser menores a 60 segundos)
                    duration = self._parse_duration(video_info['contentDetails']['duration'])
                    if duration <= 60:
                        is_short = True
                    
                    # Verificar proporciones del video (vertical)
                    if 'contentDetails' in video_info:
                        default_thumbnail = video_info['snippet']['thumbnails'].get('default', {})
                        if default_thumbnail:
                            width = default_thumbnail.get('width', 0)
                            height = default_thumbnail.get('height', 0)
                            if height > width:  # Proporción vertical
                                is_short = True

                    if is_short:
                        self.log_and_print(
                            f"Video descartado: '{title}' detectado como Short",
                            Fore.YELLOW
                        )
                        return False

                    # Verificar duración según configuración
                    min_duration = channel_config.get('min_duration', 0)
                    max_duration = channel_config.get('max_duration', float('inf'))
                    
                    if not (min_duration <= duration <= max_duration):
                        self.log_and_print(
                            f"Video descartado: '{title}' duración ({duration}s) fuera de rango",
                            Fore.YELLOW
                        )
                        return False

                    # El video cumple todos los criterios
                    self.log_and_print(
                        f"Video aceptado: '{title}'",
                        Fore.GREEN
                    )
                    return True

                except Exception as e:
                    self.log_and_print(
                        f"Error al obtener detalles del video: {str(e)}",
                        Fore.RED,
                        logging.ERROR
                    )
                    return False

            return False

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
                # Verificar si el canal tiene playlist_id
                if not channel.get('playlist_id'):
                    self.log_and_print(
                        f"Canal {channel['channel_name']} sin playlist_id configurado. Saltando...",
                        Fore.RED,
                        logging.ERROR
                    )
                    continue

                self.log_and_print(
                    f"Procesando canal: {channel['channel_name']} -> Playlist: {channel.get('playlist_name', 'Sin nombre')}",
                    Fore.YELLOW
                )

                try:
                    # Obtener videos y playlist_items usando el playlist_id del canal
                    videos = self.get_channel_videos(channel)
                    current_playlist_items = self._get_playlist_items(
                        channel['playlist_id'])

                    # Procesar los videos encontrados
                    for video in videos:
                        video_id = video['id']
                        if not self._video_in_playlist(video_id, current_playlist_items):
                            self._add_to_playlist(
                                channel['playlist_id'], video_id)

                except QuotaExceededException:
                    self.log_and_print(
                        "Cuota de YouTube excedida. Deteniendo procesamiento de canales.",
                        Fore.RED,
                        logging.ERROR
                    )
                    break

        except Exception as e:
            self.log_and_print(
                f"Error al gestionar la lista de reproducción: {str(e)}",
                Fore.RED,
                logging.ERROR
            )

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
        """Carga la configuración desde el archivo con manejo mejorado de errores."""
        try:
            if not os.path.exists(CONFIG_FILE):
                default_config = {
                    "channels": []
                }
                with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, indent=4, ensure_ascii=False)
                self.log_and_print(
                    f"Archivo de configuración creado: {CONFIG_FILE}",
                    Fore.YELLOW
                )
                return default_config

            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                try:
                    config = json.load(f)
                    self.log_and_print(
                        "Configuración cargada correctamente", Fore.GREEN)
                    return config
                except json.JSONDecodeError as e:
                    self.log_and_print(
                        f"Error de sintaxis en el archivo de configuración (línea {e.lineno}, columna {e.colno}): {e.msg}",
                        Fore.RED,
                        logging.ERROR
                    )
                    raise

        except Exception as e:
            self.log_and_print(
                f"Error al cargar la configuración: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            return {"channels": []}

    def cleanup_playlists(self):
        """Limpia las listas de reproducción según los criterios de tiempo."""
        try:
            playlist_limits = {
                'PLwFfNCxuxPv1S0Laim0gk3WOXJvLesNi0': timedelta(days=2),
                'PLwFfNCxuxPv0S6EDvvtrpcA86wiVpBvXs': timedelta(days=14)
            }

            for playlist_id, time_limit in playlist_limits.items():
                self.log_and_print(
                    f"=== Iniciando limpieza de playlist {playlist_id} (límite: {time_limit.days} días) ===",
                    Fore.YELLOW
                )

                try:
                    playlist_items = self._get_playlist_items(playlist_id)
                    
                    if not playlist_items:
                        continue

                    videos_eliminados = 0
                    for item in playlist_items:
                        try:
                            # Usar contentDetails.videoPublishedAt para la fecha real de publicación
                            video_published_at = datetime.strptime(
                                item['contentDetails']['videoPublishedAt'],
                                '%Y-%m-%dT%H:%M:%SZ'
                            )
                            
                            # Calcular tiempo desde la publicación original
                            time_passed = datetime.utcnow() - video_published_at
                            
                            # Log mejorado
                            self.log_and_print(
                                f"Video: {item['snippet']['title']}\n"
                                f"  - Fecha publicación original: {video_published_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"  - Días desde publicación: {time_passed.days}",
                                Fore.CYAN
                            )

                            if time_passed > time_limit:
                                try:
                                    self.youtube.playlistItems().delete(
                                        id=item['id']
                                    ).execute()

                                    videos_eliminados += 1
                                    self.log_and_print(
                                        f"Video {item['snippet']['title']} eliminado por antigüedad "
                                        f"(días desde publicación: {time_passed.days} > {time_limit.days})",
                                        Fore.GREEN
                                    )
                                    time.sleep(1)

                                except HttpError as e:
                                    error_details = e.error_details[0] if e.error_details else {}
                                    if error_details.get('reason') == 'quotaExceeded':
                                        raise QuotaExceededException(
                                            "Se ha excedido la cuota diaria de YouTube"
                                        )
                                    else:
                                        self.log_and_print(
                                            f"Error al eliminar video: {str(e)}",
                                            Fore.RED,
                                            logging.ERROR
                                        )

                        except Exception as e:
                            self.log_and_print(
                                f"Error procesando video: {str(e)}",
                                Fore.RED,
                                logging.ERROR
                            )
                            continue

                    self.log_and_print(
                        f"=== Limpieza completada para playlist {playlist_id}: {videos_eliminados} videos eliminados ===",
                        Fore.GREEN
                    )
                    self.cache.update_cache(playlist_id, None, 'playlists')

                except QuotaExceededException:
                    raise

            self.log_and_print(
                "=== Proceso de limpieza finalizado para todas las playlists ===",
                Fore.GREEN
            )

        except Exception as e:
            self.log_and_print(
                f"Error en limpieza de playlists: {str(e)}",
                Fore.RED,
                logging.ERROR
            )


def log_video_status(status, title, reason, pattern_match=None):
    if status == "aceptado":
        print(f"\033[92mVideo {status}: '{title}'\033[0m")
        print(f"\033[92mCoincide con patrón: {pattern_match}\033[0m")
    else:
        print(f"\033[91mVideo {status}: '{title}'\033[0m")
        print(f"\033[91mRazón: {reason}\033[0m")


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
        if not config.get('channels'):
            manager.log_and_print(
                "No hay canales configurados.", Fore.RED, logging.ERROR)
            return

        # Validar playlist_id en cada canal
        for channel in config['channels']:
            if not channel.get('playlist_id'):
                manager.log_and_print(
                    f"Error: Canal '{channel.get('channel_name')}' no tiene playlist_id.",
                    Fore.RED,
                    logging.ERROR
                )
                return

        # Gestionar la lista de reproducción
        manager.manage_playlist(config)

        # Ejecutar limpieza de playlists después de procesar todos los canales
        manager.cleanup_playlists()

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

# Fin del script
