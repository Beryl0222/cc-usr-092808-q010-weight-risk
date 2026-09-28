from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .database import transaction
from .errors import ConflictError, NotFoundError, ValidationError
from .outbox import Outbox


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ClaimDecision:
    claim_number: str
    region_id: str
    decision: str
    payable_amount: float
    reason: str


class BirthBenefitClaims:
    """管理地区内生育保障费用申报与审核。"""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.outbox = Outbox(connection)

    def create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS birth_benefit_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_number TEXT NOT NULL UNIQUE,
                region_id TEXT NOT NULL,
                patient_id TEXT NOT NULL,
                facility_id TEXT NOT NULL,
                service_package TEXT NOT NULL,
                eligible_amount REAL NOT NULL,
                additional_amount REAL NOT NULL,
                status TEXT NOT NULL,
                version INTEGER NOT NULL,
                submitted_at TEXT NOT NULL,
                decided_at TEXT,
                decision_reason TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_birth_claim_region_status
                ON birth_benefit_claims(region_id, status, submitted_at);
            """
        )

    def submit(
        self,
        claim_number: str,
        region_id: str,
        patient_id: str,
        facility_id: str,
        service_package: str,
        eligible_amount: float,
        additional_amount: float,
    ) -> dict[str, Any]:
        if eligible_amount < 0 or additional_amount < 0:
            raise ValidationError("amount", "费用不能为负")
        try:
            self.connection.execute(
                "INSERT INTO birth_benefit_claims(claim_number, region_id, patient_id, facility_id, service_package, eligible_amount, additional_amount, status, version, submitted_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, 'SUBMITTED', 1, ?)",
                (claim_number, region_id, patient_id, facility_id, service_package, eligible_amount, additional_amount, now()),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"申报编号已存在：{claim_number}") from exc
        return self.get(claim_number)

    def get(self, claim_number: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM birth_benefit_claims WHERE claim_number=?",
            (claim_number,),
        ).fetchone()
        if row is None:
            raise NotFoundError("申报不存在")
        return dict(row)

    def decide(self, claim_number: str, expected_version: int, approve: bool, reason: str) -> ClaimDecision:
        claim = self.get(claim_number)
        if int(claim["version"]) != expected_version:
            raise ConflictError("申报版本冲突")
        if claim["status"] != "SUBMITTED":
            raise ValidationError("status", "只有待审核申报可以裁定")
        decision = "APPROVED" if approve else "REJECTED"
        payable = float(claim["eligible_amount"]) if approve else 0.0
        with transaction(self.connection, immediate=True):
            self.connection.execute(
                "UPDATE birth_benefit_claims SET status=?, version=version+1, decided_at=?, decision_reason=? WHERE claim_number=? AND version=?",
                (decision, now(), reason, claim_number, expected_version),
            )
            self.outbox.enqueue(
                claim["region_id"], "BIRTH_BENEFIT_DECIDED", claim_number,
                {"claim_number": claim_number, "decision": decision, "payable_amount": payable},
                stable_key=f"{expected_version + 1}:{decision}",
            )
        return ClaimDecision(claim_number, claim["region_id"], decision, payable, reason)

    def list_region(self, region_id: str, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self.connection.execute(
                "SELECT * FROM birth_benefit_claims WHERE region_id=? AND status=? ORDER BY submitted_at, claim_number",
                (region_id, status),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM birth_benefit_claims WHERE region_id=? ORDER BY submitted_at, claim_number",
                (region_id,),
            ).fetchall()
        return [dict(row) for row in rows]


class ScreeningRiskPolicy:
    def classify(self, age: int, symptoms: set[str], family_history: bool, previous_findings: bool) -> tuple[str, list[str]]:
        if age < 0 or age > 130:
            raise ValidationError("age", "年龄无效")
        reasons: list[str] = []
        score = 0
        if age >= 50:
            score += 2
            reasons.append("年龄达到重点筛查范围")
        if family_history:
            score += 2
            reasons.append("存在家族史")
        if previous_findings:
            score += 3
            reasons.append("既往检查存在异常")
        urgent = {"bleeding", "persistent_pain", "unexplained_weight_loss"} & symptoms
        if urgent:
            score += 4
            reasons.append("出现需要尽快就医的症状")
        if score >= 6:
            return "PRIORITY_REFERRAL", reasons
        if score >= 3:
            return "CLINICAL_REVIEW", reasons
        return "ROUTINE_EDUCATION", reasons


class VaccineSeasonPolicy:
    def recommendation(self, age: int, chronic_conditions: set[str], last_dose_at: str | None, season_start: str) -> dict[str, Any]:
        if age < 0 or age > 130:
            raise ValidationError("age", "年龄无效")
        season = datetime.fromisoformat(season_start.replace("Z", "+00:00"))
        if season.tzinfo is None:
            raise ValidationError("season_start", "必须带时区")
        priority = age < 5 or age >= 65 or bool(chronic_conditions)
        due = True
        if last_dose_at:
            last = datetime.fromisoformat(last_dose_at.replace("Z", "+00:00"))
            if last.tzinfo is None:
                raise ValidationError("last_dose_at", "必须带时区")
            due = last < season
        return {
            "priority": priority,
            "due": due,
            "reason": "高风险人群优先接种" if priority else "按当季方案常规接种",
        }


class ConsentResolver:
    def effective(self, connection: sqlite3.Connection, tenant_id: str, patient_id: str, purpose: str, at_time: str) -> dict[str, Any] | None:
        target = datetime.fromisoformat(at_time.replace("Z", "+00:00"))
        if target.tzinfo is None:
            raise ValidationError("at_time", "必须带时区")
        rows = connection.execute(
            "SELECT * FROM consents WHERE tenant_id=? AND archived_at IS NULL AND json_extract(payload_json, '$.patient_id')=? ORDER BY updated_at DESC",
            (tenant_id, patient_id),
        ).fetchall()
        for row in rows:
            payload = json.loads(row["payload_json"])
            purposes = set(payload.get("purposes", []))
            if purpose not in purposes:
                continue
            start = datetime.fromisoformat(payload["valid_from"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(payload["valid_until"].replace("Z", "+00:00"))
            if start <= target <= end and row["status"] == "ACTIVE":
                return dict(row) | {"payload": payload}
        return None
