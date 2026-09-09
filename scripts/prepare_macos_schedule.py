"""Generate a reviewable launchd configuration; do not install or start it."""
import plistlib
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    data = root / "data"
    data.mkdir(exist_ok=True)
    target = data / "kz.ombre-leather.monamie.plist"
    config = {
        "Label": "kz.ombre-leather.monamie",
        "ProgramArguments": [str(root / ".venv/bin/python"), "-m", "app.check", "--store", "monamie"],
        "WorkingDirectory": str(root),
        "EnvironmentVariables": {"BROWSER_CHANNEL": "chrome", "PYTHONUNBUFFERED": "1"},
        "StartCalendarInterval": [{"Hour": 9, "Minute": 0}, {"Hour": 19, "Minute": 0}],
        "StandardOutPath": str(data / "monamie.log"),
        "StandardErrorPath": str(data / "monamie-error.log"),
        "ProcessType": "Background",
    }
    target.write_bytes(plistlib.dumps(config))
    print(f"Prepared only: {target}")
    print("Schedule uses the Mac's system timezone, which must be Asia/Almaty.")
    print("Checks require a logged-in user and an internet connection; sleep can delay them.")


if __name__ == "__main__":
    main()
