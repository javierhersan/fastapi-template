import io
import tarfile
import docker
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session
from models.container import Container
from repositories.database_repository import get_db, get_user_by_email
from controllers.auth import oauth2_scheme
import asyncio
from typing import Optional
from fastapi import UploadFile, File
import base64

from repositories.auth_repository import verify_token

docker_router = APIRouter()

client = docker.from_env()

class StartContainerRequest(BaseModel):
    user_mail: str
    token: str

@docker_router.post("/docker/create-container")
def create_container(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """
    Start a Docker container with the specified image.
    :param image_name: The name of the Docker image to use (e.g., "nginx", "ubuntu")
    """
    try:
        print(token)
        payload = verify_token(token)

        if payload == None: 
            return {"message": "Invalid credentials"}

        IMAGE_NAME = "javierhersan/code-ai"
        print(f"Starting container with image: {IMAGE_NAME}")
        # Pull the image if not available locally
        client.images.pull(IMAGE_NAME)
        # Start a container with the image
        container = client.containers.create(IMAGE_NAME)
        # container = client.containers.run(IMAGE_NAME, detach=True)

        user = get_user_by_email(db, payload.get('sub'))
        if user:
            new_container = Container(
                container_id=container.id, 
                container_name=IMAGE_NAME, 
                user_id=user.id,
                status=container.status
            )
            db.add(new_container)
            db.commit()
            db.refresh(new_container)

        return {"id":new_container.id, "container_id": new_container.id, "container_id": container.id, "container_name": IMAGE_NAME, "user_id":user.id, "status": container.status}
    
    except docker.errors.ImageNotFound:
        raise HTTPException(status_code=404, detail=f"Docker image {IMAGE_NAME} not found.")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting container: {str(e)}")

@docker_router.get("/docker/user-containers")
def list_user_containers(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """
    List all containers associated with a user.
    """
    token_payload = verify_token(token)
    
    if token_payload == None: 
        return {"message": "Invalid credentials"}
    
    user = token_payload.get('sub')
    
    user = get_user_by_email(db, user)
    if user:
        containers = db.query(Container).filter(Container.user_id == user.id).all()
        return {"containers": containers}
    else:
        raise HTTPException(status_code=404, detail="User not found.")

@docker_router.put("/docker/stop-container/{container_id}")
def stop_user_container(container_id: str, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    token_payload = verify_token(token)
    
    if token_payload is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user = token_payload.get('sub')
    user = get_user_by_email(db, user)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    container = db.query(Container).filter(Container.container_id == container_id, Container.user_id == user.id).first()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found or does not belong to the user")
    
    try:
        docker_container = client.containers.get(container.container_id)
        docker_container.stop()
        
        container.status = 'exited'
        db.commit()
        db.refresh(container)
        
        return {"message": "Container deleted successfully"}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Docker container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting container: {str(e)}")
    
@docker_router.put("/docker/start-container/{container_id}")
def start_user_container(container_id: str, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    token_payload = verify_token(token)
    
    if token_payload is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user = token_payload.get('sub')
    user = get_user_by_email(db, user)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    container = db.query(Container).filter(Container.container_id == container_id, Container.user_id == user.id).first()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found or does not belong to the user")
    
    try:
        docker_container = client.containers.get(container.container_id)
        docker_container.start()
        
        container.status = 'running'
        db.commit()
        db.refresh(container)
        
        return {"message": "Container deleted successfully"}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Docker container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting container: {str(e)}")

@docker_router.delete("/docker/delete-container/{container_id}")
def delete_user_container(container_id: str, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """
    Delete a Docker container associated with a user.
    """
    token_payload = verify_token(token)
    
    if token_payload is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user = token_payload.get('sub')
    user = get_user_by_email(db, user)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    container = db.query(Container).filter(Container.container_id == container_id, Container.user_id == user.id).first()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found or does not belong to the user")
    
    try:
        docker_container = client.containers.get(container.container_id)
        docker_container.stop()
        docker_container.remove()
        
        db.delete(container)
        db.commit()
        
        return {"message": "Container deleted successfully"}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Docker container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting container: {str(e)}")

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@docker_router.websocket("/docker-ws/{container_id}")
async def websocket_endpoint(websocket: WebSocket, container_id: str):
    await manager.connect(websocket)
    try:
        container = client.containers.get(container_id) 
        exec_instance = container.exec_run("/bin/sh", stdin=True, stdout=True, stderr=True, tty=True, detach=False, stream=True, socket=True)
        output_stream = exec_instance.output
        data = ''

        async def read_from_container():
            try:
                print("Starting to read from container")
                while True:
                    output = await asyncio.to_thread(output_stream.recv, 4096)
                    if not output:
                        break
                    decoded_output = output.decode('utf-8')
                    print("Output of container: ", decoded_output)
                    print("Data: ", data.strip())
                    if decoded_output.strip() != data.strip():
                        await websocket.send_text(decoded_output)
            except Exception as e:
                print(f"Error reading from container: {e}")

        async def write_to_container(input_data):
            try:
                print("Writing to container: ", input_data)
                await asyncio.to_thread(exec_instance.output.send, input_data.encode('utf-8'))
            except Exception as e:
                print(f"Error writing to container: {e}")

        read_task = asyncio.create_task(read_from_container())
        print("WebSocket connected")
        while True:
            try:
                # Receive data from frontend terminal (xterm)
                data = await websocket.receive_text()
                # Send the received data to the Docker container
                await write_to_container(data)
            except WebSocketDisconnect:
                manager.disconnect(websocket)
                break

        # Clean up when WebSocket disconnects
        read_task.cancel()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        await manager.disconnect(websocket)

class FileSystemItem(BaseModel):
    name: str
    path: str
    parentPath: Optional[str]
    kind: str
    handle: Optional[str]
    content: Optional[str]
    isSaved: bool
    isOpen: bool

@docker_router.get("/docker/filesystem/{container_id}")
def get_filesystem(container_id: str, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    token_payload = verify_token(token)
    if token_payload is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user = token_payload.get('sub')
    user = get_user_by_email(db, user)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    container = db.query(Container).filter(Container.container_id == container_id, Container.user_id == user.id).first()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found or does not belong to the user")
    
    try:
        docker_container = client.containers.get(container.container_id)
        
        if docker_container.status != 'running':
            raise HTTPException(status_code=400, detail="Container is not running")
        
        # Execute the command to list all files and directories
        exec_result_directories = docker_container.exec_run("find /app -type d -exec echo {} \\;", tty=True)
        exec_result_files = docker_container.exec_run("find /app -type f -exec echo {} \\;", tty=True)

        if exec_result_directories.exit_code != 0 and exec_result_files.exit_code != 0:
            raise HTTPException(status_code=500, detail="Error retrieving file system structure")
        
        directories_output = exec_result_directories.output.decode("utf-8").strip().split("\n")
        files_output = exec_result_files.output.decode("utf-8").strip().split("\n")
        
        files = []
        for item in directories_output:
            item = item.strip() 
            parent_path = '/'.join(item.split('/')[:-1]) or None
            files.append(FileSystemItem(
                name=item.split('/')[-1],
                path=item,
                parentPath=parent_path,
                kind='directory',
                handle=None,
                content=None,
                isSaved=True,
                isOpen=False
            ))
        for item in files_output:
            item = item.strip() 
            parent_path = '/'.join(item.split('/')[:-1]) or None
            files.append(FileSystemItem(
                name=item.split('/')[-1],
                path=item,
                parentPath=parent_path,
                kind= 'file',
                handle=None,
                content=None,
                isSaved=True,
                isOpen=False
            ))
        
        print(files)
        return files

    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Docker container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving file system structure: {str(e)}")

@docker_router.get("/docker/filesystem/{container_id}/{path}")
def get_container_folder_content(container_id: str, path: str, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):

    token_payload = verify_token(token)
    if token_payload is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user = token_payload.get('sub')
    user = get_user_by_email(db, user)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    container = db.query(Container).filter(Container.container_id == container_id, Container.user_id == user.id).first()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found or does not belong to the user")
    
    try:
        docker_container = client.containers.get(container.container_id)
        
        if docker_container.status != 'running':
            raise HTTPException(status_code=400, detail="Container is not running")
        
        # Execute the command to list all files and directories
        exec_result_directories = docker_container.exec_run("find /app -type d -exec echo {} \\;", tty=True)
        exec_result_files = docker_container.exec_run("find /app -type f -exec echo {} \\;", tty=True)

        if exec_result_directories.exit_code != 0 and exec_result_files.exit_code != 0:
            raise HTTPException(status_code=500, detail="Error retrieving file system structure")
        
        directories_output = exec_result_directories.output.decode("utf-8").strip().split("\n")
        files_output = exec_result_files.output.decode("utf-8").strip().split("\n")

        decoded_path= base64.b64decode(path).decode('utf-8')
        
        files = []
        for item in directories_output:
            item = item.strip() 
            parent_path = '/'.join(item.split('/')[:-1]) or None
            files.append(FileSystemItem(
                name=item.split('/')[-1],
                path=item,
                parentPath=parent_path,
                kind='directory',
                handle=None,
                content=None,
                isSaved=True,
                isOpen=False
            ))
        for item in files_output:
            item = item.strip() 
            parent_path = '/'.join(item.split('/')[:-1]) or None
            files.append(FileSystemItem(
                name=item.split('/')[-1],
                path=item,
                parentPath=parent_path,
                kind= 'file',
                handle=None,
                content=None,
                isSaved=True,
                isOpen=False
            ))
        
        files = [file for file in files if file.parentPath and decoded_path in file.parentPath]

        return files

    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Docker container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving file system structure: {str(e)}")    

@docker_router.get("/docker/file-content/{container_id}")
def get_file_content(container_id: str, file_path: str, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    token_payload = verify_token(token)
    if token_payload is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user = token_payload.get('sub')
    user = get_user_by_email(db, user)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    container = db.query(Container).filter(Container.container_id == container_id, Container.user_id == user.id).first()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found or does not belong to the user")
    
    try:
        docker_container = client.containers.get(container.container_id)
        
        if docker_container.status != 'running':
            raise HTTPException(status_code=400, detail="Container is not running")
        
        # Execute the command to read the file content
        exec_result = docker_container.exec_run(f"cat {file_path}", tty=True)

        if exec_result.exit_code != 0:
            raise HTTPException(status_code=500, detail="Error retrieving file content")
        
        file_content = exec_result.output.decode("utf-8").strip()
        
        return file_content

    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Docker container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving file content: {str(e)}")
    
class SaveContainerFile(BaseModel):
    container_id: str
    name: str
    parent_path: str
    content: str
    
@docker_router.post("/docker/save-file-content")
def save_file_content(req:SaveContainerFile, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    token_payload = verify_token(token)
    if token_payload is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user = token_payload.get('sub')
    user = get_user_by_email(db, user)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    container = db.query(Container).filter(Container.container_id == req.container_id, Container.user_id == user.id).first()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found or does not belong to the user")
    
    try:
        docker_container = client.containers.get(container.container_id)
        
        if docker_container.status != 'running':
            raise HTTPException(status_code=400, detail="Container is not running")
        
        # Normalize newlines to Unix-style
        normalized_content = req.content.replace('\r\n', '\n')

        # Create an in-memory tar archive containing the file
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode='w') as tar:
            tarinfo = tarfile.TarInfo(name=req.name)
            tarinfo.size = len(normalized_content.encode('utf-8'))
            tar.addfile(tarinfo, io.BytesIO(normalized_content.encode('utf-8')))
        tar_stream.seek(0)
        
        # Upload the tar archive to the Docker container
        docker_container.put_archive(path=req.parent_path, data=tar_stream)
        
        return {"message": "File content saved successfully"}

    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Docker container not found")
    except Exception as e:

        raise HTTPException(status_code=500, detail=f"Error saving file content: {str(e)}")
    
class MoveContainerItem(BaseModel):
    container_id: str
    source_path: str
    destination_path: str

@docker_router.post("/docker/move-item")
def move_item(req: MoveContainerItem, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    token_payload = verify_token(token)
    if token_payload is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user = token_payload.get('sub')
    user = get_user_by_email(db, user)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    container = db.query(Container).filter(Container.container_id == req.container_id, Container.user_id == user.id).first()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found or does not belong to the user")
    
    try:
        docker_container = client.containers.get(container.container_id)
        
        if docker_container.status != 'running':
            raise HTTPException(status_code=400, detail="Container is not running")
        
        # Execute the command to move the file or folder
        exec_result = docker_container.exec_run(f"mv {req.source_path} {req.destination_path}", tty=True)

        if exec_result.exit_code != 0:
            raise HTTPException(status_code=500, detail="Error moving item")
        
        return {"message": "Item moved successfully"}

    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Docker container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error moving item: {str(e)}")
    
class CreateFolderRequest(BaseModel):
    container_id: str
    folder_path: str

@docker_router.post("/docker/create-folder")
def create_folder(req: CreateFolderRequest, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    token_payload = verify_token(token)
    if token_payload is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user = token_payload.get('sub')
    user = get_user_by_email(db, user)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    container = db.query(Container).filter(Container.container_id == req.container_id, Container.user_id == user.id).first()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found or does not belong to the user")
    
    try:
        docker_container = client.containers.get(container.container_id)
        
        if docker_container.status != 'running':
            raise HTTPException(status_code=400, detail="Container is not running")
        
        # Execute the command to create the folder
        
        exec_result = docker_container.exec_run(f"mkdir -p {req.folder_path}", tty=True)

        if exec_result.exit_code != 0:
            raise HTTPException(status_code=500, detail="Error creating folder")
        
        return {"message": "Folder created successfully"}

    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Docker container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating folder: {str(e)}")
    
class CreateFileRequest(BaseModel):
    container_id: str
    file_path: str

@docker_router.post("/docker/create-file")
def create_file(req: CreateFileRequest, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    token_payload = verify_token(token)
    if token_payload is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user = token_payload.get('sub')
    user = get_user_by_email(db, user)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    container = db.query(Container).filter(Container.container_id == req.container_id, Container.user_id == user.id).first()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found or does not belong to the user")
    
    try:
        docker_container = client.containers.get(container.container_id)
        
        if docker_container.status != 'running':
            raise HTTPException(status_code=400, detail="Container is not running")
        
        # Execute the command to create the file
        exec_result = docker_container.exec_run(f"touch {req.file_path}", tty=True)

        if exec_result.exit_code != 0:
            raise HTTPException(status_code=500, detail="Error creating file")
        
        return {"message": "File created successfully"}

    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Docker container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating file: {str(e)}")
    
class RemovePathRequest(BaseModel):
    container_id: str
    path: str

@docker_router.post("/docker/remove-path")
def remove_path(req: RemovePathRequest, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    token_payload = verify_token(token)
    if token_payload is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user = token_payload.get('sub')
    user = get_user_by_email(db, user)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    container = db.query(Container).filter(Container.container_id == req.container_id, Container.user_id == user.id).first()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found or does not belong to the user")
    
    try:
        docker_container = client.containers.get(container.container_id)
        
        if docker_container.status != 'running':
            raise HTTPException(status_code=400, detail="Container is not running")
        
        # Execute the command to remove the file or folder
        exec_result = docker_container.exec_run(f"rm -rf {req.path}", tty=True)

        if exec_result.exit_code != 0:
            raise HTTPException(status_code=500, detail="Error removing path")
        
        return {"message": "Path removed successfully"}

    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Docker container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error removing path: {str(e)}")