"""
Workforce Database Client

Single source of truth for all database operations.
All mutations go through this module.
"""

import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import uuid4
from dataclasses import dataclass, asdict
from enum import Enum

from supabase import create_client, Client


class TaskStatus(Enum):
    BACKLOG = "BACKLOG"
    IN_PROGRESS = "IN_PROGRESS"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    DONE = "DONE"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class Priority(Enum):
    P0 = "P0"  # Critical
    P1 = "P1"  # High
    P2 = "P2"  # Medium
    P3 = "P3"  # Low


class EventType(Enum):
    TASK_CREATED = "TASK_CREATED"
    TASK_UPDATED = "TASK_UPDATED"
    TASK_ASSIGNED = "TASK_ASSIGNED"
    STATUS_CHANGED = "STATUS_CHANGED"
    PRIORITY_CHANGED = "PRIORITY_CHANGED"
    INSIGHT_ADDED = "INSIGHT_ADDED"
    DELIVERABLE_ADDED = "DELIVERABLE_ADDED"
    AGENT_RUN_START = "AGENT_RUN_START"
    AGENT_RUN_END = "AGENT_RUN_END"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    HUMAN_REJECTED = "HUMAN_REJECTED"
    AUTONOMY_MODE_CHANGED = "AUTONOMY_MODE_CHANGED"
    POLICY_VIOLATION_FLAGGED = "POLICY_VIOLATION_FLAGGED"
    ERROR_OCCURRED = "ERROR_OCCURRED"


@dataclass
class Task:
    id: str
    title: str
    description: Optional[str] = None
    owner_agent: Optional[str] = None
    assigned_by: Optional[str] = None
    status: str = "BACKLOG"
    priority: str = "P2"
    tags: List[str] = None
    source: str = "api"
    external_refs: Dict = None
    impact_score: Optional[int] = None
    effort_estimate: Optional[str] = None
    requires_approval: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    parent_task_id: Optional[str] = None
    due_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class WorkforceDB:
    """Database client for Workforce system"""
    
    def __init__(self):
        self.url = os.environ.get('SUPABASE_URL', '').strip().strip('"').strip("'")
        self.key = os.environ.get('SUPABASE_KEY', '').strip().strip('"').strip("'")
        self._client: Optional[Client] = None
        # Debug logging
        print(f"[DB] SUPABASE_URL: {self.url[:50] if self.url else 'NOT SET'}...")
        print(f"[DB] SUPABASE_KEY: {self.key[:20] if self.key else 'NOT SET'}...")
    
    @property
    def client(self) -> Client:
        if self._client is None:
            if not self.url or not self.key:
                raise ValueError("SUPABASE_URL and SUPABASE_KEY are required")
            self._client = create_client(self.url, self.key)
        return self._client
    
    # ==========================================
    # TASKS
    # ==========================================
    
    def create_task(
        self,
        title: str,
        description: str = None,
        owner_agent: str = None,
        assigned_by: str = "system",
        priority: str = "P2",
        tags: List[str] = None,
        source: str = "api",
        requires_approval: bool = False,
        parent_task_id: str = None,
        due_at: str = None,
        external_refs: Dict = None,
        impact_score: int = None,
        effort_estimate: str = None
    ) -> Dict:
        """Create a new task and log the event"""
        task_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        task_data = {
            "id": task_id,
            "title": title,
            "description": description,
            "owner_agent": owner_agent,
            "assigned_by": assigned_by,
            "status": "BACKLOG",
            "priority": priority,
            "tags": tags or [],
            "source": source,
            "requires_approval": requires_approval,
            "parent_task_id": parent_task_id,
            "due_at": due_at,
            "external_refs": external_refs or {},
            "impact_score": impact_score,
            "effort_estimate": effort_estimate,
            "created_at": now,
            "updated_at": now
        }
        
        result = self.client.table("workforce_tasks").insert(task_data).execute()
        
        # Log audit event
        self._log_audit(
            event_type=EventType.TASK_CREATED.value,
            entity_type="task",
            entity_id=task_id,
            actor=assigned_by,
            actor_type="agent" if assigned_by in ["jarvis", "system"] else "human",
            new_value=task_data
        )
        
        # Create event for triggers
        self._create_event(EventType.TASK_CREATED.value, {
            "task_id": task_id,
            "owner_agent": owner_agent,
            "priority": priority
        })
        
        return result.data[0] if result.data else task_data
    
    def update_task(
        self,
        task_id: str,
        actor: str,
        **updates
    ) -> Dict:
        """Update a task and log the change"""
        # Get current state
        current = self.get_task(task_id)
        if not current:
            raise ValueError(f"Task {task_id} not found")
        
        # Check for status change
        old_status = current.get("status")
        new_status = updates.get("status")
        
        # Enforce deliverable requirement for DONE
        if new_status == "DONE" and old_status != "DONE":
            deliverables = self.get_deliverables(task_id)
            if not deliverables:
                raise ValueError("Cannot mark task DONE without at least one deliverable")
            
            # Check approval requirement
            if current.get("requires_approval") and not current.get("approved_by"):
                raise ValueError("Task requires approval before marking DONE")
        
        # Update
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = self.client.table("workforce_tasks").update(updates).eq("id", task_id).execute()
        
        # Log audit
        self._log_audit(
            event_type=EventType.TASK_UPDATED.value,
            entity_type="task",
            entity_id=task_id,
            actor=actor,
            actor_type="agent" if actor in ["jarvis", "chief_of_staff", "ops_tracker", "distribution", "researcher", "system"] else "human",
            old_value={k: current.get(k) for k in updates.keys()},
            new_value=updates
        )
        
        # Status change event
        if new_status and new_status != old_status:
            self._create_event(EventType.STATUS_CHANGED.value, {
                "task_id": task_id,
                "old_status": old_status,
                "new_status": new_status
            })
        
        return result.data[0] if result.data else None
    
    def get_task(self, task_id: str) -> Optional[Dict]:
        """Get a single task by ID"""
        result = self.client.table("workforce_tasks").select("*").eq("id", task_id).execute()
        return result.data[0] if result.data else None
    
    def get_tasks(
        self,
        status: str = None,
        owner_agent: str = None,
        priority: str = None,
        limit: int = 50
    ) -> List[Dict]:
        """Query tasks with filters"""
        query = self.client.table("workforce_tasks").select("*")
        
        if status:
            query = query.eq("status", status)
        if owner_agent:
            query = query.eq("owner_agent", owner_agent)
        if priority:
            query = query.eq("priority", priority)
        
        result = query.order("created_at", desc=True).limit(limit).execute()
        return result.data
    
    def get_tasks_for_agent_run(self, agent_id: str, limit: int = 10) -> List[Dict]:
        """Get tasks that need attention from a specific agent"""
        # Get tasks assigned to this agent that are not done/cancelled
        result = self.client.table("workforce_tasks")\
            .select("*")\
            .eq("owner_agent", agent_id)\
            .not_.in_("status", ["DONE", "CANCELLED"])\
            .order("priority")\
            .order("updated_at", desc=True)\
            .limit(limit)\
            .execute()
        return result.data
    
    # ==========================================
    # DELIVERABLES
    # ==========================================
    
    def add_deliverable(
        self,
        task_id: str,
        title: str,
        content: str,
        created_by: str,
        content_type: str = "text",
        is_final: bool = False
    ) -> Dict:
        """Add a deliverable to a task"""
        deliverable_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        data = {
            "id": deliverable_id,
            "task_id": task_id,
            "title": title,
            "content": content,
            "content_type": content_type,
            "created_by": created_by,
            "is_final": is_final,
            "created_at": now
        }
        
        result = self.client.table("workforce_deliverables").insert(data).execute()
        
        self._log_audit(
            event_type=EventType.DELIVERABLE_ADDED.value,
            entity_type="deliverable",
            entity_id=deliverable_id,
            actor=created_by,
            actor_type="agent",
            new_value={"task_id": task_id, "title": title}
        )
        
        return result.data[0] if result.data else data
    
    def get_deliverables(self, task_id: str) -> List[Dict]:
        """Get all deliverables for a task"""
        result = self.client.table("workforce_deliverables")\
            .select("*")\
            .eq("task_id", task_id)\
            .order("created_at")\
            .execute()
        return result.data
    
    # ==========================================
    # INSIGHTS
    # ==========================================
    
    def add_insight(
        self,
        agent: str,
        content: str,
        task_id: str = None,
        insight_type: str = "observation"
    ) -> Dict:
        """Add an insight (observation, recommendation, etc.)"""
        insight_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        data = {
            "id": insight_id,
            "task_id": task_id,
            "agent": agent,
            "content": content,
            "insight_type": insight_type,
            "created_at": now
        }
        
        result = self.client.table("workforce_insights").insert(data).execute()
        
        self._log_audit(
            event_type=EventType.INSIGHT_ADDED.value,
            entity_type="insight",
            entity_id=insight_id,
            actor=agent,
            actor_type="agent",
            new_value={"task_id": task_id, "type": insight_type}
        )
        
        return result.data[0] if result.data else data
    
    def get_insights(self, task_id: str = None, agent: str = None, limit: int = 50) -> List[Dict]:
        """Get insights with optional filters"""
        query = self.client.table("workforce_insights").select("*")
        
        if task_id:
            query = query.eq("task_id", task_id)
        if agent:
            query = query.eq("agent", agent)
        
        result = query.order("created_at", desc=True).limit(limit).execute()
        return result.data
    
    def promote_insight_to_task(self, insight_id: str, promoted_by: str) -> Dict:
        """Promote an insight to a task (Jarvis only)"""
        # Get insight
        insight = self.client.table("workforce_insights").select("*").eq("id", insight_id).execute()
        if not insight.data:
            raise ValueError(f"Insight {insight_id} not found")
        
        insight_data = insight.data[0]
        
        # Create task from insight
        task = self.create_task(
            title=f"[From Insight] {insight_data['content'][:100]}",
            description=insight_data['content'],
            assigned_by=promoted_by,
            source="insight_promotion"
        )
        
        # Update insight
        now = datetime.now(timezone.utc).isoformat()
        self.client.table("workforce_insights").update({
            "promoted_to_task_id": task["id"],
            "promoted_at": now
        }).eq("id", insight_id).execute()
        
        return task
    
    # ==========================================
    # AGENTS
    # ==========================================
    
    def get_agent(self, agent_id: str) -> Optional[Dict]:
        """Get agent configuration"""
        result = self.client.table("workforce_agents").select("*").eq("id", agent_id).execute()
        return result.data[0] if result.data else None
    
    def get_agents(self, enabled_only: bool = True) -> List[Dict]:
        """Get all agents"""
        query = self.client.table("workforce_agents").select("*")
        if enabled_only:
            query = query.eq("enabled", True)
        result = query.execute()
        return result.data
    
    def update_agent(self, agent_id: str, **updates) -> Dict:
        """Update agent configuration"""
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = self.client.table("workforce_agents").update(updates).eq("id", agent_id).execute()
        return result.data[0] if result.data else None
    
    def create_agent(
        self,
        name: str,
        role: str,
        capabilities: List[str] = None,
        model_config: Dict = None,
        enabled: bool = True
    ) -> Dict:
        """Create a new agent"""
        agent_id = name.lower().replace(" ", "_")
        now = datetime.now(timezone.utc).isoformat()
        
        # Extract model provider and id from config
        model_provider = "openai"
        model_id = "gpt-4o-mini"
        if model_config:
            model_provider = model_config.get("provider", "openai")
            model_id = model_config.get("model", "gpt-4o-mini")
        
        data = {
            "id": agent_id,
            "name": name,
            "role": role,
            "capabilities": capabilities or [],
            "model_provider": model_provider,
            "model_id": model_id,
            "enabled": enabled,
            "created_at": now,
            "updated_at": now
        }
        
        result = self.client.table("workforce_agents").insert(data).execute()
        return result.data[0] if result.data else data
    
    def log_agent_run(
        self,
        agent_id: str,
        status: str,
        tasks_processed: int = 0,
        insights_created: int = 0,
        duration_ms: int = None,
        error_message: str = None,
        tokens_used: int = 0
    ) -> Dict:
        """Log an agent run"""
        run_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        data = {
            "id": run_id,
            "agent_id": agent_id,
            "status": status,
            "tasks_processed": tasks_processed,
            "insights_created": insights_created,
            "duration_ms": duration_ms,
            "error_message": error_message,
            "tokens_used": tokens_used,
            "started_at": now,
            "completed_at": now if status != "running" else None
        }
        
        result = self.client.table("workforce_agent_runs").insert(data).execute()
        
        # Update agent last run
        self.update_agent(agent_id, last_run_at=now, last_run_status=status)
        
        return result.data[0] if result.data else data
    
    # ==========================================
    # AUDIT & EVENTS (Internal)
    # ==========================================
    
    def _log_audit(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        actor: str,
        actor_type: str,
        old_value: Dict = None,
        new_value: Dict = None,
        metadata: Dict = None
    ):
        """Internal: Log to append-only audit log"""
        self.client.table("workforce_audit_log").insert({
            "id": str(uuid4()),
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor": actor,
            "actor_type": actor_type,
            "old_value": old_value,
            "new_value": new_value,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()
    
    def _create_event(self, event_type: str, payload: Dict):
        """Internal: Create event for event-driven triggers"""
        self.client.table("workforce_events").insert({
            "id": str(uuid4()),
            "event_type": event_type,
            "payload": payload,
            "processed": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()
    
    def get_unprocessed_events(self, limit: int = 100) -> List[Dict]:
        """Get events that haven't been processed"""
        result = self.client.table("workforce_events")\
            .select("*")\
            .eq("processed", False)\
            .order("created_at")\
            .limit(limit)\
            .execute()
        return result.data
    
    def mark_event_processed(self, event_id: str, processed_by: str):
        """Mark an event as processed"""
        now = datetime.now(timezone.utc).isoformat()
        self.client.table("workforce_events").update({
            "processed": True,
            "processed_at": now,
            "processed_by": processed_by
        }).eq("id", event_id).execute()
    
    # ==========================================
    # AUTONOMY
    # ==========================================
    
    def get_current_autonomy_mode(self, agent_id: str = None) -> str:
        """Get current autonomy mode"""
        now = datetime.now(timezone.utc).isoformat()
        
        query = self.client.table("workforce_autonomy_sessions")\
            .select("*")\
            .lt("starts_at", now)\
            .gt("expires_at", now)\
            .is_("revoked_at", "null")
        
        if agent_id:
            query = query.or_(f"granted_to.eq.{agent_id},granted_to.is.null")
        
        result = query.order("created_at", desc=True).limit(1).execute()
        
        if result.data:
            return result.data[0]["mode"]
        return "advisory"  # Default
    
    def grant_autonomy(
        self,
        mode: str,
        granted_by: str,
        duration_minutes: int,
        granted_to: str = None,
        reason: str = None
    ) -> Dict:
        """Grant time-boxed autonomy"""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=duration_minutes)
        
        data = {
            "id": str(uuid4()),
            "mode": mode,
            "granted_by": granted_by,
            "granted_to": granted_to,
            "reason": reason,
            "starts_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "created_at": now.isoformat()
        }
        
        result = self.client.table("workforce_autonomy_sessions").insert(data).execute()
        
        self._log_audit(
            event_type=EventType.AUTONOMY_MODE_CHANGED.value,
            entity_type="autonomy",
            entity_id=data["id"],
            actor=granted_by,
            actor_type="human",
            new_value={"mode": mode, "duration_minutes": duration_minutes}
        )
        
        return result.data[0] if result.data else data
    
    # ==========================================
    # APPROVAL
    # ==========================================
    
    def approve_task(self, task_id: str, approved_by: str) -> Dict:
        """Approve a task"""
        now = datetime.now(timezone.utc).isoformat()
        
        result = self.update_task(
            task_id,
            actor=approved_by,
            approved_by=approved_by,
            approved_at=now
        )
        
        self._log_audit(
            event_type=EventType.HUMAN_APPROVED.value,
            entity_type="task",
            entity_id=task_id,
            actor=approved_by,
            actor_type="human",
            new_value={"approved_at": now}
        )
        
        return result
    
    def reject_task(self, task_id: str, rejected_by: str, reason: str = None) -> Dict:
        """Reject a task back to backlog"""
        result = self.update_task(
            task_id,
            actor=rejected_by,
            status="BACKLOG",
            approved_by=None,
            approved_at=None
        )
        
        self._log_audit(
            event_type=EventType.HUMAN_REJECTED.value,
            entity_type="task",
            entity_id=task_id,
            actor=rejected_by,
            actor_type="human",
            metadata={"reason": reason}
        )
        
        return result


# Add missing import
from datetime import timedelta

# Singleton instance
_db: Optional[WorkforceDB] = None

def get_db() -> WorkforceDB:
    global _db
    if _db is None:
        _db = WorkforceDB()
    return _db
