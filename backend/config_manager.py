import time
from typing import Optional
from backend.models import SystemConfig
from backend.sheets_service import SheetsService

class ConfigManager:
    _instance: Optional["ConfigManager"] = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self, sheets_service: Optional[SheetsService] = None):
        if self.initialized:
            return
            
        self.sheets_service = sheets_service or SheetsService()
        self._cached_config: Optional[SystemConfig] = None
        self._last_fetched: float = 0.0
        self._ttl: float = 30.0  # Cache duration (seconds)
        self.initialized = True

    def get_config(self, force_refresh: bool = False) -> SystemConfig:
        """Get the system configuration, utilizing a cache with a 30-second TTL."""
        now = time.time()
        if force_refresh or not self._cached_config or (now - self._last_fetched) > self._ttl:
            # Fetch from sheets service
            config = self.sheets_service.get_config()
            self._cached_config = config
            self._last_fetched = now
            
        return self._cached_config

    def update_config(self, new_config: SystemConfig) -> bool:
        """Save new configuration to sheets database and invalidate cache."""
        success = self.sheets_service.save_config(new_config)
        if success:
            self._cached_config = new_config
            self._last_fetched = time.time()
        return success
