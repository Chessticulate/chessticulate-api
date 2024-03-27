import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chessticulate_api.routers.v1.main import router

client = TestClient(router)


def test_login(init_fake_user_data):

    # valid login
    response = client.post(
        "/login",
        headers={},
        json={"name": "fakeuser1", "password": "fakepswd1"},
    )
    resp = response.json()

    assert response.status_code == 200
    assert resp is not None and "jwt" in resp
    decoded_token = jwt.decode(resp["jwt"], options={"verify_signature": False})
    assert decoded_token["user_name"] == "fakeuser1"


def test_signup():
    # invalid signup, password too short
    bad_response = client.post(
        "/signup",
        headers={},
        json={"name": "baduser", "email": "baduser@email.com", "password": "pswd"},
    )

    assert bad_response.status_code == 401

    # valid signup
    response = client.post(
        "/signup",
        headers={},
        json={
            "name": "ChessFan12",
            "email": "chessfan@email.com",
            "password": "Knightc3!",
        },
    )

    assert response.status_code == 200

def test_get_user():
    response = client.get("/user")
    assert response.status_code == 400

    id_response = client.get("/user?user_id=1")
    assert id_response.status_code == 200 

    name_response = client.get("/user?user_name=fakeuser1")
    assert name_response.status_code == 200

