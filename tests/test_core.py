import tempfile
import unittest
from pathlib import Path

from wellness_ops.audit import AuditLog
from wellness_ops.database import connect, initialize_core
from wellness_ops.permissions import PermissionMatrix
from wellness_ops.patient import PatientRepository, PatientService


class CoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.connection = connect(Path(self.temp.name) / "app.sqlite3")
        initialize_core(self.connection)

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_repository_version_and_audit(self):
        repository = PatientRepository(self.connection)
        repository.create_schema()
        service = PatientService(repository, PermissionMatrix(), AuditLog(self.connection))
        record = service.register("tenant", "record-1", {"display_name": "示例display_name", "birth_date": "2026-09-28T10:00:00+08:00", "region_id": "示例region_id", "identity_ref": "示例identity_ref"}, "operator-1", "operator")
        self.assertEqual(record.version, 1)
        viewed = service.view("tenant", "record-1", "viewer-1", "viewer")
        self.assertEqual(viewed["record_id"], "record-1")
        self.assertGreaterEqual(len(AuditLog(self.connection).history("tenant", "record-1")), 2)

    def test_all_schemas_initialize(self):
        from wellness_ops.cli import initialize
        initialize(self.connection)
        names = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("audit_log", names)
        self.assertIn("patients", names)
    def test_health_policies_and_claim(self):
            from wellness_ops.health_workflows import BirthBenefitClaims, ScreeningRiskPolicy, VaccineSeasonPolicy
            claims = BirthBenefitClaims(self.connection); claims.create_schema()
            claim = claims.submit("C001", "R1", "P1", "F1", "基础分娩服务包", 5000, 200)
            self.assertEqual(claim["status"], "SUBMITTED")
            decision = claims.decide("C001", 1, True, "符合服务包")
            self.assertEqual(decision.payable_amount, 5000)
            risk, reasons = ScreeningRiskPolicy().classify(58, {"bleeding"}, True, False)
            self.assertEqual(risk, "PRIORITY_REFERRAL")
            self.assertTrue(reasons)
            recommendation = VaccineSeasonPolicy().recommendation(70, {"cardiovascular"}, None, "2026-09-01T00:00:00+08:00")
            self.assertTrue(recommendation["priority"])


if __name__ == "__main__":
    unittest.main()
