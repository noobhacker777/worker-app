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
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
    install_requires=[
        'requests',
        'Pillow>=10.0.0',
        'pystray>=0.19.5',
        'python-dotenv>=1.0.0',
        'mss>=10.0.0',
    ],
)