import math
import os
from datetime import datetime, timedelta, timezone

import psycopg
from jose import JWTError, jwt
from litestar import Litestar, Request, get, post, put
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_400_BAD_REQUEST, HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
from passlib.context import CryptContext
from psycopg.rows import dict_row
from pydantic import BaseModel

from domain import in_closed_range

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54395/spectrum")
SECRET = os.environ.get("JWT_SECRET", "spectrum-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "calibrator": {"role": "writer", "password_hash": pwd.hash("calib123456")},
    "inspector": {"role": "reader", "password_hash": pwd.hash("insp123456")},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id serial PRIMARY KEY,
    lamp text NOT NULL,
    nominal_nm double precision NOT NULL,
    measured_nm double precision NOT NULL,
    status text NOT NULL,
    verdict text NOT NULL DEFAULT '',
    reason text NOT NULL DEFAULT '',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS range_settings (
    id integer PRIMARY KEY DEFAULT 1,
    min_nm double precision NOT NULL,
    max_nm double precision NOT NULL,
    updated_by text NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT range_settings_singleton CHECK (id = 1)
);
CREATE TABLE IF NOT EXISTS nominal_history (
    id serial PRIMARY KEY,
    job_id integer NOT NULL REFERENCES jobs(id),
    nominal_nm double precision NOT NULL,
    event text NOT NULL,
    recorded_by text NOT NULL,
    recorded_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS nominal_history_job_idx ON nominal_history(job_id);
"""

DEFAULT_RANGE_MIN = 500.0
DEFAULT_RANGE_MAX = 600.0


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


class LoginIn(BaseModel):
    username: str
    password: str


class JobIn(BaseModel):
    lamp: str
    nominal_nm: float
    measured_nm: float


class RangeIn(BaseModel):
    min_nm: float
    max_nm: float


class NominalEditIn(BaseModel):
    nominal_nm: float


def user_from_request(request: Request) -> dict:
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = jwt.decode(auth[7:], SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="无效令牌") from exc
    if payload.get("sub") not in USERS:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="无效令牌")
    return {"username": payload["sub"], "role": payload.get("role")}


def fetch_range(conn) -> dict:
    row = conn.execute(
        "SELECT id, min_nm, max_nm, updated_by, updated_at FROM range_settings WHERE id = 1"
    ).fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="量程区间未设置")
    return row


def check_nominal_in_range(nominal: float, rng: dict) -> None:
    """闭区间卡量程：nominal 落在 [min, max] 之外则拒收。"""
    if not in_closed_range(nominal, rng["min_nm"], rng["max_nm"]):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"标称 {nominal} nm 超出量程闭区间 [{rng['min_nm']}, {rng['max_nm']}] nm，拒收",
        )


def record_history(conn, job_id: int, nominal: float, event: str, username: str) -> None:
    """标称原文快照进履历；履历只追加，从不改写旧行。"""
    conn.execute(
        """
        INSERT INTO nominal_history(job_id, nominal_nm, event, recorded_by, recorded_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (job_id, nominal, event, username, datetime.now(timezone.utc)),
    )


@get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "spectrum-wavelength-desk"}


@post("/api/login")
async def login(data: LoginIn) -> dict:
    u = USERS.get(data.username)
    if not u or not pwd.verify(data.password, u["password_hash"]):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    token = jwt.encode(
        {
            "sub": data.username,
            "role": u["role"],
            "exp": datetime.now(timezone.utc) + timedelta(hours=12),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"access_token": token, "role": u["role"], "username": data.username}


@get("/api/range")
async def get_range(request: Request) -> dict:
    user_from_request(request)
    with connect() as conn:
        return dict(fetch_range(conn))


@put("/api/range")
async def put_range(request: Request, data: RangeIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可设置区间")
    if not (math.isfinite(data.min_nm) and math.isfinite(data.max_nm)):
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="区间端点必须是有限数值")
    if data.min_nm > data.max_nm:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="区间下限不能大于上限")
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO range_settings(id, min_nm, max_nm, updated_by, updated_at)
            VALUES (1, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET min_nm = EXCLUDED.min_nm,
                max_nm = EXCLUDED.max_nm,
                updated_by = EXCLUDED.updated_by,
                updated_at = EXCLUDED.updated_at
            RETURNING id, min_nm, max_nm, updated_by, updated_at
            """,
            (data.min_nm, data.max_nm, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
        return dict(row)


@get("/api/nominal-history")
async def list_nominal_history(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT h.id, h.job_id, j.lamp, h.nominal_nm, h.event, h.recorded_by, h.recorded_at
            FROM nominal_history h
            JOIN jobs j ON j.id = h.job_id
            ORDER BY h.id DESC
            """
        ).fetchall()
        return list(rows)


@get("/api/jobs")
async def list_jobs(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, lamp, nominal_nm, measured_nm, status, verdict, reason, created_by FROM jobs ORDER BY id DESC"
        ).fetchall()
        return list(rows)


@get("/api/jobs/{job_id:int}")
async def get_job(request: Request, job_id: int) -> dict:
    user_from_request(request)
    with connect() as conn:
        row = conn.execute(
            "SELECT id, lamp, nominal_nm, measured_nm, status, verdict, reason, created_by FROM jobs WHERE id = %s",
            (job_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        return dict(row)


@post("/api/jobs")
async def create_job(request: Request, data: JobIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可提交")
    if not (math.isfinite(data.nominal_nm) and math.isfinite(data.measured_nm)):
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="波长必须是有限数值")
    with connect() as conn:
        rng = fetch_range(conn)
        check_nominal_in_range(data.nominal_nm, rng)
        row = conn.execute(
            """
            INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, created_at)
            VALUES (%s,%s,%s,'pending','','',%s,%s) RETURNING id
            """,
            (data.lamp.strip(), data.nominal_nm, data.measured_nm, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        record_history(conn, row["id"], data.nominal_nm, "送检", user["username"])
        conn.commit()
        return {"id": row["id"], "status": "pending"}


@put("/api/jobs/{job_id:int}/nominal")
async def edit_nominal(request: Request, job_id: int, data: NominalEditIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可修改标称")
    if not math.isfinite(data.nominal_nm):
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="标称必须是有限数值")
    with connect() as conn:
        exists = conn.execute("SELECT id FROM jobs WHERE id = %s", (job_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="任务不存在")
        rng = fetch_range(conn)
        check_nominal_in_range(data.nominal_nm, rng)
        row = conn.execute(
            """
            UPDATE jobs SET nominal_nm = %s WHERE id = %s
            RETURNING id, lamp, nominal_nm, measured_nm, status, verdict, reason, created_by
            """,
            (data.nominal_nm, job_id),
        ).fetchone()
        record_history(conn, job_id, data.nominal_nm, "改标称", user["username"])
        conn.commit()
        return dict(row)


def on_startup() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)
        now = datetime.now(timezone.utc)
        n = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        if n == 0:
            rows = conn.execute(
                """
                INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, created_at)
                VALUES
                ('氦灯-587', 587.56, 587.50, 'done', '合格', '偏差 0.0600 nm 在允差内', 'seed', %s),
                ('汞灯-546', 546.07, 546.30, 'done', '超差', '偏差 0.2300 nm 超过允差 0.08', 'seed', %s)
                RETURNING id, nominal_nm
                """,
                (now, now),
            ).fetchall()
            for r in rows:
                record_history(conn, r["id"], r["nominal_nm"], "送检", "seed")
        conn.execute(
            """
            INSERT INTO range_settings(id, min_nm, max_nm, updated_by, updated_at)
            VALUES (1, %s, %s, 'seed', %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (DEFAULT_RANGE_MIN, DEFAULT_RANGE_MAX, now),
        )
        conn.commit()


app = Litestar(
    route_handlers=[
        health,
        login,
        get_range,
        put_range,
        list_nominal_history,
        list_jobs,
        get_job,
        create_job,
        edit_nominal,
    ],
    on_startup=[on_startup],
)
