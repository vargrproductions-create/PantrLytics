"""Scan-to-add checks; Open Food Facts and Claude are mocked, so no network is used."""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import barcode
from barcode.writer import ImageWriter
from fastapi.testclient import TestClient
from sqlmodel import Session, select


TEST_DATA = tempfile.TemporaryDirectory(prefix="pantrlytics-scan-test-")
os.environ["DATA_DIR"] = TEST_DATA.name
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main  # noqa: E402


def ean_png(code: str) -> bytes:
    buf = io.BytesIO()
    barcode.get("ean13", code, writer=ImageWriter()).write(buf)
    return buf.getvalue()


def blank_png() -> bytes:
    buf = io.BytesIO()
    main.Image.new("RGB", (400, 300), "white").save(buf, format="PNG")
    return buf.getvalue()


def fake_claude_response(payload: dict, stop_reason: str = "end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=json.dumps(payload))])


class ScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(main.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        TEST_DATA.cleanup()

    def _scan(self, data: bytes):
        return self.client.post("/scan", files={"photo": ("scan.png", data, "image/png")})

    def test_normalize_and_pack_size(self):
        self.assertEqual(main.normalize_barcode("036000291452"), "0036000291452")
        self.assertEqual(main.normalize_barcode(" 9300633603298 "), "9300633603298")
        self.assertIsNone(main.normalize_barcode(""))
        self.assertEqual(main.parse_pack_size("1kg"), (1000, "g"))
        self.assertEqual(main.parse_pack_size("750 g"), (750, "g"))
        self.assertEqual(main.parse_pack_size("1.5L"), (1500, "ml"))
        self.assertEqual(main.parse_pack_size("nothing"), (None, None))

    def test_scan_page_loads(self):
        page = self.client.get("/scan").text
        self.assertIn("Scan a product", page)
        self.assertIn("needs an Anthropic API key", page)

    def test_local_match_offers_restock(self):
        resp = self.client.post("/api/items", json={
            "name": "Red split lentils", "location": "Pantry", "quantity": 1,
            "pack_size": 500, "pack_unit": "g", "product_barcode": "9300633603298",
        })
        item_id = resp.json()["item_id"]
        with patch.object(main, "lookup_open_food_facts") as off:
            page = self._scan(ean_png("930063360329")).text
            off.assert_not_called()
        self.assertIn("Already in PantrLytics", page)
        self.assertIn(f"/scan/restock/{item_id}", page)
        resp = self.client.post(f"/scan/restock/{item_id}", data={"product_barcode": "9300633603298"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        data = self.client.get(f"/api/items/{item_id}").json()
        self.assertEqual(data["quantity"], 2)
        self.assertEqual(data["amount_left"], 1000)

    def test_lookup_matches_upc_as_ean(self):
        self.client.post("/api/items", json={"name": "Imported oats", "product_barcode": "0036000291452"})
        matches = self.client.get("/api/items/lookup", params={"product_barcode": "036000291452"}).json()["matches"]
        self.assertEqual([m["name"] for m in matches], ["Imported oats"])

    def test_open_food_facts_prefills_form(self):
        self.client.post("/api/items", json={"name": "Seed grains category", "category": "Grains"})
        info = {"name": "Pearl Barley", "brand": "Macro", "pack_size": 500.0, "pack_unit": "g",
                "categories_tags": ["en:cereals-and-potatoes", "en:barley"], "source": "Open Food Facts"}
        with patch.object(main, "lookup_open_food_facts", return_value=info), \
             patch.object(main, "read_label_with_claude") as claude:
            page = self._scan(ean_png("931234567890")).text
            claude.assert_not_called()
        self.assertIn("Filled in from Open Food Facts", page)
        self.assertIn('value="Pearl Barley"', page)
        self.assertIn('value="500"', page)
        self.assertIn('value="9312345678907"', page)
        self.assertIn('value="Grains"', page)
        self.assertIn('name="scan_photo" value="', page)

    def test_open_food_facts_miss_without_key_gives_manual_form(self):
        with patch.object(main, "lookup_open_food_facts", return_value=None):
            page = self._scan(ean_png("931111111111")).text
        self.assertIn("no Anthropic API key", page)
        self.assertIn("Barcode 9311111111112 was read", page)
        self.assertIn("Create Item", page)

    def test_claude_reads_label_when_no_barcode(self):
        payload = {"name": "Tapioca pearls", "brand": "McKenzie's", "pack_size": 375, "pack_unit": "g", "barcode": "",
                   "best_before": "2027-03-01", "category": "", "container": "packet"}
        fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: fake_claude_response(payload))))
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("anthropic.Anthropic", return_value=fake):
            page = self._scan(blank_png()).text
        self.assertIn("Filled in from the label photo", page)
        self.assertIn('value="Tapioca pearls"', page)
        self.assertIn('value="375"', page)
        self.assertIn('value="2027-03-01"', page)
        self.assertIn('value="packet"', page)
        self.assertIn("Read size or best-before from another photo", page)

    def test_best_before_formats(self):
        self.assertEqual(main._iso_date_or_none("2027-05-14"), "2027-05-14")
        self.assertEqual(main._iso_date_or_none("2027-05"), "2027-05-31")
        self.assertEqual(main._iso_date_or_none("05/2027"), "2027-05-31")
        self.assertEqual(main._iso_date_or_none("14/05/27"), "2027-05-14")
        self.assertEqual(main._iso_date_or_none("2027/05/14"), "2027-05-14")
        self.assertIsNone(main._iso_date_or_none(""))
        self.assertIsNone(main._iso_date_or_none("31/02/2027"))

    def test_reader_runs_with_key_even_when_database_is_complete(self):
        info = {"name": "Vegemite", "brand": "Vegemite", "pack_size": 600.0, "pack_unit": "g",
                "categories_tags": ["en:yeast-extract-spreads"], "source": "Open Food Facts"}
        self.client.post("/api/items", json={"name": "Seed staples", "category": "Staples"})
        payload = {"name": "Yeast spread", "brand": "", "pack_size": 0, "pack_unit": "", "barcode": "",
                   "best_before": "2027-08", "category": "", "container": "jar"}
        fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: fake_claude_response(payload))))
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch.object(main, "lookup_open_food_facts", return_value=info), \
             patch("anthropic.Anthropic", return_value=fake):
            page = self._scan(ean_png("930065065861")).text
        self.assertIn('value="Vegemite"', page)
        self.assertIn('value="600"', page)
        self.assertIn('value="2027-08-31"', page)
        self.assertIn('value="jar"', page)
        self.assertIn('name="amount_left"', page)

    def test_new_item_amount_left_override(self):
        resp = self.client.post("/new", data={"name": "Half jar honey", "quantity": "1", "unit": "jar",
                                              "pack_size": "500", "pack_unit": "g", "amount_left": "250"},
                                follow_redirects=False)
        item_id = int(resp.headers["location"].rstrip("/").split("/")[-1])
        self.assertEqual(self.client.get(f"/api/items/{item_id}").json()["amount_left"], 250)

    def test_category_mapping(self):
        cats = ["Grains", "Staples", "Topping", "Frozen Meal"]
        self.assertEqual(main.category_from_off(["en:maple"], cats), "Topping")
        self.assertEqual(main.category_from_off(["en:plant-based-foods", "en:yeast-extract-spreads"], cats), "Staples")
        self.assertEqual(main.category_from_off(["en:legumes", "en:lentils"], cats), "Grains")
        self.assertIsNone(main.category_from_off(["en:maple"], ["Grains"]))
        self.assertIsNone(main.category_from_off([], cats))

    def test_label_photo_fills_size_missing_from_database(self):
        info = {"name": "Kirkland Signature Maple Syrup", "brand": "Kirkland", "pack_size": None, "pack_unit": None,
                "categories_tags": ["en:maple"], "source": "Open Food Facts"}
        payload = {"name": "Maple syrup", "brand": "Kirkland", "pack_size": 1000, "pack_unit": "ml", "barcode": "",
                   "best_before": "", "category": "", "container": "bottle"}
        fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: fake_claude_response(payload))))
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch.object(main, "lookup_open_food_facts", return_value=info), \
             patch("anthropic.Anthropic", return_value=fake):
            page = self._scan(ean_png("009661985512")).text
        self.assertIn("Filled in from Open Food Facts and the label photo", page)
        self.assertIn('value="Kirkland Signature Maple Syrup"', page)
        self.assertIn('value="1000"', page)
        self.assertIn('value="ml"', page)
        self.assertIn('value="bottle"', page)

    def test_more_photo_fills_only_empty_fields_and_keeps_both_photos(self):
        first = main._save_scan_photo(main.Image.new("RGB", (50, 50), "white"))
        payload = {"name": "Something else", "brand": "", "pack_size": 750, "pack_unit": "g", "barcode": "",
                   "best_before": "2027-05-30", "category": "", "container": "bag"}
        fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: fake_claude_response(payload))))
        form = {"name": "Rolled oats", "quantity": "1", "unit": "bag", "location": "Pantry", "notes": "mine",
                "product_barcode": "9300000000028", "scan_photo": first}
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), patch("anthropic.Anthropic", return_value=fake):
            page = self.client.post("/scan/more", data=form, files={"more_photo": ("front.png", blank_png(), "image/png")}).text
        self.assertIn("Added the size, best-before date from the photo", page)
        self.assertIn('value="Rolled oats"', page)
        self.assertIn('value="750"', page)
        self.assertIn('value="2027-05-30"', page)
        token_field = page.split('name="scan_photo" value="')[1].split('"')[0]
        tokens = token_field.split()
        self.assertEqual(len(tokens), 2)
        self.assertEqual(tokens[0], first)
        resp = self.client.post("/new", data={**form, "pack_size": "750", "pack_unit": "g", "scan_photo": token_field},
                                follow_redirects=False)
        item_id = int(resp.headers["location"].rstrip("/").split("/")[-1])
        with Session(main.engine) as session:
            photos = session.exec(select(main.ItemPhoto).where(main.ItemPhoto.item_id == item_id)).all()
        self.assertEqual(sorted(os.path.basename(p.path) for p in photos), sorted(tokens))

    def test_claude_refusal_falls_back_to_manual_form(self):
        fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
            create=lambda **kw: fake_claude_response({}, stop_reason="refusal"))))
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("anthropic.Anthropic", return_value=fake):
            page = self._scan(blank_png()).text
        self.assertIn("could not read this photo", page)
        self.assertIn("Create Item", page)

    def test_new_item_saves_pack_fields_and_scan_photo(self):
        token = main._save_scan_photo(main.Image.new("RGB", (100, 100), "white"))
        resp = self.client.post("/new", data={
            "name": "Basmati rice", "quantity": "2", "unit": "pack", "location": "Pantry",
            "pack_size": "1000", "pack_unit": "g", "product_barcode": "9300000000011", "scan_photo": token,
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        item_id = int(resp.headers["location"].rstrip("/").split("/")[-1])
        data = self.client.get(f"/api/items/{item_id}").json()
        self.assertEqual(data["amount_left"], 2000)
        self.assertEqual(data["product_barcode"], "9300000000011")
        with Session(main.engine) as session:
            photos = session.exec(select(main.ItemPhoto).where(main.ItemPhoto.item_id == item_id)).all()
        self.assertEqual([os.path.basename(p.path) for p in photos], [token])

    def test_scan_photo_token_rejects_traversal(self):
        resp = self.client.post("/new", data={"name": "Sneaky", "scan_photo": "../options.json"}, follow_redirects=False)
        item_id = int(resp.headers["location"].rstrip("/").split("/")[-1])
        with Session(main.engine) as session:
            photos = session.exec(select(main.ItemPhoto).where(main.ItemPhoto.item_id == item_id)).all()
        self.assertEqual(photos, [])

    def test_backup_strips_api_key(self):
        with open(main.ADDON_OPTIONS_PATH, "w") as f:
            json.dump({"serial_prefix": "X-", "anthropic_api_key": "sk-secret"}, f)
        with Session(main.engine) as session:
            fpath, _ = main.create_backup_zip({"include_db": False, "include_photos": False,
                                               "include_export": False, "include_config": True},
                                              session, target_dir=TEST_DATA.name)
        import zipfile
        with zipfile.ZipFile(fpath) as zf:
            opts = json.loads(zf.read("options.json"))
        os.remove(main.ADDON_OPTIONS_PATH)
        self.assertNotIn("anthropic_api_key", opts)
        self.assertEqual(opts["serial_prefix"], "X-")


if __name__ == "__main__":
    unittest.main()
