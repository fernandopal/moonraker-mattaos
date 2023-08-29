from setuptools import setup, find_packages

setup(
    name='moonraker-control-plugin',
    version='0.1.0',
    packages=find_packages(),
    install_requires=[
        'colorlog',
        'Flask',
        'requests',
    ],
)