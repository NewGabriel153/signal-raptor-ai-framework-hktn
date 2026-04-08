# Signal Raptor Agentic Framework

Signal Raptor is a containerized monorepo for building an agentic AI platform with a Vue-based control plane, a FastAPI backend, and a PostgreSQL state layer. The long-term goal is to provide a developer-facing framework for orchestrating autonomous agents, managing tools and prompts, and observing execution traces in real time.

At the moment, the repository is an early scaffold: the frontend is a running Vue/Vite shell, the backend exposes a health endpoint, and Docker Compose brings up the frontend, API, and database services together for local development.

## Project Description

The project is designed around four core responsibilities:

- A frontend control plane for managing and monitoring agents.
- A backend orchestration engine for agent workflows, tool execution, and API routing.
- A PostgreSQL database for persistent state, configuration, and trace history.
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

The current scaffold does not require environment variables to boot locally. PostgreSQL is provisioned in Docker Compose for the intended full-stack architecture, but the checked-in backend code is not yet wired to the database at runtime.

## Architecture Summary

### Frontend

- Stack: Vue 3, Vite, Vue Router, Pinia
- Role: control plane UI for the framework
- Current state: starter application served on port 5173

### Backend

- Stack: FastAPI, Pydantic, SQLAlchemy
- Role: API layer and future agent orchestration engine
- Current state: minimal FastAPI service with a health endpoint on port 8000

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
- A FastAPI backend starter service
- A PostgreSQL service definition for future persistence work

The agent execution loop, tool registration flow, prompt management, real-time observability features, and LLM provider integration are part of the intended architecture and design documents, but are not fully implemented in the current codebase yet.