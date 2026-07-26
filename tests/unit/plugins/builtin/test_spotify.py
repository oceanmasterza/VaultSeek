"""Tests for the Spotify client, playlist parsing, and recommender."""

from __future__ import annotations

import responses

from vaultseek.models.interfaces.recommender import RecommendationContext
from vaultseek.plugins.builtin.spotify import (
    SpotifyClient,
    SpotifyPlaylistRecommender,
    parse_playlist_id,
)

_TOKEN_URL = "https://accounts.spotify.com/api/token"
_PLAYLIST = "37i9dQZF1DXcBWIGoYBM5M"
_TRACKS_URL = f"https://api.spotify.com/v1/playlists/{_PLAYLIST}/tracks"


def test_parse_playlist_id_variants() -> None:
    assert parse_playlist_id(f"spotify:playlist:{_PLAYLIST}") == _PLAYLIST
    assert parse_playlist_id(f"https://open.spotify.com/playlist/{_PLAYLIST}?si=abc") == _PLAYLIST
    assert parse_playlist_id(_PLAYLIST) == _PLAYLIST
    assert parse_playlist_id("not a url with spaces!") is None
    assert parse_playlist_id("") is None


@responses.activate
def test_client_fetches_playlist_tracks() -> None:
    responses.add(responses.POST, _TOKEN_URL, json={"access_token": "tok", "expires_in": 3600})
    responses.add(
        responses.GET,
        _TRACKS_URL,
        json={
            "next": None,
            "items": [
                {
                    "track": {
                        "name": "Roygbiv",
                        "album": {"name": "Music Has the Right", "release_date": "1998-05-05"},
                        "artists": [{"name": "Boards of Canada"}],
                    }
                },
                {"track": {"name": "x", "album": {"name": ""}, "artists": []}},  # dropped
            ],
        },
    )
    client = SpotifyClient("cid", "secret")

    tracks = client.playlist_tracks(_PLAYLIST)

    assert len(tracks) == 1
    assert tracks[0].artist == "Boards of Canada"
    assert tracks[0].album == "Music Has the Right"
    assert tracks[0].year == 1998


@responses.activate
def test_client_raises_on_bad_credentials() -> None:
    responses.add(responses.POST, _TOKEN_URL, status=400, json={"error": "invalid_client"})
    client = SpotifyClient("cid", "bad")
    try:
        client.playlist_tracks(_PLAYLIST)
    except ConnectionError as exc:
        assert "client id/secret" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ConnectionError")


@responses.activate
def test_recommender_collapses_tracks_to_albums() -> None:
    responses.add(responses.POST, _TOKEN_URL, json={"access_token": "tok", "expires_in": 3600})
    responses.add(
        responses.GET,
        _TRACKS_URL,
        json={
            "next": None,
            "items": [
                {
                    "track": {
                        "name": "A",
                        "album": {"name": "Album One", "release_date": "2001"},
                        "artists": [{"name": "Artist"}],
                    }
                },
                {
                    "track": {
                        "name": "B",
                        "album": {"name": "Album One", "release_date": "2001"},
                        "artists": [{"name": "Artist"}],
                    }
                },
            ],
        },
    )
    recommender = SpotifyPlaylistRecommender(
        client_id="cid",
        client_secret="secret",
        playlist_urls=(f"https://open.spotify.com/playlist/{_PLAYLIST}",),
    )

    recs = recommender.recommend(RecommendationContext())

    assert len(recs) == 1
    assert recs[0].album == "Album One"
    assert recs[0].source == "spotify_playlists"


def test_recommender_requires_creds_and_playlists() -> None:
    assert SpotifyPlaylistRecommender().is_configured() is False
    assert SpotifyPlaylistRecommender(client_id="a", client_secret="b").is_configured() is False
    assert (
        SpotifyPlaylistRecommender(
            client_id="a", client_secret="b", playlist_urls=("x",)
        ).is_configured()
        is True
    )
