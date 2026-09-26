import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "upstream", Path(__file__).parents[1] / "scripts" / "upstream.py"
)
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)


def release():
    tag = "rust-v1.2.3"
    assets = []
    for target in upstream.TARGETS.values():
        for suffix in (".tar.gz", ".tar.gz.sigstore"):
            name = f"codex-package-{target}{suffix}"
            assets.append({
                "name": name,
                "browser_download_url": f"https://github.com/openai/codex/releases/download/{tag}/{name}",
                "digest": "sha256:" + "a" * 64,
            })
    return {"tag_name": tag, "draft": False, "prerelease": False, "assets": assets}


class UpstreamTests(unittest.TestCase):
    def test_stable_release(self):
        result = upstream.release_inputs(release())
        self.assertEqual(result["codex_version"], "1.2.3")
        self.assertEqual(set(result["packages"]), {"amd64", "arm64"})

    def test_reject_unstable_release(self):
        for field, value in (("prerelease", True), ("draft", True), ("tag_name", "rust-v1.2.3-alpha.1")):
            data = release()
            data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                upstream.release_inputs(data)

    def test_reject_missing_checksum(self):
        data = release()
        data["assets"][0]["digest"] = None
        with self.assertRaises(ValueError):
            upstream.release_inputs(data)

    def test_reject_external_asset(self):
        data = release()
        data["assets"][0]["browser_download_url"] = "https://example.com/package.tar.gz"
        with self.assertRaises(ValueError):
            upstream.release_inputs(data)

    def test_reject_incomplete_release(self):
        data = release()
        data["assets"].pop()
        with self.assertRaises(KeyError):
            upstream.release_inputs(data)

    def test_reject_archive_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "package.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                member = tarfile.TarInfo("../escaped")
                member.size = 1
                output.addfile(member, io.BytesIO(b"x"))
            with self.assertRaises(tarfile.FilterError):
                upstream.extract(archive, root / "package")
            self.assertFalse((root / "escaped").exists())


if __name__ == "__main__":
    unittest.main()
