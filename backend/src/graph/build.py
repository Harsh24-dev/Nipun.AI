"""
Build the legal + scheme knowledge graphs.

Validates every record against the authoritative allowlists (schema.py) BEFORE it
enters Neo4j, and logs rejects. When Neo4j is unavailable the build runs as a dry-run
and still returns accepted/rejected counts (so validation is testable offline).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from src.db.neo4j import graph_available, run_write
from src.graph import data
from src.graph.schema import is_valid_act, is_valid_ministry

log = structlog.get_logger("graph.build")


@dataclass
class BuildReport:
    graph: str
    accepted: int = 0
    rejected: int = 0
    written: int = 0
    rejects: list[str] = field(default_factory=list)


def validate_legal(sections: list[dict]) -> tuple[list[dict], list[str]]:
    accepted, rejects = [], []
    for rec in sections:
        if not rec.get("section") or not is_valid_act(rec.get("act", "")):
            rejects.append(f"legal:{rec.get('section')}/{rec.get('act')}")
            continue
        accepted.append(rec)
    return accepted, rejects


def validate_schemes(schemes: list[dict]) -> tuple[list[dict], list[str]]:
    accepted, rejects = [], []
    for rec in schemes:
        if not rec.get("scheme") or not is_valid_ministry(rec.get("ministry", "")):
            rejects.append(f"scheme:{rec.get('scheme')}/{rec.get('ministry')}")
            continue
        accepted.append(rec)
    return accepted, rejects


async def build_legal_graph() -> BuildReport:
    accepted, rejects = validate_legal(data.LEGAL_SECTIONS)
    report = BuildReport(graph="legal", accepted=len(accepted), rejected=len(rejects), rejects=rejects)
    if rejects:
        log.warning("legal_graph_rejects", count=len(rejects), rejects=rejects)

    if not graph_available():
        log.info("legal_graph_dryrun", accepted=len(accepted))
        return report

    for rec in accepted:
        await run_write(
            """
            MERGE (a:Act {name: $act})
            MERGE (s:Section {id: $section, act: $act})
            SET s.title = $title
            MERGE (s)-[:BELONGS_TO]->(a)
            """,
            act=rec["act"], section=rec["section"], title=rec.get("title", ""),
        )
        for rel in rec.get("related", []):
            await run_write(
                """
                MATCH (s:Section {id: $section, act: $act})
                MERGE (r:Section {id: $rel, act: $act})
                MERGE (s)-[:RELATED_TO]->(r)
                """,
                section=rec["section"], act=rec["act"], rel=rel,
            )
        report.written += 1

    for amend in data.LEGAL_AMENDMENTS:
        if is_valid_act(amend.get("act", "")):
            await run_write(
                """
                MATCH (s:Section {id: $section, act: $act})
                MERGE (am:Amendment {name: $amendment})
                MERGE (s)-[:AMENDED_BY]->(am)
                """,
                section=amend["section"], act=amend["act"], amendment=amend["amendment"],
            )
    log.info("legal_graph_built", written=report.written)
    return report


async def build_scheme_graph() -> BuildReport:
    accepted, rejects = validate_schemes(data.SCHEMES)
    report = BuildReport(graph="scheme", accepted=len(accepted), rejected=len(rejects), rejects=rejects)
    if rejects:
        log.warning("scheme_graph_rejects", count=len(rejects), rejects=rejects)

    if not graph_available():
        log.info("scheme_graph_dryrun", accepted=len(accepted))
        return report

    for rec in accepted:
        await run_write(
            """
            MERGE (sc:Scheme {name: $scheme})
            SET sc.benefit = $benefit
            MERGE (m:Ministry {name: $ministry})
            MERGE (sc)-[:ADMINISTERED_BY]->(m)
            """,
            scheme=rec["scheme"], ministry=rec["ministry"], benefit=rec.get("benefit", ""),
        )
        for crit in rec.get("requires", []):
            await run_write(
                """
                MATCH (sc:Scheme {name: $scheme})
                MERGE (c:Criterion {text: $crit})
                MERGE (sc)-[:REQUIRES]->(c)
                """,
                scheme=rec["scheme"], crit=crit,
            )
        for excl in rec.get("excludes", []):
            await run_write(
                """
                MATCH (sc:Scheme {name: $scheme})
                MERGE (o:Scheme {name: $excl})
                MERGE (sc)-[:EXCLUDES]->(o)
                """,
                scheme=rec["scheme"], excl=excl,
            )
        report.written += 1
    log.info("scheme_graph_built", written=report.written)
    return report


async def build_all() -> list[BuildReport]:
    return [await build_legal_graph(), await build_scheme_graph()]
