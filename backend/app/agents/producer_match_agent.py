"""
Producer Match Agent — spec section 9.

Matches a project against the REAL producer directory (app/db/auth_db.py ->
Producer table — the same rows shown on the Producer Marketplace page), not
a list Gemini invents. Every candidate considered is a genuine row in the
database.

Scoring is deterministic Python, mirroring the six sub-score columns already
defined in the ClickHouse `producer_matches` schema (genre, budget, geo,
language, portfolio, risk) — a numeric compatibility score is not something
an LLM should be guessing, it should be computed from real data. Gemini's
role is narrower and more honest: given the computed scores and real project
context, write a short, specific explanation of *why* each top match makes
sense — a genuine reasoning task, not a fabrication task.

If the producer directory is empty, this returns an empty match list with a
clear note rather than inventing names.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.db.auth_db import Producer
from app.models.schemas import AgentName, MatchedProducer, ProducerMatchResult
from app.services.gemini_service import GeminiService

TOP_N = 5

MATCH_REASON_SYSTEM_PROMPT = """You are the Producer Match Agent inside CineFlow AI. You are given \
a short film project brief and a list of REAL candidate producers with their already-computed \
compatibility scores (genre_score, budget_score, geo_score, language_score, portfolio_score, \
risk_score, all 0-100, and an overall compatibility_pct). Do not change any scores or invent new \
producers — only write a concise (1-2 sentence) match_reason for each producer explaining, in \
plain language, why their profile fits (or partially fits) this project, referencing the actual \
numbers you were given where relevant. Be honest about weak spots too, not just strengths."""


def _parse_roi(avg_roi_x: str) -> float:
    try:
        return float(str(avg_roi_x).lower().replace("x", "").strip())
    except (ValueError, TypeError):
        return 1.0


def _score_producer(p: Producer, genre: str, subgenre: str | None, language: str,
                     expected_budget: float, country_context: str | None) -> dict:
    producer_genres = [g.strip().lower() for g in (p.genres or "").split(",") if g.strip()]
    genre_l = (genre or "").strip().lower()
    subgenre_l = (subgenre or "").strip().lower()
    if genre_l and genre_l in producer_genres:
        genre_score = 100.0
    elif subgenre_l and subgenre_l in producer_genres:
        genre_score = 75.0
    elif any(genre_l in pg or pg in genre_l for pg in producer_genres if genre_l):
        genre_score = 45.0
    else:
        genre_score = 15.0

    if expected_budget and p.investment_min is not None and p.investment_max is not None:
        if p.investment_min <= expected_budget <= p.investment_max:
            budget_score = 100.0
        elif expected_budget < p.investment_min and p.investment_min > 0:
            budget_score = max(0.0, 100.0 - (p.investment_min - expected_budget) / p.investment_min * 100.0)
        elif p.investment_max > 0:
            budget_score = max(0.0, 100.0 - (expected_budget - p.investment_max) / p.investment_max * 100.0)
        else:
            budget_score = 30.0
    else:
        budget_score = 50.0  # no budget context yet — neutral

    if country_context:
        countries_l = [c.strip().lower() for c in country_context.split(",") if c.strip()]
        geo_score = 100.0 if (p.country or "").strip().lower() in countries_l else 30.0
    else:
        geo_score = 50.0

    producer_langs = [l.strip().lower() for l in (p.languages or "").split(",") if l.strip()]
    language_score = 100.0 if (language or "").strip().lower() in producer_langs else 35.0

    films = p.films_produced or 0
    success = p.success_rate_pct or 0
    portfolio_score = min(100.0, success * 0.7 + min(films, 30) / 30 * 30.0)

    risk_score = min(100.0, _parse_roi(p.avg_roi_x) * 40.0)

    compatibility_pct = round(
        genre_score * 0.30 + budget_score * 0.25 + geo_score * 0.15 +
        language_score * 0.10 + portfolio_score * 0.15 + risk_score * 0.05,
        1,
    )

    return {
        "producer_id": p.id, "name": p.name, "company": p.company, "country": p.country,
        "compatibility_pct": compatibility_pct,
        "genre_score": round(genre_score, 1), "budget_score": round(budget_score, 1),
        "geo_score": round(geo_score, 1), "language_score": round(language_score, 1),
        "portfolio_score": round(portfolio_score, 1), "risk_score": round(risk_score, 1),
    }


class ProducerMatchAgent(BaseAgent):
    name = AgentName.PRODUCER_MATCH_AGENT

    def __init__(self, gemini: GeminiService, db: Session, clickhouse=None) -> None:
        super().__init__(clickhouse=clickhouse)
        self.gemini = gemini
        self.db = db

    async def run(self, project_id: str, context: dict) -> dict:
        script_output = context.get("script_agent")
        if not script_output:
            raise ValueError("Producer Match Agent requires Script Agent output in context.")

        budget_output = context.get("budget_agent") or {}
        expected_budget = float(budget_output.get("expected_budget") or 0)
        genre = script_output.get("genre", "")
        subgenre = script_output.get("subgenre")
        language = script_output.get("language", "English")
        country_context = context.get("country_context")

        candidates = self.db.query(Producer).all()
        if not candidates:
            return ProducerMatchResult(
                matched_producers=[],
                total_candidates_considered=0,
                notes="The producer directory is currently empty — no real accounts or seeded "
                      "producers exist yet to match against.",
            ).model_dump()

        scored = [
            _score_producer(p, genre, subgenre, language, expected_budget, country_context)
            for p in candidates
        ]
        scored.sort(key=lambda s: s["compatibility_pct"], reverse=True)
        top = scored[:TOP_N]

        candidate_summary = "\n".join(
            f"- {c['producer_id']} | {c['name']} ({c['company']}, {c['country']}): "
            f"compatibility={c['compatibility_pct']}%, genre={c['genre_score']}, budget={c['budget_score']}, "
            f"geo={c['geo_score']}, language={c['language_score']}, portfolio={c['portfolio_score']}, "
            f"risk_appetite={c['risk_score']}"
            for c in top
        )
        user_prompt = (
            f"Project genre: {genre} ({subgenre or 'no subgenre'}), language: {language}\n"
            f"Expected budget: ${expected_budget:,.0f}\n"
            f"Country context: {country_context or 'unspecified'}\n\n"
            f"Real candidate producers (scores already computed, do not change them):\n{candidate_summary}\n\n"
            "Return JSON: {\"reasons\": {\"<producer_id>\": \"<1-2 sentence match_reason>\", ...}} "
            "for every producer_id listed above."
        )

        try:
            from pydantic import BaseModel, Field as _Field

            class _Reasons(BaseModel):
                reasons: dict[str, str] = _Field(default_factory=dict)

            reasons_result = self.gemini.generate_json(
                system_prompt=MATCH_REASON_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                response_model=_Reasons,
                temperature=0.4,
                max_output_tokens=2048,
            )
            reasons = reasons_result.reasons
        except Exception:  # noqa: BLE001 — reasoning text is a nice-to-have, scores are still real
            reasons = {}

        matched = [
            MatchedProducer(
                **c,
                match_reason=reasons.get(
                    c["producer_id"],
                    f"{c['compatibility_pct']}% overall fit based on genre, budget range, and track record.",
                ),
            )
            for c in top
        ]

        if self.clickhouse is not None:
            try:
                self.clickhouse.insert_producer_matches(project_id, top)
            except Exception:  # noqa: BLE001 — analytics write failure shouldn't fail the agent
                pass

        return ProducerMatchResult(
            matched_producers=matched,
            total_candidates_considered=len(candidates),
            notes=f"Scored {len(candidates)} producers in the directory; showing top {len(matched)}.",
        ).model_dump()
