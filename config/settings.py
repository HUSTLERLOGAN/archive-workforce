# Workforce Configuration
# All secrets come from environment variables

import os
from typing import Optional
from dataclasses import dataclass

@dataclass
class DatabaseConfig:
    url: str
    key: str
    
    @classmethod
    def from_env(cls) -> 'DatabaseConfig':
        url = os.environ.get('SUPABASE_URL')
        key = os.environ.get('SUPABASE_KEY')
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY are required")
        return cls(url=url, key=key)

@dataclass
class WorkforceConfig:
    """Central configuration for the Workforce system"""
    
    # Database
    db: DatabaseConfig
    
    # Execution
    default_scan_interval_minutes: int = 60
    max_insights_per_task_per_run: int = 1
    max_tasks_per_agent_run: int = 10
    
    # Autonomy
    default_autonomy_mode: str = "advisory"  # advisory, review_only, full_autonomy
    
    # Approval
    approval_required_for_done: bool = True
    human_approvers: list = None  # Discord/Telegram user IDs
    
    # Logging
    log_level: str = "INFO"
    audit_retention: str = "forever"  # forever, 90d, 30d
    
    @classmethod
    def load(cls) -> 'WorkforceConfig':
        """Load configuration from environment"""
        return cls(
            db=DatabaseConfig.from_env(),
            default_scan_interval_minutes=int(os.environ.get('WORKFORCE_SCAN_INTERVAL', 60)),
            max_insights_per_task_per_run=int(os.environ.get('WORKFORCE_MAX_INSIGHTS', 1)),
            max_tasks_per_agent_run=int(os.environ.get('WORKFORCE_MAX_TASKS_PER_RUN', 10)),
            default_autonomy_mode=os.environ.get('WORKFORCE_AUTONOMY_MODE', 'advisory'),
            log_level=os.environ.get('LOG_LEVEL', 'INFO'),
            human_approvers=os.environ.get('WORKFORCE_APPROVERS', '').split(',') if os.environ.get('WORKFORCE_APPROVERS') else []
        )

# Singleton config instance
_config: Optional[WorkforceConfig] = None

def get_config() -> WorkforceConfig:
    global _config
    if _config is None:
        _config = WorkforceConfig.load()
    return _config
