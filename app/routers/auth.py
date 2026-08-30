from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select

from ..deps import SESSION_COOKIE, SESSION_MAX_AGE, current_user, get_db, home_for, make_session
from ..i18n import DEFAULT_LANG, LANGS, LANG_COOKIE
from ..models import User
from ..security import verify_password
from ..ui import render

router = APIRouter()


@router.get("/lang/{code}")
def set_lang(code: str, request: Request):
    """Switch UI language (zh/en) via cookie and return to the previous page."""
    lang = code if code in LANGS else DEFAULT_LANG
    referer = request.headers.get("referer") or "/"
    response = RedirectResponse(referer, status_code=303)
    response.set_cookie(LANG_COOKIE, lang, max_age=365 * 24 * 3600, samesite="lax")
    return response


@router.get("/login")
def login_page(request: Request, user: User | None = Depends(current_user)):
    if user:
        return RedirectResponse(home_for(user), status_code=303)
    return render(request, "login.html", user=None)


@router.post("/login")
def login(request: Request, login_id: str = Form(...), password: str = Form(...),
          db=Depends(get_db)):
    user = db.scalars(
        select(User).where(or_(User.employee_id == login_id, User.email == login_id))
    ).first()
    if user and user.is_active and verify_password(password, user.password_hash):
        response = RedirectResponse(home_for(user), status_code=303)
        response.set_cookie(SESSION_COOKIE, make_session(user.id), max_age=SESSION_MAX_AGE,
                            httponly=True, samesite="lax")
        return response
    return render(request, "login.html", user=None, error=True)


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


def flash(url: str, msg: str) -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    return RedirectResponse(f"{url}{sep}msg={quote(msg)}", status_code=303)
