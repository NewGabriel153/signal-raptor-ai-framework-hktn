# Signal Raptor Agentic Framework

Signal Raptor is a containerized monorepo for building an agentic AI platform with a Vue-based control plane, a FastAPI backend, a Redis-backed background worker, and a PostgreSQL state layer. It provides a developer-facing framework for orchestrating autonomous agents, managing tools and prompts, and observing execution traces in real time.

The backend delivers a working API surface with 17 endpoints (16 fully implemented, 1 partial), a model-agnostic LLM adapter layer supporting three providers, and a Redis-backed queue for asynchronous agent runs. The frontend provides a dark-themed dashboard with session management, agent/tool creation modals, and a streaming operator console. Docker Compose brings up the full stack (frontend, API, worker, Redis, PostgreSQL) for local development.

## Project Description

The project is designed around five core responsibilities:

- **Frontend control plane** — Vue 3 dashboard for managing agents, tools, and monitoring live sessions.
- **Backend orchestration engine** — FastAPI service handling agent workflows, tool execution, API routing, and queued background runs.
- **PostgreSQL state layer** — Persistent storage for agent configuration, tool metadata, prompt versions, and execution traces.
- **Redis-backed ARQ worker** — Non-blocking job execution for long-running agent runs with pubsub event streaming.
- **Model-agnostic LLM integration** — Adapter abstraction supporting Google Gemini, OpenAI, and Anthropic providers with tool name sanitization and retry logic.

## Prerequisites

Choose one of the following development paths.

### Docker workflow

- Docker
- Docker Compose

### Local workflow

- Python 3.11+
- Node.js 16+
- npm
- PostgreSQL 15
- Redis 7

## Setup

### Run with Docker Compose

From the repository root:

```bash
docker compose up --build
```

Available services:

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Health check: http://localhost:8000/api/v1/health
- Redis: localhost:6379
- PostgreSQL: localhost:5432

To stop the stack:

```bash
docker compose down
```

### Run locally without Docker

Start the backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Start the frontend in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

The current scaffold uses PostgreSQL and Redis directly at runtime. If you are not using Docker Compose for those services, set the `POSTGRES_*` and `REDIS_*` variables to match your local environment before starting the API or worker.

To run the new background worker locally without Docker, start Redis, then launch the worker from the backend directory:

```bash
arq app.worker.WorkerSettings
```

## Architecture Summary

### Frontend

- **Stack:** Vue 3, Vite, Vue Router, Pinia, TailwindCSS, TypeScript
- **Role:** Control plane UI for agent management, tool configuration, and session monitoring
- **Current state:** Dashboard view with session sidebar, tabbed operator console, agent/tool creation modals, and dark-themed UI. SSE streaming integration is in progress.

### Backend

- **Stack:** FastAPI, Pydantic v2, SQLAlchemy 2 (async), asyncpg, Alembic
- **Role:** API layer, agent orchestration engine, and queued-run processor
- **Current state:** 17 API endpoints under `/api/v1` (16 fully implemented, 1 partial). Full CRUD for agents, tools, and agent-tool assignments. Queued run submission with execution log persistence.

### LLM Adapters

- **Stack:** google-genai SDK, openai SDK, anthropic SDK
- **Role:** Model-agnostic provider abstraction with tool name sanitization
- **Current state:** Three adapters implemented (Google Gemini, OpenAI, Anthropic) with retry logic, error classification, and provider-specific tool name mapping. Streaming support is partially implemented.

### Orchestrator

- **Stack:** ReAct-style reasoning loop
- **Role:** Multi-step agent execution with tool invocation
- **Current state:** Context assembly, conversation history building, and event emission implemented. Tool execution loop is partially complete.

### Queue Worker

- **Stack:** ARQ, Redis
- **Role:** Execute long-running agent runs outside the request/response cycle
- **Current state:** Fully implemented worker that dequeues runs, initializes adapters, publishes events to Redis pubsub, and writes execution logs with proper state transitions.

### Database

- **Stack:** PostgreSQL 15, Alembic migrations
- **Role:** Persistent storage for agents, tools, sessions, execution logs, and prompt versions
- **Current state:** Full relational schema with UUID primary keys, JSONB columns, cascading deletes, and proper indexing. Alembic migration for all core tables.

### Tool Registry

- **Stack:** Python async decorator pattern
- **Role:** Register and execute tools with type-safe invocation and error handling
- **Current state:** Fully implemented with `calculator` example tool. Supports async execution, timeout handling, and JSON-serializable output.

## API Endpoint Inventory

| Method | Path | Status | Purpose |
|--------|------|--------|---------|
| GET | `/api/v1/health` | ✅ | Service and database health check |
| POST | `/api/v1/agents/` | ✅ | Create an agent |
| GET | `/api/v1/agents/` | ✅ | List all agents |
| GET | `/api/v1/agents/{agent_id}` | ✅ | Fetch one agent |
| PATCH | `/api/v1/agents/{agent_id}` | ✅ | Update an agent |
| DELETE | `/api/v1/agents/{agent_id}` | ✅ | Delete an agent |
| POST | `/api/v1/tools/` | ✅ | Create a tool definition |
| GET | `/api/v1/tools/` | ✅ | List all tools |
| GET | `/api/v1/tools/{tool_id}` | ✅ | Fetch one tool |
| PATCH | `/api/v1/tools/{tool_id}` | ✅ | Update a tool |
| DELETE | `/api/v1/tools/{tool_id}` | ✅ | Delete a tool |
| POST | `/api/v1/agents/{agent_id}/tools/{tool_id}` | ✅ | Assign a tool to an agent |
| GET | `/api/v1/agents/{agent_id}/tools` | ✅ | List tools assigned to an agent |
| DELETE | `/api/v1/agents/{agent_id}/tools/{tool_id}` | ✅ | Remove a tool from an agent |
| POST | `/api/v1/runs/` | ✅ | Queue a background run |
| GET | `/api/v1/runs/{run_id}` | ✅ | Read run status and execution logs |
| POST | `/api/v1/sessions/{session_id}/run` | 🟡 | Stream a live session over SSE |

## Running Tests

The project includes four test suites covering the tool registry, LLM adapter behavior, session log serialization, and tool name sanitization across providers. All tests run without a database, Redis, or live LLM API keys.

### Prerequisites

Install the backend Python dependencies first:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Test 1: Tool Registry Smoke Test

**File:** `test_registry.py` (repository root)

Validates the async tool registry by executing the built-in `calculator` tool through four scenarios:

1. **Happy path** — Executes `calculator` with valid arguments and asserts the result
2. **Unregistered tool** — Calls a non-existent tool and asserts an error is returned
3. **Bad arguments** — Sends missing and wrong-type arguments to test validation
4. **Internal tool crash** — Registers a tool that raises an exception and verifies graceful error handling

```bash
# Run from the repository root
python test_registry.py
```

Expected output:

```
Signal Raptor ToolRegistry smoke test
=== 1. Happy Path ===
[PASS] 1. Happy Path
=== 2. Unregistered Tool ===
[PASS] 2. Unregistered Tool
=== 3. Bad Arguments (LLM Hallucination) ===
[PASS] 3. Bad Arguments (LLM Hallucination)
=== 4. Internal Tool Crash ===
[PASS] 4. Internal Tool Crash
=== Summary ===
Passed 4/4 scenarios
[PASS] All registry scenarios passed.
```

### Test 2: Gemini Adapter Tests

**File:** `backend/test_gemini_adapter.py`

Tests the Google Gemini LLM adapter with mocked API responses. Covers:

- **Config building** — Validates tool declarations use JSON schema format with AUTO function calling
- **Tool name sanitization** — Ensures invalid function names (e.g. `123 bad tool!`) are sanitized to match Gemini's `^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$` pattern
- **Response parsing** — Verifies function call parts are extracted even when text access raises
- **Sanitized name mapping** — Confirms provider tool names are mapped back to original names in responses
- **Empty candidates** — Handles responses with no candidates gracefully
- **Content filter blocking** — Raises `LLMContentFilterError` when prompt feedback indicates a safety block
- **Thought signatures** — Tests Gemini 3 `thought_signature` round-tripping (bytes → base64 → bytes)
- **Retry behavior** — Validates rate limit and server errors are retried 3 times with proper error classification

```bash
# Run from the backend directory
cd backend
python -m unittest test_gemini_adapter -v
```

### Test 3: Session Log Serialization Tests

**File:** `backend/test_session_log_serialization.py`

Validates that the `RunRead` Pydantic schema correctly handles mixed `tool_calls` payloads in execution logs. Tests:

- Execution logs where `tool_calls` is a **list** of tool call dicts (assistant messages)
- Execution logs where `tool_calls` is a **dict** (tool result messages)
- Schema validation and serialization of the full session payload

```bash
# Run from the backend directory
cd backend
python -m unittest test_session_log_serialization -v
```

### Test 4: Tool Name Sanitization Tests

**File:** `backend/test_tool_name_sanitization.py`

Tests that tool names with invalid characters (spaces, dots, etc.) are properly sanitized when sent to LLM providers and correctly mapped back to original names in responses. Covers both the Anthropic and OpenAI adapters:

- **Build tools** — Verifies the provider tool list uses sanitized names
- **Convert messages** — Confirms assistant tool calls use the provider name mapping
- **Extract tool calls** — Validates the reverse mapping from provider names back to original names

```bash
# Run from the backend directory
cd backend
python -m unittest test_tool_name_sanitization -v
```

### Run All Backend Tests at Once

```bash
cd backend
python -m unittest test_gemini_adapter test_session_log_serialization test_tool_name_sanitization -v
```

Or run everything including the root-level registry test:

```bash
# From the repository root
python test_registry.py && cd backend && python -m unittest discover -p "test_*.py" -v
```

## Repository Structure

```text
.
├── backend/
│   ├── main.py                          # FastAPI application entry point
│   ├── requirements.txt                 # Python dependencies
│   ├── Dockerfile                       # Backend container image
│   ├── alembic.ini                      # Database migration configuration
│   ├── test_gemini_adapter.py           # Gemini adapter unit tests
│   ├── test_session_log_serialization.py # Session log schema tests
│   ├── test_tool_name_sanitization.py   # Provider tool name mapping tests
│   ├── alembic/
│   │   └── versions/                    # Database migration scripts
│   └── app/
│       ├── adapters/                    # LLM provider adapters (Gemini, OpenAI, Anthropic)
│       ├── api/                         # FastAPI route handlers
│       ├── core/                        # Config, database, pubsub, queue infrastructure
│       ├── models/                      # SQLAlchemy ORM models
│       ├── orchestrator/                # ReAct-style agent execution loop
│       ├── schemas/                     # Pydantic request/response models
│       ├── tools/                       # Tool registry and built-in tools
│       └── worker.py                    # ARQ background job processor
├── frontend/
│   ├── package.json                     # Node.js dependencies
│   ├── Dockerfile                       # Frontend container image
│   ├── vite.config.ts                   # Vite build configuration
│   └── src/
│       ├── App.vue                      # Root Vue component
│       ├── views/
│       │   ├── Dashboard.vue            # Main operator console
│       │   └── HomeView.vue             # Landing page
│       ├── components/
│       │   ├── AgentModal.vue           # Agent creation/edit form
│       │   └── ToolModal.vue            # Tool creation/edit form
│       ├── stores/
│       │   ├── sessionStore.ts          # Session and streaming state
│       │   └── managementStore.ts       # Agent and tool CRUD state
│       ├── constants/
│       │   └── agentModels.ts           # Provider-to-model mappings
│       └── router/
│           └── index.ts                 # Vue Router configuration
├── docs/
│   ├── openapi.json                     # Static OpenAPI 3.1 export
│   ├── phase_report.md                  # Phase deliverable report
│   └── system_architecture.md           # Architecture documentation
├── docker-compose.yml                   # Full stack orchestration
├── postman_collection.json              # API testing collection
├── test_registry.py                     # Tool registry smoke test
└── README.md
```

## Design Documents

- [System design document (PDF)](https://drive.google.com/file/d/1hSWtKbkNTE6xA-qRW10wXQ4ChpsoQGqK/view?usp=sharing)
- [System architecture diagram](https://drive.google.com/file/d/1vhWqiK3Aw5bgLLQGvdQ2WNO5JurG8ceh/view?usp=sharing)
- [Agentic execution loop sequence diagram](https://drive.google.com/file/d/1akgkBY0Y-JBB0_aKvq6trT8wLsYMrtYW/view?usp=sharing)
- [Database schema and ERD](https://drive.google.com/file/d/1O-zjkhnBRAkUbk_ybccNUkcQ-v6bPzKB/view?usp=sharing)

## Current Status

### Implemented

- Dockerized local development environment with all five services
- Full CRUD API for agents, tools, and agent-tool assignments (16/17 endpoints)
- Queued run submission with ARQ worker and execution log persistence
- LLM adapter abstraction for Google Gemini, OpenAI, and Anthropic
- Tool name sanitization with provider-specific constraints and collision handling
- Async tool registry with decorator-based registration and error wrapping
- PostgreSQL schema with Alembic migrations (agents, tools, sessions, execution logs, prompt versions)
- Redis pubsub for real-time session event streaming
- Vue 3 dashboard with session sidebar, agent/tool modals, and dark-themed operator console
- Health endpoint with database and Redis connectivity validation
- Postman collection and static OpenAPI export for integration testing

### Partially Implemented

- Streaming session execution via Server-Sent Events (`POST /sessions/{id}/run`)
- ReAct-style tool invocation loop (context assembly complete, tool execution in progress)
- LLM adapter streaming methods
- Frontend SSE connection and real-time message rendering
- Session replay and history loading in the dashboard

### Not Yet Addressed

- Authentication and authorization
- API rate limiting
- Metrics and monitoring (Prometheus, OpenTelemetry)
- Deployment manifests (Kubernetes)
- Load testing
- Prompt version management UI

## Queued Runs API

Create an agent first, then enqueue a run:

```bash
curl -X POST http://localhost:8000/api/v1/runs/ \
	-H "Content-Type: application/json" \
	-d '{
		"agent_id": "<agent-uuid>",
		"prompt": "Summarize the latest deployment status"
	}'
```

Check the run status and execution logs:

```bash
curl http://localhost:8000/api/v1/runs/<session-uuid>
```