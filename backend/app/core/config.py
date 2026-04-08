# Configuration settings for the FastAPI application

class Config:
    # Database configuration
    DATABASE_URL = "postgresql://user:password@db:5432/mydatabase"
    
    # FastAPI settings
    TITLE = "My FastAPI Application"
    VERSION = "0.1.0"
    DESCRIPTION = "A FastAPI application with PostgreSQL and Docker Compose"
    
    # Other settings can be added here as needed
