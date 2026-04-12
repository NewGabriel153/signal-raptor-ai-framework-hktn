# Signal Raptor Agentic Framework

Signal Raptor is a containerized monorepo for building an agentic AI platform with a Vue-based control plane, a FastAPI backend, a Redis-backed background worker, and a PostgreSQL state layer. The long-term goal is to provide a developer-facing framework for orchestrating autonomous agents, managing tools and prompts, and observing execution traces in real time.

At the moment, the repository is an early scaffold: the frontend is a running Vue/Vite shell, the backend exposes CRUD and queued-run endpoints, and Docker Compose brings up the frontend, API, worker, Redis, and database services together for local development.

## Project Description

The project is designed around four core responsibilities:

- A frontend control plane for managing and monitoring agents.
- A backend orchestration engine for agent workflows, tool execution, API routing, and queued background runs.
- A PostgreSQL database for persistent state, configuration, and trace history.
- A Redis-backed ARQ worker for non-blocking job execution.
- A model-agnostic integration layer for external LLM providers.

This repository is the implementation scaffold for that architecture and the base for future agent runtime, observability, and prompt-management features.

## Prerequisites

Choose one of the following development paths.

### Docker workflow

- Docker
- Docker Compose

### Local workflow

- Python 3.9+
- Node.js 16+
- npm

## Setup

### Run with Docker Compose

From the repository root:

```bash
docker compose up --build
```

Available services:

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Health check: http://localhost:8000/api/v1/health
- Redis: localhost:6379

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

- Stack: Vue 3, Vite, Vue Router, Pinia
- Role: control plane UI for the framework
- Current state: starter application served on port 5173

### Backend

- Stack: FastAPI, Pydantic, SQLAlchemy, ARQ
- Role: API layer, queued-run entrypoint, and future agent orchestration engine
- Current state: FastAPI service with health, CRUD, and asynchronous run-enqueue endpoints on port 8000

### Queue Worker

- Stack: ARQ, Redis
- Role: execute long-running runs outside the request/response cycle
- Current state: scaffold worker that dequeues runs, writes execution logs, and marks sessions complete or failed

### Database

- Stack: PostgreSQL 15
- Role: persistent storage for agent state, tool metadata, and execution traces
- Current state: available through Docker Compose as the planned state layer

### LLM Integration

- Target direction: model-agnostic provider abstraction
- Planned default: Google AI Studio with Gemini models
- Current state: architecture goal documented, not yet implemented in the runtime flow

## Repository Structure

```text
.
├── backend/
│   ├── app/
│   ├── main.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
└── docker-compose.yml
```

## Design Documents

- System design document PDF: https://drive.google.com/file/d/1hSWtKbkNTE6xA-qRW10wXQ4ChpsoQGqK/view?usp=sharing
- System architecture diagram: https://drive.google.com/file/d/1vhWqiK3Aw5bgLLQGvdQ2WNO5JurG8ceh/view?usp=sharing
- Agentic execution loop sequence diagram: https://drive.google.com/file/d/1akgkBY0Y-JBB0_aKvq6trT8wLsYMrtYW/view?usp=sharing
- Database schema and ERD: https://drive.google.com/file/d/1O-zjkhnBRAkUbk_ybccNUkcQ-v6bPzKB/view?usp=sharing

## Current Status

The repository currently provides:

- A Dockerized local development environment
- A Vue frontend starter application
- A FastAPI backend with async CRUD and run-queue endpoints
- A Redis-backed ARQ worker scaffold for background processing
- A PostgreSQL service definition for persistence and execution traces

The real agent execution loop, tool registration flow, prompt management UX, real-time observability features, and LLM provider integration are still only partially implemented. The current worker path is a queue-backed scaffold that records session progress and a placeholder assistant response so the non-blocking infrastructure is already in place.

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