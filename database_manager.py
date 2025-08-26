import sqlite3
import os
from datetime import datetime, timedelta
from typing import Dict, Optional

class DatabaseManager:
    """Gestor de la base de datos SQLite."""
    
    def __init__(self, base_dir: str):
        """Inicializa la conexión y crea las tablas."""
        self.db_path = os.path.join(base_dir, 'db', 'YouTubeAutoList.db')
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Inicializa la estructura de la base de datos."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY,
                    title TEXT,
                    channel_id TEXT,
                    duration INTEGER,
                    published_at DATETIME,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
                    cache_valid_until DATETIME
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    quota_used INTEGER,
                    videos_added INTEGER,
                    videos_removed INTEGER,
                    duration_added INTEGER,
                    duration_removed INTEGER
                )
            ''')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS removed_videos (
                    video_id TEXT PRIMARY KEY,
                    channel_name TEXT,
                    removal_date DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

    def get_cached_video(self, video_id: str) -> Optional[Dict]:
        """Obtiene un video del caché si es válido."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            result = conn.execute('''
                SELECT * FROM videos 
                WHERE video_id = ? AND cache_valid_until > datetime('now')
            ''', (video_id,)).fetchone()
            
            if result:
                return {
                    'id': result['video_id'],
                    'snippet': {
                        'title': result['title'],
                        'channelId': result['channel_id'],
                        'publishedAt': result['published_at']
                    },
                    'contentDetails': {
                        'duration': result['duration']
                    }
                }
            return None

    def cache_video(self, video_data: Dict, cache_duration: int):
        """Almacena un video en caché."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO videos 
                (video_id, title, channel_id, duration, published_at, cache_valid_until)
                VALUES (?, ?, ?, ?, ?, datetime('now', '+' || ? || ' seconds'))
            ''', (
                video_data['id'],
                video_data['snippet']['title'],
                video_data['snippet']['channelId'],
                video_data.get('contentDetails', {}).get('duration', '0'),
                video_data['snippet']['publishedAt'],
                cache_duration
            ))

    def save_execution_stats(self, stats: Dict):
        """Guarda estadísticas de la ejecución."""
        with sqlite3.connect(self.db_path) as conn:
            videos_added = sum(stats['added'].values())
            videos_removed = sum(stats['removed'].values())
            duration_added = sum(stats['duration']['added'].values())
            duration_removed = sum(stats['duration']['removed'].values())
            quota_used = sum(stats['quota_usage'].values())
            
            conn.execute('''
                INSERT INTO executions 
                (quota_used, videos_added, videos_removed, duration_added, duration_removed)
                VALUES (?, ?, ?, ?, ?)
            ''', (quota_used, videos_added, videos_removed, duration_added, duration_removed))

    def record_removed_video(self, video_id: str, channel_name: str):
        """Registra el canal de origen de un video eliminado."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO removed_videos 
                    (video_id, channel_name) VALUES (?, ?)
                ''', (video_id, channel_name))
                conn.commit()
        except Exception as e:
            print(f"Error registrando video eliminado: {e}")

    def get_stats_summary(self) -> str:
        """Genera resumen de estadísticas históricas."""
        periods = {
            'day': datetime.now() - timedelta(days=1),
            'week': datetime.now() - timedelta(weeks=1),
            'month': datetime.now() - timedelta(days=30),
            'year': datetime.now() - timedelta(days=365)
        }

        summary = ["\n=== Estadísticas Históricas ==="]
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            for period_name, start_date in periods.items():
                result = conn.execute('''
                    SELECT 
                        COUNT(*) as total_videos,
                        SUM(videos_added) as videos_added,
                        SUM(videos_removed) as videos_removed,
                        SUM(duration_added) as duration_added,
                        SUM(duration_removed) as duration_removed,
                        SUM(quota_used) as total_quota
                    FROM executions
                    WHERE timestamp >= ?
                ''', (start_date.strftime('%Y-%m-%d %H:%M:%S'),)).fetchone()

                summary.extend([
                    f"\nÚltim{'o' if period_name != 'week' else 'a'} {period_name}:",
                    f"  Videos procesados: {result['total_videos'] or 0}",
                    f"  + Agregados: {result['videos_added'] or 0} ({self._format_duration(result['duration_added'] or 0)})",
                    f"  - Eliminados: {result['videos_removed'] or 0} ({self._format_duration(result['duration_removed'] or 0)})",
                    f"  Cuota utilizada: {result['total_quota'] or 0} unidades"
                ])

        return "\n".join(summary)

    def _format_duration(self, seconds: int) -> str:
        """Formatea duración en formato legible."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"
