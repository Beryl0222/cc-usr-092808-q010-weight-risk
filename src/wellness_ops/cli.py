from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .database import connect, initialize_core
from .patient import PatientRepository
from .consent import ConsentRepository
from .screening import ScreeningRepository
from .referral import ReferralRepository
from .vaccination import VaccinationRepository
from .care_episode import CareEpisodeRepository
from .followup import FollowupRepository
from .clinician import ClinicianRepository
from .facilitie import FacilityRepository
from .evidence import EvidenceRepository
from .notification import NotificationRepository
from .review_case import ReviewCaseRepository
from .health_workflows import BirthBenefitClaims, ScreeningRiskPolicy, VaccineSeasonPolicy


def initialize(connection: Any) -> None:
    initialize_core(connection)
    PatientRepository(connection).create_schema()
    ConsentRepository(connection).create_schema()
    ScreeningRepository(connection).create_schema()
    ReferralRepository(connection).create_schema()
    VaccinationRepository(connection).create_schema()
    CareEpisodeRepository(connection).create_schema()
    FollowupRepository(connection).create_schema()
    ClinicianRepository(connection).create_schema()
    FacilityRepository(connection).create_schema()
    EvidenceRepository(connection).create_schema()
    NotificationRepository(connection).create_schema()
    ReviewCaseRepository(connection).create_schema()
    BirthBenefitClaims(connection).create_schema()


def command_init(args: argparse.Namespace) -> int:
    connection = connect(args.database)
    initialize(connection)
    print(json.dumps({"database": str(args.database), "initialized": True}, ensure_ascii=False))
    return 0


def command_smoke(args: argparse.Namespace) -> int:
    connection = connect(args.database)
    initialize(connection)
    if 'health' == "culture":
        result = CouponSettlementPolicy().apply(30.0, 120.0, False, 0.0)
        payload = {"project": "culture_ops", "coupon_applied": result, "tables": len(connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())}
    else:
        risk, reasons = ScreeningRiskPolicy().classify(56, {"bleeding"}, True, False)
        vaccine = VaccineSeasonPolicy().recommendation(68, {"cardiovascular"}, None, "2026-09-01T00:00:00+08:00")
        payload = {"project": "wellness_ops", "risk": risk, "reasons": reasons, "vaccine": vaccine, "tables": len(connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="项目维护命令")
    parser.add_argument("--database", default=":memory:")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init")
    init_parser.set_defaults(handler=command_init)
    smoke_parser = subparsers.add_parser("smoke")
    smoke_parser.set_defaults(handler=command_smoke)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
