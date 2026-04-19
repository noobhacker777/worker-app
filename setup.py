from setuptools import setup

APP = ["gui.py"]

OPTIONS = {
    "py2app": {
        "argv_emulation": True,
        "plist": {
            "CFBundleName": "Worker",
            "CFBundleDisplayName": "Worker Activity Tracker",
            "CFBundleIdentifier": "com.worker.app",
            "NSHighResolutionCapable": True,
        },
    }
}

setup(
    name="Worker",
    app=APP,
    options=OPTIONS,
    setup_requires=["py2app"],
)
