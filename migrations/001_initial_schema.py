"""
Workforce Database Schema - Supabase/PostgreSQL Migration

This creates the core tables for the Archive Workforce system.
Run via Supabase SQL Editor or psql.
"""

SCHEMA_SQL = """
-- ============================================
-- ARCHIVE WORKFORCE SCHEMA v1
-- ============================================

-- 1. TASKS TABLE (Core unit of intelligence)
-- ============================================
CREATE TABLE IF NOT EXISTS workforce_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    description TEXT,
    
    -- Ownership & Assignment
    owner_agent TEXT,  -- jarvis, chief_of_staff, ops_tracker, distribution, researcher
    assigned_by TEXT,  -- Who/what created this task
    
    -- Status & Priority
    status TEXT NOT NULL DEFAULT 'BACKLOG',  -- BACKLOG, IN_PROGRESS, NEEDS_REVIEW, DONE, BLOCKED, CANCELLED
    priority TEXT NOT NULL DEFAULT 'P2',  -- P0 (critical), P1 (high), P2 (medium), P3 (low)
    
    -- Metadata
    tags TEXT[] DEFAULT '{}',  -- brand, domain, type tags
    source TEXT NOT NULL DEFAULT 'api',  -- discord, telegram, api, ui
    external_refs JSONB DEFAULT '{}',  -- Links to external systems
    
    -- Estimation
    impact_score INTEGER,  -- 1-10
    effort_estimate TEXT,  -- xs, s, m, l, xl
    
    -- Approval
    requires_approval BOOLEAN DEFAULT FALSE,
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    
    -- Hierarchy
    parent_task_id UUID REFERENCES workforce_tasks(id),
    
    -- Timestamps
    due_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for tasks
CREATE INDEX IF NOT EXISTS idx_tasks_status ON workforce_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_owner ON workforce_tasks(owner_agent);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON workforce_tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON workforce_tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON workforce_tasks(created_at DESC);

-- 2. DELIVERABLES TABLE (Required for task completion)
-- ============================================
CREATE TABLE IF NOT EXISTS workforce_deliverables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES workforce_tasks(id) ON DELETE CASCADE,
    
    title TEXT NOT NULL,
    content TEXT NOT NULL,  -- The actual deliverable content
    content_type TEXT DEFAULT 'text',  -- text, markdown, json, file_url
    
    -- Metadata
    created_by TEXT NOT NULL,  -- Agent or human who created it
    is_final BOOLEAN DEFAULT FALSE,  -- Marked as the final deliverable
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deliverables_task ON workforce_deliverables(task_id);

-- 3. INSIGHTS TABLE (Agent observations, not tasks)
-- ============================================
CREATE TABLE IF NOT EXISTS workforce_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES workforce_tasks(id) ON DELETE SET NULL,  -- Can be task-attached or floating
    
    agent TEXT NOT NULL,  -- Which agent posted this
    content TEXT NOT NULL,
    insight_type TEXT DEFAULT 'observation',  -- observation, recommendation, risk, question
    
    -- Promotion tracking
    promoted_to_task_id UUID REFERENCES workforce_tasks(id),
    promoted_at TIMESTAMPTZ,
    
    -- Auto-expiry
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days'),
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_insights_task ON workforce_insights(task_id);
CREATE INDEX IF NOT EXISTS idx_insights_agent ON workforce_insights(agent);
CREATE INDEX IF NOT EXISTS idx_insights_expires ON workforce_insights(expires_at);

-- 4. AGENT REGISTRY (Specialist definitions)
-- ============================================
CREATE TABLE IF NOT EXISTS workforce_agents (
    id TEXT PRIMARY KEY,  -- jarvis, chief_of_staff, ops_tracker, etc.
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    description TEXT,
    
    -- Capabilities
    capabilities TEXT[] DEFAULT '{}',
    allowed_actions TEXT[] DEFAULT '{}',
    
    -- Execution config
    model_provider TEXT DEFAULT 'openai',
    model_id TEXT DEFAULT 'gpt-4o-mini',
    schedule_interval_minutes INTEGER DEFAULT 60,
    max_tasks_per_run INTEGER DEFAULT 10,
    
    -- State
    enabled BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMPTZ,
    last_run_status TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. AGENT RUNS (Execution log)
-- ============================================
CREATE TABLE IF NOT EXISTS workforce_agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT NOT NULL REFERENCES workforce_agents(id),
    
    status TEXT NOT NULL DEFAULT 'running',  -- running, success, failed, timeout
    tasks_processed INTEGER DEFAULT 0,
    insights_created INTEGER DEFAULT 0,
    
    -- Timing
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,
    
    -- Error tracking
    error_message TEXT,
    
    -- Token usage
    tokens_used INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_runs_agent ON workforce_agent_runs(agent_id);
CREATE INDEX IF NOT EXISTS idx_runs_started ON workforce_agent_runs(started_at DESC);

-- 6. AUDIT LOG (Append-only, forever)
-- ============================================
CREATE TABLE IF NOT EXISTS workforce_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- What happened
    event_type TEXT NOT NULL,  -- TASK_CREATED, STATUS_CHANGED, etc.
    entity_type TEXT NOT NULL,  -- task, insight, deliverable, agent
    entity_id TEXT NOT NULL,
    
    -- Who did it
    actor TEXT NOT NULL,  -- Agent ID or human ID
    actor_type TEXT NOT NULL,  -- agent, human, system
    
    -- Change details
    old_value JSONB,
    new_value JSONB,
    metadata JSONB DEFAULT '{}',
    
    -- Timestamp (immutable)
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Audit log should NEVER be updated or deleted
CREATE INDEX IF NOT EXISTS idx_audit_entity ON workforce_audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_event ON workforce_audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON workforce_audit_log(actor);
CREATE INDEX IF NOT EXISTS idx_audit_created ON workforce_audit_log(created_at DESC);

-- 7. EVENT LOG (For event-driven triggers)
-- ============================================
CREATE TABLE IF NOT EXISTS workforce_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    
    -- Processing state
    processed BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMPTZ,
    processed_by TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_type ON workforce_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_processed ON workforce_events(processed, created_at);

-- 8. AUTONOMY SESSIONS (Time-boxed autonomy grants)
-- ============================================
CREATE TABLE IF NOT EXISTS workforce_autonomy_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    mode TEXT NOT NULL,  -- advisory, review_only, full_autonomy
    granted_by TEXT NOT NULL,  -- Human who granted it
    granted_to TEXT,  -- Specific agent or NULL for all
    
    reason TEXT,
    
    -- Time boxing
    starts_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    
    -- Termination
    revoked_at TIMESTAMPTZ,
    revoked_by TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_autonomy_active ON workforce_autonomy_sessions(expires_at) 
    WHERE revoked_at IS NULL;

-- ============================================
-- FUNCTIONS & TRIGGERS
-- ============================================

-- Auto-update updated_at on tasks
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tasks_updated_at ON workforce_tasks;
CREATE TRIGGER tasks_updated_at
    BEFORE UPDATE ON workforce_tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS agents_updated_at ON workforce_agents;
CREATE TRIGGER agents_updated_at
    BEFORE UPDATE ON workforce_agents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================
-- SEED DATA: Initial Agents
-- ============================================
INSERT INTO workforce_agents (id, name, role, description, capabilities, allowed_actions, model_provider, model_id, schedule_interval_minutes)
VALUES 
    ('jarvis', 'Jarvis', 'Router/Brain', 'Intake, task creation, assignment, prioritization. NEVER executes work.', 
     ARRAY['intake', 'route', 'prioritize', 'summarize'], 
     ARRAY['create_task', 'assign_task', 'update_priority', 'summarize_status'],
     'openai', 'gpt-4o', 60),
    
    ('chief_of_staff', 'Chief of Staff', 'Meta-Observer', 'Reports workflow status, agent health, problem escalation.',
     ARRAY['observe', 'report', 'escalate'],
     ARRAY['add_insight', 'create_report', 'flag_problem'],
     'openai', 'gpt-4o-mini', 30),
    
    ('ops_tracker', 'Ops Tracker', 'Pakistan Ops Spine', 'Discord bot integration, daily ops reports, creator tracking.',
     ARRAY['track', 'report', 'monitor'],
     ARRAY['add_insight', 'create_report', 'query_tracking_data'],
     'openai', 'gpt-4o-mini', 60),
    
    ('distribution', 'Distribution Specialist', 'Scale Engine', 'Phone farm automation, distribution sauce, scaling operations.',
     ARRAY['automate', 'scale', 'distribute'],
     ARRAY['add_insight', 'trigger_automation', 'report_distribution'],
     'openai', 'gpt-4o-mini', 90),
    
    ('researcher', 'Content Researcher', 'Research', 'Content research, trend analysis, competitor monitoring.',
     ARRAY['research', 'analyze', 'monitor'],
     ARRAY['add_insight', 'create_report'],
     'openai', 'gpt-4o-mini', 120)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    role = EXCLUDED.role,
    description = EXCLUDED.description,
    capabilities = EXCLUDED.capabilities,
    allowed_actions = EXCLUDED.allowed_actions,
    model_provider = EXCLUDED.model_provider,
    model_id = EXCLUDED.model_id,
    schedule_interval_minutes = EXCLUDED.schedule_interval_minutes,
    updated_at = NOW();
""";
