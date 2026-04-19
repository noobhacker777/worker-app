from setuptools import setup
import platform

APP = ['gui.py']
DATA_FILES = []
if platform.system() != 'Darwin':
    DATA_FILES = [
        ('F_icon.png', ['F_icon.png']),
        ('F_icon.ico', ['F_icon.ico']),
    ]

OPTIONS = {
    'app': {
        'name': 'Worker Activity Tracker',
        'bundle_identifier': 'com.worker.app',
        'icon_file': 'F_icon.ico',
        'icon_size': (128, 128),
        'minimal_python_version': '3.9',
        'platform': 'MacOS',
    },
    'packages': ['requests', 'pillow', 'pystray', 'dotenv', 'mss'],
    'excludes': ['test', 'tkinter'],
    'forceARC': True,
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