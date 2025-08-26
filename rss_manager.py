"""
Módulo para gestionar los feeds RSS de canales de YouTube.
Reduce el consumo de cuota de API mediante el uso de RSS para detección inicial de videos.
"""

import feedparser
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import re
import logging
from colorama import Fore
import time

class YouTubeRSSManager:
    """Gestiona la obtención de videos a través de feeds RSS de YouTube."""
    
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self._cache = {}
        self._cache_duration = 3600  # 1 hora

    def log_and_print(self, message: str, color: str = Fore.WHITE, level: int = logging.INFO):
        """Registra un mensaje en el log y lo imprime en la consola."""
        self.logger.log(level, message)
        print(f"{color}{message}{Fore.RESET}")

    def _get_channel_feed_url(self, channel_id: str) -> str:
        """Genera la URL del feed RSS para un canal de YouTube."""
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    def _is_cache_valid(self, channel_id: str) -> bool:
        """Verifica si el caché para un canal específico es válido."""
        if channel_id not in self._cache:
            return False
        cache_time = self._cache[channel_id]['timestamp']
        return (time.time() - cache_time) < self._cache_duration

    def _cache_videos(self, channel_id: str, videos: List[Dict]):
        """Almacena videos en caché."""
        self._cache[channel_id] = {
            'videos': videos,
            'timestamp': time.time()
        }

    def get_recent_videos(self, channel_config: Dict) -> List[Dict]:
        """
        Obtiene videos recientes de un canal usando su feed RSS.
        
        Args:
            channel_config: Diccionario con la configuración del canal
                - channel_id: ID del canal
                - hours_limit: Límite de horas para videos (default: 8)
                - title_pattern: Patrón regex para filtrar títulos
        
        Returns:
            Lista de videos que cumplen con los criterios
        """
        channel_id = channel_config['channel_id']
        hours_limit = channel_config.get('hours_limit', 8)
        title_pattern = channel_config.get('title_pattern')

        # Verificar caché
        if self._is_cache_valid(channel_id):
            return self._cache[channel_id]['videos']

        try:
            feed_url = self._get_channel_feed_url(channel_id)
            feed = feedparser.parse(feed_url)

            if feed.get('bozo_exception'):
                self.log_and_print(
                    f"Error al obtener feed RSS para {channel_id}: {feed.bozo_exception}",
                    Fore.RED,
                    logging.ERROR
                )
                return []

            time_limit = datetime.utcnow() - timedelta(hours=hours_limit)
            videos = []

            for entry in feed.entries:
                try:
                    # Extraer video ID de la URL
                    video_id = re.search(r'video_id=([^&]+)', entry.id).group(1)
                    published = datetime(*entry.published_parsed[:6])

                    if published < time_limit:
                        continue

                    # Filtrar por patrón de título si existe
                    if title_pattern and not re.search(title_pattern, entry.title, re.IGNORECASE):
                        continue

                    video_info = {
                        'id': video_id,
                        'title': entry.title,
                        'published_at': published.isoformat(),
                        'channel_title': entry.author,
                        'description': entry.summary
                    }
                    videos.append(video_info)

                except (AttributeError, KeyError) as e:
                    self.log_and_print(
                        f"Error procesando entrada RSS: {str(e)}",
                        Fore.YELLOW,
                        logging.WARNING
                    )
                    continue

            self._cache_videos(channel_id, videos)
            return videos

        except Exception as e:
            self.log_and_print(
                f"Error obteniendo videos RSS para {channel_id}: {str(e)}",
                Fore.RED,
                logging.ERROR
            )
            return []

    def clear_cache(self, channel_id: Optional[str] = None):
        """
        Limpia el caché de videos.
        
        Args:
            channel_id: ID del canal específico a limpiar. Si es None, limpia todo el caché.
        """
        if channel_id:
            self._cache.pop(channel_id, None)
        else:
            self._cache.clear()
