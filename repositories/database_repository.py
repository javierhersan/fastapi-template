from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Session
from models.container import Container
from models.user import User
from models.base import Base  # Import the shared Base
import hashlib


SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create database tables
# User.metadata.create_all(bind=engine)
# Container.metadata.create_all(bind=engine)
Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Utility to hash passwords
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# Utility to verify if passwords match
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hash_password(plain_password) == hashed_password

# Function to create a new user
def create_user(db: Session, username: str, email: str, password: str):
    hashed_password = hash_password(password)
    new_user = User(username=username, email=email, hashed_password=hashed_password)
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user

# Function to check if a user already exists by email or username
def get_user_by_email_or_username(db: Session, email: str, username: str):
    return db.query(User).filter((User.email == email) | (User.username == username)).first()

# Function to get user by email
def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()

