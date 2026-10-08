"""Print-profile regression checks; no physical printer is contacted."""

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select


TEST_DATA = tempfile.TemporaryDirectory(prefix="pantrlytics-profile-test-")
os.environ["DATA_DIR"] = TEST_DATA.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main  # noqa: E402


class PantryProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(main.app)
        cls.client = cls.client_context.__enter__()
        with Session(main.engine) as session:
            small = main.LabelPreset(name="Freezer Basic", media=main.SMALL_MEDIA, is_default=True)
            item = main.Item(
                serial_number="TEST-PANTRY-001",
                name="Long grain brown rice",
                quantity=2,
                unit="kg",
                use_by_date="2027-02-14",
            )
            session.add_all([small, item])
            session.commit()
            session.refresh(small)
            session.refresh(item)
            cls.small_id = small.id
            cls.item_id = item.id
            cls.pantry_id = session.exec(
                select(main.LabelPreset).where(main.LabelPreset.name == main.PANTRY_PRESET_NAME)
            ).first().id
        main.IPP_HOST = "test-cups.invalid:631"
        main.IPP_PRINTER = "Brother_QL_820NWB_ptouch"

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        TEST_DATA.cleanup()

    def test_selection_and_preview_do_not_enqueue_a_job(self):
        with patch.object(main.subprocess, "run") as run:
            selection = self.client.get(f"/print/{self.item_id}")
            self.assertEqual(selection.status_code, 200)
            self.assertIn("removable continuous 62 × 30 mm", selection.text)
            self.assertIn("matching roll is loaded", selection.text)
            preview = self.client.get(f"/label/{self.item_id}.png?preset_id={self.pantry_id}")
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(Image.open(io.BytesIO(preview.content)).size, (732, 354))
            unconfirmed = self.client.post(
                f"/print/{self.item_id}", data={"preset_id": self.pantry_id, "copies": "1"}
            )
            self.assertEqual(unconfirmed.status_code, 400)
            quick_unconfirmed = self.client.post(
                "/designer/quick/print", data={"title": "Rice"}
            )
            self.assertEqual(quick_unconfirmed.status_code, 400)
            run.assert_not_called()

    def test_selected_profile_controls_image_and_media_in_same_job(self):
        submitted = []

        def fake_lp(command, **_kwargs):
            with Image.open(command[-1]) as image:
                submitted.append((command, image.size))
            return SimpleNamespace(returncode=0, stdout="queued", stderr="")

        with patch.object(main.subprocess, "run", side_effect=fake_lp):
            for preset_id in (self.pantry_id, self.small_id):
                response = self.client.post(
                    f"/print/{self.item_id}",
                    data={"preset_id": preset_id, "copies": "1", "loaded_roll_confirmed": "true"},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303)

        pantry_cmd, pantry_size = submitted[0]
        small_cmd, small_size = submitted[1]
        self.assertEqual(pantry_size, (697, 354))
        self.assertIn("media=Custom.62x30mm", pantry_cmd)
        self.assertIn("PageSize=Custom.62x30mm", pantry_cmd)
        self.assertIn("MediaType=Tape", pantry_cmd)
        self.assertIn("CutLabel=1", pantry_cmd)
        self.assertEqual(small_size, (330, 1051))
        self.assertIn("media=w79h252", small_cmd)
        self.assertNotIn("MediaType=Tape", small_cmd)


if __name__ == "__main__":
    unittest.main()
