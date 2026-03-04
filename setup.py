"""GovernIQ Universal Evaluation Platform — Package setup."""

from setuptools import find_packages, setup

setup(
    name="governiq",
    version="0.1.0",
    description="Domain-agnostic assessment evaluation engine for Kore.ai XO Platform certifications",
    author="GovernIQ Team",
    python_requires=">=3.11",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        "fastapi>=0.109.0",
        "uvicorn[standard]>=0.27.0",
        "pydantic>=2.5.0",
        "jinja2>=3.1.3",
        "httpx>=0.27.0",
        "pyyaml>=6.0.1",
        "orjson>=3.9.0",
        "python-multipart>=0.0.6",
    ],
    extras_require={
        "llm": ["openai>=1.12.0"],
        "semantic": ["sentence-transformers>=2.3.0", "numpy>=1.26.0"],
        "dev": ["pytest>=8.0.0", "pytest-asyncio>=0.23.0", "pytest-cov>=4.1.0"],
    },
    entry_points={
        "console_scripts": [
            "governiq=governiq.main:main",
        ],
    },
)
