"""应用内反馈接口测试：multipart 提交、截图校验、频控与邮件状态回写。"""
import asyncio
import io

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers, UploadFile

from backend.app.api.v1 import feedback
from backend.app.database import Base
from backend.app.models import Feedback, FeedbackImage


def _make_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'feedback_test.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _upload(name: str, data: bytes, mime: str = "image/png") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(data),
        filename=name,
        headers=Headers({"content-type": mime}),
    )


def _submit(db, *, kind="bug", content="切换 Codex 后模型未生效", contact="",
            include_log="0", images=None):
    return asyncio.run(feedback.create_feedback(
        kind=kind, content=content, contact=contact,
        include_log=include_log, images=images, db=db,
    ))


def _fake_mail(monkeypatch, sent: bool):
    calls = []

    def _send(fb_id, *args, **kwargs):
        calls.append(fb_id)
        return sent

    monkeypatch.setattr(feedback.mail, "send_feedback_mail", _send)
    return calls


def test_create_feedback_saves_and_reports_emailed(tmp_path, monkeypatch):
    calls = _fake_mail(monkeypatch, sent=True)
    Session = _make_session(tmp_path)
    with Session() as db:
        out = _submit(db, content="  描述前后空白  ", contact=" a@b.com ",
                      images=[_upload("shot.png", b"\x89PNG fake")])
        assert out.id > 0
        assert out.emailed is True
        row = db.execute(select(Feedback)).scalar_one()
        assert row.kind == "bug"
        assert row.content == "描述前后空白"
        assert row.contact == "a@b.com"
        assert row.emailed is True
        assert "a4api 版本" in row.env_info
        assert row.log_excerpt == ""
        imgs = db.execute(select(FeedbackImage)).scalars().all()
        assert len(imgs) == 1
        assert imgs[0].seq == 1
        assert imgs[0].data == b"\x89PNG fake"
        assert calls == [out.id]


def test_include_log_attaches_tail(tmp_path, monkeypatch):
    _fake_mail(monkeypatch, sent=True)
    log_file = tmp_path / "a4api.log"
    log_file.write_text("\n".join(f"line-{i}" for i in range(1, 201)) + "\n", encoding="utf-8")
    monkeypatch.setattr(feedback, "log_path", lambda: log_file)

    Session = _make_session(tmp_path)
    with Session() as db:
        _submit(db, include_log="1")
        row = db.execute(select(Feedback)).scalar_one()
        tail = row.log_excerpt.splitlines()
        assert len(tail) == 120
        assert tail[-1] == "line-200"


def test_rejects_oversize_or_bad_mime_or_too_many(tmp_path, monkeypatch):
    _fake_mail(monkeypatch, sent=True)
    Session = _make_session(tmp_path)
    with Session() as db:
        with pytest.raises(HTTPException) as ei:  # 超过 1MB
            _submit(db, images=[_upload("big.png", b"x" * (feedback.FEEDBACK_IMAGE_MAX_BYTES + 1))])
        assert ei.value.status_code == 400
        with pytest.raises(HTTPException) as ei:  # 非图片
            _submit(db, images=[_upload("evil.png", b"data", mime="application/zip")])
        assert ei.value.status_code == 400
        with pytest.raises(HTTPException) as ei:  # 超过 10 张
            _submit(db, images=[_upload(f"{i}.png", b"x") for i in range(feedback.FEEDBACK_MAX_IMAGES + 1)])
        assert ei.value.status_code == 400


def test_empty_content_rejected(tmp_path):
    Session = _make_session(tmp_path)
    with Session() as db:
        with pytest.raises(HTTPException) as ei:
            _submit(db, content="   ")
        assert ei.value.status_code == 400


def test_daily_limit(tmp_path, monkeypatch):
    _fake_mail(monkeypatch, sent=False)
    monkeypatch.setattr(feedback, "DAILY_LIMIT", 2)
    Session = _make_session(tmp_path)
    with Session() as db:
        _submit(db)
        _submit(db)
        with pytest.raises(HTTPException) as ei:
            _submit(db)
        assert ei.value.status_code == 429


def test_mail_failure_still_saves(tmp_path, monkeypatch):
    _fake_mail(monkeypatch, sent=False)
    Session = _make_session(tmp_path)
    with Session() as db:
        out = _submit(db)
        assert out.emailed is False
        row = db.execute(select(Feedback)).scalar_one()
        assert row.emailed is False


def test_context_fields():
    ctx = feedback.feedback_context()
    assert ctx["version"]
    assert ctx["platform"]
    assert isinstance(ctx["frozen"], bool)
    assert ctx["log_path"].endswith("a4api.log")
