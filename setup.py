from setuptools import setup

APP = ['gui.py']

OPTIONS = {
    'app': {
        'name': 'Worker Activity Tracker',
        'bundle_identifier': 'com.worker.app',
    },
    'packages': ['requests', 'pillow', 'pystray', 'dotenv', 'mss'],
    'excludes': ['test', 'tkinter'],
}

setup(
    app=APP,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)