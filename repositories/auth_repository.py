import jwt
from datetime import datetime, timedelta
import time

# Secret key for JWT signing and encoding
SECRET_KEY = "your_jwt_secret_key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Function to create a JWT token
def create_access_token(data: dict[str,str]):
    to_encode = data.copy()
    expire = datetime.now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# # Function to decode the JWT token
# def verify_token(token: str, user_mail: str)-> dict[str,str]:
#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         if payload.get('sub') != user_mail:
#             return False 
#         return payload
#     except jwt.ExpiredSignatureError:
#         return None  # Token expired
#     except jwt.InvalidTokenError:
#         return None  # Invalid token

def verify_token(token: str)-> dict[str,str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None  # Token expired
    except jwt.InvalidTokenError:
        return None  # Invalid token