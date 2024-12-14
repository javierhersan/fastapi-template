from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from repositories.database_repository import get_db, create_user, get_user_by_email_or_username, get_user_by_email, verify_password
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from repositories.auth_repository import create_access_token, verify_token

# Create the router instance
auth_router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

class SignupRequest(BaseModel):
    username: str
    email: str
    password: str

class SignupResponse(BaseModel):
    id: int
    username: str
    email: str
    access_token: str
    token_type: str

@auth_router.post("/signup", response_model=SignupResponse)
def signup(user: SignupRequest, db: Session = Depends(get_db)):
    # Check if the email or username is already registered
    existing_user = get_user_by_email_or_username(db, user.email, user.username)
    if existing_user:
        raise HTTPException(status_code=400, detail="Username or email is already registered")
    # Create the user
    new_user = create_user(db, user.username, user.email, user.password)
    # Create a JWT token for the authenticated user
    access_token = create_access_token(data={"sub": user.email})
    return SignupResponse(id=new_user.id, username=new_user.username, email=new_user.email, access_token=access_token, token_type="bearer")

# Login Route - Issue JWT token if login is successful
@auth_router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = get_user_by_email(db, form_data.username)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid username or password")
    
    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid username or password")
    
    # Create a JWT token for the authenticated user
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer", "user_name": user.username, "user_mail": user.email}

class TokenResponse(BaseModel):
    message: str
    token_payload: dict

# Protected route - Requires a valid JWT token
@auth_router.get("/", response_model=TokenResponse)
async def root(token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    print(payload)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    print(payload)
    return {"message": "Hello World", "token_payload": payload}
