"""
Workforce API - Single Intake Endpoint

All external requests (Discord, Telegram, UI, webhooks) route through this API.
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import os
import sys

# Add workforce to path
sys.path.insert(0, '/root/clawd/workforce')
sys.path.insert(0, '/root/clawd/discord-bot')

from dotenv import load_dotenv
load_dotenv('/root/clawd/discord-bot/.env')

from core.database import get_db, TaskStatus, Priority

app = FastAPI(
    title="Archive Workforce API",
    description="Single Intake API for the Archive Workforce system",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# MODELS
# ==========================================

class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    owner_agent: Optional[str] = None
    priority: str = Field(default="P2", pattern="^P[0-3]$")
    tags: List[str] = []
    source: str = Field(default="api")
    requires_approval: bool = False
    parent_task_id: Optional[str] = None
    due_at: Optional[str] = None
    impact_score: Optional[int] = Field(default=None, ge=1, le=10)
    effort_estimate: Optional[str] = Field(default=None, pattern="^(xs|s|m|l|xl)$")
    external_refs: Optional[Dict[str, Any]] = {}

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    owner_agent: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(BACKLOG|IN_PROGRESS|NEEDS_REVIEW|DONE|BLOCKED|CANCELLED)$")
    priority: Optional[str] = Field(default=None, pattern="^P[0-3]$")
    tags: Optional[List[str]] = None
    requires_approval: Optional[bool] = None
    due_at: Optional[str] = None

class DeliverableCreate(BaseModel):
    title: str
    content: str
    content_type: str = "text"
    is_final: bool = False

class InsightCreate(BaseModel):
    content: str
    task_id: Optional[str] = None
    insight_type: str = "observation"

class IntakeMessage(BaseModel):
    """Universal intake format for all sources"""
    message: str
    source: str = Field(..., pattern="^(discord|telegram|api|ui|webhook)$")
    user_id: Optional[str] = None
    channel_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}

class ApprovalAction(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    reason: Optional[str] = None

class AutonomyGrant(BaseModel):
    mode: str = Field(..., pattern="^(advisory|review_only|full_autonomy)$")
    duration_minutes: int = Field(..., ge=1, le=480)  # Max 8 hours
    granted_to: Optional[str] = None
    reason: Optional[str] = None

# ==========================================
# DEPENDENCIES
# ==========================================

def get_actor(x_actor: str = Header(default="api")):
    """Extract actor from header"""
    return x_actor

# ==========================================
# ROUTES: INTAKE
# ==========================================

@app.post("/intake", tags=["Intake"])
async def intake(message: IntakeMessage, actor: str = Depends(get_actor)):
    """
    Universal intake endpoint.
    Jarvis will process and route to appropriate task.
    """
    db = get_db()
    
    # For now, create a task directly
    # In Phase 5, Jarvis will process this
    task = db.create_task(
        title=message.message[:200],
        description=message.message,
        assigned_by=actor,
        source=message.source,
        external_refs={
            "user_id": message.user_id,
            "channel_id": message.channel_id,
            **message.metadata
        }
    )
    
    return {
        "status": "received",
        "task_id": task["id"],
        "message": "Task created. Jarvis will route and assign."
    }

# ==========================================
# ROUTES: TASKS
# ==========================================

@app.post("/tasks", tags=["Tasks"])
async def create_task(task: TaskCreate, actor: str = Depends(get_actor)):
    """Create a new task"""
    db = get_db()
    result = db.create_task(
        title=task.title,
        description=task.description,
        owner_agent=task.owner_agent,
        assigned_by=actor,
        priority=task.priority,
        tags=task.tags,
        source=task.source,
        requires_approval=task.requires_approval,
        parent_task_id=task.parent_task_id,
        due_at=task.due_at,
        impact_score=task.impact_score,
        effort_estimate=task.effort_estimate,
        external_refs=task.external_refs
    )
    return result

@app.get("/tasks", tags=["Tasks"])
async def list_tasks(
    status: Optional[str] = None,
    owner_agent: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 50
):
    """List tasks with optional filters"""
    db = get_db()
    return db.get_tasks(status=status, owner_agent=owner_agent, priority=priority, limit=limit)

@app.get("/tasks/{task_id}", tags=["Tasks"])
async def get_task(task_id: str):
    """Get a single task"""
    db = get_db()
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@app.patch("/tasks/{task_id}", tags=["Tasks"])
async def update_task(task_id: str, update: TaskUpdate, actor: str = Depends(get_actor)):
    """Update a task"""
    db = get_db()
    try:
        updates = {k: v for k, v in update.dict().items() if v is not None}
        result = db.update_task(task_id, actor=actor, **updates)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/tasks/{task_id}/approve", tags=["Tasks"])
async def approve_task(task_id: str, action: ApprovalAction, actor: str = Depends(get_actor)):
    """Approve or reject a task"""
    db = get_db()
    if action.action == "approve":
        return db.approve_task(task_id, actor)
    else:
        return db.reject_task(task_id, actor, action.reason)

# ==========================================
# ROUTES: DELIVERABLES
# ==========================================

@app.post("/tasks/{task_id}/deliverables", tags=["Deliverables"])
async def add_deliverable(task_id: str, deliverable: DeliverableCreate, actor: str = Depends(get_actor)):
    """Add a deliverable to a task"""
    db = get_db()
    return db.add_deliverable(
        task_id=task_id,
        title=deliverable.title,
        content=deliverable.content,
        content_type=deliverable.content_type,
        created_by=actor,
        is_final=deliverable.is_final
    )

@app.get("/tasks/{task_id}/deliverables", tags=["Deliverables"])
async def get_deliverables(task_id: str):
    """Get deliverables for a task"""
    db = get_db()
    return db.get_deliverables(task_id)

# ==========================================
# ROUTES: INSIGHTS
# ==========================================

@app.post("/insights", tags=["Insights"])
async def add_insight(insight: InsightCreate, actor: str = Depends(get_actor)):
    """Add an insight (agent observation)"""
    db = get_db()
    return db.add_insight(
        agent=actor,
        content=insight.content,
        task_id=insight.task_id,
        insight_type=insight.insight_type
    )

@app.get("/insights", tags=["Insights"])
async def list_insights(task_id: Optional[str] = None, agent: Optional[str] = None, limit: int = 50):
    """List insights"""
    db = get_db()
    return db.get_insights(task_id=task_id, agent=agent, limit=limit)

@app.post("/insights/{insight_id}/promote", tags=["Insights"])
async def promote_insight(insight_id: str, actor: str = Depends(get_actor)):
    """Promote an insight to a task (Jarvis only)"""
    if actor != "jarvis":
        raise HTTPException(status_code=403, detail="Only Jarvis can promote insights to tasks")
    db = get_db()
    return db.promote_insight_to_task(insight_id, actor)

# ==========================================
# ROUTES: AGENTS
# ==========================================

@app.get("/agents", tags=["Agents"])
async def list_agents(enabled_only: bool = True):
    """List all agents"""
    db = get_db()
    return db.get_agents(enabled_only=enabled_only)

@app.get("/agents/{agent_id}", tags=["Agents"])
async def get_agent(agent_id: str):
    """Get agent details"""
    db = get_db()
    agent = db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent

@app.patch("/agents/{agent_id}", tags=["Agents"])
async def update_agent(agent_id: str, updates: Dict[str, Any], actor: str = Depends(get_actor)):
    """Update agent configuration"""
    db = get_db()
    return db.update_agent(agent_id, **updates)

# ==========================================
# ROUTES: AUTONOMY
# ==========================================

@app.get("/autonomy", tags=["Autonomy"])
async def get_autonomy_mode(agent_id: Optional[str] = None):
    """Get current autonomy mode"""
    db = get_db()
    mode = db.get_current_autonomy_mode(agent_id)
    return {"mode": mode}

@app.post("/autonomy", tags=["Autonomy"])
async def grant_autonomy(grant: AutonomyGrant, actor: str = Depends(get_actor)):
    """Grant time-boxed autonomy"""
    db = get_db()
    return db.grant_autonomy(
        mode=grant.mode,
        granted_by=actor,
        duration_minutes=grant.duration_minutes,
        granted_to=grant.granted_to,
        reason=grant.reason
    )

# ==========================================
# ROUTES: EVENTS & AUDIT
# ==========================================

@app.get("/events", tags=["Events"])
async def get_events(processed: Optional[bool] = None, limit: int = 100):
    """Get events (for event-driven processing)"""
    db = get_db()
    if processed is False:
        return db.get_unprocessed_events(limit)
    # For processed=True or None, return recent events
    result = db.client.table("workforce_events")\
        .select("*")\
        .order("created_at", desc=True)\
        .limit(limit)\
        .execute()
    return result.data

@app.get("/audit", tags=["Audit"])
async def get_audit_log(
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100
):
    """Query audit log (read-only)"""
    db = get_db()
    query = db.client.table("workforce_audit_log").select("*")
    
    if entity_type:
        query = query.eq("entity_type", entity_type)
    if entity_id:
        query = query.eq("entity_id", entity_id)
    if event_type:
        query = query.eq("event_type", event_type)
    
    result = query.order("created_at", desc=True).limit(limit).execute()
    return result.data

# ==========================================
# ROUTES: HEALTH
# ==========================================

@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint"""
    db = get_db()
    try:
        # Test DB connection
        db.client.table("workforce_agents").select("id").limit(1).execute()
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "database": "connected"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "timestamp": datetime.utcnow().isoformat(),
            "database": f"error: {str(e)}"
        }

@app.get("/", tags=["System"])
async def root():
    """API root"""
    return {
        "name": "Archive Workforce API",
        "version": "1.0.0",
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
