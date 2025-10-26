#!/usr/bin/env python3
"""
Setup script for CertPatrol Orchestrator
"""
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="certpatrol-orchestrator",
    version="0.1.0",
    author="Martin Aberastegue",
    author_email="martin@torito.io",
    description="Process orchestration platform for managing multiple CertPatrol instances",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ToritoIO/CertPatrol-Orchestrator",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "Topic :: Security",
        "Topic :: System :: Monitoring",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "certpatrol-orch=manager.cli:main",
        ],
    },
    include_package_data=True,
    package_data={
        "manager": [
            "../web/templates/*.html",
            "../web/static/css/*.css",
            "../web/static/js/*.js",
        ],
    },
)

