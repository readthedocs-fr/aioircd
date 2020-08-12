from setuptools import setup

setup(
    py_modules=['aioircd'],
    entry_points={
        'console_scripts': [
            'aioircd = aioircd:main'
        ],
    },
)
