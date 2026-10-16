from __future__ import annotations

import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def test_launcher_assets_and_instructions_exist(self):
        for relative in (
            "scripts/launch.ps1",
            "scripts/create_windows_launcher.ps1",
            "scripts/build_desktop_app.ps1",
            "scripts/stop_stale_backend.ps1",
            "desktop/MyVocabulary.Desktop/MyVocabulary.Desktop.csproj",
            "desktop/MyVocabulary.Desktop/App.xaml",
            "desktop/MyVocabulary.Desktop/App.xaml.cs",
            "desktop/MyVocabulary.Desktop/MainWindow.xaml",
            "desktop/MyVocabulary.Desktop/MainWindow.xaml.cs",
            "desktop/MyVocabulary.Desktop/BackendHost.cs",
            "app/assets/app-icon.svg",
            "app/assets/app-icon.ico",
            "app/assets/app-icon-v5.ico",
            "app/assets/favicon-v5.ico",
            "app/manifest.webmanifest",
            "scripts/generate_app_icon_assets.py",
            "README.md",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for phrase in (
            "启动",
            "添加单词",
            "开始复习",
            "易混词",
            "五个范围、三种可见作答方式",
            "全局复习",
            "同义词",
            "遮罩自评",
            "data/vocabulary.db",
            "CSV",
            "备份与恢复",
        ):
            self.assertIn(phrase, readme)

        launcher = (ROOT / "scripts" / "launch.ps1").read_text(encoding="utf-8")
        self.assertIn("dist\\MyVocabulary-current\\MyVocabulary.exe", launcher)
        self.assertNotIn("msedge", launcher.lower())
        self.assertNotIn("chrome", launcher.lower())

        builder = (ROOT / "scripts" / "build_desktop_app.ps1").read_text(encoding="utf-8")
        shortcut = (ROOT / "scripts" / "create_windows_launcher.ps1").read_text(encoding="utf-8")
        self.assertIn('"dist\\MyVocabulary-current"', builder)
        self.assertIn('"dist\\MyVocabulary-current\\MyVocabulary.exe"', shortcut)

    def test_desktop_wrapper_has_native_icon_and_pinned_webview2(self):
        project = (ROOT / "desktop" / "MyVocabulary.Desktop" / "MyVocabulary.Desktop.csproj").read_text(encoding="utf-8")
        self.assertIn("<UseWPF>true</UseWPF>", project)
        self.assertIn("<ApplicationIcon>..\\..\\app\\assets\\app-icon-v5.ico</ApplicationIcon>", project)
        self.assertIn('PackageReference Include="Microsoft.Web.WebView2" Version="1.0.4191.47"', project)

        window = (ROOT / "desktop" / "MyVocabulary.Desktop" / "MainWindow.xaml").read_text(encoding="utf-8")
        self.assertIn('Icon="Assets/app-icon-v5.ico"', window)
        self.assertIn("Microsoft.Web.WebView2.Wpf", window)

        backend = (ROOT / "desktop" / "MyVocabulary.Desktop" / "BackendHost.cs").read_text(encoding="utf-8")
        self.assertIn('api_version", out var version', backend)
        self.assertIn("version.GetInt32() == 4", backend)
        self.assertIn("stop_stale_backend.ps1", backend)

        stopper = (ROOT / "scripts" / "stop_stale_backend.ps1").read_text(encoding="utf-8")
        self.assertIn("Get-NetTCPConnection -LocalPort 8766", stopper)
        self.assertIn("$process.CommandLine.IndexOf($expectedStartScript", stopper)

    def test_native_startup_animation_tracks_real_loading_and_reduced_motion(self):
        project = (ROOT / "desktop" / "MyVocabulary.Desktop" / "MyVocabulary.Desktop.csproj").read_text(encoding="utf-8")
        window = (ROOT / "desktop" / "MyVocabulary.Desktop" / "MainWindow.xaml").read_text(encoding="utf-8")
        code = (ROOT / "desktop" / "MyVocabulary.Desktop" / "MainWindow.xaml.cs").read_text(encoding="utf-8")

        self.assertIn('Link="Assets\\app-icon-256.png"', project)
        for name in ("LoadingOverlay", "LogoShell", "RotatingPhrasePanel", "StatusText"):
            self.assertIn(f'x:Name="{name}"', window)
        self.assertIn('Source="Assets/app-icon-256.png"', window)
        self.assertIn('Background="#F7FBF4"', window)

        self.assertIn("MinimumSplashDuration", code)
        self.assertIn("startupClock.Restart()", code)
        self.assertIn("SystemParameters.ClientAreaAnimation", code)
        self.assertIn("LogoScale.ScaleX = 1", code)
        self.assertIn("RotateLoadingPhrasesAsync", code)
        self.assertIn("AnimatePhraseAsync", code)
        self.assertIn("HideLoadingOverlayAsync", code)
        self.assertIn("await BackendHost.EnsureRunningAsync", code)
        self.assertIn("WebView_NavigationCompleted", code)

    def test_taskbar_icon_has_native_windows_sizes(self):
        icon = (ROOT / "app" / "assets" / "app-icon-v5.ico").read_bytes()
        reserved, image_type, count = struct.unpack_from("<HHH", icon)
        self.assertEqual((reserved, image_type), (0, 1))
        sizes = []
        for index in range(count):
            width, height = struct.unpack_from("<BB", icon, 6 + 16 * index)
            sizes.append((256 if width == 0 else width, 256 if height == 0 else height))
        expected = (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 96, 128, 256)
        self.assertEqual(sizes, [(size, size) for size in expected])

    def test_small_icons_use_bold_native_pixel_art(self):
        for size in (16, 20, 24, 30, 32, 36, 40):
            with Image.open(ROOT / "app" / "assets" / "icons" / f"app-icon-{size}.png") as icon:
                rgba = icon.convert("RGBA")
                pixels = list(rgba.get_flattened_data())
                page_pixels = [
                    pixel for pixel in pixels
                    if pixel[:3] in {(255, 253, 247), (220, 235, 227), (207, 230, 220)}
                ]
                self.assertGreaterEqual(len(page_pixels), round(size * size * 0.18), size)
                self.assertLessEqual(len(set(pixels)), 5, size)

    def test_manifest_exposes_windows_and_installable_pwa_icons(self):
        manifest = json.loads((ROOT / "app" / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["id"], "/my-vocabulary")
        sizes = {entry["sizes"] for entry in manifest["icons"]}
        for size in (24, 30, 36, 44, 48, 55, 60, 66, 72, 88, 96, 176, 192, 512):
            self.assertIn(f"{size}x{size}", sizes)
            self.assertTrue((ROOT / "app" / "assets" / "icons" / f"app-icon-{size}.png").is_file())

        html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="manifest" href="manifest.webmanifest?v=5"', html)
        self.assertIn('href="assets/favicon-v5.ico?v=5"', html)
        self.assertNotIn('sizes="any"', html)
        for entry in manifest["icons"]:
            self.assertTrue(entry["src"].endswith("?v=5"), entry["src"])

    def test_shortcut_can_be_created_and_verified(self):
        script = ROOT / "scripts" / "create_windows_launcher.ps1"
        with tempfile.TemporaryDirectory() as directory:
            shortcut = Path(directory) / "我的词汇本.lnk"
            base_command = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-ShortcutPath",
                str(shortcut),
                "-AppPath",
                sys.executable,
            ]
            created = subprocess.run(
                base_command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            checked = subprocess.run(
                [*base_command, "-Check"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertIn("验证通过", checked.stdout)
            self.assertTrue(shortcut.is_file())


if __name__ == "__main__":
    unittest.main()
