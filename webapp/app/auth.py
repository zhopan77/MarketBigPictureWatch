"""
Access control seam.

Today the site is free and open: every visitor is an anonymous user with
access.  The route handlers already depend on `require_access`, so when you
are ready to charge for the service the ONLY things that change are in this
file (plus a login page):

  1. Set MW_AUTH_ENABLED=1.
  2. Implement `get_current_user` to read a session cookie / JWT.
     The easiest batteries-included option is the `fastapi-users` package
     (registration, login, password reset, OAuth).
  3. Implement `user.has_active_subscription`, e.g. by storing a Stripe
     customer id per user and checking subscription status via Stripe
     webhooks (`checkout.session.completed`, `customer.subscription.*`)
     written into your user database.

Nothing in main.py or the templates needs to change for step 1-3 other
than adding the login/billing pages themselves.
"""

from dataclasses import dataclass

from fastapi import HTTPException, Request

from . import settings


@dataclass
class User:
    id: str
    email: str | None = None
    is_authenticated: bool = False
    has_active_subscription: bool = False


ANONYMOUS = User(id="anonymous")


async def get_current_user(request: Request) -> User:
    """Resolve the current visitor.

    TODO(subscriptions): replace the body with real session handling, e.g.:
        token = request.cookies.get("session")
        user = await user_db.get_by_session(token)
        return user or ANONYMOUS
    """
    return ANONYMOUS


async def require_access(request: Request) -> User:
    """Gate for content routes.  Free mode: always allows.

    When AUTH_ENABLED is on, only authenticated users with an active
    subscription may view the figures.
    """
    user = await get_current_user(request)
    if not settings.AUTH_ENABLED:
        return user
    if not user.is_authenticated:
        raise HTTPException(status_code=401, detail="Sign in required")
    if not user.has_active_subscription:
        raise HTTPException(status_code=402, detail="Active subscription required")
    return user
