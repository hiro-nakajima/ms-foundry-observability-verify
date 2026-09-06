import azure.functions as func

from mcp_server import app


main = func.AsgiMiddleware(app).main
