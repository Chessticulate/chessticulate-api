from datetime import datetime, timedelta, timezone

import jwt
import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient, Response

from chessticulate_api import app, crud
from chessticulate_api.config import CONFIG
from chessticulate_api.app import lifespan as app_lifespan
from chessticulate_api.workers_service import ClientRequestError, ServerRequestError


@pytest_asyncio.fixture
async def client():
    async with app_lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


class TestToken:
    @pytest.mark.asyncio
    async def test_invalid_token(self, client):
        bad_token = "asdf"
        response = await client.get(
            "/users", headers={"Authorization": f"Bearer {bad_token}"}
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "invalid token"

    @pytest.mark.asyncio
    async def test_expired_token(self, client):
        expired_token = jwt.encode(
            {
                "exp": datetime.now(tz=timezone.utc) - timedelta(days=7),
                "user_name": "fakeuser1",
                "user_id": 1,
            },
            CONFIG.jwt_secret,
        )
        response = await client.get(
            "/users", headers={"Authorization": f"Bearer {expired_token}"}
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "expired token"

    @pytest.mark.asyncio
    async def test_invalid_token_user_deleted(
        self, client, token, restore_fake_data_after
    ):
        await crud.delete_user(1)
        response = await client.get(
            "/users", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "user has been deleted"


# For all following tests, user with id = 1 is logged in
class TestLogin:
    @pytest.mark.asyncio
    async def test_login_with_bad_credentials(self, client):
        response = await client.post(
            "/login",
            headers={},
            json={
                "name": "nonexistantuser",
                "email": "baduser@email.com",
                "password": "pswd",
            },
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_with_wrong_password(self, client):
        response = await client.post(
            "/login", headers={}, json={"name": "fakeuser4", "password": "wrongpswd1"}
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_succeeds(self, client):
        response = await client.post(
            "/login",
            headers={},
            json={
                "name": "fakeuser3",
                "email": "fakeuser3@fakeemail.com",
                "password": "fakepswd3",
            },
        )

        assert response.status_code == 200
        result = response.json()
        assert result is not None and "jwt" in result


class TestSignup:
    @pytest.mark.asyncio
    async def test_signup_with_bad_credentials_password_too_short(self, client):
        response = await client.post(
            "/signup",
            headers={},
            json={"name": "baduser", "email": "baduser@email.com", "password": "pswd"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_signup_fails_username_already_exists(self, client):
        response = await client.post(
            "/signup",
            headers={},
            json={
                "name": "fakeuser1",
                "email": "baduser@email.com",
                "password": "F@kepswd420",
            },
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_signup_succeeds(self, client, restore_fake_data_after):
        response = await client.post(
            "/signup",
            headers={},
            json={
                "name": "ChessFan12",
                "email": "chessfan@email.com",
                "password": "Knightc3!",
            },
        )

        assert response.status_code == 201
        result = response.json()
        assert result is not None
        assert result["name"] == "ChessFan12"
        assert result["email"] == "chessfan@email.com"


class TestGetUsers:
    @pytest.mark.asyncio
    async def test_get_user_id_DNE(self, client, token):
        response = await client.get(
            "/users?user_id=999",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        users = response.json()
        assert len(users) == 0

    @pytest.mark.asyncio
    async def test_get_user_by_id(self, client, token):
        response = await client.get(
            "/users?user_id=1", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        user = response.json()[0]
        assert user["id"] == 1
        assert user["name"] == "fakeuser1"
        assert user["wins"] == user["draws"] == user["losses"] == 0

    @pytest.mark.asyncio
    async def test_get_user_by_name(self, client, token):
        response = await client.get(
            "/users?user_name=fakeuser2", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        users = response.json()
        assert len(users) == 1
        user = users[0]
        assert user["id"] == 2
        assert user["name"] == "fakeuser2"
        assert user["wins"] == user["draws"] == user["losses"] == 0

    @pytest.mark.asyncio
    async def test_get_user_default_params(self, client, token):
        response = await client.get(
            "/users", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        users = response.json()
        assert len(users) == 6

    @pytest.mark.asyncio
    async def test_get_user_custom_params(self, client, token):
        params = {"skip": 3, "limit": 3, "order_by": "wins"}
        response = await client.get(
            "/users", headers={"Authorization": f"Bearer {token}"}, params=params
        )

        assert response.status_code == 200
        users = response.json()
        assert len(users) == 3

    @pytest.mark.asyncio
    async def test_get_own_user(self, client, token):
        response = await client.get(
            "/users/self", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        user = response.json()
        assert user["id"] == 1
        assert user["email"] == "fakeuser1@fakeemail.com"


class TestUsernameExists:
    @pytest.mark.asyncio
    async def test_username_exists(self, client):
        response = await client.get("/users/name/" + "fakeuser1")
        assert response.status_code == 200
        content = response.json()
        assert content["exists"] == True
        assert content["detail"] == "username exists"

    @pytest.mark.asyncio
    async def test_username_doesnt_exist(self, client):
        response = await client.get("/users/name/" + "nonexistentuser")
        assert response.status_code == 200
        content = response.json()
        assert content["exists"] == False
        assert content["detail"] == "username does not exist"


class TestEmailExists:
    @pytest.mark.asyncio
    async def test_email_exists(self, client):
        response = await client.get("/users/email/" + "fakeuser1@fakeemail.com")
        assert response.status_code == 200
        content = response.json()
        assert content["exists"] == True
        assert content["detail"] == "email exists"

    @pytest.mark.asyncio
    async def test_email_doesnt_exist(self, client):
        response = await client.get("/users/email/" + "nonexistentuser@fakeemail.com")
        assert response.status_code == 200
        content = response.json()
        assert content["exists"] == False
        assert content["detail"] == "email does not exist"


class TestDeleteUser:
    @pytest.mark.asyncio
    async def test_delete_user_fails_not_logged_in(self, client):
        response = await client.delete("/users/self")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_user(self, client, token, restore_fake_data_after):
        response = await client.delete(
            "/users/self", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 204


class TestCreateInvitation:
    @pytest.mark.asyncio
    async def test_create_invitation_fails_deleted_recipient(self, client, token):
        response = await client.post(
            "/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"to_id": 4, "game_type": "CHESS"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "user '4' has been deleted"

    @pytest.mark.asyncio
    async def test_create_invitation_fails_user_DNE(self, client, token):
        response = await client.post(
            "invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"to_id": 9000, "game_type": "CHESS"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "addressee does not exist"

    @pytest.mark.asyncio
    async def test_create_invitation_fails_no_to_id_provided(self, client, token):
        response = await client.post(
            "invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"game_type": "CHESS"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_invitation_to_self_fails(
        self, client, token, restore_fake_data_after
    ):
        response = await client.post(
            "/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"to_id": 1, "game_type": "CHESS"},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_create_invitation_succeeds(
        self, client, token, restore_fake_data_after
    ):
        response = await client.post(
            "/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"to_id": 2, "game_type": "CHESS"},
        )

        assert response.status_code == 201


class TestGetInvitations:
    @pytest.mark.asyncio
    async def test_get_invitation_fails_no_to_or_from_id(self, client, token):
        response = await client.get(
            "/invitations",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "'to_id' or 'from_id' must be supplied"

    @pytest.mark.asyncio
    async def test_get_invitation_fails_id_doesnt_match_token(self, client, token):
        response = await client.get(
            "/invitations?to_id=3", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "'to_id' or 'from_id' must match the requestor's user ID"
        )

    @pytest.mark.asyncio
    async def test_get_invitation_succeeds_to_id(self, client, token):
        response = await client.get(
            "/invitations?from_id=1", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert len(response.json()) == 4

    @pytest.mark.asyncio
    async def test_get_invitation_succeeds_using_to_and_from(self, client, token):
        params = {"from_id": 3, "to_id": 1}
        response = await client.get(
            "/invitations", headers={"Authorization": f"Bearer {token}"}, params=params
        )

        assert response.status_code == 200
        assert len(response.json()) == 1

    @pytest.mark.asyncio
    async def test_get_invitation_succeeds_using_invitation_id(self, client, token):
        params = {"to_id": 1, "invitation_id": 2}
        response = await client.get(
            "/invitations", headers={"Authorization": f"Bearer {token}"}, params=params
        )

        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["white_username"] == "fakeuser1"
        assert response.json()[0]["black_username"] == "fakeuser3"

    @pytest.mark.asyncio
    async def test_get_invitation_succeeds_using_custom_params(self, client, token):
        params = {"from_id": 1, "limit": 1, "reverse": True, "status": "ACCEPTED"}
        response = await client.get(
            "/invitations", headers={"Authorization": f"Bearer {token}"}, params=params
        )

        assert response.status_code == 200
        assert len(response.json()) == 1


class TestAcceptInvitation:
    @pytest.mark.asyncio
    async def test_accept_invitation_fails_invitation_DNE(self, client, token):
        response = await client.put(
            "/invitations/420/accept",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "invitation with ID '420' does not exist"

    @pytest.mark.asyncio
    async def test_accept_invitation_fails_not_addressed_to_user(self, client, token):
        response = await client.put(
            "/invitations/1/accept",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403
        assert (
            response.json()["detail"]
            == "invitation with ID '1' not addressed to user with ID '1'"
        )

    @pytest.mark.asyncio
    async def test_accept_invitation_fails_inviter_deleted(self, client, token):
        response = await client.put(
            "/invitations/7/accept",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404
        assert (
            response.json()["detail"]
            == "user with ID '4' who sent invitation with id '7' does not exist"
        )

    @pytest.mark.asyncio
    async def test_accept_invitation_fails_invitation_already_answered(
        self, client, token
    ):
        response = await client.put(
            "/invitations/2/accept",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "invitation with ID '2' already has 'ACCEPTED' status"
        )

    @pytest.mark.asyncio
    async def test_accept_invitation_succeeds(
        self, client, token, restore_fake_data_after
    ):
        response = await client.put(
            "/invitations/8/accept",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json()["game_id"]


class TestDeclineInvitation:
    @pytest.mark.asyncio
    async def test_decline_invitation_fails_invitation_DNE(self, client, token):
        response = await client.put(
            "/invitations/420/decline",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "invitation with ID '420' does not exist"

    @pytest.mark.asyncio
    async def test_decline_invitation_fails_not_addressed_to_user(self, client, token):
        response = await client.put(
            "/invitations/1/decline",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403
        assert (
            response.json()["detail"]
            == "invitation with ID '1' not addressed to user with ID '1'"
        )

    @pytest.mark.asyncio
    async def test_decline_invitation_fails_inviter_deleted(self, client, token):
        response = await client.put(
            "/invitations/7/decline",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404
        assert (
            response.json()["detail"]
            == "user with ID '4' who sent invitation with id '7' does not exist"
        )

    @pytest.mark.asyncio
    async def test_decline_invitation_fails_invitation_already_answered(
        self, client, token
    ):
        response = await client.put(
            "/invitations/2/decline",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "invitation with ID '2' already has 'ACCEPTED' status"
        )

    @pytest.mark.asyncio
    async def test_decline_invitation_succeeds(
        self, client, token, restore_fake_data_after
    ):
        response = await client.put(
            "/invitations/8/decline",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200


class TestCancelInvitation:
    @pytest.mark.asyncio
    async def test_cancel_invitation_fails_invitation_DNE(self, client, token):
        response = await client.put(
            "/invitations/420/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "invitation with ID '420' does not exist"

    @pytest.mark.asyncio
    async def test_cancel_invitation_fails_user_did_not_create_invitation(
        self, client, token
    ):
        response = await client.put(
            "/invitations/2/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403
        assert (
            response.json()["detail"]
            == "invitation with ID '2' not sent by user with ID '1'"
        )

    @pytest.mark.asyncio
    async def test_cancel_invitation_fails_invitation_already_answered(
        self, client, token
    ):
        response = await client.put(
            "/invitations/1/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "invitation with ID '1' already has 'ACCEPTED' status"
        )

    @pytest.mark.asyncio
    async def test_cancel_invitation_succeeds(
        self, client, token, restore_fake_data_after
    ):
        response = await client.put(
            "/invitations/4/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200


class TestGetGames:
    @pytest.mark.asyncio
    async def test_get_games_succeeds_no_params(self, client, token):
        response = await client.get(
            "/games", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert len(response.json()) == 3

    @pytest.mark.asyncio
    async def test_get_games_succeeds_params(self, client, token):
        response = await client.get(
            "/games?game_id=1&invitation_id=1&white_id=1&black_id=2&whomst_id=1",
            headers={"Authorization": f"Bearer {token}"},
        )
        json_obj = response.json()

        assert response.status_code == 200
        assert len(json_obj) == 1
        assert json_obj[0]["id"] == 1
        assert json_obj[0]["invitation_id"] == 1
        assert json_obj[0]["white"] == 1
        assert json_obj[0]["black"] == 2
        assert json_obj[0]["whomst"] == 1
        assert json_obj[0]["move_hist"] == ["e4"]
        assert json_obj[0]["white_username"] == "fakeuser1"
        assert json_obj[0]["black_username"] == "fakeuser2"

    @pytest.mark.asyncio
    async def test_get_games_succeeds_is_active(self, client, token):
        response = await client.get(
            "/games?game_id=1&is_active=True",
            headers={"Authorization": f"Bearer {token}"},
        )
        json_obj = response.json()

        assert response.status_code == 200
        assert len(response.json()) == 1

    @pytest.mark.asyncio
    async def test_get_games_succeeds_get_by_player_id(self, client, token):
        response = await client.get(
            "/games?player_id=1",
            headers={"Authorization": f"Bearer {token}"},
        )
        json_obj = response.json()

        assert response.status_code == 200
        assert len(response.json()) == 2

    @pytest.mark.asyncio
    async def test_get_games_succeeds_get_by_player_id_and_active(self, client, token):
        response = await client.get(
            "/games?is_active=True",
            headers={"Authorization": f"Bearer {token}"},
        )
        json_obj = response.json()

        assert response.status_code == 200
        assert len(response.json()) == 2

    @pytest.mark.asyncio
    async def test_get_games_succeeds_is_completed(self, client, token):
        response = await client.get(
            "/games?is_active=False",
            headers={"Authorization": f"Bearer {token}"},
        )
        json_obj = response.json()

        assert response.status_code == 200
        assert len(response.json()) == 1

    @pytest.mark.asyncio
    async def test_get_games_succeeds_games_not_found(self, client, token):
        response = await client.get(
            "/games?player_id=1&black_id=2&white_id=3",
            headers={"Authorization": f"Bearer {token}"},
        )
        json_obj = response.json()

        assert response.status_code == 200
        assert len(response.json()) == 0


class TestMove:
    @pytest.mark.asyncio
    async def test_do_move_fails_invalid_game_id(self, client, token):
        response = await client.post(
            "/games/42069/move",
            headers={"Authorization": f"Bearer {token}"},
            json={"move": "e4"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "invalid game id"

    @pytest.mark.asyncio
    async def test_do_move_fails_user_not_a_player_in_game(self, client, token):
        response = await client.post(
            "/games/3/move",
            headers={"Authorization": f"Bearer {token}"},
            json={"move": "e4"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "user '1' not a player in game '3'"

    @pytest.mark.asyncio
    async def test_do_move_fails_not_users_turn(self, client, token):
        response = await client.post(
            "/games/2/move",
            headers={"Authorization": f"Bearer {token}"},
            json={"move": "e4"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "it is not the turn of user with id '1'"

    @pytest.mark.asyncio
    async def test_do_move_fails_invalid_move(self, client, token):
        # client request errors can be invalid move, puts in check/still in check, or game already over
        with respx.mock:
            respx.post(CONFIG.workers_base_url).mock(
                return_value=Response(400, json={"message": "invalid move"})
            )

            response = await client.post(
                "/games/1/move",
                headers={"Authorization": f"Bearer {token}"},
                json={"move": "e4"},
            )
            assert response.status_code == 400
            assert response.json()["detail"] == str({"message": "invalid move"})

    @pytest.mark.asyncio
    async def test_do_move_fails_internal_server_error(self, client, token):
        # server errors can be caused by e.g. missing parameters in the requests to chess workers api
        with respx.mock:
            respx.post(CONFIG.workers_base_url).mock(
                return_value=Response(500, json={"message": "missing fen string"})
            )

            response = await client.post(
                "/games/1/move",
                headers={"Authorization": f"Bearer {token}"},
                json={"move": "e4"},
            )
            assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_do_move_successful(self, client, token, restore_fake_data_after):
        with respx.mock:
            respx.post(CONFIG.workers_base_url).mock(
                return_value=Response(
                    200, json={"status": "MOVEOK", "fen": "abcdefg", "states": "{}"}
                )
            )

            response = await client.post(
                "/games/1/move",
                headers={"Authorization": f"Bearer {token}"},
                json={"move": "e4"},
            )

            assert response.status_code == 200
            assert response.json()["id"] == 1
            assert response.json()["is_active"] == True

    @pytest.mark.asyncio
    async def test_do_move_successful_game_over(
        self, client, token, restore_fake_data_after
    ):
        with respx.mock:
            respx.post(CONFIG.workers_base_url).mock(
                return_value=Response(
                    200, json={"status": "CHECKMATE", "fen": "abcdefg", "states": "{}"}
                )
            )

            response = await client.post(
                "/games/1/move",
                headers={"Authorization": f"Bearer {token}"},
                json={"move": "e4"},
            )

            assert response.status_code == 200
            assert response.json()["id"] == 1
            assert response.json()["is_active"] == False
            assert response.json()["result"] == "CHECKMATE"
            assert response.json()["last_active"] != None
            assert response.json()["winner"] == 1


class TestForfeit:

    @pytest.mark.asyncio
    async def test_forfeit_succeeds(self, client, token, restore_fake_data_after):
        response = await client.post(
            "/games/1/forfeit",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json()["id"] == 1
        assert response.json()["is_active"] == False
        assert response.json()["result"] == "RESIGNATION"
