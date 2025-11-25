"""
Módulo para gestionar los feeds RSS de canales de YouTube.
Reduce el consumo de cuota de API mediante el uso de RSS para detección inicial de videos.
"""

import feedparser
from typing import List, Dict, Optional, NamedTuple
from datetime import datetime, timedelta
import re
import logging
from colorama import Fore
import time
import requests

class YouTubeVideoEntry(NamedTuple):
    """Estructura para almacenar información básica de un video de YouTube."""
    yt_videoid: str
    title: str
    published: datetime
    author: str
    description: str


class YouTubeRSSManager:
    """Gestiona la obtención de videos a través de feeds RSS de YouTube."""
    
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self._cache = {}
        self._cache_duration = 3600  # 1 hora
        self._last_cache_update = {}

    def get_channel_feed(self, channel_id: str) -> List[YouTubeVideoEntry]:
        """Obtiene los videos más recientes de un canal a través de su feed RSS."""
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        
        try:
            # Verificar caché
            if self._is_cache_valid(channel_id):
                self.logger.info(f"RSS: Usando caché para canal {channel_id}")
                return self._cache[channel_id]
            
            # Usar requests para obtener el feed con timeout
            response = requests.get(feed_url, timeout=10)
            response.raise_for_status()
            
            # Parsear el feed RSS
            feed = feedparser.parse(response.text)
            
            if feed.get('bozo_exception'):
                self.logger.error(f"Error parseando feed RSS: {feed.bozo_exception}")
                return []
                
            entries = []
            for entry in feed.entries:
                try:
                    # Extraer video ID de la URL
                    video_id_match = re.search(r'yt:video:([^<]+)', entry.id)
                    if not video_id_match:
                        continue
                        
                    video_id = video_id_match.group(1)
                    
                    # Parsear fecha de publicación
                    try:
                        published = datetime(*entry.published_parsed[:6])
                    except (TypeError, ValueError):
                        self.logger.warning(f"No se pudo parsear fecha para video {video_id}")
                        continue
                    
                    video_entry = YouTubeVideoEntry(
                        yt_videoid=video_id,
                        title=entry.title,
                        published=published,
                        author=entry.author,
                        description=entry.get('summary', '')
                    )
                    entries.append(video_entry)
                    
                except (AttributeError, KeyError, ValueError) as e:
                    self.logger.warning(f"Error procesando entrada RSS: {str(e)}")
                    continue
            
            # Guardar en caché
            self._cache[channel_id] = entries
            self._last_cache_update[channel_id] = time.time()
            
            self.logger.info(f"RSS: Obtenidos {len(entries)} videos para canal {channel_id}")
            return entries
            
        except requests.RequestException as e:
            self.logger.error(f"Error obteniendo feed RSS para {channel_id}: {str(e)}")
            return []
        except Exception as e:
            self.logger.error(f"Error inesperado en RSS: {str(e)}")
            return []

    def _is_cache_valid(self, channel_id: str) -> bool:
        """Verifica si el caché es válido."""
        if channel_id not in self._cache:
            return False
        
        if channel_id not in self._last_cache_update:
            return False
        
        elapsed = time.time() - self._last_cache_update[channel_id]
        return elapsed < self._cache_duration

    def clear_cache(self):
        """Limpia el caché de feeds RSS."""
        self._cache.clear()
        self._last_cache_update.clear()


class RSSManager:
    
    """Clase alternativa para compatibilidad."""
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    def parse_feed(self, feed_url: str) -> Dict:
        """Parsea un feed RSS y devuelve su contenido."""
        try:
            feed = feedparser.parse(feed_url)
            if feed.get('bozo_exception'):
                self.logger.error(f"Error parseando feed {feed_url}: {feed['bozo_exception']}")
                return {}
            return feed
        except Exception as e:
            self.logger.error(f"Error al procesar feed {feed_url}: {str(e)}")
            return {}
    
    def get_feed_entries(self, feed_url: str) -> List[Dict]:
        """Obtiene las entradas de un feed RSS."""
        feed = self.parse_feed(feed_url)
        return feed.get('entries', [])
    
    def get_channel_feed_url(self, channel_id: str) -> str:
        """Genera la URL del feed RSS para un canal de YouTube."""
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
