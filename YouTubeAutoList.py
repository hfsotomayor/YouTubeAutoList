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
from database_manager import DatabaseManager

# Inicialización de colorama para soporte de colores en consola
init()

# Configuración de constantes
SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']
BASE_DIR = '/app'
DB_DIR = os.path.join(BASE_DIR, 'db')
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
LOG_FILE = os.path.join(LOGS_DIR, 'YouTubeAutoList.log')
CACHE_FILE = os.path.join(BASE_DIR, 'YouTubeAutoListCache.pkl')
CONFIG_FILE = os.path.join(BASE_DIR, 'YouTubeAutoListConfig.json')
TOKEN_FILE = os.path.join(BASE_DIR, 'YouTubeAutoListToken.json')
CACHE_DURATION = 7200  # 2 horas en segundos (configurable)
NOTIFICATION_CONFIG = os.path.join(BASE_DIR, 'YouTubeAutoListNotification_config.json')

# Asegurar que los directorios existan
for directory in [DB_DIR, LOGS_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)


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
            'added': {},
            'removed': {},
            'duration': {
                'added': {},
                'removed': {}
            },
            'playlist_names': {},
            'quota_usage': {
                'search': 0,
                'video_details': 0,
                'playlist_items': 0,
                'add_video': 0,
                'delete_video': 0
            },
            'quota_saved': {  # Nuevo contador para cuota ahorrada
                'search_operations': 0,
                'total_saved': 0
            },
            'rss_stats': {    # Estadísticas específicas de RSS
                'videos_from_rss': 0,
                'videos_from_api': 0,
                'failed_rss_feeds': 0
            },
            'channel_stats': {},  # Añadir inicialización
            'video_origins': {}   # Añadir inicialización
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

    def remove_video(self, playlist_id: str, duration: int, channel_name: str = 'Unknown'):
        """Registra un video eliminado con su canal de origen."""
        # Asegurar que siempre haya un valor para channel_name
        channel_name = channel_name if channel_name else 'Unknown'
        
        self.stats['removed'][playlist_id] = self.stats['removed'].get(playlist_id, 0) + 1
        self.stats['duration']['removed'][playlist_id] = self.stats['duration']['removed'].get(playlist_id, 0) + duration
        self.totals['videos_removed'] += 1
        self.totals['duration_removed'] += duration
        
        # Registrar el canal de origen del video eliminado
        if channel_name not in self.stats['video_origins']:
            self.stats['video_origins'][channel_name] = 0
        self.stats['video_origins'][channel_name] += 1

    def update_channel_stats(self, channel_name: str, action: str):
        """Actualiza estadísticas por canal."""
        if channel_name not in self.stats['channel_stats']:
            self.stats['channel_stats'][channel_name] = {'added': 0, 'removed': 0}
        self.stats['channel_stats'][channel_name][action] += 1

    def add_quota_usage(self, operation: str, units: int):
        """Registra uso de cuota."""
        self.stats['quota_usage'][operation] += units

    def add_quota_saved(self, operation: str, amount: int):
        """Registra cuota ahorrada por usar RSS."""
        self.stats['quota_saved'][operation] = self.stats['quota_saved'].get(operation, 0) + amount
        self.stats['quota_saved']['total_saved'] += amount

    def format_duration(self, seconds: int) -> str:
        """Formatea la duración en formato legible."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"

    def get_summary(self) -> str:
        """Genera un resumen de la ejecución."""
        summary = ["=== Resumen de Ejecución ==="]
        
        # Resumen por playlist
        for playlist_id in self.stats['playlist_names'].keys():
            playlist_name = self.stats['playlist_names'][playlist_id]
            videos_added = self.stats['added'].get(playlist_id, 0)
            duration_added = self.stats['duration']['added'].get(playlist_id, 0)
            videos_removed = self.stats['removed'].get(playlist_id, 0)
            duration_removed = self.stats['duration']['removed'].get(playlist_id, 0)
            
            summary.extend([
                f"\nPlaylist: {playlist_name}",
                f"  + Agregados: {videos_added} videos ({self.format_duration(duration_added)})",
                f"  - Eliminados: {videos_removed} videos ({self.format_duration(duration_removed)})"
            ])

        # Estadísticas por canal con origen de eliminados
        summary.append("\n=== Estadísticas por Canal ===")
        for channel, stats in self.stats['channel_stats'].items():
            removed_from_channel = self.stats['video_origins'].get(channel, 0)
            summary.extend([
                f"\nCanal: {channel}",
                f"  + Videos agregados: {stats['added']}",
                f"  - Videos eliminados: {stats['removed']} (Origen de {removed_from_channel} videos eliminados)"
            ])

        summary.extend([
            "\n=== Totales ===",
            f"Videos agregados: {self.totals['videos_added']} ({self.format_duration(self.totals['duration_added'])}) - Cuota: {self.stats['quota_usage']['add_video']} unidades",
            f"Videos eliminados: {self.totals['videos_removed']} ({self.format_duration(self.totals['duration_removed'])}) - Cuota: {self.stats['quota_usage']['delete_video']} unidades"
        ])

        total_quota = sum(self.stats['quota_usage'].values())
        summary.extend([
            "\n=== Uso de Cuota ===",
            f"Búsquedas: {self.stats['quota_usage']['search']} unidades",
            f"Detalles de videos: {self.stats['quota_usage']['video_details']} unidades",
            f"Operaciones de playlist: {self.stats['quota_usage']['playlist_items']} unidades",
            f"Agregar videos: {self.stats['quota_usage']['add_video']} unidades",
            f"Eliminar videos: {self.stats['quota_usage']['delete_video']} unidades",
            f"Total cuota utilizada: {total_quota} unidades"
        ])

        # Agregar sección de ahorro de cuota
        summary.extend([
            "\n=== Ahorro de Cuota con RSS ===",
            f"Operaciones de búsqueda evitadas: {self.stats['quota_saved']['search_operations']}",
            f"Cuota total ahorrada: {self.stats['quota_saved']['total_saved']} unidades",
            f"Videos obtenidos via RSS: {self.stats['rss_stats']['videos_from_rss']}",
            f"Videos obtenidos via API: {self.stats['rss_stats']['videos_from_api']}",
            f"Feeds RSS fallidos: {self.stats['rss_stats']['failed_rss_feeds']}"
        ])

        return "\n".join(summary)


class YouTubeManager:
    """Gestiona todas las operaciones con la API de YouTube."""

    def __init__(self):
        self.youtube = None
        self.cache = YouTubeCache()
        self._setup_logging()
        self.notification = NotificationManager(self.load_notification_config())
        self.quota_exceeded = False
        self.stats = ExecutionStats()
        self.db = DatabaseManager(BASE_DIR)
        self.logger = logging.getLogger(__name__)
        
        # Importación mejorada del módulo rss_manager con logging detallado
        self.rss_manager = self._import_rss_manager()

    def _import_rss_manager(self):
        """Intenta importar el módulo RSS Manager con manejo detallado de errores."""
        try:
            # Verificar que el archivo existe
            rss_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rss_manager.py')
            
            if not os.path.exists(rss_file):
                self.log_and_print(
                    f"ADVERTENCIA: Archivo rss_manager.py no encontrado en {rss_file}. "
                    f"Funcionando en modo solo API.",
                    Fore.YELLOW,
                    logging.WARNING
                )
                return None
            
            # Agregar el directorio actual a sys.path si no está
            app_dir = os.path.dirname(os.path.abspath(__file__))
            if app_dir not in sys.path:
                sys.path.insert(0, app_dir)
            
            # Intentar importar
            from rss_manager import YouTubeRSSManager
            
            self.log_and_print(
                "Módulo RSS Manager importado correctamente",
                Fore.GREEN,
                logging.INFO
            )
            
            return YouTubeRSSManager(self.logger)
            
        except ImportError as import_error:
            self.log_and_print(
                f"ERROR importando RSS Manager - Tipo: ImportError\n"
                f"  Detalle: {str(import_error)}\n"
                f"  Ruta buscada: {app_dir if 'app_dir' in locals() else 'desconocida'}\n"
                f"  sys.path: {sys.path[:3]}...\n"
                f"  Funcionando en modo solo API",
                Fore.YELLOW,
                logging.WARNING
            )
            return None
            
        except AttributeError as attr_error:
            self.log_and_print(
                f"ERROR importando RSS Manager - Tipo: AttributeError\n"
                f"  Detalle: {str(attr_error)}\n"
                f"  Es posible que YouTubeRSSManager no esté definido en rss_manager.py\n"
                f"  Funcionando en modo solo API",
                Fore.YELLOW,
                logging.WARNING
            )
            return None
            
        except Exception as e:
            self.log_and_print(
                f"ERROR inesperado importando RSS Manager\n"
                f"  Tipo: {type(e).__name__}\n"
                f"  Detalle: {str(e)}\n"
                f"  Módulo: {e.__class__.__module__}\n"
                f"  Funcionando en modo solo API",
                Fore.YELLOW,
                logging.WARNING
            )
            return None

    def load_notification_config(self) -> Dict:
        """Carga la configuración de notificaciones."""
        try:
            with open(NOTIFICATION_CONFIG, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.log_and_print(
                f"Error al cargar configuración de notificaciones: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            return {}

    def _setup_logging(self):
        """Configura el sistema de logging con colores y formato específico."""
        # Crear directorio de logs si no existe
        if not os.path.exists(LOGS_DIR):
            os.makedirs(LOGS_DIR)

        # Generar nombre del archivo de log con la fecha actual
        log_filename = datetime.now().strftime('YouTubeAutoList_%Y%m%d.log')
        log_filepath = os.path.join(LOGS_DIR, log_filename)

        # Configurar el logger
        logging.basicConfig(
            filename=log_filepath,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )

        # Registrar inicio de nueva sesión
        logging.info("=== Iniciando nueva sesión de logging ===")
        
        # Limpiar logs antiguos (mantener solo últimos 30 días)
        self._cleanup_old_logs()

        self.logger = logging.getLogger(__name__)

    def _cleanup_old_logs(self):
        """Limpia archivos de log más antiguos que 30 días."""
        try:
            now = datetime.now()
            for filename in os.listdir(LOGS_DIR):
                if filename.startswith('YouTubeAutoList_') and filename.endswith('.log'):
                    filepath = os.path.join(LOGS_DIR, filename)
                    file_date_str = filename[15:23]  # Extraer YYYYMMDD del nombre
                    try:
                        file_date = datetime.strptime(file_date_str, '%Y%m%d')
                        if (now - file_date).days > 30:
                            os.remove(filepath)
                            logging.info(f"Log antiguo eliminado: {filename}")
                    except ValueError:
                        continue
        except Exception as e:
            logging.error(f"Error limpiando logs antiguos: {str(e)}")

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

            token_perms = oct(os.stat(TOKEN_FILE).st_mode)[-3:]
            if token_perms != '600':
                self.log_and_print(
                    f"Advertencia: Permisos incorrectos en {TOKEN_FILE}: {token_perms}",
                    Fore.YELLOW
                )

            with open(TOKEN_FILE, 'r') as token_file:
                token_data = json.load(token_file)

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

    def _check_token_error(self, error: Exception):
        """Verifica si el error está relacionado con el token."""
        error_str = str(error).lower()
        if "invalid_grant" in error_str or "token" in error_str and ("expired" in error_str or "revoked" in error_str):
            message = "¡ERROR DE TOKEN! El token ha expirado o ha sido revocado. Ejecute auth_setup.py para generar uno nuevo."
            self.log_and_print(message, Fore.RED, logging.ERROR)
            self.notification.send_notification(message, 'critical')
            raise TokenExpiredException()

    def _video_matches_criteria(self, video_details: Dict, channel_config: Dict) -> bool:
        """Verifica si un video cumple con los criterios especificados."""
        try:
            if not video_details or 'snippet' not in video_details:
                return False

            title = video_details['snippet']['title']
            
            # Verificar patrón del título si está configurado
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

            # Verificar si es un Short usando varios indicadores
            if 'contentDetails' in video_details:
                duration = self._parse_duration(video_details['contentDetails']['duration'])
                min_duration = channel_config.get('min_duration', 0)
                max_duration = channel_config.get('max_duration', float('inf'))
                
                if not (min_duration <= duration <= max_duration):
                    self.log_and_print(
                        f"Video descartado: '{title}' duración ({duration}s) fuera de rango",
                        Fore.YELLOW
                    )
                    return False

                # Detección de Shorts usando múltiples indicadores
                short_indicators = 0
                total_indicators = 4
                
                description = str(video_details['snippet'].get('description', '')).lower()
                if '#shorts' in description or '/shorts/' in description:
                    short_indicators += 1
                
                if '#shorts' in title.lower():
                    short_indicators += 1
                
                if duration <= 60:
                    short_indicators += 1
                
                default_thumbnail = video_details['snippet']['thumbnails'].get('default', {})
                if default_thumbnail:
                    width = default_thumbnail.get('width', 0)
                    height = default_thumbnail.get('height', 0)
                    if height > width:
                        short_indicators += 1

                if short_indicators >= 3:
                    self.log_and_print(
                        f"Video descartado: '{title}' detectado como Short "
                        f"(Indicadores: {short_indicators}/{total_indicators})",
                        Fore.YELLOW
                    )
                    return False

            self.log_and_print(
                f"Video aceptado: '{title}'",
                Fore.GREEN
            )
            return True

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

    def _get_video_details(self, video_id: str) -> Optional[Dict]:
        """Obtiene los detalles de un video específico."""
        try:
            # Primero intentar obtener de la caché
            cached_video = self.db.get_cached_video(video_id)
            if cached_video:
                return cached_video

            # Si no está en caché, obtener de la API
            self.stats.add_quota_usage('video_details', 1)
            response = self.youtube.videos().list(
                part="snippet,contentDetails",
                id=video_id
            ).execute()

            if response['items']:
                video_data = response['items'][0]
                # Asegurarse de que channelTitle esté presente
                if 'snippet' in video_data and 'channelTitle' not in video_data['snippet']:
                    video_data['snippet']['channelTitle'] = 'Unknown Channel'
                # Guardar en caché para futuras consultas
                self.db.cache_video(video_data, CACHE_DURATION)
                return video_data
            return None

        except Exception as e:
            self.log_and_print(
                f"Error obteniendo detalles del video {video_id}: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            return None

    def _get_video_duration(self, video_id: str) -> int:
        """Obtiene la duración de un video en segundos."""
        try:
            video_details = self._get_video_details(video_id)
            if video_details and 'contentDetails' in video_details:
                duration_str = video_details['contentDetails']['duration']
                return self._parse_duration(duration_str)
            return 0
        except Exception as e:
            self.log_and_print(
                f"Error obteniendo duración del video {video_id}: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            return 0

    def save_stats(self):
        """Guarda las estadísticas en la base de datos."""
        try:
            if hasattr(self, 'stats') and hasattr(self.stats, 'stats'):
                self.db.save_execution_stats(self.stats.stats)
        except Exception as e:
            self.log_and_print(
                f"Error guardando estadísticas: {str(e)}",
                Fore.RED,
                logging.ERROR
            )

    def get_channel_videos(self, channel_config: Dict) -> List[Dict]:
        """Obtiene videos usando primero RSS y luego API si es necesario."""
        try:
            videos = []
            channel_id = channel_config['channel_id']
            
            # 1. Intentar obtener videos via RSS si está disponible
            if self.rss_manager:
                try:
                    rss_entries = self.rss_manager.get_channel_feed(channel_id)
                    if rss_entries:
                        self.stats.stats['rss_stats']['videos_from_rss'] += len(rss_entries)
                        self.stats.add_quota_saved('search_operations', 100)
                        
                        for entry in rss_entries:
                            video_id = entry.yt_videoid
                            if self.db.get_cached_video(video_id):
                                self.stats.add_quota_saved('video_details', 1)
                                continue
                                
                            video_details = self._get_video_details(video_id)
                            if video_details:
                                videos.append(video_details)
                        
                        return videos
                except Exception as e:
                    self.log_and_print(
                        f"Error en RSS, usando API como fallback: {str(e)}",
                        Fore.YELLOW,
                        logging.WARNING
                    )
                
            # 2. Si RSS no está disponible o falla, usar API
            self.stats.stats['rss_stats']['failed_rss_feeds'] += 1
            self.stats.stats['rss_stats']['videos_from_api'] += 1
            return self._get_videos_via_api(channel_config)
                
        except Exception as e:
            self.log_and_print(
                f"Error obteniendo videos: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            return []

    def _get_videos_via_api(self, channel_config: Dict) -> List[Dict]:
        """Obtiene videos de un canal usando la API de YouTube."""
        channel_id = channel_config['channel_id']

        if self.cache.is_cache_valid(channel_id, 'videos'):
            cached_videos = self.cache.get_cached_data(channel_id, 'videos')
            if cached_videos:
                return cached_videos

        max_results = min(channel_config.get('max_results', 10), 50)

        try:
            videos = []
            page_token = None
            self.stats.add_quota_usage('search', 100)
            
            # 1. Primero obtiene todos los IDs de videos
            video_ids = []
            while True:
                request = self.youtube.search().list(
                    part="id",
                    channelId=channel_id,
                    maxResults=50,
                    pageToken=page_token,
                    order="date",
                    type="video",
                    publishedAfter=(datetime.utcnow() -
                                    timedelta(hours=channel_config.get(
                                        'hours_limit', 8))
                                    ).isoformat() + 'Z'
                )
                
                response = request.execute()
                video_ids.extend([item['id']['videoId'] for item in response['items']])
                
                if not response.get('nextPageToken'):
                    break
                page_token = response['nextPageToken']

            # 2. Procesa los videos en lotes de 50
            for i in range(0, len(video_ids), 50):  # Avanza de 50 en 50
                batch = video_ids[i:i+50]  # Toma un subconjunto de 50 IDs
                self.stats.add_quota_usage('video_details', 1)
                
                # 3. Obtiene detalles para el lote completo en una sola llamada
                details = self.youtube.videos().list(
                    part="snippet,contentDetails",
                    id=','.join(batch)  # Une los IDs con comas
                ).execute()
                
                for video in details['items']:
                    video_details = self.db.get_cached_video(video['id'])
                    if video_details:
                        videos.append(video_details)
                        continue

                    if self._video_matches_criteria(video, channel_config):
                        videos.append(video)
                        self.stats.update_channel_stats(channel_config['channel_name'], 'added')
                        self.db.cache_video(video, CACHE_DURATION)

            self.cache.update_cache(channel_id, videos, 'videos')
            return videos

        except HttpError as e:
            self._check_quota_error(e)
            raise
        except Exception as e:
            self._check_token_error(e)
            self.log_and_print(
                f"Error al obtener videos: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            raise

    def _check_quota_error(self, error: HttpError):
        """Verifica si el error es de cuota excedida y establece la bandera"""
        if isinstance(error, HttpError) and error.resp.status == 403 and "quotaExceeded" in str(error):
            self.quota_exceeded = True
            message = "¡CUOTA EXCEDIDA! Deteniendo operaciones que requieren cuota."
            self.log_and_print(message, Fore.RED, logging.ERROR)
            self.notification.send_notification(message, 'critical')
            raise QuotaExceededException()

    def manage_playlist(self, config: Dict):
        """Gestiona las listas de reproducción según la configuración."""
        try:
            for channel in config['channels']:
                if not channel.get('playlist_id'):
                    self.log_and_print(
                        f"Canal {channel['channel_name']} sin playlist_id configurado. Saltando...",
                        Fore.YELLOW
                    )
                    continue

                self.log_and_print(
                    f"Procesando canal: {channel['channel_name']} -> Playlist: {channel.get('playlist_name', 'Sin nombre')}",
                    Fore.YELLOW
                )
                
                if channel.get('playlist_id') and channel.get('playlist_name'):
                    self.stats.set_playlist_name(channel['playlist_id'], channel['playlist_name'])

                try:
                    videos = self.get_channel_videos(channel)
                    for video in videos:
                        video_id = video['id']
                        playlist_items = self._get_playlist_items(channel['playlist_id'])
                        if not self._video_in_playlist(video_id, playlist_items):
                            self._add_to_playlist(channel['playlist_id'], video_id)

                except QuotaExceededException:
                    self.log_and_print(
                        "Cuota excedida. Deteniendo procesamiento.",
                        Fore.RED
                    )
                    break

        except Exception as e:
            self.log_and_print(
                f"Error en manage_playlist: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            raise

    def _get_playlist_items(self, playlist_id: str) -> List[Dict]:
        """Obtiene los items de una playlist."""
        try:
            items = []
            next_page_token = None
            
            while True:
                request = self.youtube.playlistItems().list(
                    part="snippet,contentDetails",
                    playlistId=playlist_id,
                    maxResults=50,
                    pageToken=next_page_token
                )
                response = request.execute()
                items.extend(response['items'])
                
                next_page_token = response.get('nextPageToken')
                if not next_page_token:
                    break

            self.stats.add_quota_usage('playlist_items', 1)
            return items

        except Exception as e:
            self.log_and_print(
                f"Error obteniendo items de playlist: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            return []

    def _video_in_playlist(self, video_id: str, playlist_items: List[Dict]) -> bool:
        """Verifica si un video ya está en la playlist."""
        return any(
            item['snippet']['resourceId']['videoId'] == video_id
            for item in playlist_items
        )

    def _add_to_playlist(self, playlist_id: str, video_id: str):
        """Añade un video a la playlist."""
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
            
            self.stats.add_quota_usage('add_video', 50)
            video_details = self._get_video_details(video_id)
            if video_details and 'contentDetails' in video_details:
                duration = self._parse_duration(video_details['contentDetails']['duration'])
                self.stats.add_video(playlist_id, duration)

        except Exception as e:
            self.log_and_print(
                f"Error añadiendo video {video_id}: {str(e)}",
                Fore.RED,
                logging.ERROR
            )

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
                            published_at = None
                            try:
                                if ('contentDetails' in item and 
                                    'videoPublishedAt' in item['contentDetails']):
                                    published_at = datetime.strptime(
                                        item['contentDetails']['videoPublishedAt'],
                                        '%Y-%m-%dT%H:%M:%SZ'
                                    )
                                else:
                                    published_at = datetime.strptime(
                                        item['snippet']['publishedAt'],
                                        '%Y-%m-%dT%H:%M:%SZ'
                                    )
                                
                                time_passed = datetime.utcnow() - published_at
                                
                                self.log_and_print(
                                    f"Video: {item['snippet']['title']}\n"
                                    f"  - Fecha publicación: {published_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                                    f"  - Días desde publicación: {time_passed.days}",
                                    Fore.CYAN
                                )

                                if time_passed > time_limit:
                                    if not self.quota_exceeded:
                                        video_id = item['snippet']['resourceId']['videoId']
                                        video_details = self._get_video_details(video_id)
                                        
                                        if video_details and 'contentDetails' in video_details:
                                            duration = self._parse_duration(video_details['contentDetails']['duration'])
                                            channel_name = video_details['snippet']['channelTitle']  # Obtener nombre del canal
                                            self.stats.remove_video(playlist_id, duration, channel_name)
                                        
                                            self.youtube.playlistItems().delete(
                                                id=item['id']
                                            ).execute()

                                            videos_eliminados += 1
                                            self.log_and_print(
                                                f"Video {item['snippet']['title']} eliminado por antigüedad "
                                                f"(días desde publicación: {time_passed.days} > {time_limit.days})",
                                                Fore.GREEN
                                            )
                                            self.stats.add_quota_usage('delete_video', 50)
                                            self.stats.update_channel_stats(item['snippet']['channelTitle'], 'removed')
                                            time.sleep(1)
                                        else:
                                            self.log_and_print(
                                                f"No se pudieron obtener detalles para el video: {item['snippet']['title']}",
                                                Fore.YELLOW
                                            )
                                            continue

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
                    return
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
            self.save_stats()  # Guardar estadísticas al finalizar

        except QuotaExceededException:
            return
        except Exception as e:
            self.log_and_print(
                f"Error en limpieza de playlists: {str(e)}",
                Fore.RED,
                logging.ERROR
            )

    def get_summary(self) -> str:
        """Genera resumen completo incluyendo estadísticas históricas."""
        current_summary = self.stats.get_summary()
        historical_summary = self.db.get_stats_summary()
        return current_summary + historical_summary


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
        if not manager.check_internet_connection():
            manager.log_and_print(
                "No se puede continuar sin conexión a Internet",
                Fore.RED,
                logging.ERROR
            )
            return

        manager.authenticate()
        config = manager.load_config()

        try:
            manager.manage_playlist(config)
        except QuotaExceededException:
            pass

        if not manager.quota_exceeded:
            manager.cleanup_playlists()
        
        summary = manager.get_summary()
        
        manager.log_and_print("\n" + summary, Fore.CYAN)
        
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
        sys.exit(1)
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
