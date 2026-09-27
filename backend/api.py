import os
from datetime import datetime, timedelta, timezone

import psycopg
from jose import JWTError, jwt
from litestar import Litestar, Request, get, patch, post, put
from litestar.exceptions import HTTPException
from litestar.status_codes import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
)
from passlib.context import CryptContext
from psycopg.rows import dict_row
from pydantic import BaseModel

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
    id integer PRIMARY KEY,
    lower_nm double precision NOT NULL,
    upper_nm double precision NOT NULL,
    updated_by text NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS nominal_history (
    id serial PRIMARY KEY,
    job_id integer NOT NULL,
    nominal_nm double precision NOT NULL,
    event text NOT NULL,
    recorded_by text NOT NULL,
    recorded_at timestamptz NOT NULL
);
"""


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
    lower_nm: float
    upper_nm: float


class NominalEditIn(BaseModel):
    nominal_nm: float


def current_range(conn) -> dict:
    row = conn.execute(
        "SELECT lower_nm, upper_nm FROM range_settings WHERE id = 1"
    ).fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="量程区间未初始化")
    return row


def check_nominal_in_range(conn, nominal_nm: float) -> dict:
    """标称波长必须落在量程闭区间 [lower, upper] 内，区间外拒收。"""
    rng = current_range(conn)
    if not (rng["lower_nm"] <= nominal_nm <= rng["upper_nm"]):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=(
                f"标称 {nominal_nm} nm 超出量程闭区间 "
                f"[{rng['lower_nm']}, {rng['upper_nm']}]，拒收"
            ),
        )
    return rng


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
        row = conn.execute(
            "SELECT lower_nm, upper_nm, updated_by, updated_at FROM range_settings WHERE id = 1"
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="量程区间未设置")
        return dict(row)


@put("/api/range")
async def put_range(request: Request, data: RangeIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可设置量程区间")
    if data.lower_nm > data.upper_nm:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="区间下限不能大于上限")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO range_settings(id, lower_nm, upper_nm, updated_by, updated_at)
            VALUES (1, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET lower_nm = EXCLUDED.lower_nm,
                upper_nm = EXCLUDED.upper_nm,
                updated_by = EXCLUDED.updated_by,
                updated_at = EXCLUDED.updated_at
            """,
            (data.lower_nm, data.upper_nm, user["username"], datetime.now(timezone.utc)),
        )
        conn.commit()
    return {"lower_nm": data.lower_nm, "upper_nm": data.upper_nm}


@get("/api/nominal-history")
async def list_nominal_history(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, job_id, nominal_nm, event, recorded_by, recorded_at
            FROM nominal_history ORDER BY id DESC
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
    with connect() as conn:
        check_nominal_in_range(conn, data.nominal_nm)
        now = datetime.now(timezone.utc)
        row = conn.execute(
            """
            INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, created_at)
            VALUES (%s,%s,%s,'pending','','',%s,%s) RETURNING id
            """,
            (data.lamp.strip(), data.nominal_nm, data.measured_nm, user["username"], now),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO nominal_history(job_id, nominal_nm, event, recorded_by, recorded_at)
            VALUES (%s,%s,'submit',%s,%s)
            """,
            (row["id"], data.nominal_nm, user["username"], now),
        )
        conn.commit()
        return {"id": row["id"], "status": "pending"}


@patch("/api/jobs/{job_id:int}")
async def update_job_nominal(request: Request, job_id: int, data: NominalEditIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可修改标称")
    with connect() as conn:
        exists = conn.execute("SELECT id FROM jobs WHERE id = %s", (job_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="任务不存在")
        check_nominal_in_range(conn, data.nominal_nm)
        now = datetime.now(timezone.utc)
        conn.execute(
            "UPDATE jobs SET nominal_nm = %s WHERE id = %s",
            (data.nominal_nm, job_id),
        )
        conn.execute(
            """
            INSERT INTO nominal_history(job_id, nominal_nm, event, recorded_by, recorded_at)
            VALUES (%s,%s,'edit',%s,%s)
            """,
            (job_id, data.nominal_nm, user["username"], now),
        )
        conn.commit()
        return {"id": job_id, "nominal_nm": data.nominal_nm}


def on_startup() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)
        now = datetime.now(timezone.utc)
        conn.execute(
            """
            INSERT INTO range_settings(id, lower_nm, upper_nm, updated_by, updated_at)
            VALUES (1, 500.0, 600.0, 'seed', %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (now,),
        )
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
                conn.execute(
                    """
                    INSERT INTO nominal_history(job_id, nominal_nm, event, recorded_by, recorded_at)
                    VALUES (%s,%s,'submit','seed',%s)
                    """,
                    (r["id"], r["nominal_nm"], now),
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
        update_job_nominal,
    ],
    on_startup=[on_startup],
)
