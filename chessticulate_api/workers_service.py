"""chessticulate_api.security"""

import httpx

from chessticulate_api.config import CONFIG


class ServerRequestError(Exception):
    """Server Request Error Exception class"""

    def __init__(self, detail: str):
        self.detail = detail


class ClientRequestError(Exception):
    """CLient Request Error Exception class"""

    def __init__(self, detail: str):
        self.detail = detail


async def do_move(fen: str, move: str, states: dict[str, int]):
    """do move request to chess-workers service"""
    client = httpx.AsyncClient()
    try:
        response = await client.post(
            f"{CONFIG.workers_base_url}/move",
            json={"fen": fen, "move": move, "states": states},
        )
        if response.status_code == 200:
            return response.json()

        if 400 <= response.status_code < 500:
            raise ClientRequestError(response.json())

        raise ServerRequestError(response.json())

    finally:
        await client.aclose()


async def suggest_move(fen: str, states: dict[str, str]):
    """suggest move request to chess-workers service"""
    client = httpx.AsyncClient()
    try:
        response = await client.post(
            f"{CONFIG.workers_base_url}/suggest", json={"fen": fen, "states": states}
        )
        if response.status_code == 200:
            return response.json()

        if 400 <= response.status_code < 500:
            if response.json()["message"] in [
                "the game is already over",
            ]:
                raise ClientRequestError(response.json())

        raise ServerRequestError(response.json())

    finally:
        await client.aclose()
