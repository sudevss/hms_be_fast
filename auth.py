from datetime import timedelta, datetime
from typing import Optional

from sqlalchemy.orm import Session

from fastapi import FastAPI, Depends, HTTPException, APIRouter
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from starlette import status

import model
from database import engine, SessionLocal, get_db

SECRET_KEY = "KlgH6AzYDeZeGwD288to79I3vTHT8wp7"
ALGORITHM = "HS256"

oauth2_bearer = OAuth2PasswordBearer(tokenUrl="/admin/token")
model.Base.metadata.create_all(bind=engine)

router = FastAPI()

router = APIRouter(
    prefix="/admin",
    responses={404: {"description": "Not found"}}
)


class ui_admin(BaseModel):
    username: str = Field(default=None)
    password: str = Field(default=None)

    class Config: {
        "user_demo": {
            "username": "anoop",
            "password": "123"
        }
    }


becrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def pass_hash_converter(password):
    return becrypt_context.hash(password)


def verify_password(password, hash_pass):
    return becrypt_context.verify(password, hash_pass)


def authenticate_admin(admin_username: str, password: str, db):
    admin = db.query(model.Admin). \
        filter(model.Admin.username == admin_username) \
        .first()
    if not admin:
        return False
    if not verify_password(password, admin.hashed_pass):
        return False
    return admin


async def get_current_user(token: str = Depends(oauth2_bearer)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None or id is None:
            raise get_user_exception()
        return {"username": username}
    except JWTError:
        raise get_user_exception()


def create_access_token(username: str,
                        expires_delta: Optional[timedelta] = None):
    encode = {"sub": username}
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=20)
    encode.update({"exp": expire})
    return jwt.encode(encode, SECRET_KEY, algorithm=ALGORITHM)


@router.post("/add", tags=["admin"])
async def create_newadmin(newadmin: ui_admin, db: Session = Depends(get_db)):
    admin_value = model.Admin()

    admin_value.username = newadmin.username
    hash_pass = pass_hash_converter(newadmin.password)
    admin_value.hashed_pass = hash_pass
    db.add(admin_value)
    db.commit()

    return {
        "result": "Successful",
        "new user": "added"
    }


@router.post("/token", tags=["admin"])
async def get_token(formdata: OAuth2PasswordRequestForm = Depends(),
                    db: Session = Depends(get_db)):
    admin = authenticate_admin(formdata.username, formdata.password, db)
    if not admin:
        raise token_exception()
    token_expires = timedelta(minutes=20)
    token = create_access_token(admin.username, expires_delta=token_expires)
    return dict(access_token=token, token_type="Bearer")







def token_exception():
    token_exception_response = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )
    return token_exception_response


def get_user_exception():
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    return credentials_exception


@router.delete("/delete-admin", tags=["admin"])
async def get_token(formdata: OAuth2PasswordRequestForm = Depends(),
                    db: Session = Depends(get_db)):
    admin = authenticate_admin(formdata.username, formdata.password, db)
    if not admin:
        raise token_exception()
    get_admin=db.query(model.Admin).filter(formdata.username==model.Admin.username).first()
    db.delete(get_admin)
    db.commit()
    return {
        "result": "Successful",
        "Admin": "removed"
    }


