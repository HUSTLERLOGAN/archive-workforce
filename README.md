# Archive Workforce System

## Architecture
- **DB-First**: All state lives in Supabase/Postgres
- **Task-Centric**: Tasks are the unit of intelligence
- **Event-Driven**: All mutations logged, append-only audit

## Agents (V1)
1. Jarvis - Router/Brain
2. Chief of Staff - Meta-Observer
3. Ops Tracker - Pakistan Ops Spine
4. Distribution Specialist - Scale Engine
5. Content Researcher - (Future)

## Directories
- `/core` - Task engine, event bus, registry
- `/agents` - Specialist definitions
- `/api` - REST endpoints (Single Intake API)
- `/ui` - Mission Control dashboard
- `/config` - Environment and settings
- `/migrations` - Database migrations

## Principles
- No chat-based execution
- Deliverable-enforced completion
- Append-only audit log
- Human approval for critical actions
