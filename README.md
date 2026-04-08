# Signal Raptor Agentic Framework

## System Design Document

## 1. Executive Summary

The Signal Raptor Agentic Framework is a developer-centric infrastructure platform designed to orchestrate, observe, and manage autonomous AI agents. Built with a decoupled, model-agnostic architecture, the framework abstracts the complexities of LLM routing, dynamic tool execution, and state management. It provides a unified API and a real-time Control Plane for engineers to build, evaluate, and monitor multi-step AI agents.

The framework is optimized for production readiness, with a strong emphasis on observability through execution traces and asynchronous performance.

## 2. High-Level Architecture

The system follows a standard three-tier architecture, engineered specifically for asynchronous LLM streaming and stateful execution traces.

### A. Control Plane (Frontend)

**Tech stack:** Vue 3, Vite, Pinia, Tailwind CSS

**Responsibility:** Acts as the developer dashboard. It provides interfaces for configuring agents, registering tools, managing prompt versions, and viewing real-time execution logs.

**Key mechanism:** Uses Server-Sent Events (SSE) or WebSockets to stream the agent's thought process and token generation in real time without polling.

### B. Agentic Engine (Backend)

**Tech stack:** Python, FastAPI, Pydantic, SQLAlchemy

**Responsibility:** Serves as the core orchestration layer. It handles the business logic of receiving user inputs, assembling prompt context, routing requests to the external LLM, executing local Python tools dynamically, and managing the iterative ReAct reasoning loop.

**Key mechanism:** Highly asynchronous execution. Tool runs are isolated, and all LLM interactions are logged in detail to maximize observability.

### C. State and Memory (Database)

**Tech stack:** PostgreSQL 15

**Responsibility:** Acts as the single source of truth for the framework. It stores relational data for agent configurations, tool schemas, and the complete historical trace of every session and execution step.

### D. External LLM Provider

**Target:** Google AI Studio (Gemini 1.5 Pro / Flash)

**Responsibility:** Provides the reasoning engine and function-calling capabilities. The system is designed to be model-agnostic, allowing providers to be swapped through environment variables and API abstractions, while defaulting to Gemini for its large context window and native tool-calling reliability.

## 3. System Architecture Diagram

[View Diagram](https://mermaid.ai/d/f14914a0-11e4-4377-81b7-1da271bff374)

## 4. Core Orchestration and Data Flow

When a request is initiated from the Control Plane, the framework starts the ReAct (Reason + Act) loop. The FastAPI backend serves as the traffic controller between the user's input, the database's historical context, the registered Python functions, and the external LLM's reasoning engine. Every step is captured as an execution trace.

**Agentic Execution Loop (Sequence Diagram):**

[View Diagram](https://mermaid.ai/view/a0c97861-87a2-4c60-b64f-18726be89074)

## 5. Database Schema and State Management

The database schema is strictly relational to support reliable querying of execution logs and framework configurations. It maps tools to specific agents and preserves the chronological sequence of all session traces for the observability dashboard.

**Entity Relationship Diagram (ERD):**

[View Diagram](https://mermaid.ai/d/a0c97861-87a2-4c60-b64f-18726be89074)

## 6. Deployment and Infrastructure

The entire framework is deployed as a monorepo and containerized with Docker. The root `docker-compose.yml` orchestrates the isolated network, binding the Vue frontend, FastAPI backend, and PostgreSQL database into a unified local development environment. This ensures portability and keeps the system structurally ready for cloud deployment.