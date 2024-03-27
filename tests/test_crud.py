from datetime import datetime, timedelta, timezone

import jwt
import pytest
import sqlalchemy
from pydantic import SecretStr

from chessticulate_api import crud, models
from chessticulate_api.config import CONFIG


def test_password_hashing():
    pswd = SecretStr("test password")

    pswd_hash = crud._hash_password(pswd)

    assert crud._check_password(pswd, pswd_hash)


class TestGetUsers:
    @pytest.mark.parametrize(
        "query_params",
        [
            {"id_": 42069},
            {"name": "nonexistentuser"},
            {"id_": 1, "name": "fakeuser2"},
            {"wins": 100},
        ],
    )
    @pytest.mark.asyncio
    async def test_get_users_fails_does_not_exist(self, query_params):
        users = await crud.get_users(**query_params)
        assert users == []

    @pytest.mark.parametrize(
        "query_params,expected_count",
        [
            ({"id_": 1}, 1),
            ({"name": "fakeuser2"}, 1),
            ({"wins": 0}, 4),
            ({"deleted": True}, 1),
        ],
    )
    @pytest.mark.asyncio
    async def test_get_users_succeeds(self, query_params, expected_count):
        users = await crud.get_users(**query_params)
        assert len(users) == expected_count

    @pytest.mark.asyncio
    async def test_get_users_order_by(self):
        users = await crud.get_users(order_by="wins", limit=3, skip=3)
        assert len(users) == 3
        assert users[0].wins == 0
        assert users[1].wins == 1
        assert users[2].wins == 2

    @pytest.mark.asyncio
    async def test_get_users_order_by_reverse(self):
        users = await crud.get_users(order_by="wins", limit=3, reverse=True)
        assert len(users) == 3
        assert users[0].wins == 2
        assert users[1].wins == 1
        assert users[2].wins == 0

    @pytest.mark.asyncio
    async def test_get_deleted_users(self):
        users = await crud.get_users(deleted=True)
        assert len(users) == 1

    @pytest.mark.asyncio
    async def test_get_non_deleted_users(self):
        users = await crud.get_users(deleted=False)
        assert len(users) == 5


class TestCreateUser:
    @pytest.mark.asyncio
    async def test_create_user_fails_duplicate_name(self, fake_user_data):
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            await crud.create_user(
                fake_user_data[0]["name"],
                "unique@fakeemail.com",
                SecretStr(fake_user_data[0]["password"]),
            )

    @pytest.mark.asyncio
    async def test_create_user_fails_duplicate_email(self, fake_user_data):
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            await crud.create_user(
                "unique",
                fake_user_data[0]["email"],
                SecretStr(fake_user_data[0]["password"]),
            )

    @pytest.mark.asyncio
    async def test_create_user_succeeds(self, restore_fake_data_after):
        user = await crud.create_user(
            "unique", "unique@fakeemail.com", SecretStr("password")
        )
        assert user is not None
        assert user.name == "unique"
        assert user.email == "unique@fakeemail.com"


class TestDeleteUser:
    @pytest.mark.asyncio
    async def test_delete_user_fails_does_not_exist(self):
        assert await crud.delete_user(42069) == False

    @pytest.mark.asyncio
    async def test_delete_user_succeeds_and_cant_be_deleted_again(
        self, restore_fake_data_after, fake_user_data
    ):
        users = await crud.get_users(name=fake_user_data[0]["name"])
        assert len(users) == 1

        assert await crud.delete_user(users[0].id_) is True

        users = await crud.get_users(name=fake_user_data[0]["name"])
        assert users[0].deleted
        assert await crud.delete_user(users[0].id_) is False


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_fails_user_does_not_exist(self):
        token = await crud.login("doesnotexist", SecretStr("password"))
        assert token is None

    @pytest.mark.asyncio
    async def test_login_fails_bad_password(self, fake_user_data):
        token = await crud.login(fake_user_data[0]["name"], SecretStr("wrongpassword"))
        assert token is None

    @pytest.mark.asyncio
    async def test_login_fails_user_deleted(
        self, fake_user_data, restore_fake_data_after
    ):
        result = await crud.get_users(name=fake_user_data[0]["name"])
        assert len(result) == 1
        user = result[0]
        assert await crud.delete_user(user.id_) is True
        token = await crud.login(
            fake_user_data[0]["name"], SecretStr(fake_user_data[0]["password"])
        )
        assert token is None

    @pytest.mark.asyncio
    async def test_login_succeeds(self, fake_user_data):
        token = await crud.login(
            fake_user_data[0]["name"], SecretStr(fake_user_data[0]["password"])
        )
        assert token is not None


class TestValidateToken:
    @pytest.mark.asyncio
    async def test_validate_token_fails_bad_token(self):
        with pytest.raises(jwt.exceptions.DecodeError):
            crud.validate_token("nonsense")

    @pytest.mark.asyncio
    async def test_validate_token_fails_expired_token(self):
        token = jwt.encode(
            {
                "exp": datetime.now(tz=timezone.utc) - timedelta(days=CONFIG.token_ttl),
                "user_name": "fakeuser1",
            },
            CONFIG.secret,
        )

        with pytest.raises(jwt.exceptions.ExpiredSignatureError):
            assert crud.validate_token(token) is not None

    @pytest.mark.asyncio
    async def test_validate_token_succeeds(self, fake_user_data):
        token = await crud.login(
            fake_user_data[0]["name"], SecretStr(fake_user_data[0]["password"])
        )
        assert token is not None
        decoded_token = crud.validate_token(token)
        assert decoded_token["user_name"] == fake_user_data[0]["name"]


class TestCreateInvitation:
    @pytest.mark.asyncio
    async def test_create_invitation_fails_invitor_does_not_exist(self, fake_user_data):
        result = await crud.get_users(name=fake_user_data[0]["name"])
        assert len(result) == 1
        invitee = result[0]
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            invitation = await crud.create_invitation(42069, invitee.id_)
            print(f"{invitation.from_id=}, {invitation.to_id=}, {invitation.id_=}")

    @pytest.mark.asyncio
    async def test_create_invitation_fails_invitee_does_not_exist(self, fake_user_data):
        result = await crud.get_users(name=fake_user_data[0]["name"])
        assert len(result) == 1
        invitor = result[0]
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            invitation = await crud.create_invitation(invitor.id_, 42069)

    @pytest.mark.asyncio
    async def test_create_invitation_succeeds(
        self, restore_fake_data_after, fake_user_data
    ):
        result = await crud.get_users(name=fake_user_data[0]["name"])
        assert len(result) == 1
        invitor = result[0]

        result = await crud.get_users(name=fake_user_data[1]["name"])
        assert len(result) == 1
        invitee = result[0]

        invitation = await crud.create_invitation(invitor.id_, invitee.id_)
        assert invitation is not None
        assert invitation.from_id == invitor.id_
        assert invitation.to_id == invitee.id_
        assert invitation.status == models.InvitationStatus.PENDING
        assert invitation.game_type == models.GameType.CHESS


class TestGetInvitations:
    @pytest.mark.parametrize(
        "query_params",
        [
            {"id_": 42069},
            {"to_id": 42069},
            {"from_id": 2, "to_id": 1},
            {"from_id": 3, "to_id": 1, "status": models.InvitationStatus.PENDING},
        ],
    )
    @pytest.mark.asyncio
    async def test_get_invitations_fails_doesnt_exist(self, query_params):
        invitations = await crud.get_invitations(**query_params)
        assert invitations == [], (
            f"id_={invitations[0].id_}, status={invitations[0].status},"
            f" deleted={invitations[0].deleted}"
        )

    @pytest.mark.parametrize(
        "query_params,expected_count",
        [
            ({"status": models.InvitationStatus.ACCEPTED}, 3),
            ({"status": models.InvitationStatus.PENDING}, 1),
            ({"from_id": 1}, 4),
            ({"to_id": 3}, 1),
        ],
    )
    @pytest.mark.asyncio
    async def test_get_invitations_succeeds(self, query_params, expected_count):
        invitations = await crud.get_invitations(**query_params)
        assert len(invitations) == expected_count


class TestCancelInvitation:
    @pytest.mark.asyncio
    async def test_cancel_invitation_fails_doesnt_exist(self):
        assert await crud.cancel_invitation(42069) is False

    @pytest.mark.parametrize("id_", (1, 5, 6))
    @pytest.mark.asyncio
    async def test_cancel_invitation_fails_not_pending(self, id_):
        assert await crud.cancel_invitation(id_) is False

    @pytest.mark.parametrize("id_", (4,))
    @pytest.mark.asyncio
    async def test_cancel_invitation_succeeds(self, restore_fake_data_after, id_):
        result = await crud.get_invitations(id_=id_)
        assert len(result) == 1
        invitation = result[0]

        assert invitation.status == models.InvitationStatus.PENDING
        assert await crud.cancel_invitation(id_) is True

        result = await crud.get_invitations(id_=id_)
        assert len(result) == 1
        invitation = result[0]

        assert invitation.status == models.InvitationStatus.CANCELLED


class TestDeclineInvitation:
    @pytest.mark.asyncio
    async def test_decline_invitation_fails_doesnt_exist(self):
        assert await crud.decline_invitation(42069) is False

    @pytest.mark.parametrize("id_", (1, 5, 6))
    @pytest.mark.asyncio
    async def test_decline_invitation_fails_not_pending(self, id_):
        assert await crud.decline_invitation(id_) is False

    @pytest.mark.parametrize("id_", (4,))
    @pytest.mark.asyncio
    async def test_decline_invitation_succeeds(self, restore_fake_data_after, id_):
        result = await crud.get_invitations(id_=id_)
        assert len(result) == 1
        invitation = result[0]

        assert invitation.status == models.InvitationStatus.PENDING
        assert await crud.decline_invitation(id_) is True

        result = await crud.get_invitations(id_=id_)
        assert len(result) == 1
        invitation = result[0]

        assert invitation.status == models.InvitationStatus.DECLINED


class TestAcceptInvitation:
    @pytest.mark.asyncio
    async def test_accept_invitation_fails_doesnt_exist(self):
        assert await crud.accept_invitation(42069) is None

    @pytest.mark.parametrize("id_", (1, 5, 6))
    @pytest.mark.asyncio
    async def test_accept_invitation_fails_not_pending(self, id_):
        assert await crud.accept_invitation(id_) is None

    @pytest.mark.parametrize("id_", (4,))
    @pytest.mark.asyncio
    async def test_accept_invitation_succeeds(self, restore_fake_data_after, id_):
        result = await crud.get_invitations(id_=id_)
        assert len(result) == 1
        invitation = result[0]
        assert invitation.status == models.InvitationStatus.PENDING

        game = await crud.accept_invitation(id_)

        result = await crud.get_invitations(id_=id_)
        assert len(result) == 1
        invitation = result[0]
        assert invitation.status == models.InvitationStatus.ACCEPTED

        assert game is not None
        assert game.invitation_id == invitation.id_
        assert game.player_1 == invitation.from_id
        assert game.player_2 == invitation.to_id


class TestGetGames:
    @pytest.mark.parametrize(
        "query_params",
        [
            {"id_": 42069},
            {"player_1": 1234},
            {"player_2": 1, "player_1": -1},
            {"whomst": 6},
            {"winner": 10},
        ],
    )
    @pytest.mark.asyncio
    async def test_get_games_fails_does_not_exist(self, query_params):
        games = await crud.get_games(**query_params)
        assert games == []

    @pytest.mark.parametrize(
        "query_params,expected_count",
        [
            ({"id_": 2}, 1),
            ({"player_1": 3}, 1),
            ({"player_1": 2, "player_2": 3}, 1),
        ],
    )
    @pytest.mark.asyncio
    async def test_get_games_succeeds(self, query_params, expected_count):
        games = await crud.get_games(**query_params)
        assert len(games) == expected_count

    @pytest.mark.asyncio
    async def test_get_games_order_by(self):
        games = await crud.get_games(order_by="whomst", limit=3, skip=1)
        assert len(games) == 2
        assert games[0].whomst == 2
        assert games[1].whomst == 3

    @pytest.mark.asyncio
    async def test_get_games_order_by_reverse(self):
        games = await crud.get_games(order_by="whomst", limit=3, reverse=True)
        assert len(games) == 3
        assert games[0].whomst == 3
        assert games[1].whomst == 2
        assert games[2].whomst == 1


class TestDoMove:
    @pytest.mark.parametrize(
        "id_, new_state",
        [
            (
                {"id_": 1},
                {
                    "state": (
                        '{ "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq'
                        ' e3 0 1", "states": { "-1219502575": "2", "-1950040747": "2",'
                        ' "1823187191": "1", "1287635123": "1" } }'
                    )
                },
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_do_move_succeeds(self, id_, new_state):
        # valid game id is required
        game = await crud.get_games(**id_)
        await crud.do_move(id_["id_"], new_state["state"])
