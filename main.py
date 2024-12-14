from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from controllers.auth import auth_router
from dotenv import load_dotenv
import os

# Load the environment variables
env = os.getenv('env', 'localhost')
env_file = f".env.{env}"
load_dotenv(env_file)

# Create the FastAPI app
app = FastAPI()

# Configure CORS
frontend_url = os.getenv("FRONTEND_URL")
origins = [
    frontend_url
]

# Add the CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, 
    allow_credentials=True,  # Allow cookies and credentials
    allow_methods=["*"],     # Allow all HTTP methods
    allow_headers=["*"],     # Allow all headers
)

# Include the authentication controllers
app.include_router(auth_router)