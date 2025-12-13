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


class TestCreateInvitation:
    @pytest.mark.asyncio
    async def test_create_invitation_fails_invitor_does_not_exist(self, fake_user_data):
        result = await crud.get_users(name=fake_user_data[0]["name"])
        assert len(result) == 1
        invitee = result[0]
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            invitation = await crud.create_invitation(42069, invitee.id_)

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
            {"from_id": 2, "to_id": 10},
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
            ({"status": models.InvitationStatus.PENDING}, 3),
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
        invitation = result[0]["invitation"]

        assert invitation.status == models.InvitationStatus.PENDING
        assert await crud.cancel_invitation(id_) is True

        result = await crud.get_invitations(id_=id_)
        assert len(result) == 1
        invitation = result[0]["invitation"]

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
        invitation = result[0]["invitation"]

        assert invitation.status == models.InvitationStatus.PENDING
        assert await crud.decline_invitation(id_) is True

        result = await crud.get_invitations(id_=id_)
        assert len(result) == 1
        invitation = result[0]["invitation"]

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
        invitation = result[0]["invitation"]
        assert invitation.status == models.InvitationStatus.PENDING

        game = await crud.accept_invitation(id_)

        result = await crud.get_invitations(id_=id_)
        assert len(result) == 1
        invitation = result[0]["invitation"]
        assert invitation.status == models.InvitationStatus.ACCEPTED
        assert invitation.date_answered != None

        assert game is not None
        assert game.invitation_id == invitation.id_


class TestGetGames:
    @pytest.mark.parametrize(
        "query_params",
        [
            {"id_": 42069},
            {"white": 1234},
            {"black": 1, "white": -1},
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
            ({"white": 3}, 1),
            ({"white": 2, "black": 3}, 1),
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
        assert games[0]["game"].whomst == 2
        assert games[1]["game"].whomst == 3

    @pytest.mark.asyncio
    async def test_get_games_order_by_reverse(self):
        games = await crud.get_games(order_by="whomst", limit=3, reverse=True)
        assert len(games) == 3
        assert games[0]["game"].whomst == 3
        assert games[1]["game"].whomst == 2
        assert games[2]["game"].whomst == 1

    @pytest.mark.asyncio
    async def test_get_games_succeeds_move_hist(self):
        games = await crud.get_games(id_=1)
        assert games[0]["move_hist"] == ["e4"]


class TestDoMove:
    @pytest.mark.parametrize(
        "game_id, user_id, whomst, move, states, fen, status",
        [
            (
                1,
                1,
                2,
                "e4",
                '{ "-1219502575": "2", "-1950040747": "2", "1823187191": "1", "1287635123": "1" }',
                "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                "MOVEOK",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_do_move_succeeds(
        self,
        game_id,
        user_id,
        whomst,
        move,
        states,
        fen,
        status,
        restore_fake_data_after,
    ):
        # assert default game.state
        game = await crud.get_games(id_=game_id)
        assert game[0]["game"].states == "{}"
        assert (
            game[0]["game"].fen
            == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        )

        await crud.do_move(game_id, user_id, whomst, move, states, fen, status)

        game_after_move = await crud.get_games(id_=game_id)
        assert (
            game_after_move[0]["game"].fen
            == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        )
        assert (
            game_after_move[0]["game"].states
            == '{ "-1219502575": "2", "-1950040747": "2", "1823187191": "1", "1287635123": "1" }'
        )
        assert game_after_move[0]["game"].last_active != None
        assert game_after_move[0]["game"].winner == None
        assert game_after_move[0]["game"].result == None
        assert game_after_move[0]["game"].is_active == True
        # assert that it is blacks turn after white moves
        assert game_after_move[0]["game"].whomst == 2

    @pytest.mark.parametrize(
        "game_id, user_id, whomst, move, states, fen, status",
        [
            (
                1,
                1,
                2,
                "e4",
                '{ "-1219502575": "2", "-1950040747": "2", "1823187191": "1", "1287635123": "1" }',
                "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                "CHECKMATE",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_do_move_succeeds_gameover(
        self,
        game_id,
        user_id,
        whomst,
        move,
        states,
        fen,
        status,
        restore_fake_data_after,
    ):
        # assert default game.state
        game = await crud.get_games(id_=game_id)

        await crud.do_move(game_id, user_id, whomst, move, states, fen, status)
        game_after_move = await crud.get_games(id_=game_id)

        assert game_after_move[0]["game"].last_active != None
        assert game_after_move[0]["game"].winner == user_id
        assert game_after_move[0]["game"].is_active == False
        assert game_after_move[0]["game"].result == models.GameResult.CHECKMATE


class TestCreateChallenge:
    @pytest.mark.asyncio
    async def test_create_challenge_fails_requester_does_not_exist(self):
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            await crud.create_challenge(42069)

    @pytest.mark.asyncio
    async def test_create_challenge_succeeds(self, restore_fake_data_after):
        requester_id = 1

        challenge = await crud.create_challenge(requester_id)

        assert challenge is not None
        assert challenge.requester_id == requester_id
        assert challenge.status == models.ChallengeRequestStatus.PENDING
        assert challenge.fulfilled_by is None
        assert challenge.game_id is None
        assert challenge.game_type == models.GameType.CHESS


class TestGetChallenges:
    @pytest.mark.asyncio
    async def test_get_challenges_fails_does_not_exist(self):
        challenges = await crud.get_challenges(id_=42069)
        assert challenges == []

    @pytest.mark.asyncio
    async def test_get_challenges_succeeds_includes_username(
        self, restore_fake_data_after
    ):
        requester_id = 1
        requester = (await crud.get_users(id_=requester_id))[0]

        created = await crud.create_challenge(requester_id)

        rows = await crud.get_challenges(id_=created.id_)
        assert len(rows) == 1

        row = rows[0]
        assert "challenge" in row
        assert "requester_username" in row

        challenge = row["challenge"]
        assert challenge.id_ == created.id_
        assert challenge.requester_id == requester_id
        assert row["requester_username"] == requester.name

    @pytest.mark.asyncio
    async def test_get_challenges_filters(self, restore_fake_data_after):
        requester_id = 1

        c1 = await crud.create_challenge(requester_id)
        c2 = await crud.create_challenge(requester_id)

        rows = await crud.get_challenges(requester_id=requester_id)
        ids = [r["challenge"].id_ for r in rows]
        assert c1.id_ in ids
        assert c2.id_ in ids

        # filter by id_
        rows = await crud.get_challenges(id_=c1.id_)
        assert len(rows) == 1
        assert rows[0]["challenge"].id_ == c1.id_

        # filter by status
        rows = await crud.get_challenges(status=models.ChallengeRequestStatus.PENDING)
        pending_ids = [r["challenge"].id_ for r in rows]
        assert c1.id_ in pending_ids
        assert c2.id_ in pending_ids


class TestAcceptChallenge:
    @pytest.mark.asyncio
    async def test_accept_challenge_fails_doesnt_exist(self):
        assert await crud.accept_challenge(42069, 2) is None

    @pytest.mark.asyncio
    async def test_accept_challenge_fails_not_pending(self, restore_fake_data_after):
        requester_id = 1
        acceptor_id = 2

        challenge = await crud.create_challenge(requester_id)

        game1 = await crud.accept_challenge(challenge.id_, acceptor_id)
        assert game1 is not None

        game2 = await crud.accept_challenge(challenge.id_, acceptor_id)
        assert game2 is None

    @pytest.mark.asyncio
    async def test_accept_challenge_succeeds_sets_fields_and_creates_game(
        self, restore_fake_data_after
    ):
        requester_id = 1
        acceptor_id = 2

        challenge = await crud.create_challenge(requester_id)
        assert challenge.status == models.ChallengeRequestStatus.PENDING
        assert challenge.fulfilled_by is None
        assert challenge.game_id is None

        game = await crud.accept_challenge(challenge.id_, acceptor_id)
        assert game is not None

        assert game.challenge_id == challenge.id_
        assert game.invitation_id is None
        assert game.game_type == models.GameType.CHESS

        assert set([game.white, game.black]) == set([requester_id, acceptor_id])
        assert game.whomst in (game.white, game.black)

        rows = await crud.get_challenges(id_=challenge.id_, limit=1)
        assert len(rows) == 1
        updated = rows[0]["challenge"]

        assert updated.status == models.ChallengeRequestStatus.ACCEPTED
        assert updated.fulfilled_by == acceptor_id
        assert updated.game_id == game.id_


class TestCancelChallenge:
    @pytest.mark.asyncio
    async def test_cancel_challenge_fails_doesnt_exist(self):
        assert await crud.cancel_challenge(42069) is False

    @pytest.mark.asyncio
    async def test_cancel_challenge_fails_not_pending(self, restore_fake_data_after):
        requester_id = 1
        acceptor_id = 2

        challenge = await crud.create_challenge(requester_id)
        game = await crud.accept_challenge(challenge.id_, acceptor_id)
        assert game is not None

        assert await crud.cancel_challenge(challenge.id_) is False

    @pytest.mark.asyncio
    async def test_cancel_challenge_succeeds(self, restore_fake_data_after):
        requester_id = 1
        challenge = await crud.create_challenge(requester_id)

        rows = await crud.get_challenges(id_=challenge.id_, limit=1)
        assert len(rows) == 1
        assert rows[0]["challenge"].status == models.ChallengeRequestStatus.PENDING

        assert await crud.cancel_challenge(challenge.id_) is True

        rows = await crud.get_challenges(id_=challenge.id_, limit=1)
        assert len(rows) == 1
        assert rows[0]["challenge"].status == models.ChallengeRequestStatus.CANCELLED
