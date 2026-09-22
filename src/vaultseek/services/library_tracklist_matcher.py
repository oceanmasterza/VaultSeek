"""Match unidentified tracks against existing library album tracklists.

Filename / title, artist, release, duration, and recording evidence can
corroborate a unique album slot. Ambiguous live / remix / demo / conflicting
editions stay out of auto-approve and surface as Review recommendations.

Identity is independent of quality: a better LIBRARY copy does not block a
unique identity match (duplicate/archive handles quality afterward).
Invalid / conflicting candidates never defeat uniqueness among eligible ones.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from rapidfuzz import fuzz

from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.models.entities.album import Album
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.interfaces.metadata import (
    MetadataQuery,
    ProviderFieldResult,
    ProviderResult,
)
from vaultseek.services.review_display import filename_song, looks_like_opaque_id

_DURATION_TOLERANCE_MS = 3500
_DURATION_TOLERANCE_RATIO = 0.035
_TITLE_SCORE_MIN = 82.0
_UNIQUE_SCORE_MIN = 0.90
_PAREN = re.compile(r"\s*[\(\[]([^\)\]]+)[\)\]]")
_VERSION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("live", re.compile(r"\b(live|concert|unplugged)\b", re.IGNORECASE)),
    (
        "remix",
        re.compile(
            r"\b(remix|rmx|bootleg|(?:radio|club|extended)\s+mix)\b",
            re.IGNORECASE,
        ),
    ),
    ("demo", re.compile(r"\bdemo\b", re.IGNORECASE)),
    ("acoustic", re.compile(r"\bacoustic\b", re.IGNORECASE)),
    ("instrumental", re.compile(r"\binstrumental\b", re.IGNORECASE)),
)
_NAMED_MIX = re.compile(
    r"\(([^)]*?\b(?:mix|edit|remix)[^)]*)\)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AcquisitionProvenance:
    """Folder-level acquisition context — never inherit the job's desired title."""

    artist: str | None
    album: str | None
    mb_release_id: str | None


@dataclass(frozen=True, slots=True)
class AlbumSlotRecommendation:
    """One candidate album + track slot for Review assignment."""

    album_id: UUID
    album_title: str
    artist_id: UUID | None
    artist_name: str
    disc_number: int
    track_number: int | None
    slot_title: str
    score: float
    reasons: tuple[str, ...]
    existing_track_id: UUID | None
    existing_is_better: bool
    version_kind: str
    version_conflict: bool
    corroboration_count: int = 0
    duration_ok: bool = True
    song_corroboration: int = 0
    release_mismatch: bool = False
    exact_release: bool = False
    evidence_rank: float = 0.0


@dataclass(frozen=True, slots=True)
class LibraryMatchResult:
    """Outcome of matching one track to library album slots."""

    recommendations: tuple[AlbumSlotRecommendation, ...]
    unique: AlbumSlotRecommendation | None
    provider_result: ProviderResult | None


class LibraryTracklistMatcher:
    """Score incoming tracks against same-library album tracklists."""

    provider_id = "library_tracklist"
    priority = 35

    def __init__(
        self,
        *,
        track_repo: TrackRepository,
        album_repo: AlbumRepository,
        artist_repo: ArtistRepository,
        confidence_threshold: float = 0.90,
    ) -> None:
        self._tracks = track_repo
        self._albums = album_repo
        self._artists = artist_repo
        self._threshold = confidence_threshold

    def match(
        self,
        track: Track,
        query: MetadataQuery | None = None,
        *,
        provenance: AcquisitionProvenance | None = None,
    ) -> LibraryMatchResult:
        """Return ranked slot recommendations and an optional unique ProviderResult."""
        title = _seed_title(track, query)
        if not title:
            return LibraryMatchResult(recommendations=(), unique=None, provider_result=None)

        artist_hint = _first_str(
            query.artist if query is not None else None,
            provenance.artist if provenance is not None else None,
        )
        album_hint = _first_str(
            query.album if query is not None else None,
            provenance.album if provenance is not None else None,
        )
        release_mbid = provenance.mb_release_id if provenance is not None else None
        track_number = (
            query.track_number
            if query is not None and query.track_number is not None
            else track.track_number
        )
        duration_ms = (
            query.duration_ms
            if query is not None and query.duration_ms is not None
            else track.duration_ms
        )
        incoming_version = _version_kind(title)
        incoming_mix = _named_mix(title)

        candidates = self._tracks.find_title_candidates(track.library_id, title, limit=80)
        scored: list[AlbumSlotRecommendation] = []
        for candidate in candidates:
            if candidate.id == track.id or candidate.album_id is None:
                continue
            album = self._albums.get(candidate.album_id)
            if album is None:
                continue
            release_mismatch = bool(release_mbid and album.mbid and album.mbid != release_mbid)
            exact_release = bool(release_mbid and album.mbid and album.mbid == release_mbid)
            artist_name, artist_id = self._artist_label(album, candidate)
            if artist_hint and artist_name and not _artist_compatible(artist_hint, artist_name):
                continue
            slot_title = candidate.title or filename_song(candidate.file_name)
            slot_version = _version_kind(slot_title)
            slot_mix = _named_mix(slot_title)
            mix_conflict = bool(incoming_mix and slot_mix and incoming_mix != slot_mix)
            edition_conflict = _edition_conflict(title, slot_title)
            version_conflict = (
                _versions_conflict(incoming_version, slot_version)
                or mix_conflict
                or edition_conflict
            )
            title_score = _title_similarity(title, slot_title)
            if title_score < _TITLE_SCORE_MIN:
                continue

            reasons: list[str] = [f"title {title_score:.0f}%"]
            # Display score may be capped; evidence_rank drives uniqueness order.
            score = title_score / 100.0
            evidence = title_score / 100.0
            song_corroboration = 0
            provenance_corroboration = 0
            duration_ok = True

            if track_number is not None and candidate.track_number == track_number:
                score += 0.08
                evidence += 0.12
                song_corroboration += 1
                reasons.append(f"track #{track_number}")

            if duration_ms is not None and candidate.duration_ms is not None:
                if _duration_close(duration_ms, candidate.duration_ms):
                    score += 0.10
                    evidence += 0.15
                    song_corroboration += 1
                    reasons.append("duration")
                else:
                    duration_ok = False
                    score -= 0.20
                    evidence -= 0.40
                    reasons.append("duration mismatch")

            if artist_hint and artist_name and _artist_compatible(artist_hint, artist_name):
                score += 0.06
                evidence += 0.05
                provenance_corroboration = 1
                reasons.append("artist")

            if album_hint and _title_similarity(album_hint, album.title) >= 90.0:
                score += 0.05
                evidence += 0.05
                provenance_corroboration = 1
                reasons.append("release title")

            if exact_release:
                score += 0.08
                evidence += 0.25
                provenance_corroboration = 1
                reasons.append("release MBID")
            if release_mismatch:
                score -= 0.25
                evidence -= 0.50
                reasons.append("release MBID mismatch")

            if version_conflict:
                score -= 0.35
                evidence -= 0.55
                reasons.append(
                    f"version conflict ({incoming_version}/{incoming_mix or '-'} vs "
                    f"{slot_version}/{slot_mix or '-'})"
                )
            elif incoming_version == "studio" and slot_version == "studio":
                score += 0.03
                evidence += 0.04
                reasons.append("studio title")

            # Provenance counts as at most one corroboration source.
            corroboration = song_corroboration + provenance_corroboration
            score = max(0.0, min(score, 0.99))
            if release_mismatch or version_conflict:
                score = min(score, 0.70)
            evidence = max(0.0, evidence)
            scored.append(
                AlbumSlotRecommendation(
                    album_id=album.id,
                    album_title=album.title,
                    artist_id=artist_id,
                    artist_name=artist_name or "",
                    disc_number=candidate.disc_number,
                    track_number=candidate.track_number,
                    slot_title=slot_title,
                    score=score,
                    reasons=tuple(reasons),
                    existing_track_id=candidate.id,
                    existing_is_better=_existing_is_better(track, candidate),
                    version_kind=slot_version,
                    version_conflict=version_conflict or release_mismatch,
                    corroboration_count=corroboration,
                    duration_ok=duration_ok,
                    song_corroboration=song_corroboration,
                    release_mismatch=release_mismatch,
                    exact_release=exact_release,
                    evidence_rank=evidence,
                )
            )

        deduped = _dedupe_slots(scored)
        folder_boost = self._folder_corroboration(track, deduped)
        if folder_boost:
            boosted: list[AlbumSlotRecommendation] = []
            for item in deduped:
                if item.album_id in folder_boost:
                    boosted.append(
                        AlbumSlotRecommendation(
                            album_id=item.album_id,
                            album_title=item.album_title,
                            artist_id=item.artist_id,
                            artist_name=item.artist_name,
                            disc_number=item.disc_number,
                            track_number=item.track_number,
                            slot_title=item.slot_title,
                            score=min(0.99, item.score + 0.07),
                            reasons=item.reasons + ("folder siblings",),
                            existing_track_id=item.existing_track_id,
                            existing_is_better=item.existing_is_better,
                            version_kind=item.version_kind,
                            version_conflict=item.version_conflict,
                            corroboration_count=item.corroboration_count + 1,
                            duration_ok=item.duration_ok,
                            song_corroboration=item.song_corroboration + 1,
                            release_mismatch=item.release_mismatch,
                            exact_release=item.exact_release,
                            evidence_rank=item.evidence_rank + 0.10,
                        )
                    )
                else:
                    boosted.append(item)
            deduped = boosted

        ranked = _rank_recommendations(deduped)
        unique = _pick_unique(ranked, self._threshold)
        provider = _to_provider_result(unique, incoming_title=title) if unique is not None else None
        return LibraryMatchResult(
            recommendations=ranked[:12],
            unique=unique,
            provider_result=provider,
        )

    def recommend(
        self,
        track: Track,
        query: MetadataQuery | None = None,
        *,
        provenance: AcquisitionProvenance | None = None,
    ) -> tuple[AlbumSlotRecommendation, ...]:
        return self.match(track, query, provenance=provenance).recommendations

    def _artist_label(self, album: Album, track: Track) -> tuple[str | None, UUID | None]:
        artist_id = album.album_artist_id or track.artist_id
        if artist_id is None:
            return None, None
        artist = self._artists.get(artist_id)
        if artist is None:
            return None, artist_id
        return artist.name, artist_id

    def _folder_corroboration(
        self, track: Track, recommendations: Sequence[AlbumSlotRecommendation]
    ) -> set[UUID]:
        """Albums that also match sibling filenames in the same download folder."""
        parent = Path(track.file_path).parent
        siblings = self._tracks.list_by_path_prefix(track.library_id, str(parent), limit=40)
        album_hits: dict[UUID, int] = {}
        for sibling in siblings:
            if sibling.id == track.id:
                continue
            sib_title = filename_song(sibling.file_name)
            if not sib_title or looks_like_opaque_id(sib_title):
                continue
            sib_num = _track_number_from_name(sibling.file_name)
            for item in recommendations:
                album_tracks = self._tracks.list_by_album(
                    track.library_id, item.album_id, limit=200
                )
                for album_track in album_tracks:
                    other = album_track.title or filename_song(album_track.file_name)
                    if _title_similarity(sib_title, other) < _TITLE_SCORE_MIN:
                        continue
                    if sib_num is not None and album_track.track_number not in (None, sib_num):
                        continue
                    if _versions_conflict(_version_kind(sib_title), _version_kind(other)):
                        continue
                    album_hits[item.album_id] = album_hits.get(item.album_id, 0) + 1
                    break
        return {album_id for album_id, count in album_hits.items() if count >= 2}


def _seed_title(track: Track, query: MetadataQuery | None) -> str:
    for raw in (
        query.title if query is not None else None,
        track.title,
        filename_song(track.file_name),
        filename_song(Path(track.file_path).name),
    ):
        if not raw:
            continue
        text = str(raw).strip()
        if text and not looks_like_opaque_id(text):
            return text
    return ""


def _title_similarity(left: str, right: str) -> float:
    """Strict title similarity — no token_set subset inflation."""
    a = _normalize_title(left)
    b = _normalize_title(right)
    if not a or not b:
        return 0.0
    base_a, mix_a = _split_mix(a)
    base_b, mix_b = _split_mix(b)
    if mix_a and mix_b and mix_a != mix_b:
        return 0.0
    if bool(mix_a) != bool(mix_b):
        # Studio vs named mix/demo parenthetical — keep low for auto-approve.
        return min(float(fuzz.ratio(base_a, base_b)) * 0.55, 70.0)
    return float(fuzz.ratio(base_a, base_b))


def _normalize_title(value: str) -> str:
    text = value.replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def _split_mix(title: str) -> tuple[str, str | None]:
    mix = _named_mix(title)
    base = _PAREN.sub("", title).strip()
    return base or title, mix


def _named_mix(title: str) -> str | None:
    match = _NAMED_MIX.search(title)
    if match is None:
        return None
    return _normalize_title(match.group(1))


def _version_kind(title: str) -> str:
    # Explicit mix/edit parentheticals are distinct from bare studio.
    if _named_mix(title) is not None:
        return "remix"
    for kind, pattern in _VERSION_PATTERNS:
        if pattern.search(title):
            return kind
    return "studio"


def _versions_conflict(incoming: str, slot: str) -> bool:
    if incoming == slot:
        return False
    if incoming == "studio" and slot != "studio":
        return True
    if slot == "studio" and incoming != "studio":
        return True
    return incoming != slot


def _duration_close(left_ms: int, right_ms: int) -> bool:
    delta = abs(left_ms - right_ms)
    if delta <= _DURATION_TOLERANCE_MS:
        return True
    longer = max(left_ms, right_ms, 1)
    return (delta / longer) <= _DURATION_TOLERANCE_RATIO


def _artist_compatible(hint: str, name: str) -> bool:
    return fuzz.ratio(_normalize_title(hint), _normalize_title(name)) >= 85.0


def _existing_is_better(incoming: Track, existing: Track) -> bool:
    """True only for an active LIBRARY physical copy that outranks Incoming."""
    if existing.zone is not LibraryZone.LIBRARY:
        return False
    if existing.is_lossless and not incoming.is_lossless:
        return True
    if incoming.is_lossless and not existing.is_lossless:
        return False
    in_q = incoming.quality_score or 0
    ex_q = existing.quality_score or 0
    if ex_q != in_q:
        return ex_q > in_q
    in_br = incoming.bitrate or 0
    ex_br = existing.bitrate or 0
    return ex_br > in_br


def _slot_key(item: AlbumSlotRecommendation) -> tuple[object, ...]:
    """Identity key retains full recording/version text — never strip editions."""
    return (
        item.album_id,
        item.disc_number,
        item.track_number,
        _normalize_title(item.slot_title),
        item.version_kind,
    )


def _dedupe_slots(
    items: Sequence[AlbumSlotRecommendation],
) -> list[AlbumSlotRecommendation]:
    """Collapse physical copies of the *same* recording into one recommendation.

    Studio vs demo/remix stay separate. The winner is one internally consistent
    candidate — never Frankenstein max/AND evidence across different versions.
    """
    best: dict[tuple[object, ...], AlbumSlotRecommendation] = {}
    for item in items:
        key = _slot_key(item)
        previous = best.get(key)
        if previous is None:
            best[key] = item
            continue
        prefer_item = item.evidence_rank > previous.evidence_rank or (
            item.evidence_rank == previous.evidence_rank and item.score > previous.score
        )
        winner = item if prefer_item else previous
        loser = previous if prefer_item else item
        # Same recording only: surface that a better LIBRARY copy exists among twins.
        if loser.existing_is_better and not winner.existing_is_better:
            winner = AlbumSlotRecommendation(
                album_id=winner.album_id,
                album_title=winner.album_title,
                artist_id=winner.artist_id,
                artist_name=winner.artist_name,
                disc_number=winner.disc_number,
                track_number=winner.track_number,
                slot_title=winner.slot_title,
                score=winner.score,
                reasons=winner.reasons,
                existing_track_id=winner.existing_track_id,
                existing_is_better=True,
                version_kind=winner.version_kind,
                version_conflict=winner.version_conflict,
                corroboration_count=winner.corroboration_count,
                duration_ok=winner.duration_ok,
                song_corroboration=winner.song_corroboration,
                release_mismatch=winner.release_mismatch,
                exact_release=winner.exact_release,
                evidence_rank=winner.evidence_rank,
            )
        best[key] = winner
    return list(best.values())


def _rank_recommendations(
    items: Sequence[AlbumSlotRecommendation],
) -> tuple[AlbumSlotRecommendation, ...]:
    """Order by eligibility evidence — exact release first, conflicts last."""

    def sort_key(item: AlbumSlotRecommendation) -> tuple[object, ...]:
        eligible = _is_eligible(item, threshold=_UNIQUE_SCORE_MIN)
        return (
            0 if eligible else 1,
            0 if item.exact_release else 1,
            0 if not item.version_conflict else 1,
            0 if not item.release_mismatch else 1,
            0 if item.duration_ok else 1,
            -item.evidence_rank,
            -item.song_corroboration,
            -item.score,
        )

    return tuple(sorted(items, key=sort_key))


def _is_eligible(item: AlbumSlotRecommendation, *, threshold: float) -> bool:
    if item.version_conflict or item.release_mismatch:
        return False
    if not item.duration_ok:
        return False
    if item.corroboration_count < 2:
        return False
    if item.song_corroboration < 1:
        return False
    return not (item.evidence_rank < threshold and item.score < threshold)


def _pick_unique(
    items: Sequence[AlbumSlotRecommendation], threshold: float
) -> AlbumSlotRecommendation | None:
    """Pick a unique eligible match; conflicting tops never shadow eligible peers.

    ``existing_is_better`` does **not** block identity — quality is handled by
    the duplicate/archive path after correct tagging. Known provenance MBID
    matches outrank other eligible editions when present.
    """
    eligible = [item for item in items if _is_eligible(item, threshold=threshold)]
    if not eligible:
        return None
    exact = [item for item in eligible if item.exact_release]
    pool = exact if exact else eligible
    top = pool[0]
    for other in pool[1:]:
        if other.album_id == top.album_id:
            close = other.evidence_rank >= top.evidence_rank - 0.08
            if other.track_number != top.track_number and close:
                return None
            continue
        # Distinct albums for the same song — ambiguous unless one exact release.
        if not top.exact_release and _same_song_base(top, other):
            if other.evidence_rank >= top.evidence_rank - 0.12:
                return None
        elif top.exact_release and other.exact_release and _same_song_base(top, other):
            if other.evidence_rank >= top.evidence_rank - 0.08:
                return None
        elif not top.exact_release and other.evidence_rank >= top.evidence_rank - 0.08:
            return None
    return top


def _same_song_base(left: AlbumSlotRecommendation, right: AlbumSlotRecommendation) -> bool:
    return _normalize_title(_split_mix(left.slot_title)[0]) == _normalize_title(
        _split_mix(right.slot_title)[0]
    )


def _to_provider_result(match: AlbumSlotRecommendation, *, incoming_title: str) -> ProviderResult:
    confidence = min(0.95, max(match.score, match.evidence_rank, 0.90))
    # Keep distinctive incoming edition wording when it is not a classified conflict.
    title_value = incoming_title.strip() if incoming_title.strip() else match.slot_title
    if looks_like_opaque_id(title_value):
        title_value = match.slot_title
    fields = [
        ProviderFieldResult("title", title_value, confidence),
        ProviderFieldResult("album", match.album_title, confidence),
    ]
    if match.artist_name:
        fields.append(ProviderFieldResult("artist", match.artist_name, confidence))
    if match.track_number is not None:
        fields.append(ProviderFieldResult("track_number", match.track_number, confidence))
    fields.append(ProviderFieldResult("library_album_id", str(match.album_id), confidence))
    if match.artist_id is not None:
        fields.append(ProviderFieldResult("library_artist_id", str(match.artist_id), confidence))
    return ProviderResult(
        provider_id=LibraryTracklistMatcher.provider_id,
        fields=fields,
        overall_confidence=confidence,
        lookup_method="library",
        priority=LibraryTracklistMatcher.priority,
        raw_response={
            "album_id": str(match.album_id),
            "existing_track_id": str(match.existing_track_id) if match.existing_track_id else None,
            "existing_is_better": match.existing_is_better,
            "reasons": list(match.reasons),
            "corroboration_count": match.corroboration_count,
            "song_corroboration": match.song_corroboration,
            "exact_release": match.exact_release,
        },
    )


def _edition_conflict(incoming: str, slot: str) -> bool:
    """True when parenthetical edition notes differ (Single Version, From …, etc.)."""
    left = {_normalize_title(m.group(1)) for m in _PAREN.finditer(incoming)}
    right = {_normalize_title(m.group(1)) for m in _PAREN.finditer(slot)}
    if not left and not right:
        return False
    # Mix conflicts are handled separately; bare vs any parenthetical is a conflict.
    return left != right


def _track_number_from_name(file_name: str) -> int | None:
    stem = Path(file_name).stem
    match = re.match(r"^(\d{1,3})\s*[-._)]\s*", stem)
    if match is None:
        return None
    return int(match.group(1))


def _first_str(*values: str | None) -> str | None:
    for value in values:
        if value and value.strip() and not looks_like_opaque_id(value):
            return value.strip()
    return None
