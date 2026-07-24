"""Tests for the Last.fm client and similar-music recommender."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import responses

from vaultseek.models.interfaces.recommender import RecommendationContext
from vaultseek.plugins.builtin.lastfm import LastfmClient, LastfmSimilarRecommender

_API = "https://ws.audioscrobbler.com/2.0/"


def _callback(request):
    params = parse_qs(urlparse(request.url).query)
    method = params.get("method", [""])[0]
    artist = params.get("artist", [""])[0]
    if method == "artist.getSimilar":
        body = {
            "similarartists": {
                "artist": [
                    {"name": "Aphex Twin", "match": "1.0"},
                    {"name": artist, "match": "0.9"},  # self — should be filtered as owned
                ]
            }
        }
    elif method == "artist.getTopAlbums":
        body = {
            "topalbums": {
                "album": [
                    {"name": "Selected Ambient Works", "artist": {"name": "Aphex Twin"}},
                    {"name": "(null)", "artist": {"name": "Aphex Twin"}},
                ]
            }
        }
    else:
        body = {}
    return (200, {}, json.dumps(body))


@responses.activate
def test_client_parses_similar_and_top_albums() -> None:
    responses.add_callback(responses.GET, _API, callback=_callback)
    client = LastfmClient("key")

    similar = client.similar_artists("Boards of Canada", limit=5)
    assert similar[0].name == "Aphex Twin"
    assert similar[0].match == 1.0

    albums = client.top_albums("Aphex Twin", limit=2)
    # "(null)" placeholder is dropped.
    assert [a.album for a in albums] == ["Selected Ambient Works"]


@responses.activate
def test_client_raises_on_api_error() -> None:
    responses.add(
        responses.GET,
        _API,
        json={"error": 10, "message": "Invalid API key"},
        status=200,
    )
    client = LastfmClient("bad")
    try:
        client.similar_artists("X")
    except ConnectionError as exc:
        assert "Invalid API key" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ConnectionError")


@responses.activate
def test_recommender_suggests_similar_artist_albums() -> None:
    responses.add_callback(responses.GET, _API, callback=_callback)
    recommender = LastfmSimilarRecommender(api_key="key")
    context = RecommendationContext(seed_artists=("Boards of Canada",))

    recs = recommender.recommend(context)

    assert any(r.album == "Selected Ambient Works" and r.artist == "Aphex Twin" for r in recs)
    assert all(r.source == "lastfm_similar" for r in recs)


def test_recommender_not_configured_without_key() -> None:
    assert LastfmSimilarRecommender().is_configured() is False
    assert LastfmSimilarRecommender(api_key="k").is_configured() is True
    assert LastfmSimilarRecommender().recommend(RecommendationContext()) == []
