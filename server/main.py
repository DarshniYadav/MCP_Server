from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict
from datetime import datetime
import httpx
from pymongo import MongoClient
from bson import ObjectId
import os

app = FastAPI()

# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["employee_db"]
employees_collection = db["employees"]

# In-memory session storage
chat_sessions: Dict[str, List[Dict[str, str]]] = {}

# Pydantic models
class ChatRequest(BaseModel):
    sessionId: str
    message: str

class Employee(BaseModel):
    employee_id: str
    name: str
    department: str
    salary: float

class EmployeeUpdate(BaseModel):
    name: str | None = None
    department: str | None = None
    salary: float | None = None

# TOOL: Get Current Time
def get_current_time():
    return f"The current time is {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."

# Register tools here
available_tools = {
    "get_time": get_current_time
}

# Ollama API config
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "mistral"

async def query_ollama(messages: List[Dict[str, str]]) -> str:
    system_prompt = (
        "You are an assistant. If the user asks for the current time, "
        "reply exactly with: CALL::get_time"
    )

    full_messages = [{"role": "system", "content": system_prompt}] + messages

    body = {
        "model": MODEL_NAME,
        "messages": full_messages
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(OLLAMA_URL, json=body)
            response.raise_for_status()
            result = response.json()
            return result['message']['content']
    except httpx.HTTPStatusError as e:
        return f"Ollama API error: {str(e)}"
    except KeyError:
        return "Unexpected Ollama API response format"

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    session_id = request.sessionId
    user_message = {"role": "user", "content": request.message}

    # Retrieve chat history
    history = chat_sessions.setdefault(session_id, [])
    history.append(user_message)

    # Ask LLM
    reply_content = await query_ollama(history)

    # 🧠 Tool call detected
    if reply_content.startswith("CALL::"):
        tool_name = reply_content.replace("CALL::", "").strip()
        if tool_name in available_tools:
            tool_result = available_tools[tool_name]()
            assistant_message = {"role": "assistant", "content": tool_result}
        else:
            assistant_message = {"role": "assistant", "content": f"Unknown tool: {tool_name}"}
    else:
        assistant_message = {"role": "assistant", "content": reply_content}

    history.append(assistant_message)
    return {"reply": assistant_message["content"]}

# CRUD Endpoints for Employee
@app.post("/api/employees", response_model=Employee)
async def create_employee(employee: Employee):
    existing = employees_collection.find_one({"employee_id": employee.employee_id})
    if existing:
        raise HTTPException(status_code=400, detail="Employee ID already exists")
    employee_dict = employee.dict()
    result = employees_collection.insert_one(employee_dict)
    employee_dict["_id"] = str(result.inserted_id)
    return employee_dict

@app.get("/api/employees/{employee_id}")
async def view_employee(employee_id: str):
    employee = employees_collection.find_one({"employee_id": employee_id})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    employee["_id"] = str(employee["_id"])
    return employee

@app.put("/api/employees/{employee_id}")
async def update_employee(employee_id: str, update: EmployeeUpdate):
    update_dict = {k: v for k, v in update.dict().items() if v is not None}
    if not update_dict:
        raise HTTPException(status_code=400, detail="No fields provided for update")
    result = employees_collection.update_one(
        {"employee_id": employee_id},
        {"$set": update_dict}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {"message": "Employee updated successfully"}

@app.delete("/api/employees/{employee_id}")
async def delete_employee(employee_id: str):
    result = employees_collection.delete_one({"employee_id": employee_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {"message": "Employee deleted successfully"}