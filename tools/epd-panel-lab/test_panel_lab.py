"""Focused binary-contract test; no hardware or device writes."""
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import panel_lab as lab


class PanelLabTest(unittest.TestCase):
    def test_fixture_contract(self):
        profiles, _ = lab.load_profiles()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            manifest = lab.generate(output)
            self.assertEqual(manifest["panelIdentity"]["nativeSize"], [720, 480])
            self.assertEqual(len(manifest["assets"]), 5)
            for asset in manifest["assets"]:
                raw = (output / asset["path"]).read_bytes()
                body_size, width, height, color_count, fmt, frames = struct.unpack("<IHHBBH", raw[:12])
                self.assertEqual((width, height, color_count, fmt, frames),
                                 (720, 480, 0, asset["format"], asset["frameCount"]))
                self.assertEqual(raw[12:32], bytes(20))
                self.assertEqual(len(raw), 32 + body_size)
                self.assertEqual(body_size, 345600 * frames if fmt != 1 else 43200 * frames)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), asset["sha256"])
                if fmt != 1:
                    self.assertTrue(set(range(*[asset["codeRange"][0], asset["codeRange"][1] + 1])).issubset(set(raw[32:])))
                else:
                    bodies = [raw[32 + i * 43200:32 + (i + 1) * 43200] for i in range(frames)]
                    self.assertEqual(len(set(bodies)), 12)
                    self.assertEqual([lab.sha256(body) for body in bodies], asset["frameBodySha256"])
                    # Every transition is represented across the alternating checker and stationary background/marker.
                    transitions = set()
                    for old, new in zip(bodies, bodies[1:]):
                        for a, b in zip(old, new):
                            for shift in range(8):
                                transitions.add((((a >> shift) & 1), ((b >> shift) & 1)))
                    self.assertEqual(transitions, {(0, 0), (0, 1), (1, 0), (1, 1)})
            saved = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, manifest)
        # Asymmetric fixture: a top-left portrait pixel must land on native row 7,
        # col 708, matching Flutter physical=x*height+height-1-y and Web mapping.
        physical = 7 * 720 + 719 - 11
        indexed = Image.new("P", lab.PORTRAIT, 21)
        indexed.putpixel((7, 11), 37)
        body = lab.frame_body(indexed, 3)
        self.assertEqual(body[physical], 37)
        self.assertEqual(body.count(37), 1)
        mono = Image.new("L", lab.PORTRAIT, 255)
        mono.putpixel((7, 11), 0)
        body = lab.frame_body(mono, 1)
        self.assertEqual(body[physical // 8], 128 >> (physical % 8))
        self.assertEqual(sum(byte.bit_count() for byte in body), 1)
        for name, profile in profiles.items():
            covered = set()
            for first in (0, 32):
                card = lab.color_card(name, profile, first, 32)
                for offset in range(32):
                    x, y = 12 + (offset % 4) * 114, 105 + (offset // 4) * 70
                    code = first + offset
                    # Flat raw-code margin remains even on an X-marked excluded swatch.
                    self.assertEqual(card.getpixel((x + 4, y + 4)), code)
                    self.assertEqual(card.convert("RGB").getpixel((x + 4, y + 4)), tuple(profile["palette"][code]))
                    covered.add(code)
            self.assertEqual(covered, set(range(64)))


if __name__ == "__main__":
    unittest.main()
