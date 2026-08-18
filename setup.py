"""
setup.py — Optional pip-installable entry point.

Usage:
  pip install -e .          # installs as 'streamscoop' command
  streamscoop               # launch from anywhere'
"""

from setuptools import setup, find_packages

setup(
    name='streamscoop',
    version='2.0.0',
    description='A powerful terminal video downloader built on yt-dlp',
    author='Stream Scoop',
    python_requires='>=3.9',
    install_requires=[
        'yt-dlp',
        'colorama',
    ],
    packages=find_packages(),
    py_modules=[
        'main',
        'config',
        'utilities',
        'colours',
        'download_logic',
        'concurrent_dl',
        'format_inspector',
        'thumbnail_dl',
        'batch_manager',
        'file_converter',
        'archive_manager',
        'stats_manager',
        'search_dl',
    ],
    entry_points={
        'console_scripts': [
            'streamscoop=main:main',
        ],
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'Environment :: Console',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
)
