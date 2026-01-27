from math import floor

from fastapi import FastAPI, Request, Form, Response, Cookie, UploadFile, File, HTTPException,Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from requests_oauthlib import OAuth2Session
from fastapi.staticfiles import StaticFiles

from sqlalchemy import or_

from pathlib import Path
import os, uuid, shutil, time, json

from PIL import Image, ImageStat

import db_tools.db_reader as dbr
import db_tools.db_inserter as dbi
from database import engine, SessionLocal
from models import Base, User, Book, AdminLog

# -------------------- SETUP --------------------
Base.metadata.create_all(bind=engine)
app = FastAPI()
frontend = Jinja2Templates(directory="frontend")
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_email_list(raw: str) -> list[str]:
    if not raw:
        return []
    parts = raw.replace(";", ",").replace("\n", ",").split(",")
    return [p.strip().lower() for p in parts if p.strip()]


# -------------------- CONFIG --------------------
# No secrets.json on Azure: configure via environment variables.
# - GOOGLE_CLIENT_ID
# - GOOGLE_CLIENT_SECRET
# - GOOGLE_REDIRECT_URI (optional)
# - ADMIN_EMAILS (optional, comma-separated)
USE_HTTPS = _env_bool("USE_HTTPS", True)
PROTOCOL = "https" if USE_HTTPS else "http"
HOST = os.getenv("HOST") or os.getenv("WEBSITE_HOSTNAME") or "localhost"

DEFAULT_REDIRECT_URI = f"{PROTOCOL}://{HOST}/auth/callback"

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "").strip() or DEFAULT_REDIRECT_URI

admin_emails = _parse_email_list(os.getenv("ADMIN_EMAILS", ""))
ACTIONS = {
    0: 'add',
    1: 'remove',
}

AUTHORIZATION_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = ["https://www.googleapis.com/auth/userinfo.email", "openid"]

ALLOWED_DOMAIN = os.getenv("ALLOWED_DOMAIN", "levi.edu.it").strip().lower()
SESSION_TTL = 3600
EMAIL_CHECK = False
ALL_ADMINS = True
sessions = {}
oauth2_sessions = {}

UPLOAD_DIR = Path("frontend/static/assets/covers/")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# -------------------- HELPERS --------------------
def is_allowed_email(email: str) -> bool:
    email = email.lower()
    return email.endswith(f"@{ALLOWED_DOMAIN}") or email in admin_emails

def get_session_email(session_id: str):
    if not session_id:
        return None
    session = sessions.get(session_id)
    if not session:
        return None
    if time.time() - session["created"] > SESSION_TTL:
        sessions.pop(session_id, None)
        return None
    return session["email"]

def average_color(image_path: Path):
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        stat = ImageStat.Stat(img)
        r, g, b = stat.mean
        r, g, b = int(r * 0.8), int(g * 0.8), int(b * 0.8)
        return f"rgb({r}, {g}, {b})"

async def save_cover(file: UploadFile):
    if not file or not file.filename:
        return "static/assets/placeholder_cover.png"

    ext = file.filename.split(".")[-1]
    filename = f"book_{uuid.uuid4().hex}.{ext}"
    filepath = UPLOAD_DIR / filename
    with filepath.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    return f"static/assets/covers/{filename}"

# -------------------- ROUTES --------------------
@app.get("/", response_class=HTMLResponse)
def homepage(
    request: Request,
    page: int = 1,
    q: str | None = Query(default=None),
    session_id: str = Cookie(None)
):
    email = get_session_email(session_id)
    if not email:
        return RedirectResponse(url="/login")

    BOOKS_PER_PAGE = 30
    offset = (page - 1) * BOOKS_PER_PAGE
    db = SessionLocal()

    query = db.query(Book)

    if q:
        query = query.filter(
            or_(
                Book.id.ilike(f"%{q}%"),
                Book.title.ilike(f"%{q}%"),
                Book.author.ilike(f"%{q}%")
            )
        )

    books = (
        query
        .order_by(Book.id)
        .offset(offset)
        .limit(BOOKS_PER_PAGE)
        .all()
    )

    # Get the current user
    user = db.query(User).filter(User.email == email).first()

    for book in books:
        cover_path = Path("frontend") / book.cover
        if cover_path.exists():
            book.avg_color = average_color(cover_path)
        else:
            book.avg_color = "rgb(44, 44, 44)"

        # Flags for frontend
        book.is_borrowed = book.lent is not None
        book.is_mine = user.id == book.lent if book.is_borrowed else False

    db.close()

    return frontend.TemplateResponse(
        "home.html",
        {
            "request": request,
            "logged_in": True,
            "email": email,
            "books": books,
            "page": page,
            "total_pages": floor(len(books)/BOOKS_PER_PAGE),
            "q": q
        }
    )

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return frontend.TemplateResponse("login.html", {"request": request})

@app.get("/returnbookpage", response_class=HTMLResponse)
def returnbook_page(request: Request, session_id: str = Cookie(None)):
    email = get_session_email(session_id)
    if not email:
        return RedirectResponse(url="/login")

    db = SessionLocal()

    user = db.query(User).filter(User.email == email).first()

    book = None

    if user and user.borrowing:
        book = db.query(Book).filter(Book.id == user.borrowing).first()

        if book:
            cover_path = Path("frontend") / book.cover
            if cover_path.exists():
                book.avg_color = average_color(cover_path)
            else:
                book.avg_color = "rgb(44, 44, 44)"

    db.close()

    if not book:
        class PlaceholderBook:
            id = None
            title = "Book Title"
            author = "Book Author"
            cover = "static/assets/placeholder_cover.png"
            avg_color = "rgb(44, 44, 44)"

        book = PlaceholderBook()

    return frontend.TemplateResponse(
        "returnbook.html",
        {
            "request": request,
            "logged_in": True,
            "email": email,
            "book": book
        }
    )

@app.post("/returnbook", response_class=JSONResponse)
def return_book(book_id: int = Query(...), session_id: str = Cookie(None)):
    email = get_session_email(session_id)
    if not email:
        return RedirectResponse(url="/login")

    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        db.close()
        return JSONResponse({"success": False, "message": "Utente non trovato."})

    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        db.close()
        return JSONResponse({"success": False, "message": "Libro non trovato."})

    if user.borrowing != book.id:
        db.close()
        return JSONResponse({"success": False, "message": "Non possiedi questo libro."})

    book.lent = None
    user.borrowing = None
    db.commit()

    dbi.log_action(db, user_email=email, action=4, book=book)

    db.close()

    return JSONResponse({"success": True, "message": "Libro restituito."})

@app.get("/login/redirect")
def login_redirect():
    google = OAuth2Session(CLIENT_ID, scope=SCOPE, redirect_uri=REDIRECT_URI)
    authorization_url, state = google.authorization_url(AUTHORIZATION_BASE_URL, access_type="offline")
    oauth2_sessions[state] = google
    return RedirectResponse(authorization_url)

@app.get("/auth/callback")
def callback(response: Response, request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    google = oauth2_sessions.pop(state)
    token = google.fetch_token(TOKEN_URL, client_secret=CLIENT_SECRET, code=code)
    user_info = google.get("https://www.googleapis.com/oauth2/v2/userinfo").json()
    email = user_info["email"]
    is_admin = email.lower() in admin_emails or ALL_ADMINS

    if is_allowed_email(email) or not EMAIL_CHECK:
        db = SessionLocal()
        dbi.add_entry(db, email)
        db.close()

        session_id = str(uuid.uuid4())
        sessions[session_id] = {"email": email, "admin": is_admin, "created": time.time()}

        response = RedirectResponse(url="/")
        response.set_cookie("session_id", session_id, max_age=SESSION_TTL, httponly=True, samesite="lax", secure=False)
        return response
    return RedirectResponse(url="/loginrejected")

@app.get("/loginrejected", response_class=HTMLResponse)
def login_rejected(request: Request):
    return frontend.TemplateResponse("loginrejected.html", {"request": request})

@app.get("/adminpanel", response_class=HTMLResponse)
def admin_panel(request: Request, session_id: str = Cookie(None)):
    if not session_id or session_id not in sessions or not sessions[session_id].get("admin"):
        return RedirectResponse(url="/login")

    admins = admin_emails

    db = SessionLocal()
    logs = db.query(AdminLog).order_by(AdminLog.timestamp.asc()).all()
    db.close()

    return frontend.TemplateResponse(
        "adminpanel.html",
        {
            "request": request,
            "logs": logs,
            "admins": admins,
        }
    )


@app.get("/adminpanel/getbook")
def get_book(request: Request, id: int, session_id: str = Cookie(None)):
    email = get_session_email(session_id)
    if not email:
        raise HTTPException(status_code=401, detail="Not logged in")
    db = SessionLocal()
    book = db.query(Book).filter(Book.id == id).first()
    db.close()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    return JSONResponse({
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "cover": book.cover
    })

@app.post("/adminpanel/addbook")
async def add_book(
    request: Request,
    title: str = Form(...),
    author: str = Form(...),
    cover: UploadFile | None = File(None)
):
    session_id = request.cookies.get("session_id")
    email = get_session_email(session_id)
    if not email:
        return RedirectResponse(url="/login")
    if not session_id or session_id not in sessions or not sessions[session_id].get("admin"):
        raise HTTPException(status_code=403, detail="Access denied")

    db = SessionLocal()
    cover_path = await save_cover(cover)
    dbi.add_entry(db, title, user_table=False, author=author, cover=cover_path)

    new_book = db.query(Book).filter(Book.title == title, Book.author == author).order_by(Book.id.desc()).first()

    dbi.log_action(db, user_email=email, action=1, book=new_book)

    db.close()

    return JSONResponse({"success": True, "cover": cover_path})

@app.post("/adminpanel/removebook")
async def remove_book(
    request: Request,
    id: int = Form(...),
):
    session_id = request.cookies.get("session_id")
    email = get_session_email(session_id)
    if not email:
        return RedirectResponse(url="/login")
    if not session_id or session_id not in sessions or not sessions[session_id].get("admin"):
        raise HTTPException(status_code=403, detail="Access denied")

    db = SessionLocal()

    book = db.query(Book).filter(Book.id == id).first()
    if book:
        dbi.remove_entry(db, id, user_table=False)
        dbi.log_action(db, user_email=email, action=2, book=book)

    db.close()
    return JSONResponse({"success": True})

@app.get("/logout")
def logout(response: Response, session_id: str = Cookie(None)):
    if session_id in sessions:
        sessions.pop(session_id)
    response = RedirectResponse(url="/")
    response.delete_cookie("session_id")
    return response

@app.get("/borrow")
def borrow_book(request: Request, book_id: int, session_id: str = Cookie(None)):
    email = get_session_email(session_id)
    if not email:
        return RedirectResponse(url="/login")

    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    book = db.query(Book).filter(Book.id == book_id).first()
    if not user or not book:
        db.close()
        return {"success": False, "message": "Libro o utente non trovato"}

    if user.borrowing is not None or book.lent is not None:
        db.close()
        return {"success": False, "message": "Il libro non è stato prenotato"}

    user.borrowing = book.id
    book.lent = user.id
    db.commit()

    dbi.log_action(db, user_email=email, action=3, book=book)

    db.close()
    return RedirectResponse(url="/")

@app.post("/adminpanel/adminchange")
def change_admin(
    subject: str = Form(...),
    action: int = Form(...),
    session_id: str = Cookie(None)
):
    email = get_session_email(session_id)
    if not email:
        return RedirectResponse(url="/login")
    if not session_id or session_id not in sessions or not sessions[session_id].get("admin"):
        raise HTTPException(status_code=403, detail="Access denied")

    db = SessionLocal()
    dbi.update_admin(email, subject, action, db)
    db.close()

    return JSONResponse({"success": True})
