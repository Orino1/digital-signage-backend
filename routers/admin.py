from fastapi import APIRouter, HTTPException, status, Response

from ..dependencies import AdminKeyDep, LoginFormDep, SessionDep
from sqlmodel import select
from ..utils import pwd_context, create_token, TokenType
from ..models.admin import Admin, AdminOutput

router = APIRouter()



@router.post("/login", response_model=AdminOutput, summary="Admin Login",
    description="This endpoint logs in an admin user. The credentials are verified and a JWT token is issued if valid. The token is stored in an HttpOnly cookie.",
    responses={
        200: {
            "description": "Login successful. Admin details and token set in HttpOnly cookie.",
            "content": {
                "application/json": {
                    "example": {
                        "id": 1,
                        "username": "admin_user"
                    }
                }
            }
        },
        401: {
            "description": "Invalid credentials.",
            "content": {"application/json": {"example": {"detail": "check credentials"}}}
        },
    },
    tags=["Authentication"])
def admin_login(login_data: LoginFormDep, session: SessionDep, resonse: Response) -> AdminOutput:
    admin = session.exec(select(Admin).filter_by(username=login_data.username)).first()

    if not admin:
        raise HTTPException(detail="check credentials", status_code=status.HTTP_401_UNAUTHORIZED)
    
    if not pwd_context.verify(login_data.password, admin.password):
        raise HTTPException(detail="check credentials", status_code=status.HTTP_401_UNAUTHORIZED)

    token = create_token(admin.id, TokenType.REFRESH)

    # TODO: handle CORS config via env
    resonse.set_cookie(
        key="TOKEN",
        value=token,
        httponly=True,
    )

    return admin
