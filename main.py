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
from pymongo.errors import ConnectionFailure
from bson import ObjectId
from dotenv import load_dotenv
from workforce import WorkforceDocument
from uuid import uuid4

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
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

MONGO_URI = "mongodb+srv://Vipul:ESG@cluster0.et73cxg.mongodb.net/?retryWrites=true&w=majority"
if not MONGO_URI:
    raise ValueError("MONGO_URI environment variable is not set")

# MongoDB connection setup
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["esg_databse"]
module_collection = db["modules"]

@app.on_event("startup")
async def startup_db_client():
    global mongo_client, db, module_collection
    try:
        mongo_client = MongoClient(MONGO_URI)
        mongo_client.admin.command('ping')
        logger.info("Successfully pinged MongoDB server")
        db = mongo_client["esg_databse"]
        module_collection = db["modules"]
        collections = db.list_collection_names()
        logger.info(f"Connected to database 'esg_databse'. Available collections: {collections}")
        if "modules" not in collections:
            logger.warning("Collection 'modules' does not exist. Creating it now.")
            db.create_collection("modules")
            logger.info("Collection 'modules' created.")
        logger.info("MongoDB connection established")
    except ConnectionFailure as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise ValueError(f"MongoDB connection failed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error while connecting to MongoDB: {e}")
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
ALLOWED_FIELDS = {
    "employees": {"name", "department", "salary"},
    "departments": {"name", "manager"},
    "projects": {"name", "employee_id", "status"},
    "module": {
        "_id", "id", "company_id", "plant_id", "financial_year", "module_name", "submodules", "created_at", "updated_at",
        "submodules.id", "submodules.submodule_name", "submodules.question_categories",
        "submodules.question_categories.id", "submodules.question_categories.category_name", "submodules.question_categories.questions",
        "submodules.question_categories.questions.question_id", "submodules.question_categories.questions.question",
        "submodules.question_categories.questions.type", "submodules.question_categories.questions.has_string_value",
        "submodules.question_categories.questions.has_decimal_value", "submodules.question_categories.questions.has_boolean_value",
        "submodules.question_categories.questions.has_link", "submodules.question_categories.questions.has_note",
        "submodules.question_categories.questions.string_value_required", "submodules.question_categories.questions.decimal_value_required",
        "submodules.question_categories.questions.boolean_value_required", "submodules.question_categories.questions.link_required",
        "submodules.question_categories.questions.note_required", "submodules.question_categories.questions.table_metadata",
        "submodules.question_categories.questions.table_metadata.headers", "submodules.question_categories.questions.table_metadata.rows",
        "submodules.question_categories.questions.table_metadata.cell_type", "submodules.question_categories.questions.table_metadata.min_col_width",
        "submodules.question_categories.questions.table_metadata.max_col_width", "submodules.question_categories.questions.table_metadata.horizontal_scroll_threshold",
        "submodules.question_categories.questions.table_metadata.headers.label", "submodules.question_categories.questions.table_metadata.headers.headers",
        "submodules.question_categories.questions.table_metadata.headers.cell_type", "submodules.question_categories.questions.table_metadata.headers.required",
        "submodules.question_categories.questions.table_metadata.headers.allowed_values", "submodules.question_categories.questions.table_metadata.headers.min_value",
        "submodules.question_categories.questions.table_metadata.headers.max_value", "submodules.question_categories.questions.table_metadata.headers.default_value",
        "submodules.question_categories.questions.table_metadata.headers.min_width", "submodules.question_categories.questions.table_metadata.headers.max_width",
        "submodules.question_categories.questions.table_metadata.headers.help_text",
        "submodules.question_categories.questions.table_metadata.rows.name", "submodules.question_categories.questions.table_metadata.rows.required",
        "submodules.question_categories.questions.table_metadata.rows.allowed_values", "submodules.question_categories.questions.table_metadata.rows.min_value",
        "submodules.question_categories.questions.table_metadata.rows.max_value", "submodules.question_categories.questions.table_metadata.rows.default_value",
        "submodules.question_categories.questions.table_metadata.rows.help_text"
    }
}

def validate_query(query: Dict, collection: str) -> tuple[bool, str]:
    if collection != "module":
        return False, "Only queries on the 'module' collection are supported at this time."

    if collection not in ALLOWED_FIELDS:
        return False, f"Collection '{collection}' is not supported"

    allowed_fields = ALLOWED_FIELDS[collection]

    def flatten_query_keys(d: Dict, prefix: str = "") -> List[str]:
        keys = []
        for key, value in d.items():
            new_key = f"{prefix}{key}" if prefix else key
            if key in ALLOWED_OPERATORS:
                continue
            keys.append(new_key)
            if isinstance(value, dict):
                keys.extend(flatten_query_keys(value, f"{new_key}."))
        return keys

    def check_dict(d: Dict) -> tuple[bool, str]:
        query_keys = flatten_query_keys(d)
        for key in query_keys:
            if key not in allowed_fields:
                return False, f"Invalid field: '{key}' is not supported in collection '{collection}'. Only {', '.join(sorted(allowed_fields))} are allowed."
        
        for key, value in d.items():
            if key in ALLOWED_OPERATORS:
                if not isinstance(value, (int, float, str)):
                    return False, f"Invalid value for operator '{key}': {value}"
            elif isinstance(value, dict):
                valid, msg = check_dict(value)
                if not valid:
                    return False, msg
            elif not isinstance(value, (str, int, float)):
                return False, f"Invalid value for field '{key}': {value}"
        return True, ""

    logger.info(f"Validating query for collection '{collection}': {json.dumps(query)}")
    valid, message = check_dict(query)
    if not valid:
        logger.error(f"Query validation failed: {message}")
    return valid, message

# Tool functions
def create_module(data: Dict) -> str:
    try:
        logger.info(f"Creating module with data: {data}")
        module_name = data.get("module_name")
        company_id = data.get("company_id")
        plant_id = data.get("plant_id")
        financial_year = data.get("financial_year")
        if not all([module_name, company_id, plant_id, financial_year]):
            logger.error("Missing required fields")
            return "Missing required fields: module_name, company_id, plant_id, financial_year"
        module_data = {
            "id": str(uuid4()),
            "module_name": module_name,
            "company_id": company_id,
            "plant_id": plant_id,
            "financial_year": financial_year,
            "submodules": [],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        module = WorkforceDocument(**module_data)
        result = module_collection.insert_one(module.dict())
        logger.info(f"Module created with ID: {str(result.inserted_id)}")
        return f"Module {module_name} created with ID {str(result.inserted_id)}"
    except Exception as e:
        logger.error(f"Error creating module: {e}")
        return f"Failed to create module: {str(e)}"

def list_modules(data: Dict = None) -> str:
    try:
        logger.info("Listing all modules")
        # Validate MongoDB connection
        try:
            mongo_client.admin.command('ping')
            logger.info("MongoDB connection is active before listing modules")
        except Exception as e:
            logger.error(f"MongoDB connection failed before listing modules: {e}")
            return f"MongoDB connection failed: {str(e)}"
            
        modules = list(module_collection.find())
        logger.info(f"Raw modules list: {json.dumps(modules, default=str)}")
        if not modules:
            logger.info("No modules found in database")
            return "No modules found"
        result = []
        for mod in modules:
            module = WorkforceDocument(**mod)
            result.append(
                f"ID: {str(module._id)}, Name: {module.module_name}, Company: {module.company_id}, Plant: {module.plant_id}, Financial Year: {module.financial_year}"
            )
        logger.info(f"Found {len(result)} modules")
        return "\n".join(result)
    except Exception as e:
        logger.error(f"Error listing modules: {e}")
        return f"Failed to list modules: {str(e)}"

def query_modules(query: Dict) -> str:
    try:
        logger.info(f"Received query for modules: {json.dumps(query)}")
        # Validate MongoDB connection
        try:
            mongo_client.admin.command('ping')
            logger.info("MongoDB connection is active before executing query")
        except Exception as e:
            logger.error(f"MongoDB connection failed before query: {e}")
            return f"MongoDB connection failed: {str(e)}"
            
        valid, message = validate_query(query['query'], "module")
        if not valid:
            logger.error(f"Invalid query rejected: {message}")
            return message
        logger.info("Query validated successfully, executing MongoDB query")
        modules = module_collection.find(query["query"])
        modules_list = list(modules)
        logger.info(f"Raw query result: {json.dumps(modules_list, default=str)}")
        result = []
        for mod in modules_list:
            logger.info(f"Processing module: {json.dumps(mod, default=str)}")
            module = WorkforceDocument(**mod)
            result.append(
                f"ID: {str(module._id)}, Name: {module.module_name}, Company: {module.company_id}, Plant: {module.plant_id}, Financial Year: {module.financial_year}"
            )
        logger.info(f"Query result: {len(result)} modules found")
        if not result:
            return "No modules found"
        return "\n".join(result)
    except Exception as e:
        logger.error(f"Error executing query {json.dumps(query)}: {e}")
        return f"Failed to execute query: {str(e)}"

def list_submodules(data: Dict) -> str:
    try:
        logger.info(f"Listing submodules for module: {data}")
        module_id = data.get("module_id")
        if not module_id:
            logger.error("Missing required field: module_id")
            return "Missing required field: module_id"
        query = {"_id": ObjectId(module_id)}
        valid, message = validate_query({"_id": module_id}, "module")
        if not valid:
            logger.error(f"Invalid query rejected: {message}")
            return message
        # Validate MongoDB connection
        try:
            mongo_client.admin.command('ping')
            logger.info("MongoDB connection is active before listing submodules")
        except Exception as e:
            logger.error(f"MongoDB connection failed before listing submodules: {e}")
            return f"MongoDB connection failed: {str(e)}"
            
        module = module_collection.find_one(query)
        if not module:
            logger.info(f"No module found with ID: {module_id}")
            return f"No module found with ID {module_id}"
        module_obj = WorkforceDocument(**module)
        if not module_obj.submodules:
            return "No submodules found"
        result = [
            f"Submodule ID: {sub.id}, Name: {sub.submodule_name}"
            for sub in module_obj.submodules
        ]
        logger.info(f"Found {len(result)} submodules")
        return "\n".join(result)
    except Exception as e:
        logger.error(f"Error listing submodules: {e}")
        return f"Failed to list submodules: {str(e)}"

def get_current_time(data: Dict = None) -> str:
    return f"The current time is {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

# Available tools
available_tools = {
    "get_time": get_current_time,
    "create_module": create_module,
    "list_modules": list_modules,
    "query_modules": query_modules,
    "list_submodules": list_submodules
}

async def query_groq(messages: List[Dict[str, str]]) -> Dict:
    context = """
You are an AI assistant managing a company database with the following collection:
- 'module' collection with fields: id (string), company_id (string), plant_id (string), financial_year (string), module_name (string), submodules (list of objects), created_at (datetime), updated_at (datetime). Submodules contain id (string), submodule_name (string), and question_categories (list of objects). Question_categories contain id (string), category_name (string), and questions (list of objects). Questions contain question_id (string), question (string), type (string), has_string_value (boolean), has_decimal_value (boolean), has_boolean_value (boolean), has_link (boolean), has_note (boolean), string_value_required (boolean), decimal_value_required (boolean), boolean_value_required (boolean), link_required (boolean), note_required (boolean), and table_metadata (optional object). Table_metadata contains headers (list), rows (list), cell_type (string), min_col_width (integer), max_col_width (integer), horizontal_scroll_threshold (integer). Headers contain label (string), headers (list, optional), cell_type (string), required (boolean), allowed_values (list, optional), min_value (number/string, optional), max_value (number/string, optional), default_value (number/string, optional), min_width (integer, optional), max_width (integer, optional), help_text (string, optional). Rows contain name (string), required (boolean), allowed_values (list, optional), min_value (number/string, optional), max_value (number/string, optional), default_value (number/string, optional), help_text (string, optional).

For any user input, determine if it relates to the 'module' collection and dynamically convert the input into a MongoDB query or action. Respond with a JSON object using the appropriate tool. If the input involves the 'module' collection, use dot notation for nested fields in queries (e.g., "submodules.submodule_name"). If the input is irrelevant to the 'module' collection, return a fallback response.

Tools and mappings:
- Time queries (e.g., "What's the current time?"):
    {"tool_call": {"name": "get_time", "arguments": {}}}
- Create module (e.g., "Create module Workforce test for company COMP001, plant PLANT001, financial year 2024_2025"):
    {"tool_call": {"name": "create_module", "arguments": {"module_name": "string", "company_id": "string", "plant_id": "string", "financial_year": "string"}}}
- List all modules (e.g., "List all modules"):
    {"tool_call": {"name": "list_modules", "arguments": {}}}
- Query modules (e.g., "Find modules with name Workforce test"):
    {"tool_call": {"name": "query_modules", "arguments": {"query": "MongoDB query as JSON"}}}
- List submodules for a module (e.g., "List submodules for module [module_id]"):
    {"tool_call": {"name": "list_submodules", "arguments": {"module_id": "string"}}}

Use only MongoDB operators $gt, $lt, $gte, $lte, $eq, $ne for queries. For range queries, combine $gte and $lte in a single field object. If the input references unsupported fields, return an error via the tool.

For non-database queries that are clear (e.g., "What's 2+2?"):
    {"response": "your_answer_here"}
For inputs irrelevant to the 'module' collection, unclear, or ambiguous (e.g., "abc xyz"):
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
    if mongo_client is None or module_collection is None:
        logger.error("MongoDB connection not established")
        raise HTTPException(status_code=503, detail="Database connection not available")
    try:
        logger.info(f"Received chat request: sessionId={request.sessionId}, message={request.message}")
        if not request.sessionId or len(request.sessionId) > 100:
            raise HTTPException(status_code=400, detail="Invalid sessionId")
        if not request.message or len(request.message) > 1000:
            raise HTTPException(status_code=400, detail="Message too long or empty")
        
        chat_sessions.add(request.sessionId)
        
        response = await query_groq([{"role": "user", "content": request.message}])
        logger.info(f"Groq response: {json.dumps(response)}")
        
        if "tool_call" in response: 
            tool_name = response["tool_call"]["name"]
            tool_args = response["tool_call"]["arguments"]
            logger.info(f"Calling tool: {tool_name} with arguments: {tool_args}")
            
            if tool_name not in available_tools:
                logger.error(f"Unknown tool requested: {tool_name}")
                return JSONResponse({"reply": f"Unknown tool: {tool_name}"}, status_code=400)
            
            try:
                if tool_args is None:
                    tool_args = {}
                result = available_tools[tool_name](tool_args)
                logger.info(f"Tool result: {result}")
                return JSONResponse({"reply": result})
            except Exception as e:
                logger.error(f"Error executing tool {tool_name}: {str(e)}")
                return JSONResponse({"reply": f"Error executing tool: {str(e)}"}, status_code=500)
        
        result = response.get("response", "No response provided")
        logger.info(f"Non-tool response: {result}")
        return JSONResponse({"reply": result})
    
    except HTTPException as he:
        logger.error(f"HTTP error: {he}")
        raise he
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {e}")
        return JSONResponse({"reply": f"Unexpected error: {str(e)}"}, status_code=500)