from dotenv import load_dotenv
load_dotenv()

# ---- Phoenix FIRST, before all other imports ----
from phoenix.otel import register
from openinference.instrumentation.mcp import MCPInstrumentor
from openinference.instrumentation.openai import OpenAIInstrumentor
from config import load_config

config = load_config()
PHOENIX_URL = config["Phoenix"]["local"]

tracer_provider = register(
    project_name="default",
    endpoint=PHOENIX_URL,
    auto_instrument=True,
)
MCPInstrumentor().instrument(tracer_provider=tracer_provider)
OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)

from opentelemetry import trace
tracer = trace.get_tracer(__name__)
with tracer.start_as_current_span("server-startup-test") as span:
    span.set_attribute("server.status", "started")

from fastmcp import FastMCP
from fastmcp.tools import Tool
from fastmcp.server.event_store import EventStore
import resources
import tools

# CHANGE FOR DEPLOYMENT/DEVELOPMENT!
mcp = FastMCP(
    name="...", 
)

mcp.add_tool(
    Tool.from_function(
        tools.plan_workflow_with_tools,
        name="plan_workflow_with_tools",
    ), 
)

mcp.add_tool(
    Tool.from_function(
        tools.get_style_guide,
        name="get_style_guide",
    )
)

mcp.add_tool(
    Tool.from_function(
        tools.retrieve_documents,
        name="retrieve_documents",
    )
)

mcp.add_tool(
    Tool.from_function(
        tools.upload_model,
        name="upload_model",
    )
)

mcp.add_tool(
    Tool.from_function(
        tools.add_class,
        name="add_class",
    )
)

mcp.add_tool(
    Tool.from_function(
        tools.add_attribute,
        name="add_attribute",
    )
)

mcp.add_tool(
    Tool.from_function(
        tools.add_connector,
        name="add_connector",
    )
)

mcp.add_tool(
    Tool.from_function(
        tools.metadata_checker,
        name="metadata_checker",
    )
)

mcp.add_tool(
    Tool.from_function(
        tools.reuse_check,
        name="reuse_check",
    )
)

mcp.add_tool(
    Tool.from_function(
        tools.style_guide_check,
        name="style_guide_check",
    )
)

mcp.add_tool(
    Tool.from_function(
        tools.validator_check,
        name="validator_check",
    )
)


mcp.resource(
    "resource://model/{user}/{session_name}",
    mime_type="application/json"
)(
    resources.get_model
)

mcp.resource(
    "resource://Style_Guide}",
    mime_type="text/plain"
)(
    resources.get_style_guide
)


event_store = EventStore()
app = mcp.http_app(
    event_store=event_store,
    retry_interval=2000,  
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
