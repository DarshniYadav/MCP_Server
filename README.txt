# MCP Server (Python + Ollama)

## 🧰 Prerequisites

- Python 3.8+
- Ollama installed: https://ollama.com/download
- Model downloaded (e.g., mistral)

Run this to start the LLM:
```bash
ollama run mistral
```

## 🚀 Setup Instructions

1. Navigate to the project folder:
```bash
cd mcp_server_python
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the server:
```bash
uvicorn main:main --reload --port 8000
```

4. Test the API:
```bash
curl -X POST http://localhost:8000/api/chat   -H "Content-Type: application/json"   -d '{"sessionId":"demo", "message":"What time is it?"}'
```

If everything works, you'll get the current time returned via a tool call.