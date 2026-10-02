import logging

import mysql.connector
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mysql.connector import errorcode

from config import CORS_ORIGINS
from routes import courses, registration, students, waitlist

logger = logging.getLogger(__name__)

app = FastAPI()

# CORS: only the local frontend may call the API from a browser.
# No cookies/auth headers are used, so allow_credentials stays off.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

# No URL prefixes: every path stays exactly as the frontend calls it.
app.include_router(students.router)
app.include_router(courses.router)
app.include_router(registration.router)
app.include_router(waitlist.router)


# ------------------ ERROR HANDLING ------------------
# Every error response has the same shape: {"detail": "<message>"}.
# HTTPException (404/409/400 raised by endpoints) already produces it.

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # FastAPI's default is 422 with a list of error objects. Return one
    # readable 400 message instead so the frontend can show it as-is.
    error = exc.errors()[0]
    field = ".".join(str(part) for part in error["loc"] if part != "body") or "request body"
    return JSONResponse(status_code=400, content={"detail": f"Invalid {field}: {error['msg']}"})


@app.exception_handler(mysql.connector.IntegrityError)
async def integrity_error_handler(request: Request, exc: mysql.connector.IntegrityError):
    if exc.errno == errorcode.ER_DUP_ENTRY:
        return JSONResponse(status_code=409, content={"detail": "This record already exists"})
    if exc.errno == errorcode.ER_NO_REFERENCED_ROW_2:
        return JSONResponse(status_code=400, content={"detail": "A referenced record does not exist"})
    return JSONResponse(status_code=400, content={"detail": "Invalid data"})


TRANSIENT_DB_ERRORS = {errorcode.ER_LOCK_WAIT_TIMEOUT, errorcode.ER_LOCK_DEADLOCK}


@app.exception_handler(mysql.connector.Error)
async def database_error_handler(request: Request, exc: mysql.connector.Error):
    # Log the real error server-side; never send SQL details to the client.
    logger.error("Database error on %s %s: %s", request.method, request.url.path, exc)
    if (
        isinstance(exc, (mysql.connector.InterfaceError, mysql.connector.OperationalError))
        or exc.errno in TRANSIENT_DB_ERRORS
    ):
        return JSONResponse(
            status_code=503,
            content={"detail": "Database is unavailable or busy, please try again"},
        )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
