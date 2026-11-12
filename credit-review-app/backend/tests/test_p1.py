import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app.core.db import engine
from app.main import app
from app.models import Asset, Task, TaskFile


def _login(username: str, password: str) -> tuple[TestClient, str]:
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c, r.json()["csrf_token"]


@pytest.fixture()
def r1():
    return _login("reviewer1", "Review12345")


@pytest.fixture()
def r2():
    return _login("reviewer2", "Review12345")


def test_login_and_me(r1):
    c, _ = r1
    r = c.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "reviewer1"


def test_login_failure():
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"username": "reviewer1", "password": "wrong"})
    assert r.status_code == 401


def test_csrf_required_on_write(r1):
    c, _ = r1
    r = c.post("/api/v1/tasks", json={"customer_role": "borrower"})
    assert r.status_code == 403


def test_role_disabled(r1):
    c, csrf = r1
    r = c.post(
        "/api/v1/tasks",
        json={"customer_role": "guarantor"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 409


def test_task_and_file_isolation(r1, r2):
    c1, csrf1 = r1
    c2, _ = r2

    # reviewer1 建任务
    r = c1.post(
        "/api/v1/tasks",
        json={"customer_role": "borrower"},
        headers={"X-CSRF-Token": csrf1},
    )
    assert r.status_code == 201
    task_id = r.json()["id"]

    try:
        # reviewer1 可见，reviewer2 不可见
        assert c1.get(f"/api/v1/tasks/{task_id}").status_code == 200
        assert c2.get(f"/api/v1/tasks/{task_id}").status_code == 404

        # reviewer1 上传文件
        pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
        r = c1.post(
            f"/api/v1/tasks/{task_id}/files",
            headers={"X-CSRF-Token": csrf1},
            files={"file": ("license.pdf", pdf, "application/pdf")},
        )
        assert r.status_code == 201
        file_id = r.json()["id"]
        asset_id = r.json()["original_asset_id"]

        # reviewer2 不能列文件、不能下载资产
        assert c2.get(f"/api/v1/tasks/{task_id}/files").status_code == 404
        assert c2.get(f"/api/v1/tasks/{task_id}/assets/{asset_id}").status_code == 404
        # reviewer1 能下载
        assert c1.get(f"/api/v1/tasks/{task_id}/assets/{asset_id}").status_code == 200
    finally:
        with Session(engine) as s:
            for f in s.exec(select(TaskFile).where(TaskFile.task_id == task_id)).all():
                s.exec(delete(Asset).where(Asset.file_id == f.id))
                s.delete(f)
            t = s.get(Task, task_id)
            if t:
                s.delete(t)
            s.commit()
