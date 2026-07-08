import os
from typing import Dict, List
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import json
import logging
from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load environment variables
load_dotenv()
GROQ_API_KEY = "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"
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY environment variable is not set")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

MONGO_URI = "mongodb://localhost:27017/"
if not MONGO_URI:
    raise ValueError("MONGO_URI environment variable is not set")

# MongoDB connection setup
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["employee_db"]
employees_collection = db["employees"]

@app.on_event("startup")
async def startup_db_client():
    global mongo_client, db, employees_collection
    try:
        mongo_client = MongoClient(MONGO_URI)
        db = mongo_client.employee_db
        employees_collection = db.employees
        logger.info("MongoDB connection established")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise ValueError(f"MongoDB connection failed: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    global mongo_client
    if mongo_client:
        mongo_client.close()
        logger.info("MongoDB connection closed")

chat_sessions = set()

# Define request model
class ChatRequest(BaseModel):
    sessionId: str
    message: str

# Allowed MongoDB operators and fields for query validation
ALLOWED_OPERATORS = {"$gt", "$lt", "$gte", "$lte", "$eq", "$ne"}
ALLOWED_FIELDS = {"name", "department", "salary"}

def validate_query(query: Dict) -> tuple[bool, str]:
    """Validate MongoDB query and return status with specific error message."""
    def check_dict(d):
        for key, value in d.items():
            if key in ALLOWED_OPERATORS:
                if not isinstance(value, (int, float, str)):
                    return False, f"Invalid value for operator {key}: {value}"
            elif key in ALLOWED_FIELDS:
                if isinstance(value, dict):
                    valid, msg = check_dict(value)
                    if not valid:
                        return False, msg
                elif not isinstance(value, (str, int, float)):
                    return False, f"Invalid value for field {key}: {value}"
            else:
                return False, f"Invalid field: {key} is not supported. Only {', '.join(ALLOWED_FIELDS)} are allowed."
        return True, ""
    logger.info(f"Validating query: {json.dumps(query)}")
    valid, message = check_dict(query)
    if not valid:
        logger.error(f"Query validation failed: {message}")
    return valid, message

# Tool functions
def get_current_time(data: Dict = None) -> str:
    return f"The current time is {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

def create_employee(data: Dict) -> str:
    try:
        logger.info(f"Creating employee with data: {data}")
        name = data.get("name")
        department = data.get("department")
        salary = data.get("salary")
        
        # Validate required fields
        if not all([name, department, salary]):
            logger.error("Missing required fields")
            return "Missing required fields: name, department, salary"
            
        # Validate salary is a number
        try:
            salary = float(salary)
            if salary < 0:
                logger.error("Salary cannot be negative")
                return "Salary cannot be negative"
        except (TypeError, ValueError):
            logger.error("Invalid salary format")
            return "Salary must be a valid number"
        employee = {"name": name, "department": department, "salary": salary}
        result = employees_collection.insert_one(employee)
        logger.info(f"Employee created with ID: {str(result.inserted_id)}")
        return f"Employee {name} created with ID {str(result.inserted_id)}"
    except Exception as e:
        logger.error(f"Error creating employee: {e}")
        return f"Failed to create employee: {str(e)}"

def view_employee(data: Dict) -> str:
    try:
        logger.info(f"Viewing employee with ID: {data.get('employee_id')}")
        employee_id = ObjectId(data.get("employee_id"))
        employee = employees_collection.find_one({"_id": employee_id})
        if not employee:
            logger.warning(f"No employee found with ID: {employee_id}")
            return f"No employee found with ID {employee_id}"
        return f"Employee: {employee['name']}, Department: {employee['department']}, Salary: {employee['salary']}"
    except Exception as e:
        logger.error(f"Error viewing employee: {e}")
        return f"Failed to view employee: {str(e)}"

def update_employee(data: Dict) -> str:
    try:
        logger.info(f"Updating employee with data: {data}")
        employee_id = ObjectId(data.get("employee_id"))
        update_data = {k: v for k, v in data.items() if k in ["name", "department", "salary"] and v is not None}
        if not update_data:
            logger.error("No valid fields to update")
            return "No valid fields to update"
        result = employees_collection.update_one({"_id": employee_id}, {"$set": update_data})
        if result.matched_count == 0:
            logger.warning(f"No employee found with ID: {employee_id}")
            return f"No employee found with ID {employee_id}"
        logger.info(f"Employee {employee_id} updated")
        return f"Employee {employee_id} updated successfully"
    except Exception as e:
        logger.error(f"Error updating employee: {e}")
        return f"Failed to update employee: {str(e)}"

def delete_employee(data: Dict) -> str:
    try:
        logger.info(f"Deleting employee with ID: {data.get('employee_id')}")
        employee_id = ObjectId(data.get("employee_id"))
        result = employees_collection.delete_one({"_id": employee_id})
        if result.deleted_count == 0:
            logger.warning(f"No employee found with ID: {employee_id}")
            return f"No employee found with ID {employee_id}"
        logger.info(f"Employee {employee_id} deleted")
        return f"Employee {employee_id} deleted successfully"
    except Exception as e:
        logger.error(f"Error deleting employee: {e}")
        return f"Failed to delete employee: {str(e)}"

def list_employees(data: Dict = None) -> str:
    try:
        logger.info("Listing all employees")
        employees = list(employees_collection.find())
        if not employees:
            logger.info("No employees found in database")
            return "No employees found"
        result = [
            f"ID: {str(emp['_id'])}, Name: {emp['name']}, Department: {emp['department']}, Salary: {emp['salary']}"
            for emp in employees
        ]
        logger.info(f"Found {len(result)} employees")
        return "\n".join(result)
    except Exception as e:
        logger.error(f"Error listing employees: {e}")
        return f"Failed to list employees: {str(e)}"

def count_employees(data: Dict = None) -> str:
    try:
        logger.info("Counting all employees")
        count = employees_collection.count_documents({})
        logger.info(f"Total employees: {count}")
        return f"Total number of employees: {count}"
    except Exception as e:
        logger.error(f"Error counting employees: {e}")
        return f"Failed to count employees: {str(e)}"

def query_employees(query: Dict) -> str:
    try:
        logger.info(f"Received query for execution: {json.dumps(query)}")
        valid, message = validate_query(query)
        if not valid:
            logger.error(f"Invalid query rejected: {message}")
            return message
        employees = employees_collection.find(query)
        result = [
            f"ID: {str(emp['_id'])}, Name: {emp['name']}, Department: {emp['department']}, Salary: {emp['salary']}"
            for emp in employees
        ]
        logger.info(f"Query result: {len(result)} employees found")
        if not result:
            return "Sorry, I did not understand your ask, could you explain further?"
        return "\n".join(result)
    except Exception as e:
        logger.error(f"Error executing query {json.dumps(query)}: {e}")
        return f"Failed to execute query: {str(e)}"

# Available tools
available_tools = {
    "get_time": get_current_time,
    "create_employee": create_employee,
    "view_employee": view_employee,
    "update_employee": update_employee,
    "delete_employee": delete_employee,
    "list_employees": list_employees,
    "count_employees": count_employees,
    "query_employees": query_employees
}

async def query_groq(messages: List[Dict[str, str]]) -> Dict:
    context = """
    You are an AI assistant managing an employee database with fields: name (string), department (string), salary (number). For any user input, dynamically convert it into a MongoDB query if it references these fields or related actions (e.g., find, list, count). Respond with a JSON object using the appropriate tool. If the input is irrelevant to the database, return a fallback response.

    Tools and mappings:
    - Time queries (e.g., "What's the current time?"):
      {"tool_call": {"name": "get_time", "arguments": {}}}
    - Create employee (e.g., "Create employee John in Sales with salary 50000"):
      {"tool_call": {"name": "create_employee", "arguments": {"name": "string", "department": "string", "salary": number}}}
    - View employee by ID (e.g., "View employee 123"):
      {"tool_call": {"name": "view_employee", "arguments": {"employee_id": "string"}}}
    - Update employee (e.g., "Update employee 123 with salary 60000"):
      {"tool_call": {"name": "update_employee", "arguments": {"employee_id": "string", "name": "string|null", "department": "string|null", "salary": number|null}}}
    - Delete employee (e.g., "Delete employee 123"):
      {"tool_call": {"name": "delete_employee", "arguments": {"employee_id": "string"}}}
    - List all employees (e.g., "List all employees", "Show all employees", "Display all employees", "Get all employees"):
      {"tool_call": {"name": "list_employees", "arguments": {}}}
    - Count employees (e.g., "Total number of employees", "How many employees?", "Employee count", "Give me total number of employees"):
      {"tool_call": {"name": "count_employees", "arguments": {}}}
    - Query employees with criteria (e.g., "Find employees in Sales", "Show employees with salary more than 50000", "Employees named Alice"):
      {"tool_call": {"name": "query_employees", "arguments": {"query": "MongoDB query as JSON"}}}
      Parse the input to generate a valid MongoDB query for name, department, or salary.
      Examples:
      - "Find employees in Sales" -> {"query": {"department": "Sales"}}
      - "Show employees with salary more than 60000" -> {"query": {"salary": {"$gt": 60000}}}
      - "Find employees with salary above 60000" -> {"query": {"salary": {"$gt": 60000}}}
      - "Find employees named Alice" -> {"query": {"name": "Alice"}}
      - "Employees in Sales with salary more than 50000" -> {"query": {"department": "Sales", "salary": {"$gt": 50000}}}
      - "Show employees in HR named Alice" -> {"query": {"department": "HR", "name": "Alice"}}
      - "Find employees with salary between 50000 and 70000" -> {"query": {"salary": {"$gte": 50000, "$lte": 70000}}}
      - "Employees earning from 50000 to 70000" -> {"query": {"salary": {"$gte": 50000, "$lte": 70000}}}
      - "Find employees with name John and department Sales" -> {"query": {"name": "John", "department": "Sales"}}
      - "Show employees with salary greater than 70000" -> {"query": {"salary": {"$gt": 70000}}}

    Use only MongoDB operators $gt, $lt, $gte, $lte, $eq, $ne. Do not use $range, $and, $or. For range queries, combine $gte and $lte in a single salary object. If the input references fields other than name, department, or salary (e.g., "Find employees with age 30"), use query_employees, which will validate and return an error.

    For non-database queries that are clear (e.g., "What's 2+2?"):
      {"response": "your_answer_here"}
    For inputs irrelevant to the database, unclear, or ambiguous (e.g., "abc xyz", "What's the weather?"):
      {"response": "Sorry, I did not understand your ask, could you explain further?"}
    """
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": context}] + messages,
        "response_format": {"type": "json_object"}
    }
    try:
        logger.info(f"Sending request to Groq API with messages: {messages}")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(GROQ_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            logger.info(f"Received response from Groq API: {content}")
            return json.loads(content)
    except httpx.HTTPStatusError as e:
        logger.error(f"Groq API error: {e}")
        return {"response": f"Error querying Groq API: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error in Groq query: {e}")
        return {"response": f"Unexpected error: {str(e)}"}

# MCP metadata endpoint
@app.get("/.well-known/mcp")
async def get_mcp_metadata():
    logger.info("MCP metadata endpoint called")
    return {
        "version": "1.0",
        "capabilities": ["chat", "tool_execution"],
        "tools": list(available_tools.keys())
    }

# Chat endpoint
@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    # Validate MongoDB connection
    if mongo_client is None or employees_collection is None:
        logger.error("MongoDB connection not established")
        raise HTTPException(status_code=503, detail="Database connection not available")
    try:
        logger.info(f"Received chat request: sessionId={request.sessionId}, message={request.message}")
        if not request.sessionId or len(request.sessionId) > 100:
            raise HTTPException(status_code=400, detail="Invalid sessionId")
        if not request.message or len(request.message) > 1000:
            raise HTTPException(status_code=400, detail="Message too long or empty")
        
        chat_sessions.add(request.sessionId)
        
        # Query Groq API
        response = await query_groq([ #llm calling
            {"role": "user", "content": request.message}
        ])
        logger.info(f"Groq response: {json.dumps(response)}")
        
        # Handle tool call
        if "tool_call" in response: 
            tool_name = response["tool_call"]["name"]
            tool_args = response["tool_call"]["arguments"]
            logger.info(f"Calling tool: {tool_name} with arguments: {tool_args}")
            
            # Fallback for misidentified tools
            if tool_name not in available_tools:
                logger.warning(f"Unknown tool requested: {tool_name}. Attempting fallback.")
                if tool_name in ["list_all_employees", "show_all_employees", "view_all_employees"]:
                    logger.info(f"Redirecting {tool_name} to list_employees")
                    tool_name = "list_employees"
                    tool_args = {}
                elif tool_name in ["get_total_employees", "count_employees"]:
                    logger.info(f"Redirecting {tool_name} to count_employees")
                    tool_name = "count_employees"
                    tool_args = {}
                else:
                    logger.error(f"No fallback available for unknown tool: {tool_name}")
                    return JSONResponse({"reply": f"Unknown tool: {tool_name}"}, status_code=400)
            
            try:
                # Handle cases where tool_args might be None or invalid
                if tool_args is None:
                    tool_args = {}
                
                # For query_employees, ensure query is a dict
                if tool_name == "query_employees" and isinstance(tool_args, dict):
                    if "query" not in tool_args or not isinstance(tool_args["query"], dict):
                        logger.error("Invalid query format")
                        return JSONResponse({"reply": "Invalid query format"}, status_code=400)
                
                result = available_tools[tool_name](tool_args)
                logger.info(f"Tool result: {result}")
                return JSONResponse({"reply": result})
            except Exception as e:
                logger.error(f"Error executing tool {tool_name}: {str(e)}")
                return JSONResponse({"reply": f"Error executing tool: {str(e)}"}, status_code=500)
        
        # Handle other responses
        result = response.get("response", "No response provided")
        logger.info(f"Non-tool response: {result}")
        return JSONResponse({"reply": result})
    
    except HTTPException as he:
        logger.error(f"HTTP error: {he}")
        raise he
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {e}")
        return JSONResponse({"reply": f"Unexpected error: {str(e)}"}, status_code=500)