import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from task_api.database import Base, get_db
from task_api.main import app

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_create_task():
    response = client.post("/tasks", json={"title": "Test task"})
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test task"
    assert data["status"] == "pending"
    assert data["priority"] == "medium"
    assert data["description"] is None
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


def test_create_task_full():
    response = client.post(
        "/tasks",
        json={
            "title": "Full task",
            "description": "A detailed description",
            "status": "in_progress",
            "priority": "high",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Full task"
    assert data["description"] == "A detailed description"
    assert data["status"] == "in_progress"
    assert data["priority"] == "high"


def test_create_task_validation_empty_title():
    response = client.post("/tasks", json={"title": ""})
    assert response.status_code == 422


def test_create_task_validation_long_title():
    response = client.post("/tasks", json={"title": "x" * 201})
    assert response.status_code == 422


def test_list_tasks_empty():
    response = client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_list_tasks():
    assert client.post("/tasks", json={"title": "Task 1"}).status_code == 201
    assert client.post("/tasks", json={"title": "Task 2"}).status_code == 201
    response = client.get("/tasks")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_tasks_filter_by_status():
    assert client.post("/tasks", json={"title": "Pending", "status": "pending"}).status_code == 201
    assert client.post("/tasks", json={"title": "Done", "status": "completed"}).status_code == 201
    response = client.get("/tasks", params={"status": "pending"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Pending"


def test_list_tasks_filter_by_priority():
    assert client.post("/tasks", json={"title": "Low", "priority": "low"}).status_code == 201
    assert client.post("/tasks", json={"title": "High", "priority": "high"}).status_code == 201
    response = client.get("/tasks", params={"priority": "high"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "High"


def test_list_tasks_pagination():
    for i in range(5):
        assert client.post("/tasks", json={"title": f"Task {i}"}).status_code == 201
    response = client.get("/tasks", params={"skip": 2, "limit": 2})
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_task():
    create = client.post("/tasks", json={"title": "Get me"})
    assert create.status_code == 201
    task_id = create.json()["id"]
    response = client.get(f"/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json()["title"] == "Get me"


def test_get_task_not_found():
    response = client.get("/tasks/9999")
    assert response.status_code == 404


def test_update_task():
    create = client.post("/tasks", json={"title": "Original"})
    assert create.status_code == 201
    task_id = create.json()["id"]
    response = client.put(
        f"/tasks/{task_id}",
        json={"title": "Updated", "status": "completed", "priority": "high"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated"
    assert data["status"] == "completed"
    assert data["priority"] == "high"


def test_update_task_partial():
    create = client.post("/tasks", json={"title": "Original", "priority": "low"})
    assert create.status_code == 201
    task_id = create.json()["id"]
    response = client.put(f"/tasks/{task_id}", json={"title": "New title"})
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "New title"
    assert data["priority"] == "low"


def test_update_task_not_found():
    response = client.put("/tasks/9999", json={"title": "Nope"})
    assert response.status_code == 404


def test_update_task_invalid_status():
    create = client.post("/tasks", json={"title": "Task"})
    assert create.status_code == 201
    task_id = create.json()["id"]
    response = client.put(f"/tasks/{task_id}", json={"status": "not_a_status"})
    assert response.status_code == 422


def test_delete_task():
    create = client.post("/tasks", json={"title": "Delete me"})
    assert create.status_code == 201
    task_id = create.json()["id"]
    response = client.delete(f"/tasks/{task_id}")
    assert response.status_code == 204
    get_response = client.get(f"/tasks/{task_id}")
    assert get_response.status_code == 404


def test_delete_task_not_found():
    response = client.delete("/tasks/9999")
    assert response.status_code == 404
