from setuptools import setup, find_packages
import pathlib

here = pathlib.Path(__file__).parent.resolve()

# Get the long description from the README file
LONG_DESCRIPTION = (here / "README.md").read_text(encoding="utf-8")

VERSION = "1.0.14"

# Setting up
setup(
    name="kia_hyundai_api",
    version=VERSION,
    author="Brendan Dahl",
    author_email="dahl.brendan@gmail.com",
    description="Kia Uvo/Hyundai Blue Link Api Wrapper",
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=["aiohttp>=3.8.1", "pytz"],
    keywords=["Kia", "Uvo", "Api", "Hyundai", "Bluelink"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Framework :: AsyncIO",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows",
    ],
    python_requires=">=3.9, <4",
    url="https://github.com/dahlb/kia_hyundai_api",
    project_urls={
        "Bug Reports": "https://github.com/dahlb/kia_hyundai_api/issues",
        "Source": "https://github.com/dahlb/kia_hyundai_api",
    },
)
