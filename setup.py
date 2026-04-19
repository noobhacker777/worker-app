from setuptools import setup

APP = ['gui.py']

OPTIONS = {
    'app': {
        'name': 'Worker Activity Tracker',
    },
}

setup(
    app=APP,
    options={'py2app': OPTIONS},
)