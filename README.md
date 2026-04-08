# signal-raptor-ai-framework-hktn

This project is a fullstack application built with Vue 3, Vite, Pinia for the frontend, and FastAPI with PostgreSQL for the backend. The entire application is orchestrated using Docker Compose.

## Project Structure

```
signal-raptor-ai-framework-hktn
├── docker-compose.yml
├── README.md
├── backend
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   └── app
│       ├── __init__.py
│       ├── api
│       │   ├── __init__.py
│       │   └── routes.py
│       ├── models
│       │   ├── __init__.py
│       │   └── base.py
│       ├── schemas
│       │   ├── __init__.py
│       │   └── health.py
│       └── core
│           ├── __init__.py
│           ├── config.py
│           └── database.py
├── frontend
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── env.d.ts
│   └── src
│       ├── main.ts
│       ├── App.vue
│       ├── router
│       │   └── index.ts
│       ├── stores
│       │   └── counter.ts
│       ├── views
│       │   └── HomeView.vue
│       └── components
│           └── HelloWorld.vue
└── .env.example
```

## Getting Started

### Prerequisites

- Docker
- Docker Compose

### Running the Application

1. Clone the repository:

   ```bash
   git clone <repository-url>
   cd signal-raptor-ai-framework-hktn
   ```

2. Build and start the application using Docker Compose:

   ```bash
   docker-compose up --build
   ```

3. Access the frontend at `http://localhost:5173` and the backend API at `http://localhost:8000`.

### Stopping the Application

To stop the application, press `CTRL+C` in the terminal where Docker Compose is running, or run:

```bash
docker-compose down
```

## Folder Descriptions

- **backend/**: Contains the FastAPI backend code.
- **frontend/**: Contains the Vue 3 + Vite frontend code.
- **.env.example**: Example environment variables for the application.

## License

This project is licensed under the MIT License.