System Design Document: Signal Raptor Agentic Framework
1. Executive Summary
The Signal Raptor Agentic Framework is a developer-centric infrastructure platform designed to orchestrate, observe, and manage autonomous AI agents. Built with a decoupled, model-agnostic architecture, the framework abstracts the complexities of LLM routing, dynamic tool execution, and state management. It provides a unified API and a real-time Control Plane for engineers to build, evaluate, and monitor multi-step AI agents.

The framework is optimized for production readiness, focusing heavily on observability (execution traces) and asynchronous performance.

2. High-Level Architecture
The system follows a standard three-tier architecture, engineered specifically for asynchronous LLM streaming and stateful execution traces.

A. The Control Plane (Frontend)
Tech Stack: Vue 3, Vite, Pinia, TailwindCSS.

Responsibility: Acts as the developer dashboard. It provides interfaces for configuring agents, registering tools, managing prompt versions, and viewing real-time execution logs.

Key Mechanism: Utilizes Server-Sent Events (SSE) or WebSockets to stream the "thought process" and token generation of the agent in real-time without polling.

B. The Agentic Engine (Backend)
Tech Stack: Python, FastAPI, Pydantic, SQLAlchemy.

Responsibility: The core orchestration layer. It handles the business logic of receiving user inputs, assembling the prompt context, routing requests to the external LLM, executing local Python tools dynamically, and managing the iterative reasoning loop (ReAct pattern).

Key Mechanism: Highly asynchronous. Tool executions are isolated, and all LLM interactions are logged meticulously to ensure maximum observability.

C. State & Memory (Database)
Tech Stack: PostgreSQL 15.

Responsibility: The single source of truth for the framework. It stores relational data for agent configurations, tool schemas, and the complete historical trace of every session and execution step.

D. External LLM Provider
Target: Google AI Studio (Gemini 1.5 Pro / Flash).

Responsibility: Provides the reasoning engine and function-calling capabilities. The system is designed to be model-agnostic, allowing seamless swapping of providers via environment variables and API abstractions, but defaults to Gemini for its massive context window and native tool-calling reliability.

3. System Architecture Diagram
Code snippet
graph TD
    User[User]
    subgraph "Layer 1: Control Plane (Vue 3)"
        Frontend[Frontend Application]
    end
    subgraph "Layer 2: Agentic Engine (FastAPI)"
        Backend[Backend API]
        Orchestrator[Orchestration Loop]
        ContextAssembly[Context Assembly]
        ToolRegistry[Tool Registry]
    end
    subgraph "Layer 3: State & Memory (PostgreSQL)"
        Database[PostgreSQL Database]
    end
    LLMProvider["External LLM Provider (Google AI Studio / Gemini)"]

    %% Connections
    User --> Frontend
    Frontend <-> Backend
    Backend --> Orchestrator
    Orchestrator --> ContextAssembly
    ContextAssembly <-> Database
    Orchestrator --> ToolRegistry
    Orchestrator <-> LLMProvider
4. Core Orchestration & Data Flow
When a request is initiated from the Control Plane, the framework initiates the ReAct (Reason + Act) loop. The FastAPI backend serves as the traffic controller between the user's input, the database's historical context, the registered Python functions, and the external LLM's reasoning engine. Every step is captured as an execution trace.

Agentic Execution Loop (Sequence Diagram)
Code snippet
sequenceDiagram
    autonumber
    actor User
    participant Vue Frontend
    participant FastAPI Backend
    participant Postgres DB
    participant Tool Registry
    participant Google API (Gemini)

    User->>Vue Frontend: Submit Prompt
    Vue Frontend->>FastAPI Backend: POST /run {session_id, prompt}
    
    rect rgb(30, 30, 30)
        Note right of FastAPI Backend: 1. Context Assembly
        FastAPI Backend->>Postgres DB: Fetch Agent Config & Tools
        FastAPI Backend->>Postgres DB: Fetch Conversation History
    end

    loop Agentic Reasoning (ReAct)
        FastAPI Backend->>Google API (Gemini): Send Context + Tool Schemas
        Google API (Gemini)-->>FastAPI Backend: Response (Tool Call Requested)
        
        Note over FastAPI Backend,Tool Registry: 2. Dynamic Execution
        FastAPI Backend->>Tool Registry: Execute mapped Python function
        Tool Registry-->>FastAPI Backend: Return Tool Result (JSON)
        FastAPI Backend->>Postgres DB: Log Execution Trace (Tool Output)
        FastAPI Backend-->>Vue Frontend: Stream Trace Update (SSE)
    end

    FastAPI Backend->>Google API (Gemini): Send Context + Tool Results
    Google API (Gemini)-->>FastAPI Backend: Final Natural Language Response
    
    rect rgb(30, 30, 30)
        Note right of FastAPI Backend: 3. Finalization
        FastAPI Backend->>Postgres DB: Save Final Assistant Message
        FastAPI Backend-->>Vue Frontend: Stream Final Response
    end
    Vue Frontend-->>User: Display Output
5. Database Schema & State Management
The database schema is strictly relational to support reliable querying of execution logs and framework configurations. It handles the mapping of tools to specific agents and maintains the chronological sequence of all session traces for the observability dashboard.

Entity Relationship Diagram (ERD)
Code snippet
erDiagram
    AGENT {
        uuid id PK
        string name
        string description
        string model_provider "e.g., google_genai, openai"
        string target_model "e.g., gemini-1.5-pro, gemini-1.5-flash"
        timestamp created_at
        timestamp updated_at
    }

    PROMPT_VERSION {
        uuid id PK
        uuid agent_id FK
        text system_prompt_template
        int version_number
        boolean is_active
        timestamp created_at
    }

    TOOL {
        uuid id PK
        string name
        string description
        jsonb json_schema "OpenAPI/JSON schema for LLM"
        string python_function_name "Mapped internal function"
        timestamp created_at
    }

    AGENT_TOOL {
        uuid agent_id PK, FK
        uuid tool_id PK, FK
    }

    SESSION {
        uuid id PK
        uuid agent_id FK
        string status "active, completed, failed"
        timestamp start_time
        timestamp end_time
    }

    EXECUTION_LOG {
        uuid id PK
        uuid session_id FK
        int step_sequence
        string role "user, assistant, tool, system"
        text content "Text response or tool output"
        jsonb tool_calls "Details if a tool was requested"
        int prompt_tokens
        int completion_tokens
        timestamp created_at
    }

    %% Relationships
    AGENT ||--o{ PROMPT_VERSION : "has"
    AGENT ||--o{ AGENT_TOOL : "configures"
    TOOL ||--o{ AGENT_TOOL : "assigned to"
    AGENT ||--o{ SESSION : "runs"
    SESSION ||--o{ EXECUTION_LOG : "generates traces"
6. Deployment & Infrastructure
The entire framework is deployed as a monorepo, containerized via Docker. A root docker-compose.yml orchestrates the isolated network, binding the Vue frontend, FastAPI backend, and PostgreSQL database into a unified local development environment. This ensures immediate portability and guarantees that the system is structurally ready for cloud deployment.