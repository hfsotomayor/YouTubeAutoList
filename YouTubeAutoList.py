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
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from colorama import init, Fore
import pickle
import sys  # Añadir import de sys
import telegram  # Añadir al requirements.txt
import smtplib
from email.mime.text import MIMEText

# Inicialización de colorama para soporte de colores en consola
init()

# Configuración de constantes
SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']
BASE_DIR = '/app'
CACHE_FILE = os.path.join(BASE_DIR, 'YouTubeAutoListCache.pkl')
CONFIG_FILE = os.path.join(BASE_DIR, 'YouTubeAutoListConfig.json')
TOKEN_FILE = os.path.join(BASE_DIR, 'YouTubeAutoListToken.json')
LOG_FILE = os.path.join(BASE_DIR, 'YouTubeAutoList.log')
CACHE_DURATION = 7200  # 2 horas en segundos (configurable)
NOTIFICATION_CONFIG = os.path.join(BASE_DIR, 'YouTubeAutoListNotification_config.json')


class QuotaExceededException(Exception):
    """Excepción personalizada para manejar el exceso de cuota de YouTube."""
    def __init__(self, message="Se ha excedido la cuota diaria de YouTube"):
        self.message = message
        super().__init__(self.message)


class TokenExpiredException(Exception):
    """Excepción personalizada para manejar tokens expirados o revocados."""
    def __init__(self, message="El token ha expirado o ha sido revocado"):
        self.message = message
        super().__init__(self.message)


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


class NotificationManager:
    """Gestiona las notificaciones del sistema."""
    
    def __init__(self, config):
        self.telegram_token = config.get('telegram_token')
        self.telegram_chat_id = config.get('telegram_chat_id')
        self.email_config = config.get('email')
        self.bot = None
        if self.telegram_token:
            try:
                self.bot = telegram.Bot(token=self.telegram_token)
            except telegram.error.InvalidToken:
                logging.warning("Token de Telegram inválido. Las notificaciones por Telegram estarán deshabilitadas.")

    def send_notification(self, message: str, level: str = 'info'):
        """Envía notificación por múltiples canales."""
        try:
            # Telegram
            if self.bot:
                self.bot.send_message(
                    chat_id=self.telegram_chat_id,
                    text=f"[{level.upper()}] YouTubeAutoList: {message}"
                )
            
            # Email para errores críticos
            if level == 'critical' and self.email_config:
                self._send_email(message)
        except Exception as e:
            logging.error(f"Error enviando notificación: {str(e)}")

    def _send_email(self, message: str):
        """Envía email para errores críticos."""
        try:
            msg = MIMEText(message)
            msg['Subject'] = 'YouTubeAutoList - ERROR CRÍTICO'
            msg['From'] = self.email_config['from']
            msg['To'] = self.email_config['to']

            with smtplib.SMTP_SSL(self.email_config['smtp_server']) as server:
                server.login(
                    self.email_config['username'],
                    self.email_config['password']
                )
                server.send_message(msg)
        except Exception as e:
            logging.error(f"Error enviando email: {str(e)}")


class ExecutionStats:
    """Mantiene estadísticas de la ejecución."""
    def __init__(self):
        self.stats = {
            'added': {},      # videos añadidos por playlist
            'removed': {},    # videos eliminados por playlist
            'duration': {     # duración total por playlist
                'added': {},
                'removed': {}
            },
            'playlist_names': {}  # mapeo de IDs a nombres
        }
        self.totals = {
            'videos_added': 0,
            'videos_removed': 0,
            'duration_added': 0,
            'duration_removed': 0
        }

    def set_playlist_name(self, playlist_id: str, name: str):
        """Guarda el nombre de la playlist para mostrar en el resumen."""
        self.stats['playlist_names'][playlist_id] = name

    def add_video(self, playlist_id: str, duration: int):
        """Registra un video añadido."""
        self.stats['added'][playlist_id] = self.stats['added'].get(playlist_id, 0) + 1
        self.stats['duration']['added'][playlist_id] = self.stats['duration']['added'].get(playlist_id, 0) + duration
        self.totals['videos_added'] += 1
        self.totals['duration_added'] += duration

    def remove_video(self, playlist_id: str, duration: int):
        """Registra un video eliminado."""
        self.stats['removed'][playlist_id] = self.stats['removed'].get(playlist_id, 0) + 1
        self.stats['duration']['removed'][playlist_id] = self.stats['duration']['removed'].get(playlist_id, 0) + duration
        self.totals['videos_removed'] += 1
        self.totals['duration_removed'] += duration

    def format_duration(self, seconds: int) -> str:
        """Formatea la duración en formato legible."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"

    def get_summary(self) -> str:
        """Genera un resumen de la ejecución."""
        summary = ["=== Resumen de Ejecución ==="]
        
        for playlist_id in set(self.stats['added'].keys()) | set(self.stats['removed'].keys()):
            # Usar nombre de playlist si está disponible, si no usar ID
            playlist_name = self.stats['playlist_names'].get(playlist_id, playlist_id)
            summary.append(f"\nPlaylist: {playlist_name}")
            
            # Videos agregados
            videos_added = self.stats['added'].get(playlist_id, 0)
            duration_added = self.stats['duration']['added'].get(playlist_id, 0)
            summary.append(f"  + Agregados: {videos_added} videos ({self.format_duration(duration_added)})")
            
            # Videos eliminados
            videos_removed = self.stats['removed'].get(playlist_id, 0)
            duration_removed = self.stats['duration']['removed'].get(playlist_id, 0)
            summary.append(f"  - Eliminados: {videos_removed} videos ({self.format_duration(duration_removed)})")

        # Agregar totales al final
        summary.extend([
            "\n=== Totales ===",
            f"Videos agregados: {self.totals['videos_added']} ({self.format_duration(self.totals['duration_added'])})",
            f"Videos eliminados: {self.totals['videos_removed']} ({self.format_duration(self.totals['duration_removed'])})"
        ])

        return "\n".join(summary)


class YouTubeManager:
    """Gestiona todas las operaciones con la API de YouTube."""

    def __init__(self):
        self.youtube = None
        self.cache = YouTubeCache()
        self._setup_logging()
        self.notification = NotificationManager(self.load_notification_config())
        self.quota_exceeded = False  # Nueva bandera para control de cuota
        self.stats = ExecutionStats()

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
        """Autenticación usando archivo de token con mejor manejo de errores"""
        self.log_and_print("=== Iniciando autenticación OAuth 2.0 ===", Fore.YELLOW)
        try:
            if not os.path.exists(TOKEN_FILE):
                self.log_and_print(
                    f"Archivo de token no encontrado en {TOKEN_FILE}",
                    Fore.RED,
                    logging.ERROR
                )
                raise FileNotFoundError(f"Token file not found at {TOKEN_FILE}")

            # Verificar permisos del archivo
            token_perms = oct(os.stat(TOKEN_FILE).st_mode)[-3:]
            if token_perms != '600':
                self.log_and_print(
                    f"Advertencia: Permisos incorrectos en {TOKEN_FILE}: {token_perms}",
                    Fore.YELLOW
                )

            with open(TOKEN_FILE, 'r') as token_file:
                token_data = json.load(token_file)

            # Verificar que todos los campos necesarios estén presentes
            required_fields = ['token', 'refresh_token', 'token_uri', 'client_id', 'client_secret', 'scopes']
            missing_fields = [field for field in required_fields if field not in token_data]
            
            if missing_fields:
                self.log_and_print(
                    f"Campos faltantes en el token: {', '.join(missing_fields)}. Regenere el token.",
                    Fore.RED,
                    logging.ERROR
                )
                raise ValueError(f"Missing fields in token: {', '.join(missing_fields)}")

            try:
                creds = Credentials(
                    token=token_data['token'],
                    refresh_token=token_data['refresh_token'],
                    token_uri=token_data['token_uri'],
                    client_id=token_data['client_id'],
                    client_secret=token_data['client_secret'],
                    scopes=token_data['scopes']
                )

                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    # Actualizar token file con el nuevo token
                    token_data['token'] = creds.token
                    with open(TOKEN_FILE, 'w') as token_file:
                        json.dump(token_data, token_file)

                self.youtube = build('youtube', 'v3', credentials=creds)
                self.log_and_print("Autenticación exitosa", Fore.GREEN)
                return True

            except Exception as e:
                self.log_and_print(
                    f"Error al crear/refrescar credenciales: {str(e)}",
                    Fore.RED,
                    logging.ERROR
                )
                raise

        except json.JSONDecodeError as e:
            self.log_and_print(
                f"Error al decodificar el archivo de token: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            raise
        except Exception as e:
            self.log_and_print(
                f"Error en autenticación: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            raise

    def _check_token_error(self, error: Exception):
        """Verifica si el error está relacionado con el token."""
        error_str = str(error).lower()
        if "invalid_grant" in error_str or "token" in error_str and ("expired" in error_str or "revoked" in error_str):
            message = "¡ERROR DE TOKEN! El token ha expirado o ha sido revocado. Ejecute auth_setup.py para generar uno nuevo."
            self.log_and_print(message, Fore.RED, logging.ERROR)
            self.notification.send_notification(message, 'critical')
            raise TokenExpiredException()

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

        except HttpError as e:
            self._check_quota_error(e)
            raise
        except Exception as e:
            self._check_token_error(e)  # Verificar error de token
            self.log_and_print(
                f"Error al obtener videos: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            raise  # Propagar la excepción

    def _check_quota_error(self, error: HttpError):
        """Verifica si el error es de cuota excedida y establece la bandera"""
        if isinstance(error, HttpError) and error.resp.status == 403 and "quotaExceeded" in str(error):
            self.quota_exceeded = True
            message = "¡CUOTA EXCEDIDA! Deteniendo operaciones que requieren cuota."
            self.log_and_print(message, Fore.RED, logging.ERROR)
            self.notification.send_notification(message, 'critical')
            raise QuotaExceededException()

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
                try:
                    response = request.execute()
                    items.extend(response['items'])
                    request = self.youtube.playlistItems().list_next(request, response)
                except HttpError as e:
                    self._check_quota_error(e)
                    raise

            self.cache.update_cache(playlist_id, items, 'playlists')
            return items

        except QuotaExceededException:
            raise
        except Exception as e:
            self._check_token_error(e)  # Verificar error de token
            self.log_and_print(
                f"Error al obtener items de la lista {playlist_id}: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            raise  # Propagar la excepción

    def _video_matches_criteria(self, video_details: Dict, channel_config: Dict) -> bool:
        """Verifica si un video cumple con los criterios especificados."""
        try:
            if not video_details or 'snippet' not in video_details:
                return False

            title = video_details['snippet']['title']

            # Verificar el patrón del título si está configurado
            title_pattern = channel_config.get('title_pattern')
            if title_pattern:
                try:
                    match = re.search(title_pattern, title, re.IGNORECASE)
                    if not match:
                        self.log_and_print(
                            f"Video descartado: '{title}' no coincide con el patrón configurado",
                            Fore.YELLOW
                        )
                        return False
                    else:
                        # Mostrar el grupo coincidente y su contexto
                        match_start = max(0, match.start() - 10)
                        match_end = min(len(title), match.end() + 10)
                        context = title[match_start:match_end]
                        
                        self.log_and_print(
                            f"Coincidencia encontrada en título: '{title}'\n"
                            f"Patrón coincidente: '{match.group(0)}'\n"
                            f"Contexto: '...{context}...'",
                            Fore.CYAN
                        )
                except re.error as e:
                    self.log_and_print(
                        f"Error en el patrón regex '{title_pattern}': {str(e)}",
                        Fore.RED,
                        logging.ERROR
                    )
                    return False

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
                    
                    # Sistema mejorado de detección de Shorts
                    is_short = False
                    short_indicators = 0
                    total_indicators = 4  # Número total de indicadores
                    
                    # 1. Verificar en la descripción
                    description = str(video_info['snippet'].get('description', '')).lower()
                    if '#shorts' in description or '/shorts/' in description:
                        short_indicators += 1
                    
                    # 2. Verificar en el título
                    if '#shorts' in title.lower():
                        short_indicators += 1
                    
                    # 3. Verificar duración
                    duration = self._parse_duration(video_info['contentDetails']['duration'])
                    if duration <= 60:
                        short_indicators += 1
                    
                    # 4. Verificar proporciones del video
                    if 'contentDetails' in video_info:
                        default_thumbnail = video_info['snippet']['thumbnails'].get('default', {})
                        if default_thumbnail:
                            width = default_thumbnail.get('width', 0)
                            height = default_thumbnail.get('height', 0)
                            if height > width:  # Proporción vertical
                                short_indicators += 1

                    # Un video es considerado short si cumple con al menos 3 de los 4 indicadores
                    is_short = short_indicators >= 3

                    if is_short:
                        self.log_and_print(
                            f"Video descartado: '{title}' detectado como Short "
                            f"(Indicadores: {short_indicators}/{total_indicators})",
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
                # Guardar nombre de playlist para las estadísticas
                if channel.get('playlist_id') and channel.get('playlist_name'):
                    self.stats.set_playlist_name(channel['playlist_id'], channel['playlist_name'])

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

            # Registrar estadística
            video_details = self._get_video_details(video_id)
            if video_details:
                duration = self._parse_duration(video_details['contentDetails']['duration'])
                self.stats.add_video(playlist_id, duration)

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

    def load_notification_config(self) -> Dict:
        try:
            with open(NOTIFICATION_CONFIG, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.log_and_print(
                f"Error al cargar configuración de notificaciones: {str(e)}",
                Fore.YELLOW
            )
            return {}

    def cleanup_playlists(self):
        """Limpia las listas de reproducción según los criterios de tiempo."""
        if self.quota_exceeded:
            self.log_and_print(
                "Omitiendo limpieza por cuota excedida",
                Fore.YELLOW
            )
            return

        try:
            playlist_limits = {
                'PLwFfNCxuxPv1S0Laim0gk3WOXJvLesNi0': timedelta(days=2),
                'PLwFfNCxuxPv0S6EDvvtrpcA86wiVpBvXs': timedelta(days=14)
            }

            for playlist_id, time_limit in playlist_limits.items():
                try:
                    self.log_and_print(
                        f"=== Iniciando limpieza de playlist {playlist_id} (límite: {time_limit.days} días) ===",
                        Fore.YELLOW
                    )

                    playlist_items = self._get_playlist_items(playlist_id)
                    
                    if not playlist_items:
                        continue

                    videos_eliminados = 0
                    for item in playlist_items:
                        if self.quota_exceeded:
                            self.log_and_print(
                                "Deteniendo limpieza por cuota excedida",
                                Fore.YELLOW
                            )
                            return

                        try:
                            # Extraer fecha del item ya obtenido (no requiere llamada adicional a la API)
                            published_at = None
                            try:
                                if ('contentDetails' in item and 
                                    'videoPublishedAt' in item['contentDetails']):
                                    published_at = datetime.strptime(
                                        item['contentDetails']['videoPublishedAt'],
                                        '%Y-%m-%dT%H:%M:%SZ'
                                    )
                                else:
                                    # Si no hay fecha de publicación, usar snippet.publishedAt como fallback
                                    published_at = datetime.strptime(
                                        item['snippet']['publishedAt'],
                                        '%Y-%m-%dT%H:%M:%SZ'
                                    )
                                
                                # Calcular tiempo desde la publicación
                                time_passed = datetime.utcnow() - published_at
                                
                                # Log mejorado
                                self.log_and_print(
                                    f"Video: {item['snippet']['title']}\n"
                                    f"  - Fecha publicación: {published_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                                    f"  - Días desde publicación: {time_passed.days}",
                                    Fore.CYAN
                                )

                                if time_passed > time_limit:
                                    try:
                                        if not self.quota_exceeded:  # Solo intentar eliminar si no hay exceso de cuota
                                            # Obtener detalles del video antes de eliminarlo
                                            video_id = item['snippet']['resourceId']['videoId']
                                            video_details = self._get_video_details(video_id)
                                            
                                            if video_details and 'contentDetails' in video_details:
                                                duration = self._parse_duration(video_details['contentDetails']['duration'])
                                                # Registrar estadística antes de eliminar
                                                self.stats.remove_video(playlist_id, duration)
                                            
                                                # Eliminar el video
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
                                            else:
                                                self.log_and_print(
                                                    f"No se pudieron obtener detalles para el video: {item['snippet']['title']}",
                                                    Fore.YELLOW
                                                )
                                                continue

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

                            except (KeyError, ValueError) as e:
                                self.log_and_print(
                                    f"No se pudo determinar la fecha de publicación para: {item['snippet']['title']}. Error: {str(e)}",
                                    Fore.YELLOW
                                )
                                continue

                        except Exception as e:
                            if "quotaExceeded" in str(e):
                                self.quota_exceeded = True
                                return
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
                    return  # Salir inmediatamente
                except Exception as e:
                    self.log_and_print(
                        f"Error procesando playlist {playlist_id}: {str(e)}",
                        Fore.RED,
                        logging.ERROR
                    )

            self.log_and_print(
                "=== Proceso de limpieza finalizado para todas las playlists ===",
                Fore.GREEN
            )

        except QuotaExceededException:
            return  # Salir inmediatamente
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

        # Autenticar y ejecutar procesos principales
        manager.authenticate()
        config = manager.load_config()

        # Gestionar la lista de reproducción
        try:
            manager.manage_playlist(config)
        except QuotaExceededException:
            # Continuar con otras operaciones que no requieren cuota
            pass

        # Solo ejecutar limpieza si no hay exceso de cuota
        if not manager.quota_exceeded:
            manager.cleanup_playlists()
        
        # Generar y mostrar resumen
        summary = manager.stats.get_summary()
        
        # Mostrar en consola
        manager.log_and_print("\n" + summary, Fore.CYAN)
        
        # Enviar notificación
        manager.notification.send_notification(summary, 'info')
        
        manager.log_and_print(
            "Proceso completado" + (" (con limitación de cuota)" if manager.quota_exceeded else " exitosamente"),
            Fore.GREEN
        )

    except QuotaExceededException as e:
        manager.log_and_print(
            f"ERROR CRÍTICO: {str(e)}. Deteniendo el programa inmediatamente.",
            Fore.RED,
            logging.ERROR
        )
        sys.exit(1)  # Asegura que el programa termine inmediatamente
    except TokenExpiredException as e:
        manager.log_and_print(
            f"ERROR CRÍTICO: {str(e)}. Ejecute auth_setup.py para generar un nuevo token.",
            Fore.RED,
            logging.ERROR
        )
        sys.exit(1)
    except Exception as e:
        manager.log_and_print(
            f"Error en el proceso principal: {str(e)}",
            Fore.RED,
            logging.ERROR
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

# Fin del script
