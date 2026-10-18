"""Pantry stock API checks: pack sizes, restocking and lookup."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


TEST_DATA = tempfile.TemporaryDirectory(prefix="pantrlytics-stock-test-")
os.environ["DATA_DIR"] = TEST_DATA.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main  # noqa: E402


class PantryStockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(main.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        TEST_DATA.cleanup()

    def _create(self, **body):
        resp = self.client.post("/api/items", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["item_id"]

    def test_create_sets_amount_left_from_packs(self):
        item_id = self._create(
            name="Red split lentils", location="Pantry", quantity=2, unit="bag",
            pack_size=500, pack_unit="g", stockcode="111111", product_barcode="9300000000011",
        )
        data = self.client.get(f"/api/items/{item_id}").json()
        self.assertEqual(data["amount_left"], 1000)
        self.assertEqual(data["stockcode"], "111111")
        self.assertEqual(data["product_barcode"], "9300000000011")

    def test_restock_adds_packs_and_amount(self):
        item_id = self._create(name="Rolled oats", quantity=1, pack_size=750, pack_unit="g", amount_left=200)
        resp = self.client.post(f"/api/items/{item_id}/restock", json={"packs": 2, "stockcode": "222222"})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["quantity"], 3)
        self.assertEqual(data["amount_left"], 1700)
        self.assertEqual(data["stockcode"], "222222")

    def test_restock_keeps_amount_checked_date(self):
        item_id = self._create(name="Quinoa", quantity=1, pack_size=500, pack_unit="g")
        with main.Session(main.engine) as session:
            item = session.get(main.Item, item_id)
            item.amount_checked_at = "2026-10-01"
            session.add(item)
            session.commit()
        data = self.client.post(f"/api/items/{item_id}/restock", json={"packs": 1}).json()
        self.assertEqual(data["amount_left"], 1000)
        self.assertEqual(data["amount_checked_at"], "2026-10-01")
        self.client.post(f"/item/{item_id}/mark-reviewed")
        self.assertEqual(self.client.get(f"/api/items/{item_id}").json()["amount_checked_at"], "2026-10-01")

    def test_restock_without_known_amount_counts_packs_only(self):
        item_id = self._create(name="Cous cous", quantity=1)
        data = self.client.post(f"/api/items/{item_id}/restock", json={"packs": 1, "pack_size": 500, "pack_unit": "g"}).json()
        self.assertEqual(data["quantity"], 2)
        self.assertIsNone(data["amount_left"])
        self.assertEqual(data["pack_size"], 500)

    def test_restock_revives_depleted_item(self):
        item_id = self._create(name="Pearl barley", quantity=1, pack_size=500, pack_unit="g")
        self.client.post(f"/item/{item_id}/deplete", data={"reason": "Used"})
        data = self.client.post(f"/api/items/{item_id}/restock", json={"packs": 1, "purchased_on": "2026-10-18"}).json()
        self.assertEqual(data["quantity"], 1)
        self.assertEqual(data["amount_left"], 500)
        item = self.client.get(f"/api/items/{item_id}").json()
        self.assertIsNone(item["depleted_at"])

    def test_restock_rejects_bad_packs(self):
        item_id = self._create(name="Tapioca pearls")
        self.assertEqual(self.client.post(f"/api/items/{item_id}/restock", json={"packs": 0}).status_code, 400)
        self.assertEqual(self.client.post("/api/items/999999/restock", json={"packs": 1}).status_code, 404)

    def test_lookup_by_stockcode_barcode_and_name(self):
        self._create(name="Brown Sugar", stockcode="333333", product_barcode="9300000000033")
        for params in ({"stockcode": "333333"}, {"product_barcode": "9300000000033"}, {"name": "brown sugar"}):
            matches = self.client.get("/api/items/lookup", params=params).json()["matches"]
            self.assertEqual([m["name"] for m in matches], ["Brown Sugar"], params)
        self.assertEqual(self.client.get("/api/items/lookup").status_code, 400)

    def test_edit_form_keeps_pack_fields_when_not_sent(self):
        item_id = self._create(name="Basmati rice", quantity=1, pack_size=1000, pack_unit="g")
        self.client.post(f"/item/{item_id}/edit", data={"name": "Basmati rice", "quantity": 1})
        self.assertEqual(self.client.get(f"/api/items/{item_id}").json()["amount_left"], 1000)
        self.client.post(f"/item/{item_id}/edit", data={"name": "Basmati rice", "quantity": 1, "amount_left": "400"})
        self.assertEqual(self.client.get(f"/api/items/{item_id}").json()["amount_left"], 400)
        self.assertEqual(self.client.get(f"/api/items/{item_id}").json()["amount_checked_at"], main.dt.date.today().isoformat())
        page = self.client.get(f"/item/{item_id}").text
        self.assertIn("Amount left", page)

    def test_export_includes_stock_columns(self):
        self._create(name="Chickpeas", pack_size=400, pack_unit="g")
        header = self.client.get("/export.csv").text.splitlines()[0]
        for col in ("Pack size", "Pack unit", "Amount left", "Amount checked at", "Stockcode", "Product barcode"):
            self.assertIn(col, header)


if __name__ == "__main__":
    unittest.main()
