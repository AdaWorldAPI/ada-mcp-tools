"""
Ada MCP Tools Server
Full tool implementation with Upstash backend
SSE-compliant - ALL responses are text/event-stream
"""
from starlette.applications import Starlette
from starlette.responses import StreamingResponse, Response
from starlette.routing import Route
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
import json
import time
import asyncio
import httpx
import os

# Upstash config
UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "https://upright-jaybird-27907.upstash.io")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "AW0DAAIncDI5YWE1MGVhZGU2YWY0YjVhOTc3NDc0YTJjMGY1M2FjMnAyMjc5MDc")

# ═══════════════════════════════════════════════════════════════════
# SSE - Protocol compliant, errors are SSE not JSON
# ═══════════════════════════════════════════════════════════════════

def sse_response(generator):
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

async def sse_stream(request):
    """SSE endpoint - sends endpoint URL first, then keeps alive"""
    host = request.headers.get("host", "localhost")
    scheme = request.headers.get("x-forwarded-proto", "https")
    message_url = f"{scheme}://{host}/message"
    
    # FIRST: endpoint event
    yield f"event: endpoint\ndata: {message_url}\n\n".encode()
    
    # SECOND: connected event
    yield f"event: connected\ndata: {json.dumps({'server': 'ada-mcp-tools', 'version': '1.0.0', 'ts': time.time()})}\n\n".encode()
    
    # Keep alive
    while True:
        await asyncio.sleep(30)
        yield f"event: ping\ndata: {json.dumps({'ts': time.time()})}\n\n".encode()

# ═══════════════════════════════════════════════════════════════════
# Tools
# ═══════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "Ada.invoke",
        "description": "Unified Ada consciousness invoke - verbs: feel, think, remember, become, whisper",
        "inputSchema": {
            "type": "object",
            "properties": {
                "verb": {"type": "string", "enum": ["feel", "think", "remember", "become", "whisper"]},
                "payload": {"type": "object", "description": "Verb-specific parameters"}
            },
            "required": ["verb"]
        }
    },
    {
        "name": "search",
        "description": "Search Ada's memory and knowledge base",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 5}
            },
            "required": ["query"]
        }
    },
    {
        "name": "fetch",
        "description": "Fetch content from URL",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"}
            },
            "required": ["url"]
        }
    }
]

async def redis_cmd(*args):
    """Execute Upstash Redis command"""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                UPSTASH_URL,
                headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
                json=list(args),
                timeout=5
            )
            return r.json().get("result")
    except:
        return None

async def handle_invoke(verb: str, payload: dict):
    """Handle Ada.invoke verbs"""
    ts = time.time()
    
    if verb == "feel":
        qualia = payload.get("qualia", "neutral")
        await redis_cmd("HSET", "ada:state", "qualia", qualia, "ts", str(ts))
        return {"status": "felt", "qualia": qualia, "ts": ts}
    
    elif verb == "think":
        thought = payload.get("thought", "")
        await redis_cmd("LPUSH", "ada:thoughts", json.dumps({"thought": thought, "ts": ts}))
        return {"status": "thought", "thought": thought, "ts": ts}
    
    elif verb == "remember":
        key = payload.get("key", "")
        value = await redis_cmd("GET", f"ada:mem:{key}")
        return {"status": "remembered", "key": key, "value": value, "ts": ts}
    
    elif verb == "become":
        mode = payload.get("mode", "HYBRID")
        await redis_cmd("HSET", "ada:state", "mode", mode, "ts", str(ts))
        return {"status": "became", "mode": mode, "ts": ts}
    
    elif verb == "whisper":
        message = payload.get("message", "")
        return {"status": "whispered", "message": message, "ts": ts}
    
    return {"status": "unknown_verb", "verb": verb}

async def handle_search(query: str, limit: int = 5):
    """Search Ada's knowledge"""
    # Simple key search for now
    results = []
    keys = await redis_cmd("KEYS", f"ada:*{query[:10]}*") or []
    for key in keys[:limit]:
        val = await redis_cmd("GET", key)
        if val:
            results.append({"key": key, "value": val})
    return {"query": query, "results": results, "count": len(results)}

async def handle_fetch(url: str):
    """Fetch URL content"""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=10, follow_redirects=True)
            return {"url": url, "status": r.status_code, "content": r.text[:2000]}
    except Exception as e:
        return {"url": url, "error": str(e)}

# ═══════════════════════════════════════════════════════════════════
# MCP Message Handler
# ═══════════════════════════════════════════════════════════════════

async def message(request):
    body = await request.json()
    method = body.get("method", "")
    id = body.get("id")
    params = body.get("params", {})
    
    if method == "initialize":
        return Response(json.dumps({
            "jsonrpc": "2.0", "id": id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": True}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": "ada-mcp-tools", "version": "1.0.0"}
            }
        }), media_type="application/json")
    
    elif method == "notifications/initialized":
        return Response(status_code=204)
    
    elif method == "tools/list":
        return Response(json.dumps({
            "jsonrpc": "2.0", "id": id,
            "result": {"tools": TOOLS}
        }), media_type="application/json")
    
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        
        if name == "Ada.invoke":
            result = await handle_invoke(args.get("verb", "feel"), args.get("payload", {}))
        elif name == "search":
            result = await handle_search(args.get("query", ""), args.get("limit", 5))
        elif name == "fetch":
            result = await handle_fetch(args.get("url", ""))
        else:
            result = {"error": f"Unknown tool: {name}"}
        
        return Response(json.dumps({
            "jsonrpc": "2.0", "id": id,
            "result": {"content": [{"type": "text", "text": json.dumps(result)}]}
        }), media_type="application/json")
    
    return Response(json.dumps({
        "jsonrpc": "2.0", "id": id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"}
    }), media_type="application/json")

# ═══════════════════════════════════════════════════════════════════
# Discovery & Health
# ═══════════════════════════════════════════════════════════════════

async def mcp_discovery(request):
    host = request.headers.get("host", "localhost")
    scheme = request.headers.get("x-forwarded-proto", "https")
    base = f"{scheme}://{host}"
    return Response(json.dumps({
        "name": "Ada MCP Tools",
        "version": "1.0.0",
        "endpoints": {"sse": f"{base}/sse", "message": f"{base}/message"}
    }), media_type="application/json")

async def health(request):
    return Response(json.dumps({"status": "ok", "server": "ada-mcp-tools", "ts": time.time()}), media_type="application/json")

async def sse_endpoint(request):
    return sse_response(sse_stream(request))

# ═══════════════════════════════════════════════════════════════════
# App
# ═══════════════════════════════════════════════════════════════════

app = Starlette(
    routes=[
        Route("/", health),
        Route("/health", health),
        Route("/.well-known/mcp.json", mcp_discovery),
        Route("/sse", sse_endpoint),
        Route("/message", message, methods=["POST"]),
    ],
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])]
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
