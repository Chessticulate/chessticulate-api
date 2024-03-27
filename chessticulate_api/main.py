"""app.main

Contains the main FastAPI object definition.

Variables:
    chess_app
"""

from fastapi import FastAPI

from chessticulate_api import models, routers

app = FastAPI()


@app.on_event("startup")
async def on_startup_and_shutdown():
    """initialize database with DDL"""

    await models.init_db()


app.include_router(routers.v1.router)
