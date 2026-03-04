# Task Management REST API - Specification

## Overview
A RESTful API for managing tasks (to-do items) built with FastAPI and Python. Supports full CRUD operations with filtering, sorting, and status management.

## Tech Stack
- **Framework**: FastAPI (async, auto-docs, Pydantic validation)
- **Database**: SQLite via SQLAlchemy (lightweight, no external DB needed)
- **Validation**: Pydantic v2 models
- **Testing**: pytest + httpx (async test client)
- **Python**: 3.10+

## Data Model

### Task
| Field        | Type     | Required | Default     | Description                     |
|-------------|----------|----------|-------------|---------------------------------|
| id          | int      | auto     | auto-inc    | Primary key                     |
| title       | str      | yes      | -           | Task title (1-200 chars)        |
| description | str      | no       | null        | Task description                |
| status      | enum     | no       | "pending"   | pending/in_progress/completed   |
| priority    | enum     | no       | "medium"    | low/medium/high                 |
| created_at  | datetime | auto     | now()       | Creation timestamp              |
| updated_at  | datetime | auto     | now()       | Last update timestamp           |

## API Endpoints

| Method | Path           | Description          |
|--------|---------------|----------------------|
| GET    | /tasks        | List tasks (filter/sort) |
| POST   | /tasks        | Create a task        |
| GET    | /tasks/{id}   | Get task by ID       |
| PUT    | /tasks/{id}   | Update a task        |
| DELETE | /tasks/{id}   | Delete a task        |
| GET    | /health       | Health check         |

### Query Parameters for GET /tasks
- `status`: Filter by status
- `priority`: Filter by priority
- `skip`: Pagination offset (default 0)
- `limit`: Pagination limit (default 20, max 100)

## Project Structure
```
task_api/
  task_api/
    __init__.py
    main.py          # FastAPI app, routes
    models.py        # SQLAlchemy models
    schemas.py       # Pydantic schemas
    database.py      # DB engine/session
  tests/
    __init__.py
    test_api.py      # API endpoint tests
```

## Non-Functional Requirements
- Input validation on all endpoints
- Proper HTTP status codes (201, 404, 422)
- Auto-generated OpenAPI docs at /docs
- Timestamps in ISO 8601 format
